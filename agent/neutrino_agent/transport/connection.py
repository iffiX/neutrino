"""One connection to the transport's listener: a Unix socket, or a named pipe.

Every local connection carries one thread reading and another writing: the
control connection's reader takes lines while commands go out, and a
stream's reader takes records while its handler sends. A Unix socket does
that as it is. A Windows named pipe opened for synchronous use lets one
call wait on the other, so the pipe is opened overlapped through
``_winapi``, as :mod:`multiprocessing.connection` opens its own.

Not pure: opens sockets and pipes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import socket
import threading
import time

from neutrino_agent.transport.constants import (
    TRANSPORT_LINE_BYTES_MAX,
    TRANSPORT_PIPE_PREFIX,
)

try:
    import _winapi
except ImportError:  # Only Windows has it.
    _winapi = None

# How long a pipe that is busy is waited for, and how often a pending read
# looks whether its connection was closed.
PIPE_BUSY_WAIT_MS = 1000
PIPE_WAIT_SLICE_MS = 500
# Win32 codes a pipe answers with, beside the ones ``_winapi`` names.
ERROR_PIPE_BUSY = 231
ERROR_SEM_TIMEOUT = 121
ERROR_BROKEN_PIPE = 109
ERROR_NO_DATA = 232
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_OPERATION_ABORTED = 995
PIPE_ENDED_CODES = (
    ERROR_BROKEN_PIPE,
    ERROR_NO_DATA,
    ERROR_PIPE_NOT_CONNECTED,
    ERROR_OPERATION_ABORTED,
)


def open_local(listen: str, *, timeout_s: float = 5.0):
    """A new connection to the transport's listener.

    Args:
        listen: The socket's path, or the pipe's name starting
            ``\\\\.\\pipe\\``.
        timeout_s: How long a busy pipe is waited for.

    Returns:
        :class:`LocalSocketConnection` or :class:`WindowsPipeConnection`.

    Raises:
        OSError: When nothing listens there, or the caller is refused.
    """
    if listen.startswith(TRANSPORT_PIPE_PREFIX):
        return WindowsPipeConnection(listen, timeout_s=timeout_s)
    return LocalSocketConnection(listen)


class LocalSocketConnection:
    """A connection to a Unix socket."""

    def __init__(self, path: str, *, sock=None):
        """
        Args:
            path: The socket's path.
            sock: An already connected socket, which a test hands in; None
                connects to ``path``.

        Raises:
            OSError: When nothing listens there.
        """
        if sock is None:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(path)
            except OSError:
                sock.close()
                raise
        self._socket = sock

    def sendall(self, data: bytes) -> None:
        """Write every byte.

        Raises:
            OSError: When the connection is gone.
        """
        self._socket.sendall(data)

    def recv(self, size: int) -> bytes:
        """Read what is there, up to ``size`` bytes; empty at the end.

        Raises:
            OSError: When the connection fails.
        """
        return self._socket.recv(size)

    def close(self) -> None:
        """Close it, waking a thread that waits in :meth:`recv`."""
        with contextlib.suppress(OSError):
            self._socket.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            self._socket.close()


class WindowsPipeConnection:
    """A connection to a named pipe, read and written overlapped."""

    def __init__(self, name: str, *, timeout_s: float = 5.0, api=None):
        """
        Args:
            name: The pipe's name.
            timeout_s: How long a busy pipe is waited for.
            api: The ``_winapi`` module; None takes the real one.

        Raises:
            OSError: When the pipe cannot be opened.
        """
        self._api = api if api is not None else _winapi
        if self._api is None:
            raise OSError("named pipes are Windows'")
        self._lock = threading.Lock()
        self._is_closed = False
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                self._handle = self._api.CreateFile(
                    name,
                    self._api.GENERIC_READ | self._api.GENERIC_WRITE,
                    0,
                    self._api.NULL,
                    self._api.OPEN_EXISTING,
                    self._api.FILE_FLAG_OVERLAPPED,
                    self._api.NULL,
                )
                return
            except OSError as error:
                code = getattr(error, "winerror", 0)
                if code not in (ERROR_PIPE_BUSY, ERROR_SEM_TIMEOUT):
                    raise
                if time.monotonic() >= deadline:
                    raise
                with contextlib.suppress(OSError):
                    self._api.WaitNamedPipe(name, PIPE_BUSY_WAIT_MS)

    def sendall(self, data: bytes) -> None:
        """Write every byte.

        Raises:
            OSError: When the pipe is gone.
        """
        view = memoryview(bytes(data))
        while view:
            written = self._overlapped(False, bytes(view))
            if not written:
                raise BrokenPipeError("the transport's pipe is closed")
            view = view[written:]

    def recv(self, size: int) -> bytes:
        """Read what is there, up to ``size`` bytes; empty at the end.

        Raises:
            OSError: When the pipe fails other than by ending.
        """
        try:
            return self._overlapped(True, min(size, TRANSPORT_LINE_BYTES_MAX))
        except OSError as error:
            if getattr(error, "winerror", 0) in PIPE_ENDED_CODES or self._is_closed:
                return b""
            raise

    def close(self) -> None:
        """Close the pipe; a read waiting on it ends empty."""
        with self._lock:
            if self._is_closed:
                return
            self._is_closed = True
        with contextlib.suppress(OSError):
            self._api.CloseHandle(self._handle)

    def _overlapped(self, is_read: bool, argument):
        """One overlapped read or write, waited for in slices so a close ends it.

        Args:
            is_read: A read of up to ``argument`` bytes, else a write of
                ``argument``.
            argument: The size to read, or the bytes to write.

        Returns:
            The bytes read for a read, the count written for a write.

        Raises:
            OSError: When the call fails, or the pipe was closed meanwhile.
        """
        if self._is_closed:
            raise BrokenPipeError("the transport's pipe is closed")
        call = self._api.ReadFile if is_read else self._api.WriteFile
        overlapped, error = call(self._handle, argument, overlapped=True)
        try:
            if error == self._api.ERROR_IO_PENDING:
                while True:
                    waited = self._api.WaitForMultipleObjects(
                        [overlapped.event], False, PIPE_WAIT_SLICE_MS
                    )
                    if waited == self._api.WAIT_OBJECT_0:
                        break
                    if self._is_closed:
                        overlapped.cancel()
                        break
        finally:
            count, error = overlapped.GetOverlappedResult(True)
        if error and error != self._api.ERROR_MORE_DATA:
            failure = OSError(f"the transport's pipe answered {error}")
            failure.winerror = error
            raise failure
        if is_read:
            return bytes(overlapped.getbuffer())
        return count
