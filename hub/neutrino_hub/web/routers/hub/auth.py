"""Login, logout, and session probing."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response

from neutrino_hub.web.dependencies import get_runtime, session_cookie
from neutrino_hub.web.models import LoginRequest, SessionView
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/hub/auth", tags=["auth"])

# Fixed when this process imported it; a page that saw another value is
# talking to a restarted panel.
AUTH_PANEL_STARTED_AT = datetime.now(timezone.utc).isoformat()


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
        session_cookie(runtime),
        token,
        httponly=True,
        samesite="lax",
        max_age=runtime.settings.get("session_ttl_hours", 168) * 3600,
    )
    return SessionView(is_authenticated=True)


@router.post("/logout", response_model=SessionView)
def logout(
    request: Request,
    response: Response,
    runtime: PanelRuntime = Depends(get_runtime),
) -> SessionView:
    """End the caller's session.

    Args:
        request: The incoming request, read for its session cookie.
        response: Response the cookie is cleared on.
        runtime: The shared runtime.

    Returns:
        Always unauthenticated.
    """
    name = session_cookie(runtime)
    token = request.cookies.get(name)
    if token:
        runtime.sessions.logout(token)
    response.delete_cookie(name)
    return SessionView(is_authenticated=False)


@router.get("/session", response_model=SessionView)
def session(
    request: Request,
    runtime: PanelRuntime = Depends(get_runtime),
) -> SessionView:
    """Report whether the caller is logged in.

    Args:
        request: The incoming request, read for its session cookie.
        runtime: The shared runtime.

    Returns:
        The current authentication state.
    """
    token = request.cookies.get(session_cookie(runtime))
    return SessionView(
        is_authenticated=runtime.sessions.is_valid(token),
        lockout_remaining_s=runtime.sessions.lockout_remaining_s(),
        panel_started_at=AUTH_PANEL_STARTED_AT,
    )
