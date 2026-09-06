"""One control server, one transport, one handler set.

The control socket — a Unix socket on Linux and macOS, a named pipe on
Windows — authenticates every request by the kernel's peer credentials. What
a caller may do is decided by scope in the handlers: connect, disconnect and
module toggles are privileged verbs, service actions carry the caller's
identity into their type's handler, and state answers are shaped to the
asking identity.

Connections persist between requests, and each is served on its own thread:
``nagent gui`` hands its connected descriptor to the window process, whose
whole session rides that one connection in the scope its opener owned.

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
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import AGENT_CONTROL_PIPE_PREFIX
from neutrino_agent.control.identity import ControlIdentity, peer_identity
from neutrino_agent.core import enrollment
from neutrino_agent.core.metrics import hostname
from neutrino_agent.platforms.base import PlatformUnsupportedError


def _scoped_state(agent, identity: ControlIdentity) -> dict:
    """Everything the page draws, shaped to the asking identity.

    Args:
        agent: The running :class:`~neutrino_agent.core.loop.Agent`.
        identity: Who is asking.

    Returns:
        The state payload; an ordinary account's accounts list is itself
        alone, and its AI rows carry only its own.
    """
    config = enrollment.load_config()
    catalog = agent.catalog()
    targets = agent.ai_targets()
    ai_states = agent.ai_states()
    if identity.is_privileged:
        accounts = agent.accounts()
    else:
        accounts = [identity.account]
        targets = {identity.account: bool(targets.get(identity.account))}
        ai_states = {
            account: state
            for account, state in ai_states.items()
            if account == identity.account
        }
    state = {
        "version": AGENT_VERSION,
        "hostname": hostname(),
        "platform": agent.platform(),
        # What a mount location is on this machine; the page greys the
        # directory browser where it is a drive letter.
        "mount_location_shape": agent.mount_location_shape(),
        "caller": {
            "account": identity.account,
            "is_privileged": identity.is_privileged,
            "home": agent.account_home(identity.account),
        },
        "is_connected": bool(config.get("gateway_url") and config.get("token")),
        "gateway_url": config.get("gateway_url", ""),
        "last_error": agent.last_error(),
        "operation": agent.operation(),
        "modules": _module_rows(agent, catalog.get("modules", {})),
        "services": agent.service_entries(),
        "accounts": accounts,
        "ai_targets": targets,
        "ai_states": ai_states,
        "ai_tool_configs": agent.ai_tool_configs(),
    }
    state.update(agent.service_states())
    # The access password a share was set up with, for the scope that set
    # it. It is read from this machine's own file and goes nowhere else.
    if isinstance(state.get("rdp"), dict):
        state["rdp"]["password"] = agent.rdp_password(  # scan: allow
            is_privileged=identity.is_privileged
        )
    return state


def _module_rows(agent, modules: dict) -> list:
    """The Modules section, from the catalog the hub already resolved.

    Args:
        agent: The running agent.
        modules: The catalog's modules half, each entry resolved for this
            platform — so nothing here searches a platform table.

    Returns:
        One row per module.
    """
    reported = agent.module_states()
    rows = []
    for name, resolved in sorted(modules.items()):
        if not isinstance(resolved, dict):
            continue
        status = reported.get(name, {})
        rows.append(
            {
                "name": name,
                "title": resolved.get("title", name),
                "description": resolved.get("description", ""),
                "kind": resolved.get("kind", ""),
                # user-tier rows offer no button: the person installs the
                # software, and the row only shows what is detected.
                "installer": resolved.get("installer", ""),
                "is_supported": resolved.get("entry") is not None,
                # The platform carries this natively: worded built in, no
                # button.
                "is_native": resolved.get("entry") == {},
                # What the hub conveys under a copyleft license, and where
                # its corresponding source is.
                "license": resolved.get("license", ""),
                "corresponding_source": resolved.get("corresponding_source", ""),
                "state": status.get("state", "unknown"),
                "code": status.get("code", ""),
                "params": status.get("params", {}),
                "details": status.get("details", {}),
            }
        )
    return rows


class ControlServer:
    """Serves the control socket or pipe from one handler set."""

    def __init__(
        self,
        *,
        agent,
        platform,
        log=print,
        socket_path: str = "",
    ):
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
            if path.startswith(AGENT_CONTROL_PIPE_PREFIX):
                from neutrino_agent.control.windows_pipe import ControlPipeHttpServer

                server = ControlPipeHttpServer(path, _ControlRequestHandler)
            else:
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

    # AF_UNIX is absent on Windows, where the pipe transport serves instead;
    # the fallback only keeps this module importable there.
    address_family = getattr(socket, "AF_UNIX", socket.AF_INET)

    def handle_error(self, request, client_address) -> None:
        """A dropped client goes to the agent's log, never to stderr."""
        self.control_log(traceback.format_exc())

    def server_bind(self) -> None:
        """Bind the path: make its directory, drop a stale socket, open wide.

        The directory is root's 0755; the socket itself is 0666, because any
        local account may connect and the kernel reports who each one is.
        """
        directory = os.path.dirname(self.server_address)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
            os.chmod(directory, 0o755)
        try:
            os.unlink(self.server_address)
        except OSError:
            pass
        socketserver.TCPServer.server_bind(self)
        os.chmod(self.server_address, 0o666)
        self.server_name = "neutrino_agent"
        self.server_port = 0


class _ControlRequestHandler(BaseHTTPRequestHandler):
    """The one handler set the socket and the pipe share."""

    # Connections persist between requests, which is what lets a handed-over
    # GUI connection keep the scope its opener owned.
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
        route = self.path.split("?")[0]
        identity = self._authenticate()
        if identity is None:
            return
        if route == "/api/state":
            self._send_json(_scoped_state(self.server.control_agent, identity))
        elif route == "/api/fs":
            self._list_directories(identity)
        else:
            self._send_json({"code": "unknown_request"}, status=404)

    def _route_post(self) -> None:
        route = self.path.split("?")[0]
        identity = self._authenticate()
        if identity is None:
            return
        body = self._read_body()
        if route == "/api/connect":
            self._connect(identity, body)
        elif route == "/api/disconnect":
            self._disconnect(identity)
        elif route == "/api/module":
            self._request_module(identity, body)
        elif route.startswith("/api/services/"):
            self._service_action(identity, route[len("/api/services/") :], body)
        elif route == "/api/fs":
            self._make_directory(identity, body)
        else:
            self._send_json({"code": "unknown_request"}, status=404)

    def _authenticate(self) -> "ControlIdentity | None":
        """The caller's identity, or None after a refusal was sent.

        The kernel reports who the peer is; nothing in the request itself
        can name a different caller.
        """
        try:
            return peer_identity(self.server.control_platform, self.connection)
        except PlatformUnsupportedError:
            self._send_json({"code": "unsupported_platform"}, status=403)
            return None
        except KeyError:
            self._send_json({"code": "control_identity_unknown"}, status=403)
            return None

    def _require_privilege(self, identity: ControlIdentity) -> bool:
        if identity.is_privileged:
            return True
        self._send_json({"code": "control_scope_refused"}, status=403)
        return False

    def _connect(self, identity: ControlIdentity, body: dict) -> None:
        if not self._require_privilege(identity):
            return
        agent = self.server.control_agent
        try:
            agent.connect(str(body.get("link", "")))
        except enrollment.EnrollmentError as error:
            state = _scoped_state(agent, identity)
            state["error"] = str(error)
            self._send_json(state)
            return
        self._send_json(_scoped_state(agent, identity))

    def _disconnect(self, identity: ControlIdentity) -> None:
        if not self._require_privilege(identity):
            return
        agent = self.server.control_agent
        agent.disconnect()
        self._send_json(_scoped_state(agent, identity))

    def _request_module(self, identity: ControlIdentity, body: dict) -> None:
        if not self._require_privilege(identity):
            return
        agent = self.server.control_agent
        agent.request_module(
            str(body.get("name", "")), is_enabled=body.get("is_enabled")
        )
        self._send_json(_scoped_state(agent, identity))

    def _service_action(
        self, identity: ControlIdentity, service_type: str, body: dict
    ) -> None:
        agent = self.server.control_agent
        outcome = agent.service_action(
            service_type,
            account=identity.account,
            is_privileged=identity.is_privileged,
            body=body,
        )
        if outcome:
            self._send_refusal(outcome)
            return
        self._send_json(_scoped_state(agent, identity))

    def _list_directories(self, identity: ControlIdentity) -> None:
        query = urllib.parse.urlparse(self.path).query
        values = urllib.parse.parse_qs(query).get("path", [])
        path = values[0] if values else ""
        if not path:
            path = self.server.control_agent.account_home(identity.account) or "/"
        account = "" if identity.is_privileged else identity.account
        try:
            names = self.server.control_platform.list_directories(
                account=account, path=path
            )
        except (OSError, PlatformUnsupportedError):
            self._send_json({"code": "fs_refused"}, status=403)
            return
        self._send_json({"path": path, "dirs": names})

    def _make_directory(self, identity: ControlIdentity, body: dict) -> None:
        path = str(body.get("path", ""))
        if not path.startswith("/"):
            self._send_json({"code": "fs_refused"}, status=403)
            return
        account = "" if identity.is_privileged else identity.account
        try:
            self.server.control_platform.make_directory(account=account, path=path)
        except (OSError, PlatformUnsupportedError):
            self._send_json({"code": "fs_refused"}, status=403)
            return
        self._send_json({"path": path})

    def _send_refusal(self, outcome: dict) -> None:
        code = outcome.get("code", "")
        if code == "unknown_request":
            status = 404
        elif code in ("control_scope_refused", "fs_refused"):
            status = 403
        else:
            status = 400
        self._send_json(outcome, status=status)

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
