"""Refusing state-changing requests that carry a foreign Origin.

The session cookie is already ``SameSite=Lax``; this is the belt behind it: a
POST, PUT, PATCH or DELETE whose ``Origin`` header names anything but the
panel's own origin is refused before its route runs. A request without the
header — same-origin fetches in older browsers, curl, the agents — passes,
and reads are left alone.
"""

import json
from urllib.parse import urlsplit

ORIGIN_GUARD_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ORIGIN_REFUSED_CODE = "origin_refused"

_DEFAULT_PORTS = {"http": 80, "https": 443}


class OriginGuardMiddleware:
    """Rejects writes whose Origin is present and not the panel's own."""

    def __init__(self, app):
        """
        Args:
            app: The wrapped ASGI application.
        """
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ORIGIN_GUARD_METHODS:
            await self._app(scope, receive, send)
            return
        headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope.get("headers", [])
        }
        origin = headers.get("origin")
        if origin is None or _is_own_origin(
            origin, headers.get("host", ""), scope.get("scheme", "http")
        ):
            await self._app(scope, receive, send)
            return
        body = json.dumps(
            {"detail": {"code": ORIGIN_REFUSED_CODE, "params": {}}}
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _is_own_origin(origin: str, host: str, scheme: str) -> bool:
    """Whether an Origin header names the host this request arrived on.

    Args:
        origin: The header value, for example ``http://192.168.100.1:8080``.
        host: The request's own ``Host`` header.
        scheme: The scheme the request arrived over, for its default port.

    Returns:
        True when host and effective port match; an unparseable origin —
        ``null`` included — never does.
    """
    try:
        origin_parts = urlsplit(origin)
        host_parts = urlsplit(f"//{host}")
        origin_name = origin_parts.hostname
        origin_port = origin_parts.port or _DEFAULT_PORTS.get(origin_parts.scheme)
        host_name = host_parts.hostname
        host_port = host_parts.port or _DEFAULT_PORTS.get(scheme)
    except ValueError:
        return False
    if not origin_name or not host_name:
        return False
    return origin_name == host_name and origin_port == host_port
