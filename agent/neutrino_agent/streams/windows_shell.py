"""PowerShell on a Windows pseudo console, over one stream.

Two anonymous pipes carry the console's input and output, and the console is
created at the size the hub opened the stream with. PowerShell is started
suspended on it, in the console account's profile directory or the system
drive's root, with the agent's own standard handles set aside so the
child is born with the console's, put into a job object that kills every
process in it when its last handle closes, and then resumed. The console's
output is read and sent up, no faster than the hub's credit; the hub's bytes
are written to the console's input, a resize resizes the console, and ending
the shell terminates it. Once the shell exits the console is closed, which
ends its output. The shell is a
:class:`~neutrino_agent.streams.shell_session.ShellSession`, kept by id when
the stream's open names one.

Windows 10 1809 is the first with a pseudo console; an older Windows refuses
the stream with ``unsupported_platform``.

Not pure: starts processes and owns handles.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ctypes
import queue
import subprocess
import threading
import time

from neutrino_agent.constants import (
    AGENT_ANSWER_PROMPT_TIMEOUT_S,
    AGENT_SHELL_COMMANDS,
    AGENT_SHELL_KILL_TIMEOUT_S,
    AGENT_SHELL_READ_BYTES,
    AGENT_SHELL_WINDOWS_ACCOUNT,
)
from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.answered_run import answer_on_prompt
from neutrino_agent.platforms.windows import WindowsPlatform
from neutrino_agent.streams.shell_session import SessionShellStream, ShellSession

# How long the wait for the shell's exit sleeps before looking again.
WINDOWS_SHELL_POLL_MS = 500
# The exit code a shell that was ended is terminated with.
WINDOWS_SHELL_TERMINATED_CODE = 1
# The size of the console a question is answered on.
WINDOWS_ANSWER_COLUMNS = 120
WINDOWS_ANSWER_ROWS = 40


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


def _start(kernel32, argv: list, attributes, start_dir: str):
    """Start the shell suspended on the pseudo console.

    Args:
        kernel32: The bound kernel32.
        argv: Argument vector.
        attributes: The attribute list naming the console.
        start_dir: The shell's working directory.

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
            start_dir,
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


class ConsoleTerminal:
    """PowerShell, or another program, on a pseudo console."""

    def __init__(
        self,
        kernel32,
        *,
        cols: int,
        rows: int,
        start_dir: str,
        argv: "list | None" = None,
    ):
        """
        Args:
            kernel32: The bound kernel32.
            cols: The console's first width.
            rows: The console's first height.
            start_dir: The program's working directory.
            argv: The program; None is the shell.
        """
        self._kernel32 = kernel32
        self._start_dir = start_dir
        self._argv = list(argv) if argv else list(AGENT_SHELL_COMMANDS["win32"])
        self._columns = cols
        self._rows = rows
        self._console = None
        self._process = None
        self._attributes = None
        self._job = None
        self._input_writer = None
        self._output_reader = None
        self._exit_code = WINDOWS_SHELL_TERMINATED_CODE
        self._waiter: "threading.Thread | None" = None

    def start(self) -> None:
        """Make the console, start PowerShell on it in its job, resume it.

        Raises:
            OSError: When the console or the shell cannot be made.
        """
        kernel32 = self._kernel32
        console_input, self._input_writer = _pipe(kernel32)
        self._output_reader, console_output = _pipe(kernel32)
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
            self._release()
            raise OSError(f"CreatePseudoConsole answered {result}")
        self._console = console
        try:
            self._attributes = _attribute_list(kernel32, console)
            self._process = _start(
                kernel32,
                self._argv,
                self._attributes,
                self._start_dir,
            )
            self._job = _kill_on_close_job(kernel32)
            kernel32.AssignProcessToJobObject(self._job, self._process.hProcess)
            kernel32.ResumeThread(self._process.hThread)
        except OSError:
            if self._process is not None:
                kernel32.TerminateProcess(self._process.hProcess, 1)
            self._release()
            raise
        self._waiter = threading.Thread(
            target=self._wait_for_exit, name="agent_shell_console_exit", daemon=True
        )
        self._waiter.start()

    def read(self) -> bytes:
        """The console's next output.

        Returns:
            The bytes; empty once the console closed.
        """
        buffer = ctypes.create_string_buffer(AGENT_SHELL_READ_BYTES)
        read = win32.DWORD(0)
        if not self._kernel32.ReadFile(
            self._output_reader,
            buffer,
            AGENT_SHELL_READ_BYTES,
            ctypes.byref(read),
            None,
        ):
            return b""
        return buffer.raw[: read.value]

    def write(self, data: bytes) -> None:
        """Type into the console.

        Args:
            data: The bytes.
        """
        _write(self._kernel32, self._input_writer, data)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the console.

        Args:
            cols: The width.
            rows: The height.
        """
        self._columns = max(1, int(cols))
        self._rows = max(1, int(rows))
        console = self._console
        if console is not None:
            self._kernel32.ResizePseudoConsole(
                console, win32.Coord(self._columns, self._rows)
            )

    def terminate(self) -> None:
        """End the shell; its job ends everything it started."""
        if self._process is not None:
            self._kernel32.TerminateProcess(
                self._process.hProcess, WINDOWS_SHELL_TERMINATED_CODE
            )

    def finish(self) -> int:
        """Release the console, the job and every handle.

        Returns:
            The shell's exit code.
        """
        if self._waiter is not None:
            self._waiter.join(timeout=AGENT_SHELL_KILL_TIMEOUT_S)
        self._release()
        return self._exit_code

    def _wait_for_exit(self) -> None:
        """Wait for the shell to exit, then close the console to end its output."""
        kernel32 = self._kernel32
        handle = self._process.hProcess
        while (
            kernel32.WaitForSingleObject(handle, WINDOWS_SHELL_POLL_MS)
            != win32.WAIT_OBJECT_0
        ):
            continue
        code = win32.DWORD(0)
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        self._exit_code = int(code.value)
        console, self._console = self._console, None
        if console is not None:
            kernel32.ClosePseudoConsole(console)

    def _release(self) -> None:
        """Close the job, which ends every process left in it, and the handles."""
        kernel32 = self._kernel32
        if self._job is not None:
            kernel32.CloseHandle(self._job)
            self._job = None
        if self._attributes is not None:
            kernel32.DeleteProcThreadAttributeList(self._attributes)
            self._attributes = None
        console, self._console = self._console, None
        if console is not None:
            kernel32.ClosePseudoConsole(console)
        handles = [self._input_writer, self._output_reader]
        process, self._process = self._process, None
        if process is not None:
            handles += [process.hThread, process.hProcess]
        self._input_writer = self._output_reader = None
        for handle in handles:
            if handle is not None:
                with contextlib.suppress(OSError):
                    kernel32.CloseHandle(handle)


def run_answering(
    argv: list,
    *,
    prompt: str,
    answer: str,
    timeout_s: float,
    start_dir: str,
    kernel32=None,
) -> tuple:
    """Run a program on a pseudo console of its own and answer one question.

    Args:
        argv: Argument vector.
        prompt: The text the answer follows.
        answer: The keystrokes to send; Enter on a console is a carriage
            return.
        timeout_s: How long the whole run may take.
        start_dir: The program's working directory.
        kernel32: The bound kernel32; None binds the real one.

    Returns:
        ``(returncode, output)``, the output as the console drew it.

    Raises:
        OSError: When the console or the program cannot be made.
    """
    kernel32 = kernel32 if kernel32 is not None else win32.libraries().kernel32
    terminal = ConsoleTerminal(
        kernel32,
        cols=WINDOWS_ANSWER_COLUMNS,
        rows=WINDOWS_ANSWER_ROWS,
        start_dir=start_dir,
        argv=argv,
    )
    terminal.start()
    chunks: "queue.Queue[bytes]" = queue.Queue()

    def pump() -> None:
        while True:
            chunk = terminal.read()
            chunks.put(chunk)
            if not chunk:
                return

    def read(wait_s: float):
        try:
            return chunks.get(timeout=wait_s)
        except queue.Empty:
            return None

    threading.Thread(target=pump, name="agent_answer_console", daemon=True).start()
    started = time.monotonic()
    try:
        output = answer_on_prompt(
            read,
            terminal.write,
            prompt=prompt,
            answer=answer,
            deadline=started + timeout_s,
            prompt_deadline=started + min(timeout_s, AGENT_ANSWER_PROMPT_TIMEOUT_S),
        )
    finally:
        terminal.terminate()
    return terminal.finish(), output.decode("utf-8", "replace")


class WindowsShellStream(SessionShellStream):
    """PowerShell on a pseudo console, kept by id when the open names one."""

    def __init__(
        self, channel, args: dict, *, kernel32=None, sessions=None, platform=None
    ):
        """
        Args:
            channel: The stream's channel.
            args: ``{"cols", "rows"}``, the console's first size, with
                ``session_id`` and ``is_resumed`` for a kept shell.
            kernel32: The bound kernel32; None binds the real one.
            sessions: The agent's shell registry; None keeps no shell past
                its stream.
            platform: Names the directory the shell starts in; None asks
                the Windows platform.
        """
        super().__init__(channel, args, sessions=sessions)
        self._kernel32 = kernel32
        self._platform = platform

    def _check_platform(self) -> None:
        """Refuse a Windows with no pseudo console, or no kernel32."""
        try:
            kernel32 = self._bound_kernel32()
        except (OSError, AttributeError):
            raise StreamRefused("unsupported_platform") from None
        if not hasattr(kernel32, "CreatePseudoConsole"):
            raise StreamRefused("unsupported_platform")

    def _make_session(self, *, on_change=None, on_end=None) -> ShellSession:
        return ShellSession(
            session_id=self._session_id,
            terminal=ConsoleTerminal(
                self._bound_kernel32(),
                cols=self._columns,
                rows=self._rows,
                start_dir=self._bound_platform().shell_start_dir(),
            ),
            account=AGENT_SHELL_WINDOWS_ACCOUNT,
            title=AGENT_SHELL_COMMANDS["win32"][0],
            on_change=on_change,
            on_end=on_end,
        )

    def _bound_platform(self):
        """The Windows platform, made on first use."""
        if self._platform is None:
            self._platform = WindowsPlatform()
        return self._platform

    def _bound_kernel32(self):
        """kernel32, bound on first use."""
        if self._kernel32 is None:
            self._kernel32 = win32.libraries().kernel32
        return self._kernel32
