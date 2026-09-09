"""One control server, one transport, one route table.

The control socket, a Unix socket on Linux and a named pipe on Windows,
authenticates every request by the kernel's peer credentials. Only the
person the resident runs as is answered; any other peer is refused with
``control_peer_refused``. What a request may do is then the route table's,
shared with the window's in-process channel.

A handler exception never drops the connection: the caller gets
``client_internal`` carrying only the exception's class name, and the
traceback goes to the resident's own log.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from neutrino_client.constants import CLIENT_CONTROL_PIPE_PREFIX
from neutrino_client.control import routes
from neutrino_client.control.identity import peer_identity
from neutrino_client.platforms.base import PlatformUnsupportedError


def is_socket_live(path: str) -> bool:
    """Whether a resident answers on a Unix socket path.

    Args:
        path: The socket path.

    Returns:
        True when a connection is accepted.
    """
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(1)
        probe.connect(path)
        return True
    except OSError:
        return False
    finally:
        probe.close()


class ControlServer:
    """Serves the control socket or pipe from the shared route table."""

    def __init__(self, *, session, platform, log=print, socket_path: str = ""):
        """
        Args:
            session: The running :class:`~neutrino_client.core.session.ClientSession`.
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            socket_path: The control socket path; empty asks the platform.
        """
        self._session = session
        self._platform = platform
        self._log = log
        self._socket_path = socket_path
        self._socket_server = None

    @property
    def socket_path(self) -> str:
        """The path the socket transport serves on, empty when it is not."""
        return self._socket_path if self._socket_server is not None else ""

    def bind(self) -> bool:
        """Bind the socket or pipe without serving yet.

        Returns:
            True when bound; False when the platform has no socket or the
            path is already held, logged either way.
        """
        if self._socket_server is not None:
            return True
        path = self._socket_path
        if not path:
            try:
                path = self._platform.control_socket_path()
            except PlatformUnsupportedError as error:
                self._log(f"control socket not available: {error}")
                return False
        try:
            if path.startswith(CLIENT_CONTROL_PIPE_PREFIX):
                from neutrino_client.control.windows_pipe import ControlPipeHttpServer

                server = ControlPipeHttpServer(path, _ControlRequestHandler)
            else:
                server = _ControlSocketHttpServer(path, _ControlRequestHandler)
        except OSError as error:
            self._log(f"control socket not available: {error}")
            return False
        server.control_session = self._session
        server.control_platform = self._platform
        server.control_log = self._log
        self._socket_path = path
        self._socket_server = server
        return True

    def start(self) -> bool:
        """Bind and serve on a thread.

        Returns:
            True when serving.
        """
        if not self.bind():
            return False
        threading.Thread(target=self._socket_server.serve_forever, daemon=True).start()
        self._log(f"control socket on {self._socket_path}")
        return True

    def stop(self) -> None:
        """Stop the transport when it is serving. Idempotent."""
        server = self._socket_server
        self._socket_server = None
        if server is not None:
            server.shutdown()
            server.server_close()


class _ControlSocketHttpServer(ThreadingHTTPServer):
    """An HTTP server bound to a Unix socket path, one thread per client."""

    # AF_UNIX is absent on Windows, where the pipe transport serves instead;
    # the fallback only keeps this module importable there.
    address_family = getattr(socket, "AF_UNIX", socket.AF_INET)
    is_bound = False

    def handle_error(self, request, client_address) -> None:
        """A dropped client goes to the resident's log, never to stderr."""
        self.control_log(traceback.format_exc())

    def server_bind(self) -> None:
        """Bind the path: make its directory, drop a dead socket, mode 0600.

        A path a live resident answers on is left alone and the bind fails.
        """
        directory = os.path.dirname(self.server_address)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, mode=0o700, exist_ok=True)
        if os.path.exists(self.server_address):
            if is_socket_live(self.server_address):
                raise OSError(f"{self.server_address} is already served")
            os.unlink(self.server_address)
        socketserver.TCPServer.server_bind(self)
        os.chmod(self.server_address, 0o600)
        self.server_name = "neutrino_client"
        self.server_port = 0
        self.is_bound = True

    def server_close(self) -> None:
        """Close the socket and remove its path; a path never bound is left."""
        super().server_close()
        if not self.is_bound:
            return
        try:
            os.unlink(self.server_address)
        except OSError:
            pass


class _ControlRequestHandler(BaseHTTPRequestHandler):
    """The one handler set the socket and the pipe share."""

    protocol_version = "HTTP/1.1"
    timeout = 10

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def log_message(self, *args) -> None:
        return

    def _dispatch(self, method: str) -> None:
        """Judge the peer, then run the route; an exception answers typed.

        Args:
            method: The HTTP method.
        """
        try:
            if not self._is_same_user():
                return
            body = self._read_body() if method == "POST" else None
            status, reply = routes.dispatch(
                method, self.path, body, self.server.control_session
            )
            self._send_json(reply, status=status)
        except Exception as error:  # noqa: BLE001 - answered, never a dropped wire
            self.server.control_log(traceback.format_exc())
            try:
                self._send_json(
                    {
                        "code": "client_internal",
                        "params": {"error": type(error).__name__},
                    },
                    status=500,
                )
            except OSError:
                return

    def _is_same_user(self) -> bool:
        """Whether the peer is the person this resident runs as.

        A refusal is sent before False is returned.
        """
        try:
            identity = peer_identity(self.server.control_platform, self.connection)
        except PlatformUnsupportedError:
            self._send_json({"code": "unsupported_platform"}, status=403)
            return False
        if not identity.is_same_user:
            self._send_json({"code": "control_peer_refused"}, status=403)
            return False
        return True

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
