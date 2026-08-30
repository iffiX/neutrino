"""Shared FastAPI dependencies: the runtime object and session enforcement."""

from fastapi import Cookie, Depends, HTTPException, Request, status

from neutrino_hub.web.constants import WEB_SESSION_COOKIE
from neutrino_hub.web.panel_runtime import PanelRuntime


def get_runtime(request: Request) -> PanelRuntime:
    """Reach the runtime built at application startup.

    Args:
        request: The incoming request.

    Returns:
        The shared runtime object.
    """
    return request.app.state.runtime


def require_session(
    runtime: PanelRuntime = Depends(get_runtime),
    neutrino_session: str | None = Cookie(default=None),
) -> None:
    """Reject a request that carries no valid session cookie.

    Args:
        runtime: The shared runtime.
        neutrino_session: The session cookie, when present.

    Raises:
        HTTPException: 401 when the session is missing or expired, which is the
            frontend's signal to show the login page.
    """
    if not runtime.sessions.is_valid(neutrino_session):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
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


__all__ = ["get_runtime", "require_session", "is_session_valid", "WEB_SESSION_COOKIE"]
