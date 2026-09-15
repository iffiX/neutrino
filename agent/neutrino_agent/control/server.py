"""The local control channel: one Unix socket, one handler set.

The agent is root and so is everyone it answers. The socket file is 0600
under a 0700 directory, so the kernel refuses anyone else before a request
is read and no identity has to be judged in a handler.

Connections persist between requests, and each is served on its own thread.

Every refusal is ``{"code": ...}``; each surface does its own wording. A
handler exception never drops the connection: the caller gets
``agent_internal`` carrying only the exception's class name, and the
traceback goes to the agent's own log.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from neutrino_agent import AGENT_VERSION
from neutrino_agent.core import enrollment
from neutrino_agent.core.metrics import hostname
from neutrino_agent.exceptions import EnrollmentError, PlatformUnsupportedError


def _state(agent) -> dict:
    """Everything the control channel answers about this machine.

    Args:
        agent: The running :class:`~neutrino_agent.core.loop.Agent`.

    Returns:
        The state payload.
    """
    binding = enrollment.load_binding()
    return {
        "version": AGENT_VERSION,
        "hostname": hostname(),
        "platform": agent.platform(),
        "is_connected": bool(binding),
        "is_online": agent.is_online(),
        "binding": {
            "id": binding.get("id", ""),
            "gateway_url": binding.get("gateway_url", ""),
        },
        "state_hash": agent.state_hash(),
        "last_error": agent.last_error(),
        # Each module as the report says it: observed state, unit, code.
        "modules": agent.module_states(),
        "rdp": agent.rdp_state(),
    }


class ControlServer:
    """Serves the control socket from one handler set."""

    def __init__(self, *, agent, platform, log=print, socket_path: str = ""):
        """
        Args:
            agent: The running :class:`~neutrino_agent.core.loop.Agent`.
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            socket_path: The control socket path; empty asks the platform.
        """
        self._agent = agent
        self._platform = platform
        self._log = log
        self._socket_path = socket_path
        self._socket_server = None

    @property
    def socket_path(self) -> str:
        """The path the socket transport serves on, empty when it is not."""
        return self._socket_path if self._socket_server is not None else ""

    def start(self) -> None:
        """Serve the socket, logging when it could not bind.

        A machine that cannot bind the socket is still a working agent, so
        this never takes the process down with it.
        """
        path = self._socket_path
        if not path:
            try:
                path = self._platform.control_socket_path()
            except PlatformUnsupportedError:
                self._log("control socket not available on this platform")
                return
        try:
            server = _ControlSocketHttpServer(path, _ControlRequestHandler)
        except OSError as error:
            self._log(f"control socket not available: {error}")
            return
        server.control_agent = self._agent
        server.control_platform = self._platform
        server.control_log = self._log
        self._socket_path = path
        self._socket_server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._log(f"control socket on {path}")

    def stop(self) -> None:
        """Stop the transport when it is serving."""
        if self._socket_server is not None:
            self._socket_server.shutdown()
            self._socket_server.server_close()
        self._socket_server = None


class _ControlSocketHttpServer(ThreadingHTTPServer):
    """An HTTP server bound to a Unix socket path, one thread per client."""

    address_family = socket.AF_UNIX

    def handle_error(self, request, client_address) -> None:
        """A dropped client goes to the agent's log, never to stderr."""
        self.control_log(traceback.format_exc())

    def server_bind(self) -> None:
        """Bind the path: make its directory, drop a stale socket, close it off.

        The directory is 0700 and the socket 0600, both root's. Everything
        this channel does is root's to do, so the kernel refuses anyone else
        at connect time.
        """
        directory = os.path.dirname(self.server_address)
        if directory:
            os.makedirs(directory, exist_ok=True)
            os.chmod(directory, 0o700)
        try:
            os.unlink(self.server_address)
        except OSError:
            pass
        socketserver.TCPServer.server_bind(self)
        os.chmod(self.server_address, 0o600)
        self.server_name = "neutrino_agent"
        self.server_port = 0


class _ControlRequestHandler(BaseHTTPRequestHandler):
    """The six routes the control socket serves."""

    protocol_version = "HTTP/1.1"
    timeout = 10

    def do_GET(self) -> None:
        self._dispatch(self._route_get)

    def do_POST(self) -> None:
        self._dispatch(self._route_post)

    def log_message(self, *args) -> None:
        # The journal already has the agent's own lines; access logs for a
        # single-machine channel would only bury them.
        return

    def _dispatch(self, route) -> None:
        """Run one route; an unexpected exception answers a typed refusal.

        Args:
            route: The bound route handler for this request method.
        """
        try:
            route()
        except Exception as error:  # noqa: BLE001 - answered, never a dropped wire
            self.server.control_log(traceback.format_exc())
            try:
                self._send_json(
                    {
                        "code": "agent_internal",
                        "params": {"error": type(error).__name__},
                    },
                    status=500,
                )
            except OSError:
                return

    def _route_get(self) -> None:
        if self.path.split("?")[0] == "/api/state":
            self._send_json(_state(self.server.control_agent))
            return
        self._send_json({"code": "unknown_request"}, status=404)

    def _route_post(self) -> None:
        route = self.path.split("?")[0]
        body = self._read_body()
        if route == "/api/join":
            self._join(body)
        elif route == "/api/leave":
            self._leave()
        elif route == "/api/sync":
            self._sync()
        elif route == "/api/rdp/start":
            self._rdp_start(body)
        elif route == "/api/rdp/stop":
            self._rdp_stop()
        else:
            self._send_json({"code": "unknown_request"}, status=404)

    def _join(self, body: dict) -> None:
        agent = self.server.control_agent
        try:
            agent.join(str(body.get("link", "")))
        except EnrollmentError as error:
            state = _state(agent)
            state["error"] = str(error)
            self._send_json(state)
            return
        self._send_json(_state(agent))

    def _leave(self) -> None:
        agent = self.server.control_agent
        agent.leave()
        self._send_json(_state(agent))

    def _sync(self) -> None:
        agent = self.server.control_agent
        outcome = agent.sync()
        if outcome:
            self._send_refusal(outcome)
            return
        self._send_json(_state(agent))

    def _rdp_start(self, body: dict) -> None:
        agent = self.server.control_agent
        outcome = agent.rdp_share(account=str(body.get("user", "")))
        if outcome:
            self._send_refusal(outcome)
            return
        self._send_json(_state(agent))

    def _rdp_stop(self) -> None:
        agent = self.server.control_agent
        outcome = agent.rdp_unshare()
        if outcome:
            self._send_refusal(outcome)
            return
        self._send_json(_state(agent))

    def _send_refusal(self, outcome: dict) -> None:
        code = outcome.get("code", "")
        self._send_json(outcome, status=404 if code == "unknown_request" else 400)

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
