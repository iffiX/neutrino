"""Shared FastAPI dependencies: the runtime object and session enforcement."""

from fastapi import Depends, HTTPException, Request, status

import ipaddress

from neutrino_hub.utils.peer_address import unmapped
from neutrino_hub.web.constants import (
    WEB_DEFAULT_LISTEN_PORT,
    WEB_PANEL_COOKIE_HUB_CHARS,
    WEB_PANEL_COOKIE_PREFIX,
    WEB_SESSION_COOKIE_PREFIX,
)
from neutrino_hub.web.identity import hub_id
from neutrino_hub.web.panel_runtime import PanelRuntime


def get_runtime(request: Request) -> PanelRuntime:
    """Reach the runtime built at application startup.

    Args:
        request: The incoming request.

    Returns:
        The shared runtime object.
    """
    return request.app.state.runtime


def session_cookie(runtime: PanelRuntime, *, is_loopback_peer: bool = False) -> str:
    """The name of this panel's session cookie for one kind of peer.

    Args:
        runtime: The shared runtime.
        is_loopback_peer: Whether the request's peer is on loopback, which is
            a client's forward of the panel.

    Returns:
        ``neutrino_session_<port>`` for the panel's HTTP port, whichever
        port the panel is on, so a cookie a hub on another port of this
        host set is not this hub's; ``neutrino_panel_<hub>`` for a loopback
        peer, the first 12 characters of the hub's id, so two hubs' panels a
        client opens on 127.0.0.1 keep two sessions. The cookie is
        ``Secure`` when it was set over HTTPS, and the port the panel leaves
        deletes it in its redirect, so a browser holds one at a time.
    """
    if is_loopback_peer:
        try:
            identity = hub_id()
        except (FileNotFoundError, ValueError):
            identity = ""
        return f"{WEB_PANEL_COOKIE_PREFIX}{identity[:WEB_PANEL_COOKIE_HUB_CHARS]}"
    port = int(runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT))
    return f"{WEB_SESSION_COOKIE_PREFIX}{port}"


def request_cookie(runtime: PanelRuntime, request) -> str:
    """The cookie name one request's session rides in.

    Args:
        runtime: The shared runtime.
        request: The request or socket, whose peer picks the name.

    Returns:
        :func:`session_cookie` for the request's peer.
    """
    client = getattr(request, "client", None)
    host = unmapped(client.host) if client is not None and client.host else ""
    return session_cookie(runtime, is_loopback_peer=is_loopback(host))


def is_loopback(host: str) -> bool:
    """Whether a peer address is loopback, ``127.0.0.0/8`` or ``::1``."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_session(
    request: Request,
    runtime: PanelRuntime = Depends(get_runtime),
) -> None:
    """Reject a request that carries no valid session cookie.

    Args:
        request: The incoming request, read for its session cookie.
        runtime: The shared runtime.

    Raises:
        HTTPException: 401 when the session is missing or expired, which is the
            frontend's signal to show the login page.
    """
    if not runtime.sessions.is_valid(
        request.cookies.get(request_cookie(runtime, request))
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "not_authenticated", "params": {}},
        )


def is_session_valid(runtime: PanelRuntime, token: str | None) -> bool:
    """Check a session outside the dependency system.

    Websocket routes cannot raise ``HTTPException`` the way routes do, so they
    check here and close the socket themselves.

    Args:
        runtime: The shared runtime.
        token: The session cookie value, when present.

    Returns:
        True when the session is valid.
    """
    return runtime.sessions.is_valid(token)


__all__ = [
    "get_runtime",
    "require_session",
    "is_session_valid",
    "request_cookie",
    "session_cookie",
]
