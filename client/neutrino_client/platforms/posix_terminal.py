"""This process's own terminal in raw mode, on Linux and macOS.

Every key goes through as it is typed, Ctrl-C and Ctrl-D among them, so the
remote shell sees them; the mode the terminal had is put back on the way
out, whatever ended the run. A size change arrives as ``SIGWINCH``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import shutil
import signal
import sys

try:
    import termios
    import tty
except ImportError:  # Windows has no termios.
    termios = None
    tty = None

from neutrino_client.exceptions import PlatformUnsupportedError

POSIX_READ_BYTES = 4096


class PosixRawTerminal:
    """Standard input in raw mode for the length of a ``with`` block."""

    def __init__(
        self, *, stdin_fd: "int | None" = None, stdout_fd: "int | None" = None
    ):
        """
        Args:
            stdin_fd: The terminal read from; None is standard input.
            stdout_fd: The terminal written to; None is standard output.
        """
        self._stdin_fd = sys.stdin.fileno() if stdin_fd is None else stdin_fd
        self._stdout_fd = sys.stdout.fileno() if stdout_fd is None else stdout_fd
        self._saved = None
        self._previous_handler = None

    def __enter__(self) -> "PosixRawTerminal":
        """Put the terminal in raw mode.

        Raises:
            PlatformUnsupportedError: Where there is no termios, or standard
                input is not a terminal.
        """
        if termios is None or not os.isatty(self._stdin_fd):
            raise PlatformUnsupportedError("standard input is not a terminal")
        self._saved = termios.tcgetattr(self._stdin_fd)
        tty.setraw(self._stdin_fd)
        return self

    def __exit__(self, *_exc) -> None:
        """Put the terminal's own mode and the size handler back."""
        if self._saved is not None:
            termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, self._saved)
            self._saved = None
        if self._previous_handler is not None:
            signal.signal(signal.SIGWINCH, self._previous_handler)
            self._previous_handler = None

    def read(self) -> bytes:
        """The next keys typed, empty once input ends."""
        try:
            return os.read(self._stdin_fd, POSIX_READ_BYTES)
        except OSError:
            return b""

    def write(self, data: bytes) -> None:
        """Put bytes on the terminal.

        Args:
            data: The bytes.
        """
        view = memoryview(data)
        while view:
            written = os.write(self._stdout_fd, view)
            view = view[written:]

    def on_resize(self, callback) -> None:
        """Be told the terminal's new size whenever it changes.

        Called on the main thread, which is where a signal handler lives.

        Args:
            callback: ``callback(cols, rows)``.
        """

        def resized(_signum, _frame) -> None:
            size = shutil.get_terminal_size()
            callback(size.columns, size.lines)

        self._previous_handler = signal.signal(signal.SIGWINCH, resized)
