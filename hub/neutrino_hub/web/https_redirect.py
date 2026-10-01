"""Sending the HTTP port's browsers to the HTTPS port while HTTPS is on.

Both ports serve the same panel. While ``is_https_enabled`` is on, a request
that arrived over plain HTTP is answered 301 to the same host and path on the
HTTPS port, and a plain websocket is closed. The setting is read from the
runtime on every request, so turning HTTPS on or off restarts nothing. The
authority's download is the one path the HTTP port keeps serving.
"""

from urllib.parse import urlsplit

from neutrino_hub.web.constants import (
    WEB_DEFAULT_HTTPS_LISTEN_PORT,
    WEB_HTTPS_SCHEME_PORT,
    WEB_PANEL_TLS_AUTHORITY_ROUTE,
    WEB_SETTING_HTTPS,
    WEB_SETTING_HTTPS_PORT,
)

HTTPS_REDIRECT_STATUS = 301
# The close code a plain websocket gets while HTTPS is on: policy violation.
HTTPS_REDIRECT_WEBSOCKET_CLOSE = 1008


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
    try:
        name = urlsplit(f"//{host}").hostname or ""
    except ValueError:
        name = ""
    if ":" in name:
        name = f"[{name}]"
    port = "" if https_port == WEB_HTTPS_SCHEME_PORT else f":{https_port}"
    location = f"https://{name}{port}{path or '/'}"
    return f"{location}?{query}" if query else location


class PanelHttpsRedirectMiddleware:
    """Answers plain requests with a 301 to the HTTPS port while HTTPS is on."""

    def __init__(self, app, *, runtime):
        """
        Args:
            app: The wrapped ASGI application.
            runtime: The shared runtime, whose settings say whether HTTPS is
                on and which port serves it.
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
        location = https_location(
            headers.get("host", ""),
            self._https_port(),
            raw_path.decode("latin-1"),
            scope.get("query_string", b"").decode("latin-1"),
        )
        await send(
            {
                "type": "http.response.start",
                "status": HTTPS_REDIRECT_STATUS,
                "headers": [
                    (b"location", location.encode("latin-1")),
                    (b"content-length", b"0"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    def _is_redirected(self, scope) -> bool:
        """Whether this request came over plain HTTP while HTTPS is on."""
        if scope["type"] not in ("http", "websocket"):
            return False
        if scope.get("scheme") in ("https", "wss"):
            return False
        if not self._runtime.settings.get(WEB_SETTING_HTTPS, False):
            return False
        return scope.get("path") != WEB_PANEL_TLS_AUTHORITY_ROUTE

    def _https_port(self) -> int:
        """The port the panel serves HTTPS on, from the runtime's settings."""
        return int(
            self._runtime.settings.get(
                WEB_SETTING_HTTPS_PORT, WEB_DEFAULT_HTTPS_LISTEN_PORT
            )
        )
