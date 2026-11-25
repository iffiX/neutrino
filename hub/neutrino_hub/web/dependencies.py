"""Shared FastAPI dependencies: the runtime object, session enforcement and
the machine page's default account check."""

from fastapi import Depends, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from neutrino_hub.modules.devices.registry import DeviceRegistry

from neutrino_hub.web.constants import (
    WEB_SESSION_COOKIE_HUB_CHARS,
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


def session_cookie() -> str:
    """The name of this panel's session cookie.

    Returns:
        ``neutrino_session_<hub>``, the first 12 characters of the hub's id,
        for every login and every request on either port.
        ``neutrino_session_`` while the identity file cannot be read.
    """
    try:
        identity = hub_id()
    except (OSError, ValueError):
        identity = ""
    return f"{WEB_SESSION_COOKIE_PREFIX}{identity[:WEB_SESSION_COOKIE_HUB_CHARS]}"


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
    if not runtime.sessions.is_valid(request.cookies.get(session_cookie())):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "not_authenticated", "params": {}},
        )


async def require_default_account(
    request: Request,
    runtime: PanelRuntime = Depends(get_runtime),
) -> None:
    """Reject a write of the machine page on a machine with no default account.

    A POST whose body names a stored ``device_id`` is refused while that
    machine's ``accounts.json`` names no default account
    (agent/accounts.md, "A machine with no default"); a read, and a body
    that names no device, pass to the route.

    Args:
        request: The incoming request, whose JSON body names the device.
        runtime: The shared runtime.

    Raises:
        HTTPException: 409 ``default_account_missing``.
    """
    if request.method != "POST":
        return
    try:
        body = await request.json()
    except ValueError:
        return
    device_id = body.get("device_id") if isinstance(body, dict) else None
    if not isinstance(device_id, str) or not device_id:
        return
    if await run_in_threadpool(_is_default_missing, runtime, device_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "default_account_missing", "params": {}},
        )


def _is_default_missing(runtime: PanelRuntime, device_id: str) -> bool:
    """Whether a stored managed machine has no default account."""
    device = DeviceRegistry().get(device_id)
    if device is None or not device.is_managed:
        return False
    return not runtime.desired_states.default_account(device.id)


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
    "require_default_account",
    "require_session",
    "is_session_valid",
    "session_cookie",
]
