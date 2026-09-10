"""Running a console tool on a pseudo console, and answering its one prompt.

A tool that asks a yes-or-no question on its terminal and takes no flag in
its place is given a pseudo console here, and the answer. The child attaches
to the console only when this process hands down no standard handles of its
own; the resident is ``pythonw`` and has none, so the question lands on the
console where the answer can meet it.

The reader stops as soon as the child has exited and its last bytes are
drained: the output pipe itself does not end until the console is closed,
which is after the run returns, so waiting for the pipe's end would wait the
whole timeout every time.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes
import subprocess
import threading
import time

from neutrino_client.platforms import win32
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.base import answer_on_prompt

CONSOLE_COLUMNS = 120
CONSOLE_ROWS = 40
CONSOLE_READ_POLL_S = 0.05
CONSOLE_PIPE_BUFFER = 4096


class WindowsConsoleApi:
    """The pseudo console the Windows platform answers a prompt on."""

    def run(
        self, argv: list, *, prompt: str, answer: str, timeout_s: float
    ) -> "tuple[int, str]":
        """Run a program on a pseudo console and answer one prompt.

        Args:
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long the whole run may take.

        Returns:
            ``(returncode, output)``.

        Raises:
            PlatformUnsupportedError: When this Windows has no pseudo console.
            OSError: When a console call is refused.
        """
        kernel32 = win32.libraries().kernel32
        if not hasattr(kernel32, "CreatePseudoConsole"):
            raise PlatformUnsupportedError("no pseudo console on this Windows")

        console_input, input_writer = _pipe(kernel32)
        output_reader, console_output = _pipe(kernel32)
        console = ctypes.c_void_p()
        result = kernel32.CreatePseudoConsole(
            win32.Coord(CONSOLE_COLUMNS, CONSOLE_ROWS),
            console_input,
            console_output,
            0,
            ctypes.byref(console),
        )
        if result != 0:
            raise OSError(result, "CreatePseudoConsole failed")
        # The console holds its own ends of the pipes from here on.
        kernel32.CloseHandle(console_input)
        kernel32.CloseHandle(console_output)

        attributes = _attribute_list(kernel32, console)
        process = _start(kernel32, argv, attributes, console)

        chunks: list = []
        is_pipe_closed = threading.Event()

        def pump() -> None:
            buffer = ctypes.create_string_buffer(CONSOLE_PIPE_BUFFER)
            read = ctypes.c_ulong(0)
            while kernel32.ReadFile(
                output_reader, buffer, CONSOLE_PIPE_BUFFER, ctypes.byref(read), None
            ):
                if read.value == 0:
                    break
                chunks.append(buffer.raw[: read.value])
            is_pipe_closed.set()

        reader = threading.Thread(target=pump, name="client_console", daemon=True)
        reader.start()
        taken = 0

        def has_exited() -> bool:
            return (
                kernel32.WaitForSingleObject(process.hProcess, 0) == win32.WAIT_OBJECT_0
            )

        def read(wait_s: float):
            nonlocal taken
            deadline = time.monotonic() + wait_s
            while len(chunks) == taken:
                if is_pipe_closed.is_set():
                    break
                # The pipe ends only when the console is closed, after this
                # run; the child exiting is the end of anything to read.
                if has_exited() and len(chunks) == taken:
                    return b""
                if time.monotonic() >= deadline:
                    return None
                time.sleep(CONSOLE_READ_POLL_S)
            if len(chunks) == taken:
                return b""
            chunk = chunks[taken]
            taken += 1
            return chunk

        def write(data: bytes) -> None:
            written = ctypes.c_ulong(0)
            kernel32.WriteFile(
                input_writer, data, len(data), ctypes.byref(written), None
            )

        try:
            output = answer_on_prompt(
                read,
                write,
                prompt=prompt,
                answer=answer,
                deadline=time.monotonic() + timeout_s,
            )
            if kernel32.WaitForSingleObject(process.hProcess, int(timeout_s * 1000)):
                kernel32.TerminateProcess(process.hProcess, 1)
            code = ctypes.c_ulong(0)
            kernel32.GetExitCodeProcess(process.hProcess, ctypes.byref(code))
        finally:
            kernel32.ClosePseudoConsole(console)
            kernel32.DeleteProcThreadAttributeList(attributes)
            for handle in (
                input_writer,
                output_reader,
                process.hThread,
                process.hProcess,
            ):
                kernel32.CloseHandle(handle)
        return int(code.value), output.decode("utf-8", "replace")


def _pipe(kernel32) -> "tuple":
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
        raise ctypes.WinError(ctypes.get_last_error())
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
        raise ctypes.WinError(ctypes.get_last_error())
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
        raise ctypes.WinError(ctypes.get_last_error())
    return attributes


def _start(kernel32, argv: list, attributes, console):
    """Start the child on the pseudo console.

    Args:
        kernel32: The bound kernel32.
        argv: Argument vector.
        attributes: The attribute list naming the console.
        console: The pseudo console handle, closed on failure.

    Returns:
        The :class:`win32.ProcessInformation` of the started child.

    Raises:
        OSError: When the child cannot be started.
    """
    startup = win32.StartupInfoEx()
    startup.StartupInfo.cb = ctypes.sizeof(win32.StartupInfoEx)
    startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
    process = win32.ProcessInformation()
    if not kernel32.CreateProcessW(
        None,
        subprocess.list2cmdline(argv),
        None,
        None,
        False,
        win32.EXTENDED_STARTUPINFO_PRESENT,
        None,
        None,
        ctypes.byref(startup),
        ctypes.byref(process),
    ):
        error = ctypes.get_last_error()
        kernel32.ClosePseudoConsole(console)
        raise ctypes.WinError(error)
    return process
