"""The control channel's Windows transport: a named pipe, same handler set.

On Windows the control socket is a named pipe of the person's own. This
module shapes a pipe handle like an accepted socket, so the request handler
serves it unchanged, and the platform reads the peer's identity from pipe
impersonation through the connection's ``pipe_handle``. The pipe's security
descriptor names the current user's SID alone. Every Win32 call rides one
seam class, so nothing here needs Windows to import or to test.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes
import io
import threading
import time

from neutrino_client.platforms import win32

# How long the accept loop waits after a failed ConnectNamedPipe before
# trying again with a fresh instance.
PIPE_RETRY_DELAY_S = 0.5


def pipe_security_sddl(owner_sid: str) -> str:
    """The security descriptor a pipe instance is created with.

    Args:
        owner_sid: The current user's string SID.

    Returns:
        An SDDL granting full access to that SID and nobody else.
    """
    return f"D:(A;;GA;;;{owner_sid})"


def open_pipe_connection(pipe_name: str, *, api=None) -> "PipeConnection":
    """Dial the resident's control pipe as a client.

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
        """
        Raises:
            OSError: When the libraries cannot be loaded.
        """
        libraries = win32.libraries()
        self._kernel32 = libraries.kernel32
        self._advapi32 = libraries.advapi32
        self._security = None

    def create_instance(self, pipe_name: str, *, is_first: bool = False) -> int:
        """Create one server instance of the pipe, open to this user alone.

        Args:
            pipe_name: The pipe name.
            is_first: Refuse when the pipe already exists, so two residents
                cannot serve one person.

        Returns:
            The instance handle.

        Raises:
            OSError: When the pipe cannot be created.
        """
        open_mode = win32.PIPE_ACCESS_DUPLEX
        if is_first:
            open_mode |= win32.FILE_FLAG_FIRST_PIPE_INSTANCE
        handle = self._kernel32.CreateNamedPipeW(
            pipe_name,
            open_mode,
            win32.PIPE_TYPE_BYTE | win32.PIPE_WAIT,
            win32.PIPE_UNLIMITED_INSTANCES,
            win32.PIPE_BUFFER_BYTES,
            win32.PIPE_BUFFER_BYTES,
            0,
            ctypes.byref(self._security_attributes()),
        )
        if not handle or handle == win32.INVALID_HANDLE_VALUE:
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
        return ctypes.get_last_error() == win32.ERROR_PIPE_CONNECTED

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
            win32.GENERIC_READ | win32.GENERIC_WRITE,
            0,
            None,
            win32.OPEN_EXISTING,
            0,
            None,
        )
        if not handle or handle == win32.INVALID_HANDLE_VALUE:
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
            if ctypes.get_last_error() in (
                win32.ERROR_BROKEN_PIPE,
                win32.ERROR_NO_DATA,
            ):
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

    def current_user_sid(self) -> str:
        """This process's user, as a string SID.

        Returns:
            The SID.

        Raises:
            OSError: When the process token cannot be read.
        """
        token = ctypes.c_void_p()
        ok = self._advapi32.OpenProcessToken(
            self._kernel32.GetCurrentProcess(), win32.TOKEN_QUERY, ctypes.byref(token)
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            user = win32.TokenUser(advapi32=self._advapi32, token=token.value)
            string_sid = ctypes.c_wchar_p()
            if not self._advapi32.ConvertSidToStringSidW(
                ctypes.c_void_p(user.sid), ctypes.byref(string_sid)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                return string_sid.value or ""
            finally:
                self._kernel32.LocalFree(string_sid)
        finally:
            self._kernel32.CloseHandle(token)

    def _security_attributes(self):
        """Security attributes whose descriptor lets this user alone connect.

        Built once and kept: the descriptor must outlive every instance
        created with it.
        """
        if self._security is not None:
            return self._security
        convert = self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
        descriptor = ctypes.c_void_p()
        sddl = pipe_security_sddl(self.current_user_sid())
        if not convert(sddl, win32.SDDL_REVISION_1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = win32.SecurityAttributes()
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
        # Each makefile wrapper is counted here so the handle outlives an
        # http.client close until the last reader closes.
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
    """Serves the control handler set over a named pipe.

    The shape mirrors what ``ControlServer`` asks of an ``HTTPServer``:
    ``serve_forever``, ``shutdown``, ``server_close``, and the control
    attributes it sets are read back by the handler through ``self.server``.
    """

    def __init__(self, pipe_name: str, handler_class, *, api=None):
        """
        Args:
            pipe_name: The pipe to serve on.
            handler_class: The request handler.
            api: The Win32 seam; None uses the real one.

        Raises:
            OSError: When the pipe already exists or cannot be created.
        """
        self._pipe_name = pipe_name
        self._handler_class = handler_class
        self._api = api if api is not None else Win32PipeApi()
        self._is_stopping = False
        probe = self._api.create_instance(pipe_name, is_first=True)
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
        """Run the handler over one connected client."""
        connection = PipeConnection(api=self._api, handle=handle)
        try:
            self._handler_class(connection, ("pipe", 0), self)
        except Exception:  # noqa: BLE001 - one client must not kill the server
            pass
        finally:
            connection.close()


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
