"""Sending a browser from the port the panel left to the port it is on.

Both ports are served, but the panel is on one of them: the HTTPS port while
``is_https_enabled`` is on, the HTTP port otherwise. A request that arrives
on the other port is answered 301 to the same host and path on the right
one, and a websocket there is closed. The redirect also deletes the session
cookie, so a browser holds a session on one port at a time and a ``Secure``
cookie never stays behind to block a plain login, which a browser refuses to
overwrite. The setting is read from the runtime on every request, so turning
HTTPS on or off restarts nothing. The authority's download and the trust probe
are served on both ports. A plain request from loopback, the hub's own
forward of a client's panel, is served on the HTTP port whatever the
setting says.
"""

import ipaddress
from urllib.parse import urlsplit

from neutrino_hub.web.constants import (
    WEB_DEFAULT_HTTPS_LISTEN_PORT,
    WEB_DEFAULT_LISTEN_PORT,
    WEB_HTTP_SCHEME_PORT,
    WEB_HTTPS_SCHEME_PORT,
    WEB_PANEL_TLS_AUTHORITY_ROUTE,
    WEB_PANEL_TLS_PROBE_ROUTE,
    WEB_SESSION_COOKIE_PREFIX,
    WEB_SETTING_HTTPS,
    WEB_SETTING_HTTPS_PORT,
)

HTTPS_REDIRECT_STATUS = 301
# The close code a websocket gets on the port the panel is not on.
HTTPS_REDIRECT_WEBSOCKET_CLOSE = 1008
# The paths both ports serve whatever the setting says.
PORT_SHARED_PATHS = (WEB_PANEL_TLS_AUTHORITY_ROUTE, WEB_PANEL_TLS_PROBE_ROUTE)
SECURE_SCHEMES = ("https", "wss")


def https_location(host: str, https_port: int, path: str, query: str = "") -> str:
    """The HTTPS address a plain request is sent to.

    Args:
        host: The request's ``Host`` header, with or without a port.
        https_port: The port the panel serves HTTPS on.
        path: The request's path, as it arrived.
        query: The request's query string, without the ``?``.

    Returns:
        ``https://<host>[:<port>]<path>[?<query>]``, the port left out when
        it is 443.
    """
    return _location("https", host, https_port, WEB_HTTPS_SCHEME_PORT, path, query)


def http_location(host: str, http_port: int, path: str, query: str = "") -> str:
    """The plain address a request on the HTTPS port is sent to while HTTPS is off.

    Args:
        host: The request's ``Host`` header, with or without a port.
        http_port: The port the panel serves HTTP on.
        path: The request's path, as it arrived.
        query: The request's query string, without the ``?``.

    Returns:
        ``http://<host>[:<port>]<path>[?<query>]``, the port left out when
        it is 80.
    """
    return _location("http", host, http_port, WEB_HTTP_SCHEME_PORT, path, query)


def _location(
    scheme: str, host: str, port: int, scheme_port: int, path: str, query: str
) -> str:
    try:
        name = urlsplit(f"//{host}").hostname or ""
    except ValueError:
        name = ""
    if ":" in name:
        name = f"[{name}]"
    suffix = "" if port == scheme_port else f":{port}"
    location = f"{scheme}://{name}{suffix}{path or '/'}"
    return f"{location}?{query}" if query else location


def _is_loopback_peer(scope) -> bool:
    """Whether a request comes from this machine's own loopback."""
    client = scope.get("client")
    if not client:
        return False
    try:
        return ipaddress.ip_address(str(client[0])).is_loopback
    except ValueError:
        return False


class PanelHttpsRedirectMiddleware:
    """Answers requests on the port the panel is not on with a 301 to the other."""

    def __init__(self, app, *, runtime):
        """
        Args:
            app: The wrapped ASGI application.
            runtime: The shared runtime, whose settings say whether HTTPS is
                on and which ports serve the panel.
        """
        self._app = app
        self._runtime = runtime

    async def __call__(self, scope, receive, send):
        if not self._is_redirected(scope):
            await self._app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send(
                {"type": "websocket.close", "code": HTTPS_REDIRECT_WEBSOCKET_CLOSE}
            )
            return
        headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope.get("headers", [])
        }
        raw_path = scope.get("raw_path") or scope.get("path", "/").encode("utf-8")
        path = raw_path.decode("latin-1")
        query = scope.get("query_string", b"").decode("latin-1")
        is_secure = scope.get("scheme") in SECURE_SCHEMES
        if is_secure:
            location = http_location(
                headers.get("host", ""), self._http_port(), path, query
            )
        else:
            location = https_location(
                headers.get("host", ""), self._https_port(), path, query
            )
        await send(
            {
                "type": "http.response.start",
                "status": HTTPS_REDIRECT_STATUS,
                "headers": [
                    (b"location", location.encode("latin-1")),
                    (b"set-cookie", self._deleted_cookie(is_secure).encode("latin-1")),
                    (b"content-length", b"0"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    def _is_redirected(self, scope) -> bool:
        """Whether this request arrived on the port the panel is not on."""
        if scope["type"] not in ("http", "websocket"):
            return False
        if scope.get("path") in PORT_SHARED_PATHS:
            return False
        is_secure = scope.get("scheme") in SECURE_SCHEMES
        if not is_secure and _is_loopback_peer(scope):
            return False
        is_on = bool(self._runtime.settings.get(WEB_SETTING_HTTPS, False))
        return is_secure != is_on

    def _deleted_cookie(self, is_secure: bool) -> str:
        """The header that removes the session cookie on the port left."""
        name = f"{WEB_SESSION_COOKIE_PREFIX}{self._http_port()}"
        secure = "; Secure" if is_secure else ""
        return f"{name}=; Max-Age=0; Path=/; HttpOnly; SameSite=lax{secure}"

    def _http_port(self) -> int:
        """The port the panel serves HTTP on, from the runtime's settings."""
        return int(self._runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT))

    def _https_port(self) -> int:
        """The port the panel serves HTTPS on, from the runtime's settings."""
        return int(
            self._runtime.settings.get(
                WEB_SETTING_HTTPS_PORT, WEB_DEFAULT_HTTPS_LISTEN_PORT
            )
        )
