"""Shared FastAPI dependencies: the runtime object and session enforcement."""

from fastapi import Depends, HTTPException, Request, status

from neutrino_hub.web.constants import (
    WEB_DEFAULT_LISTEN_PORT,
    WEB_SESSION_COOKIE_PREFIX,
)
from neutrino_hub.web.panel_runtime import PanelRuntime


def get_runtime(request: Request) -> PanelRuntime:
    """Reach the runtime built at application startup.

    Args:
        request: The incoming request.

    Returns:
        The shared runtime object.
    """
    return request.app.state.runtime


def session_cookie(runtime: PanelRuntime) -> str:
    """The name of this panel's session cookie.

    Args:
        runtime: The shared runtime.

    Returns:
        ``neutrino_session_<port>`` for the port the panel answers on, so a
        cookie a hub on another port of this host set is not this hub's.
    """
    port = int(runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT))
    return f"{WEB_SESSION_COOKIE_PREFIX}{port}"


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
    if not runtime.sessions.is_valid(request.cookies.get(session_cookie(runtime))):
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


__all__ = ["get_runtime", "require_session", "is_session_valid", "session_cookie"]
