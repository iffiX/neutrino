"""One control server, two transports, one handler set.

The Unix socket authenticates every request by the kernel's peer
credentials, and is the only place tokens are minted, watched and revoked.
The loopback page transport authenticates only by bearer token; its POSTs
must carry a JSON content type, and an Origin other than the page's own is
refused regardless of the token. What a caller may do is decided by scope in
the handlers: connect, disconnect and module toggles are privileged verbs,
service actions carry the caller's identity into their type's handler, and
state answers are shaped to the asking identity.

A page token is minted only while the agent actually holds the loopback
port: started with ``--no-ui``, or with the port taken by something else, it
refuses — a privileged token opened into a page some other local process is
serving would be that process's to read.

Every refusal is ``{"code": ...}``; each surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_CONTROL_PAGE_HOST,
    AGENT_CONTROL_PAGE_ORIGIN,
    AGENT_CONTROL_PAGE_PORT,
)
from neutrino_agent.control.identity import (
    ControlIdentity,
    ControlTokenStore,
    peer_identity,
)
from neutrino_agent.control.page import CONTROL_PAGE_HTML
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
                "is_supported": resolved.get("entry") is not None,
                # The platform carries this natively: worded built in, no
                # button.
                "is_native": resolved.get("entry") == {},
                "state": status.get("state", "unknown"),
                "code": status.get("code", ""),
                "params": status.get("params", {}),
            }
        )
    return rows


class ControlServer:
    """Serves the control socket and the loopback page from one handler set."""

    def __init__(
        self,
        *,
        agent,
        platform,
        log=print,
        socket_path: str = "",
        page_host: str = AGENT_CONTROL_PAGE_HOST,
        page_port: int = AGENT_CONTROL_PAGE_PORT,
        is_page_served: bool = True,
        tokens: "ControlTokenStore | None" = None,
    ):
        """
        Args:
            agent: The running :class:`~neutrino_agent.core.loop.Agent`.
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            socket_path: The control socket path; empty asks the platform.
            page_host: The loopback address the page binds.
            page_port: The page's port; 0 binds a free one.
            is_page_served: Serve the loopback page transport as well.
            tokens: The token store; None creates one.
        """
        self._agent = agent
        self._platform = platform
        self._log = log
        self._socket_path = socket_path
        self._page_host = page_host
        self._page_port = page_port
        self._is_page_served = is_page_served
        self._tokens = tokens if tokens is not None else ControlTokenStore()
        self._socket_server = None
        self._page_server = None

    @property
    def socket_path(self) -> str:
        """The path the socket transport serves on, empty when it is not."""
        return self._socket_path if self._socket_server is not None else ""

    @property
    def page_port(self) -> int:
        """The port the page transport bound, 0 when it is not serving."""
        return self._page_port if self._page_server is not None else 0

    def start(self) -> None:
        """Serve both transports, logging any that could not bind.

        A machine that cannot bind either transport is still a working
        agent, so this never takes the process down with it. The page
        transport is bound first: the socket mints page tokens, and a
        socket answering before the page's fate is known could mint into
        a port somebody else holds.
        """
        if self._is_page_served:
            self._start_page()
        self._start_socket()

    def stop(self) -> None:
        """Stop whichever transports are serving."""
        for server in (self._socket_server, self._page_server):
            if server is not None:
                server.shutdown()
                server.server_close()
        self._socket_server = None
        self._page_server = None

    def _start_socket(self) -> None:
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
        self._configure(server, is_socket_transport=True)
        self._socket_path = path
        self._socket_server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._log(f"control socket on {path}")

    def _start_page(self) -> None:
        try:
            server = HTTPServer(
                (self._page_host, self._page_port), _ControlRequestHandler
            )
        except OSError as error:
            self._log(f"local page not available: {error}")
            return
        self._configure(server, is_socket_transport=False)
        self._page_port = server.server_address[1]
        self._page_server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._log(f"local page on http://{self._page_host}:{self._page_port}")

    def _configure(self, server, *, is_socket_transport: bool) -> None:
        server.control_agent = self._agent
        server.control_platform = self._platform
        server.control_tokens = self._tokens
        server.control_channel = self
        server.is_socket_transport = is_socket_transport


class _ControlSocketHttpServer(HTTPServer):
    """An HTTP server bound to a Unix socket path."""

    address_family = socket.AF_UNIX

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
    """The one handler set both transports share."""

    timeout = 10

    def do_GET(self) -> None:
        route = self.path.split("?")[0]
        if route == "/api/state":
            identity = self._authenticate()
            if identity is None:
                return
            self._send_json(_scoped_state(self.server.control_agent, identity))
        elif route == "/api/fs":
            identity = self._authenticate()
            if identity is None:
                return
            self._list_directories(identity)
        elif route.startswith("/api/"):
            self._send_json({"code": "unknown_request"}, status=404)
        else:
            self._send_html(CONTROL_PAGE_HTML)

    def do_POST(self) -> None:
        route = self.path.split("?")[0]
        if route == "/api/token/watch" and self.server.is_socket_transport:
            # Holding the token is the authorization; the asker may be the
            # waiting command of a session another account opened.
            body = self._read_body()
            self._send_json(
                {
                    "is_claimed": self.server.control_tokens.is_claimed(
                        str(body.get("token", ""))
                    ),
                    "is_alive": self.server.control_tokens.is_alive(
                        str(body.get("token", ""))
                    ),
                }
            )
            return
        if route == "/api/token/revoke" and self.server.is_socket_transport:
            body = self._read_body()
            self.server.control_tokens.revoke(str(body.get("token", "")))
            self._send_json({})
            return
        identity = self._authenticate()
        if identity is None:
            return
        body = self._read_body()
        if route == "/api/token" and self.server.is_socket_transport:
            self._mint_token(identity, body)
        elif route == "/api/connect":
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

    def log_message(self, *args) -> None:
        # The journal already has the agent's own lines; access logs for a
        # single-machine channel would only bury them.
        return

    def _authenticate(self) -> "ControlIdentity | None":
        """The caller's identity, or None after a refusal was sent.

        The socket transport asks the kernel who the peer is; the loopback
        transport accepts only a bearer token, and its POSTs must look like
        the page's own.
        """
        if self.server.is_socket_transport:
            try:
                return peer_identity(self.server.control_platform, self.connection)
            except PlatformUnsupportedError:
                self._send_json({"code": "unsupported_platform"}, status=403)
                return None
            except KeyError:
                self._send_json({"code": "control_identity_unknown"}, status=403)
                return None
        if self.command == "POST":
            origin = self.headers.get("Origin", "")
            if origin and origin != AGENT_CONTROL_PAGE_ORIGIN:
                self._send_json({"code": "control_origin_refused"}, status=403)
                return None
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";")[0].strip() != "application/json":
                self._send_json({"code": "control_content_type_refused"}, status=400)
                return None
        header = self.headers.get("Authorization", "")
        token = header[len("Bearer ") :] if header.startswith("Bearer ") else ""
        identity = self.server.control_tokens.identity_of(token)
        if identity is None:
            self._send_json({"code": "control_token_invalid"}, status=401)
            return None
        return identity

    def _require_privilege(self, identity: ControlIdentity) -> bool:
        if identity.is_privileged:
            return True
        self._send_json({"code": "control_scope_refused"}, status=403)
        return False

    def _mint_token(self, identity: ControlIdentity, body: dict) -> None:
        if self.server.control_channel.page_port == 0:
            self._send_json({"code": "control_page_not_served"}, status=409)
            return
        account = str(body.get("account", "") or identity.account)
        if account == identity.account:
            minted = identity
        else:
            if not self._require_privilege(identity):
                return
            try:
                humans = self.server.control_platform.human_accounts()
            except PlatformUnsupportedError:
                humans = []
            if account not in humans:
                self._send_json({"code": "control_unknown_account"}, status=400)
                return
            minted = ControlIdentity(account=account, uid=-1, is_privileged=False)
        token = self.server.control_tokens.mint(minted)
        self._send_json(
            {
                "token": token,
                "account": minted.account,
                "is_privileged": minted.is_privileged,
                "page_port": self.server.control_channel.page_port,
            }
        )

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

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
