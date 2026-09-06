"""The control channel's Windows transport: a named pipe, same handler set.

On Windows the control socket is a named pipe. This module shapes a pipe
handle like an accepted socket, so ``_ControlRequestHandler`` serves it
unchanged, and the platform reads the peer's identity from pipe
impersonation through the connection's ``pipe_handle``. Every Win32 call
rides one seam class, so nothing here needs Windows to import or to test.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import io
import threading
import time

# One pipe instance per client, like one accepted socket per client.
PIPE_BUFFER_BYTES = 64 * 1024
PIPE_UNLIMITED_INSTANCES = 255
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_NO_DATA = 232
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
# As the unsigned value a c_void_p restype hands back.
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# Any local account may connect, as with the 0666 control socket; the
# identity is read from impersonation, never assumed from the connect.
PIPE_SECURITY_SDDL = "D:(A;;GRGW;;;WD)(A;;FA;;;SY)(A;;FA;;;BA)"

# How long the accept loop waits after a failed ConnectNamedPipe before
# trying again with a fresh instance.
PIPE_RETRY_DELAY_S = 0.5


def open_pipe_connection(pipe_name: str, *, api=None) -> "PipeConnection":
    """Dial the agent's control pipe as a client.

    Args:
        pipe_name: The pipe to open.
        api: The Win32 seam; None uses the real one.

    Returns:
        A connection the HTTP client machinery can use.

    Raises:
        OSError: When nothing answers on the pipe.
    """
    pipe_api = api if api is not None else Win32PipeApi()
    handle = pipe_api.open_client(pipe_name)
    return PipeConnection(api=pipe_api, handle=handle, is_server_end=False)


class Win32PipeApi:
    """The Win32 named-pipe calls, one seam the tests replace whole."""

    def __init__(self):
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        # Handles are pointers: without these prototypes a 64-bit handle
        # comes back truncated to an int.
        self._kernel32.CreateNamedPipeW.restype = ctypes.c_void_p
        self._kernel32.CreateFileW.restype = ctypes.c_void_p
        for name in (
            "ConnectNamedPipe",
            "FlushFileBuffers",
            "DisconnectNamedPipe",
            "CloseHandle",
        ):
            getattr(self._kernel32, name).argtypes = [ctypes.c_void_p]
        self._kernel32.ConnectNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._kernel32.ReadFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._kernel32.WriteFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._security = None

    def create_instance(self, pipe_name: str) -> int:
        """Create one server instance of the pipe, open to every account.

        Args:
            pipe_name: The pipe name.

        Returns:
            The instance handle.

        Raises:
            OSError: When the pipe cannot be created.
        """
        handle = self._kernel32.CreateNamedPipeW(
            pipe_name,
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES,
            PIPE_BUFFER_BYTES,
            PIPE_BUFFER_BYTES,
            0,
            ctypes.byref(self._security_attributes()),
        )
        if not handle or handle == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def wait_for_client(self, handle: int) -> bool:
        """Block until a client connects to this instance.

        Args:
            handle: The instance handle.

        Returns:
            True when a client is connected.
        """
        if self._kernel32.ConnectNamedPipe(handle, None):
            return True
        return ctypes.get_last_error() == ERROR_PIPE_CONNECTED

    def open_client(self, pipe_name: str) -> int:
        """Open the pipe as a client.

        Args:
            pipe_name: The pipe name.

        Returns:
            The client handle.

        Raises:
            OSError: When the pipe cannot be opened.
        """
        handle = self._kernel32.CreateFileW(
            pipe_name,
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if not handle or handle == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def read(self, handle: int, size: int) -> bytes:
        """Read up to ``size`` bytes; a broken pipe reads as end of stream.

        Args:
            handle: The pipe handle.
            size: The most to read.

        Returns:
            The bytes read, empty at end of stream.
        """
        buffer = ctypes.create_string_buffer(size)
        read_count = ctypes.c_ulong(0)
        ok = self._kernel32.ReadFile(
            handle, buffer, size, ctypes.byref(read_count), None
        )
        if not ok:
            if ctypes.get_last_error() in (ERROR_BROKEN_PIPE, ERROR_NO_DATA):
                return b""
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw[: read_count.value]

    def write(self, handle: int, data: bytes) -> None:
        """Write all the bytes.

        Args:
            handle: The pipe handle.
            data: What to write.

        Raises:
            OSError: When the pipe refuses the write.
        """
        view = memoryview(data)
        while view:
            written = ctypes.c_ulong(0)
            ok = self._kernel32.WriteFile(
                handle, bytes(view), len(view), ctypes.byref(written), None
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
            view = view[written.value :]

    def disconnect(self, handle: int) -> None:
        """Flush and disconnect a served client. Best-effort."""
        self._kernel32.FlushFileBuffers(handle)
        self._kernel32.DisconnectNamedPipe(handle)

    def close(self, handle: int) -> None:
        """Close a handle. Best-effort."""
        self._kernel32.CloseHandle(handle)

    def _security_attributes(self):
        """Security attributes whose descriptor lets any account connect.

        Built once and kept: the descriptor must outlive every instance
        created with it.
        """
        if self._security is not None:
            return self._security
        convert = self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        descriptor = ctypes.c_void_p()
        if not convert(PIPE_SECURITY_SDDL, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = _SecurityAttributes()
        attributes.nLength = ctypes.sizeof(attributes)
        attributes.lpSecurityDescriptor = descriptor
        attributes.bInheritHandle = 0
        self._security = attributes
        return attributes


class PipeConnection:
    """One pipe end, shaped like the socket the request handler expects."""

    def __init__(self, *, api, handle: int, is_server_end: bool = True):
        """
        Args:
            api: The Win32 seam.
            handle: The pipe handle this connection owns.
            is_server_end: Whether closing should disconnect the instance.
        """
        self.pipe_handle = handle
        self._api = api
        self._is_server_end = is_server_end
        self._is_closed = False
        # http.client closes the connection on an HTTP/1.0 reply before the
        # body is read; each makefile wrapper is counted here so the handle
        # outlives that close until the last reader closes, the way
        # socket.socket's _io_refs keep a SocketIO readable past close.
        self._io_refs = 0
        self._is_handle_closed = False

    def settimeout(self, value) -> None:
        """Accepted for socket shape; a blocking pipe carries no deadline."""

    def makefile(self, mode: str = "rb", buffering: int = -1):
        """A buffered reader over the pipe, for the handler's ``rfile``.

        Args:
            mode: Only binary reading is served.
            buffering: Buffer size; non-positive uses the default.

        Returns:
            The buffered stream.
        """
        self._io_refs += 1
        stream = _PipeStream(connection=self, api=self._api, handle=self.pipe_handle)
        size = buffering if buffering and buffering > 0 else io.DEFAULT_BUFFER_SIZE
        return io.BufferedReader(stream, size)

    def sendall(self, data: bytes) -> None:
        """Write all the bytes to the peer.

        Args:
            data: What to send.
        """
        self._api.write(self.pipe_handle, bytes(data))

    def shutdown(self, how) -> None:
        """Accepted for socket shape; the close does the disconnecting."""

    def close(self) -> None:
        """Close the handle once the last makefile wrapper is also closed."""
        if self._is_closed:
            return
        self._is_closed = True
        if self._io_refs <= 0:
            self._close_handle()

    def decref(self) -> None:
        """Drop one makefile wrapper; close the handle when both are gone."""
        if self._io_refs > 0:
            self._io_refs -= 1
        if self._is_closed and self._io_refs <= 0:
            self._close_handle()

    def _close_handle(self) -> None:
        """Disconnect a served client and close the handle, at most once."""
        if self._is_handle_closed:
            return
        self._is_handle_closed = True
        if self._is_server_end:
            self._api.disconnect(self.pipe_handle)
        self._api.close(self.pipe_handle)


class ControlPipeHttpServer:
    """Serves the shared control handler set over a named pipe.

    The shape mirrors what ``ControlServer`` asks of an ``HTTPServer``:
    ``serve_forever``, ``shutdown``, ``server_close``, and the control
    attributes it sets are read back by the handler through ``self.server``.
    """

    def __init__(self, pipe_name: str, handler_class, *, api=None):
        """
        Args:
            pipe_name: The pipe to serve on.
            handler_class: The request handler both transports share.
            api: The Win32 seam; None uses the real one.
        """
        self._pipe_name = pipe_name
        self._handler_class = handler_class
        self._api = api if api is not None else Win32PipeApi()
        self._is_stopping = False
        # Probed at start the way a bind is: a name nobody may create
        # raises here rather than inside serve_forever's thread.
        probe = self._api.create_instance(pipe_name)
        self._standing_instance: "int | None" = probe

    def serve_forever(self) -> None:
        """Accept clients one instance at a time until shut down."""
        while not self._is_stopping:
            handle = self._take_instance()
            if handle is None:
                break
            if not self._api.wait_for_client(handle):
                self._api.close(handle)
                if not self._is_stopping:
                    time.sleep(PIPE_RETRY_DELAY_S)
                continue
            if self._is_stopping:
                self._api.close(handle)
                break
            threading.Thread(
                target=self._serve_one, args=(handle,), daemon=True
            ).start()

    def shutdown(self) -> None:
        """Stop accepting; a waiting instance is woken by a dialed client."""
        self._is_stopping = True
        try:
            self._api.close(self._api.open_client(self._pipe_name))
        except OSError:
            pass

    def server_close(self) -> None:
        """Close the instance still waiting, if any."""
        instance = self._standing_instance
        self._standing_instance = None
        if instance is not None:
            self._api.close(instance)

    def _take_instance(self) -> "int | None":
        """The instance to accept on next, created fresh when needed."""
        instance = self._standing_instance
        self._standing_instance = None
        if instance is not None:
            return instance
        try:
            return self._api.create_instance(self._pipe_name)
        except OSError:
            return None

    def _serve_one(self, handle: int) -> None:
        """Run the shared handler over one connected client."""
        connection = PipeConnection(api=self._api, handle=handle)
        try:
            self._handler_class(connection, ("pipe", 0), self)
        except Exception:  # noqa: BLE001 - one client must not kill the server
            pass
        finally:
            connection.close()


class _SecurityAttributes(ctypes.Structure):
    """The SECURITY_ATTRIBUTES a pipe instance is created with."""

    _fields_ = [
        ("nLength", ctypes.c_ulong),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
    ]


class _PipeStream(io.RawIOBase):
    """A raw stream over a pipe handle; the connection owns the handle."""

    def __init__(self, *, connection, api, handle: int):
        """
        Args:
            connection: The pipe connection whose reference count this holds.
            api: The Win32 seam.
            handle: The pipe handle to read.
        """
        super().__init__()
        self._connection = connection
        self._api = api
        self._handle = handle

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        data = self._api.read(self._handle, len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def close(self) -> None:
        """Release the connection's reference before closing the stream."""
        if self.closed:
            return
        super().close()
        connection = self._connection
        self._connection = None
        if connection is not None:
            connection.decref()
