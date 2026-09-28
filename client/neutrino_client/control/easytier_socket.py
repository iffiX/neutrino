"""The EasyTier daemon's local socket: one JSON request and one answer per connection.

A request is one line of JSON and so is its answer; the connection then
ends. On Linux and macOS the socket is a Unix socket every account may
open, mode 0666 like NetBird's; on Windows it is a named pipe whose security
descriptor admits SYSTEM, the administrators and the accounts logged on at
the machine, none of which may create an instance of it. What a request may
do is the daemon's to judge; nothing here reads who asked.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import errno
import json
import os
import socket
import socketserver
import threading

from neutrino_client.constants import (
    CLIENT_CONTROL_PIPE_PREFIX,
    CLIENT_EASYTIER_REQUEST_LIMIT_BYTES,
    CLIENT_EASYTIER_REQUEST_TIMEOUT_S,
)

# Full access for LocalSystem and the administrators; for interactive users,
# read and write but not FILE_CREATE_PIPE_INSTANCE, so none can stand up a
# pipe of the same name to take another account's request.
EASYTIER_PIPE_SDDL = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x12019b;;;IU)"
# Everyone may open the Unix socket, as NetBird's.
EASYTIER_SOCKET_MODE = 0o666


def _is_pipe(address: str) -> bool:
    return address.startswith(CLIENT_CONTROL_PIPE_PREFIX)


def _is_answering(path: str) -> bool:
    """Whether something accepts a connection on a Unix socket path."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(1)
        probe.connect(path)
        return True
    except OSError:
        return False
    finally:
        probe.close()


def ask_easytier_daemon(
    address: str,
    request: dict,
    *,
    timeout_s: float = CLIENT_EASYTIER_REQUEST_TIMEOUT_S,
    pipe_api=None,
) -> dict:
    """Send one request to the daemon and read its answer.

    Args:
        address: The daemon's socket path or pipe name.
        request: The request.
        timeout_s: How long connecting and the answer may take on a Unix
            socket.
        pipe_api: The Win32 pipe seam; None uses the real one.

    Returns:
        The answer.

    Raises:
        OSError: When nothing answers.
        ValueError: When the answer is not one JSON object.
    """
    payload = (json.dumps(request) + "\n").encode("utf-8")
    if _is_pipe(address):
        from neutrino_client.platforms.windows_pipe import open_pipe_connection

        connection = open_pipe_connection(address, api=pipe_api)
    else:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(timeout_s)
        try:
            connection.connect(address)
        except OSError:
            connection.close()
            raise
    try:
        connection.sendall(payload)
        reader = connection.makefile("rb")
        try:
            line = reader.readline(CLIENT_EASYTIER_REQUEST_LIMIT_BYTES + 1)
        finally:
            reader.close()
    finally:
        connection.close()
    answer = json.loads(line.decode("utf-8") or "null")
    if not isinstance(answer, dict):
        raise ValueError("the EasyTier daemon answered with no object")
    return answer


class _EasytierRequestHandler(socketserver.StreamRequestHandler):
    """Reads one request line, answers one line, and ends."""

    timeout = CLIENT_EASYTIER_REQUEST_TIMEOUT_S

    def handle(self) -> None:
        daemon = self.server.easytier_daemon
        line = self.rfile.readline(CLIENT_EASYTIER_REQUEST_LIMIT_BYTES + 1)
        if len(line) > CLIENT_EASYTIER_REQUEST_LIMIT_BYTES:
            answer = {"code": "overlay_request_invalid", "params": {}}
        else:
            try:
                request = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                request = None
            try:
                answer = daemon.handle(request)
            except (
                Exception
            ) as error:  # noqa: BLE001 - one request must not end the daemon
                self.server.easytier_log(
                    f"a request failed: {type(error).__name__}: {error}"
                )
                answer = {
                    "code": "client_internal",
                    "params": {"kind": type(error).__name__},
                }
        self.wfile.write((json.dumps(answer) + "\n").encode("utf-8"))


class _EasytierUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class EasytierSocketServer:
    """Serves the daemon's requests on its socket or pipe."""

    def __init__(self, *, daemon, address: str, log=print, pipe_api=None):
        """
        Args:
            daemon: The :class:`~neutrino_client.core.easytier_daemon.EasytierDaemon`.
            address: The socket path or pipe name to serve on.
            log: Callable used for progress messages.
            pipe_api: The Win32 pipe seam; None uses the real one.
        """
        self._daemon = daemon
        self._address = address
        self._log = log
        self._pipe_api = pipe_api
        self._server = None

    def bind(self) -> None:
        """Take the socket or the pipe, without serving yet.

        A Unix socket left by an earlier run is replaced; one a running
        daemon answers on is not.

        Raises:
            OSError: When it cannot be taken.
        """
        if _is_pipe(self._address):
            from neutrino_client.platforms.windows_pipe import (
                ControlPipeHttpServer,
                Win32PipeApi,
            )

            api = (
                self._pipe_api
                if self._pipe_api is not None
                else Win32PipeApi(sddl=EASYTIER_PIPE_SDDL)
            )
            server = ControlPipeHttpServer(
                self._address, _EasytierRequestHandler, api=api
            )
        else:
            directory = os.path.dirname(self._address)
            if directory:
                os.makedirs(directory, exist_ok=True)
            if os.path.lexists(self._address):
                if _is_answering(self._address):
                    raise OSError(
                        errno.EADDRINUSE, "a daemon answers there", self._address
                    )
                os.unlink(self._address)
            server = _EasytierUnixServer(self._address, _EasytierRequestHandler)
            os.chmod(self._address, EASYTIER_SOCKET_MODE)
        server.easytier_daemon = self._daemon
        server.easytier_log = self._log
        self._server = server

    def start(self) -> None:
        """Bind, then serve on a thread of its own.

        Raises:
            OSError: When the socket or the pipe cannot be taken.
        """
        if self._server is None:
            self.bind()
        threading.Thread(
            target=self._server.serve_forever, name="easytier_socket", daemon=True
        ).start()
        self._log(f"answering on {self._address}")

    def stop(self) -> None:
        """Stop serving and let the socket go. Idempotent."""
        server = self._server
        self._server = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if not _is_pipe(self._address):
            try:
                os.unlink(self._address)
            except OSError:
                pass
