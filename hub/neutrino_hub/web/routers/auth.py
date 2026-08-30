"""Login, logout, and session probing."""

from fastapi import APIRouter, Cookie, Depends, Response

from neutrino_hub.web.constants import WEB_SESSION_COOKIE
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import LoginRequest, SessionView
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=SessionView)
def login(
    request: LoginRequest,
    response: Response,
    runtime: PanelRuntime = Depends(get_runtime),
) -> SessionView:
    """Start a session if the password is right.

    Args:
        request: The submitted password.
        response: Response the session cookie is set on.
        runtime: The shared runtime.

    Returns:
        Whether a session was created. A lockout is explicit: the page shows
        a countdown, and hiding it would only punish the owner's typos while
        telling an attacker nothing they cannot measure.
    """
    token = runtime.sessions.login(request.password)
    if token is None:
        return SessionView(
            is_authenticated=False,
            lockout_remaining_s=runtime.sessions.lockout_remaining_s(),
        )
    response.set_cookie(
        WEB_SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=runtime.settings.get("session_ttl_hours", 168) * 3600,
    )
    return SessionView(is_authenticated=True)


@router.post("/logout", response_model=SessionView)
def logout(
    response: Response,
    runtime: PanelRuntime = Depends(get_runtime),
    neutrino_session: str | None = Cookie(default=None),
) -> SessionView:
    """End the caller's session.

    Args:
        response: Response the cookie is cleared on.
        runtime: The shared runtime.
        neutrino_session: The session cookie, when present.

    Returns:
        Always unauthenticated.
    """
    if neutrino_session:
        runtime.sessions.logout(neutrino_session)
    response.delete_cookie(WEB_SESSION_COOKIE)
    return SessionView(is_authenticated=False)


@router.get("/session", response_model=SessionView)
def session(
    runtime: PanelRuntime = Depends(get_runtime),
    neutrino_session: str | None = Cookie(default=None),
) -> SessionView:
    """Report whether the caller is logged in.

    Args:
        runtime: The shared runtime.
        neutrino_session: The session cookie, when present.

    Returns:
        The current authentication state.
    """
    return SessionView(
        is_authenticated=runtime.sessions.is_valid(neutrino_session),
        lockout_remaining_s=runtime.sessions.lockout_remaining_s(),
    )
