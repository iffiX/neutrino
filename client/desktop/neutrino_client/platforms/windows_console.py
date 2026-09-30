"""Running a console tool on a pseudo console, answering its one prompt, and
this process's own console in raw mode.

A tool that asks a yes-or-no question on its terminal and takes no flag in
its place is given a pseudo console here, and the answer. A parent's open
standard handles are handed to the child in the console's place, and a
windowed program's are open on NUL, so they are set aside while the child
is made: the question then lands on the console where the answer can meet
it. Measured on Windows 11 with the compiled resident, 2026-09-23: with the
handles left in place the console received nothing and the tool's question
went to NUL.

The reader stops as soon as the child has exited and its last bytes are
drained: the output pipe itself does not end until the console is closed,
which is after the run returns, so waiting for the pipe's end would wait the
whole timeout every time. A prompt that has not shown within
``CLIENT_PROMPT_TIMEOUT_S`` ends the reading, and a child still there
``CLIENT_PROMPT_EXIT_TIMEOUT_S`` after the reading ended is terminated.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import threading
import time

from neutrino_client.constants import (
    CLIENT_PROMPT_EXIT_TIMEOUT_S,
    CLIENT_PROMPT_TIMEOUT_S,
)
from neutrino_client.platforms import win32
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.base import answer_on_prompt

# How often a raw console looks at its own size.
CONSOLE_SIZE_POLL_S = 0.5
# How many UTF-16 units one read of a raw console takes.
CONSOLE_READ_UNITS = 1024
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
            started = time.monotonic()
            output = answer_on_prompt(
                read,
                write,
                prompt=prompt,
                answer=answer,
                deadline=started + timeout_s,
                prompt_deadline=started + min(timeout_s, CLIENT_PROMPT_TIMEOUT_S),
            )
            code = exit_code_after(
                kernel32, process.hProcess, CLIENT_PROMPT_EXIT_TIMEOUT_S
            )
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
        return code, output.decode("utf-8", "replace")


def exit_code_after(kernel32, process_handle, wait_s: float) -> int:
    """A child's exit code, the child terminated when it has not exited in time.

    Args:
        kernel32: The bound kernel32.
        process_handle: The child's process handle.
        wait_s: How long its exit is waited for.

    Returns:
        The exit code; 1 for a child terminated here.
    """
    waited = kernel32.WaitForSingleObject(process_handle, int(wait_s * 1000))
    if waited != win32.WAIT_OBJECT_0:
        kernel32.TerminateProcess(process_handle, 1)
    code = ctypes.c_ulong(0)
    kernel32.GetExitCodeProcess(process_handle, ctypes.byref(code))
    return int(code.value)


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
    # A parent whose standard handles are open hands the child copies of
    # them, and the child then reads and writes there rather than on the
    # pseudo console; a windowed program's are open on NUL. They are set
    # aside while the child is made and put back after, so the console's
    # own handles are the ones the child is born with.
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
            win32.EXTENDED_STARTUPINFO_PRESENT,
            None,
            None,
            ctypes.byref(startup),
            ctypes.byref(process),
        )
        error = 0 if is_started else ctypes.get_last_error()
    finally:
        for name, handle in zip(win32.STD_HANDLE_NAMES, held):
            kernel32.SetStdHandle(name, handle)
    if not is_started:
        kernel32.ClosePseudoConsole(console)
        raise ctypes.WinError(error)
    return process


class WindowsRawConsole:
    """This process's console in raw VT mode for the length of a ``with`` block.

    Keys arrive as the VT sequences a remote shell reads; output is drawn as
    VT; the size is looked at every ``CONSOLE_SIZE_POLL_S``, since a console
    sends no signal for it.
    """

    def __init__(self, *, kernel32=None):
        """
        Args:
            kernel32: The bound kernel32; None binds the real one on entry.
        """
        self._kernel32 = kernel32
        self._input = None
        self._output = None
        self._saved: "tuple | None" = None
        self._stop = threading.Event()

    def __enter__(self) -> "WindowsRawConsole":
        """Set both modes, keeping the old ones.

        Raises:
            PlatformUnsupportedError: When there is no console to set.
        """
        if self._kernel32 is None:
            try:
                self._kernel32 = win32.libraries().kernel32
            except OSError as error:
                raise PlatformUnsupportedError(str(error))
        self._input = self._kernel32.GetStdHandle(win32.STD_INPUT_HANDLE)
        self._output = self._kernel32.GetStdHandle(win32.STD_OUTPUT_HANDLE)
        input_mode = ctypes.c_ulong(0)
        output_mode = ctypes.c_ulong(0)
        if not self._kernel32.GetConsoleMode(
            self._input, ctypes.byref(input_mode)
        ) or not self._kernel32.GetConsoleMode(self._output, ctypes.byref(output_mode)):
            raise PlatformUnsupportedError("standard input is not a console")
        self._saved = (input_mode.value, output_mode.value)
        raw_input = (
            input_mode.value
            & ~(
                win32.ENABLE_LINE_INPUT
                | win32.ENABLE_ECHO_INPUT
                | win32.ENABLE_PROCESSED_INPUT
            )
        ) | win32.ENABLE_VIRTUAL_TERMINAL_INPUT
        raw_output = (
            output_mode.value
            | win32.ENABLE_VIRTUAL_TERMINAL_PROCESSING
            | win32.ENABLE_PROCESSED_OUTPUT
        )
        self._kernel32.SetConsoleMode(self._input, raw_input)
        self._kernel32.SetConsoleMode(self._output, raw_output)
        return self

    def __exit__(self, *_exc) -> None:
        """Put both modes back and stop looking at the size."""
        self._stop.set()
        if self._saved is not None:
            self._kernel32.SetConsoleMode(self._input, self._saved[0])
            self._kernel32.SetConsoleMode(self._output, self._saved[1])
            self._saved = None

    def read(self) -> bytes:
        """The next keys typed, as UTF-8; empty once the console is gone."""
        buffer = ctypes.create_unicode_buffer(CONSOLE_READ_UNITS)
        count = ctypes.c_ulong(0)
        if not self._kernel32.ReadConsoleW(
            self._input, buffer, CONSOLE_READ_UNITS, ctypes.byref(count), None
        ):
            return b""
        return buffer[: count.value].encode("utf-8", "surrogatepass")

    def write(self, data: bytes) -> None:
        """Put bytes on the console.

        Args:
            data: VT-encoded UTF-8.
        """
        stream = getattr(sys.stdout, "buffer", None)
        if stream is None:
            return
        stream.write(data)
        stream.flush()

    def on_resize(self, callback) -> None:
        """Be told the console's new size whenever it changes.

        Args:
            callback: ``callback(cols, rows)``, called on a thread of its own.
        """
        threading.Thread(target=self._watch_size, args=(callback,), daemon=True).start()

    def _watch_size(self, callback) -> None:
        size = shutil.get_terminal_size()
        while not self._stop.wait(CONSOLE_SIZE_POLL_S):
            current = shutil.get_terminal_size()
            if current != size:
                size = current
                callback(size.columns, size.lines)
