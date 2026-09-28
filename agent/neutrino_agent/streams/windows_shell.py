"""PowerShell on a Windows pseudo console, over one stream.

Two anonymous pipes carry the console's input and output, and the console is
created at the size the hub opened the stream with. PowerShell is started
suspended on it, with the agent's own standard handles set aside so the
child is born with the console's, put into a job object that kills every
process in it when its last handle closes, and then resumed. A thread reads
the console's output and sends it up, no faster than the hub's credit; the
hub's bytes are written to the console's input, a resize resizes the
console, and a close terminates the shell. The stream closes with the
shell's exit code.

Windows 10 1809 is the first with a pseudo console; an older Windows refuses
the stream with ``unsupported_platform``.

Not pure: starts processes and owns handles.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ctypes
import subprocess
import threading

from neutrino_agent.constants import (
    AGENT_SHELL_COMMANDS,
    AGENT_SHELL_KILL_TIMEOUT_S,
    AGENT_SHELL_READ_BYTES,
    AGENT_WS_STREAM_CREDIT_BYTES,
)
from neutrino_agent.exceptions import StreamClosed, StreamRefused
from neutrino_agent.platforms import win32

DEFAULT_COLUMNS = 80
DEFAULT_ROWS = 24
# How long the wait for the shell's exit, and the wait for the hub's next
# item, sleep before looking again.
WINDOWS_SHELL_POLL_MS = 500
WINDOWS_SHELL_POLL_S = WINDOWS_SHELL_POLL_MS / 1000
# The exit code a shell the hub closed is terminated with.
WINDOWS_SHELL_TERMINATED_CODE = 1


class WindowsShellStream:
    """One PowerShell on a pseudo console, served over one stream."""

    def __init__(self, channel, args: dict, *, kernel32=None):
        """
        Args:
            channel: The stream's channel.
            args: ``{"cols", "rows"}``, the console's first size.
            kernel32: The bound kernel32; None binds the real one.
        """
        self._channel = channel
        self._columns = max(1, int(args.get("cols", DEFAULT_COLUMNS) or 0))
        self._rows = max(1, int(args.get("rows", DEFAULT_ROWS) or 0))
        self._kernel32 = kernel32
        self._console = None
        self._process = None
        self._is_done = threading.Event()

    def open(self) -> None:
        """Check the stream can be served here.

        Raises:
            StreamRefused: ``unsupported_platform`` on a Windows with no
                pseudo console, or where kernel32 cannot be loaded.
        """
        try:
            kernel32 = self._bound_kernel32()
        except (OSError, AttributeError):
            raise StreamRefused("unsupported_platform") from None
        if not hasattr(kernel32, "CreatePseudoConsole"):
            raise StreamRefused("unsupported_platform")

    def run(self) -> dict:
        """Serve the shell until it exits or the hub closes the stream.

        Returns:
            ``{"code", "params"}``, with ``exit_code`` in the params once the
            shell ran, ``shell_failed`` with ``detail`` when it could not
            start.
        """
        kernel32 = self._bound_kernel32()
        try:
            console_input, input_writer = _pipe(kernel32)
            output_reader, console_output = _pipe(kernel32)
        except OSError as error:
            return _failed(error)
        console = ctypes.c_void_p()
        result = kernel32.CreatePseudoConsole(
            win32.Coord(self._columns, self._rows),
            console_input,
            console_output,
            0,
            ctypes.byref(console),
        )
        # The console holds its own ends of the pipes from here on.
        kernel32.CloseHandle(console_input)
        kernel32.CloseHandle(console_output)
        if result != 0:
            for handle in (input_writer, output_reader):
                kernel32.CloseHandle(handle)
            return {
                "code": "shell_failed",
                "params": {"detail": f"CreatePseudoConsole answered {result}"},
            }
        self._console = console
        attributes = None
        job = None
        try:
            attributes = _attribute_list(kernel32, console)
            self._process = _start(
                kernel32, list(AGENT_SHELL_COMMANDS["win32"]), attributes
            )
            job = _kill_on_close_job(kernel32)
            kernel32.AssignProcessToJobObject(job, self._process.hProcess)
            kernel32.ResumeThread(self._process.hThread)
        except OSError as error:
            if self._process is not None:
                kernel32.TerminateProcess(self._process.hProcess, 1)
            self._release(kernel32, attributes, job, input_writer, output_reader)
            return _failed(error)
        self._channel.offer_credit(AGENT_WS_STREAM_CREDIT_BYTES)
        reader = threading.Thread(
            target=self._pump_output,
            args=(kernel32, output_reader),
            name=f"agent_shell_output_{self._channel.id}",
            daemon=True,
        )
        feeder = threading.Thread(
            target=self._feed_input,
            args=(kernel32, input_writer),
            name=f"agent_shell_input_{self._channel.id}",
            daemon=True,
        )
        reader.start()
        feeder.start()
        exit_code = self._wait_for_exit(kernel32)
        self._is_done.set()
        # Closing the console ends its output pipe, which ends the reader.
        kernel32.ClosePseudoConsole(console)
        self._console = None
        reader.join(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
        feeder.join(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
        self._release(kernel32, attributes, job, input_writer, output_reader)
        return {"code": "", "params": {"exit_code": exit_code}}

    def _bound_kernel32(self):
        """kernel32, bound on first use."""
        if self._kernel32 is None:
            self._kernel32 = win32.libraries().kernel32
        return self._kernel32

    def _wait_for_exit(self, kernel32) -> int:
        """Wait for the shell to exit, or end it once the hub closed the stream."""
        handle = self._process.hProcess
        while (
            kernel32.WaitForSingleObject(handle, WINDOWS_SHELL_POLL_MS)
            != win32.WAIT_OBJECT_0
        ):
            if self._is_done.is_set():
                kernel32.TerminateProcess(handle, WINDOWS_SHELL_TERMINATED_CODE)
        code = win32.DWORD(0)
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return int(code.value)

    def _pump_output(self, kernel32, output_reader) -> None:
        """Send the console's output until it ends or the hub is gone."""
        buffer = ctypes.create_string_buffer(AGENT_SHELL_READ_BYTES)
        read = win32.DWORD(0)
        while kernel32.ReadFile(
            output_reader, buffer, AGENT_SHELL_READ_BYTES, ctypes.byref(read), None
        ):
            if read.value == 0:
                return
            try:
                self._channel.send_bytes(buffer.raw[: read.value])
            except StreamClosed:
                return

    def _feed_input(self, kernel32, input_writer) -> None:
        """Write the hub's bytes to the console and apply its resizes."""
        while not self._is_done.is_set():
            item = self._channel.recv(timeout=WINDOWS_SHELL_POLL_S)
            if item is None:
                continue
            if item[0] == "data":
                _write(kernel32, input_writer, item[1])
                self._channel.offer_credit(len(item[1]))
            elif item[0] == "resize":
                self._columns = max(1, int(item[1]))
                self._rows = max(1, int(item[2]))
                console = self._console
                if console is not None:
                    kernel32.ResizePseudoConsole(
                        console, win32.Coord(self._columns, self._rows)
                    )
            elif item[0] == "close":
                self._is_done.set()
                kernel32.TerminateProcess(
                    self._process.hProcess, WINDOWS_SHELL_TERMINATED_CODE
                )
                return

    def _release(self, kernel32, attributes, job, *handles) -> None:
        """Close the job, which ends every process left in it, and the handles."""
        if job is not None:
            kernel32.CloseHandle(job)
        if attributes is not None:
            kernel32.DeleteProcThreadAttributeList(attributes)
        if self._console is not None:
            kernel32.ClosePseudoConsole(self._console)
            self._console = None
        process = self._process
        if process is not None:
            handles = handles + (process.hThread, process.hProcess)
        for handle in handles:
            with contextlib.suppress(OSError):
                kernel32.CloseHandle(handle)


def _failed(error: OSError) -> dict:
    """A shell that could not start, as the stream closes with it."""
    return {"code": "shell_failed", "params": {"detail": str(error)[:200]}}


def _write(kernel32, handle, data: bytes) -> None:
    """Write all of ``data`` to a pipe, stopping at the first refusal."""
    view = memoryview(data)
    while view:
        written = win32.DWORD(0)
        if not kernel32.WriteFile(
            handle, bytes(view), len(view), ctypes.byref(written), None
        ):
            return
        view = view[written.value :]


def _pipe(kernel32) -> tuple:
    """A read end and a write end of an anonymous pipe.

    Args:
        kernel32: The bound kernel32.

    Returns:
        ``(read_handle, write_handle)``.

    Raises:
        OSError: When the pipe cannot be made.
    """
    read = ctypes.c_void_p()
    write = ctypes.c_void_p()
    if not kernel32.CreatePipe(ctypes.byref(read), ctypes.byref(write), None, 0):
        raise win32.last_error()
    return read, write


def _attribute_list(kernel32, console):
    """A process attribute list naming the pseudo console.

    Args:
        kernel32: The bound kernel32.
        console: The pseudo console handle.

    Returns:
        The attribute list buffer.

    Raises:
        OSError: When the list cannot be built.
    """
    size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attributes = ctypes.create_string_buffer(size.value)
    if not kernel32.InitializeProcThreadAttributeList(
        attributes, 1, 0, ctypes.byref(size)
    ):
        raise win32.last_error()
    # The attribute's value is the console handle itself.
    if not kernel32.UpdateProcThreadAttribute(
        attributes,
        0,
        win32.PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
        console,
        ctypes.sizeof(ctypes.c_void_p),
        None,
        None,
    ):
        raise win32.last_error()
    return attributes


def _start(kernel32, argv: list, attributes):
    """Start the shell suspended on the pseudo console.

    Args:
        kernel32: The bound kernel32.
        argv: Argument vector.
        attributes: The attribute list naming the console.

    Returns:
        The :class:`win32.ProcessInformation` of the started shell.

    Raises:
        OSError: When the shell cannot be started.
    """
    startup = win32.StartupInfoEx()
    startup.StartupInfo.cb = ctypes.sizeof(win32.StartupInfoEx)
    startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
    process = win32.ProcessInformation()
    # A parent whose standard handles are open hands the child copies of
    # them, and the child then reads and writes there rather than on the
    # pseudo console. They are set aside while the child is made and put
    # back after.
    held = [kernel32.GetStdHandle(name) for name in win32.STD_HANDLE_NAMES]
    for name in win32.STD_HANDLE_NAMES:
        kernel32.SetStdHandle(name, None)
    try:
        is_started = kernel32.CreateProcessW(
            None,
            subprocess.list2cmdline(argv),
            None,
            None,
            False,
            win32.EXTENDED_STARTUPINFO_PRESENT | win32.CREATE_SUSPENDED,
            None,
            None,
            ctypes.byref(startup),
            ctypes.byref(process),
        )
        error = None if is_started else win32.last_error()
    finally:
        for name, handle in zip(win32.STD_HANDLE_NAMES, held):
            kernel32.SetStdHandle(name, handle)
    if error is not None:
        raise error
    return process


def _kill_on_close_job(kernel32):
    """A job object that ends every process in it when its last handle closes.

    Args:
        kernel32: The bound kernel32.

    Returns:
        The job handle.

    Raises:
        OSError: When the job cannot be made or limited.
    """
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise win32.last_error()
    limits = win32.JobObjectExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        win32.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        kernel32.CloseHandle(job)
        raise win32.last_error()
    return job
