"""The Samba tab: shares, users, and who is connected.

Everything but passwords goes through config/ — save a group, apply the group
— exactly like the rest of the panel. A password is the one imperative action:
it lands in Samba's credential store and nowhere else, so it is set directly
rather than staged, and a restored backup shows 'no password yet' instead of
pretending to know one.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.samba.config import SambaConfig, SambaShare
from neutrino_hub.modules.samba.ops import SambaStatusReader, SambaUserManager
from neutrino_hub.utils.subprocess_run import CommandError
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ApplyResult,
    SambaDiskView,
    SambaPasswordUpdate,
    SambaSessionView,
    SambaSettingsView,
    SambaShareListUpdate,
    SambaShareView,
    SambaStatusView,
    SambaUserListUpdate,
    SambaUserView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/samba", tags=["samba"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=SambaSettingsView)
def read_settings(runtime: PanelRuntime = Depends(get_runtime)) -> SambaSettingsView:
    """Read the share configuration and each user's live state.

    Args:
        runtime: The shared runtime.

    Returns:
        Shares as configured; users as configured, each with whether its
        account exists yet and whether it has a password.
    """
    config = runtime.samba()
    surveyed = SambaUserManager().survey(config.users)
    return SambaSettingsView(
        shares=[SambaShareView(**share.to_dict()) for share in config.shares],
        users=[SambaUserView(**vars(state)) for state in surveyed],
    )


@router.put("/shares", response_model=SambaSettingsView)
def update_shares(
    update: SambaShareListUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> SambaSettingsView:
    """Replace the share list.

    Args:
        update: The new shares.
        runtime: The shared runtime.

    Returns:
        The stored settings.

    Raises:
        HTTPException: 400 when the configuration does not hold together.
    """
    config = runtime.samba()
    config.shares = [
        SambaShare.from_dict(share.model_dump()) for share in update.shares
    ]
    _write(runtime, config)
    return read_settings(runtime)


@router.put("/users", response_model=SambaSettingsView)
def update_users(
    update: SambaUserListUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> SambaSettingsView:
    """Replace the user list.

    Removing a user also drops it from every share that named it: a share
    restricted to accounts that no longer exist would otherwise refuse
    everyone, silently.

    Args:
        update: The new user names.
        runtime: The shared runtime.

    Returns:
        The stored settings.

    Raises:
        HTTPException: 400 when the configuration does not hold together.
    """
    config = runtime.samba()
    config.users = update.users
    for share in config.shares:
        share.valid_users = [user for user in share.valid_users if user in update.users]
    _write(runtime, config)
    return read_settings(runtime)


@router.post("/apply", response_model=ApplyResult)
async def apply(runtime: PanelRuntime = Depends(get_runtime)) -> ApplyResult:
    """Render the stored configuration, converge accounts, and load it.

    Args:
        runtime: The shared runtime.

    Returns:
        Whether the apply succeeded and what was done. A failure is reported
        rather than raised, so the panel shows the reason beside the button —
        a refused file operation included, which is what a sandboxed unit
        turns a share-directory chmod into.
    """
    try:
        message = await runtime.apply_samba()
    except (CommandError, ValueError, OSError) as error:
        return ApplyResult(is_applied=False, message=str(error))
    return ApplyResult(is_applied=True, message=message)


@router.post("/users/{name}/password", response_model=SambaUserView)
def set_password(
    name: str,
    update: SambaPasswordUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> SambaUserView:
    """Set one user's share password.

    Args:
        name: A configured user.
        update: The new password.
        runtime: The shared runtime.

    Returns:
        The user's state afterwards.

    Raises:
        HTTPException: 404 for a name not in the configuration — passwords are
            set for configured users, not to conjure new ones — and 502 when
            Samba refuses, most often because the account has not been applied
            yet.
    """
    config = runtime.samba()
    if name not in config.users:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{name!r} is not a configured user",
        )
    manager = SambaUserManager()
    try:
        manager.set_password(name, update.password)
    except CommandError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error
    surveyed = manager.survey([name])
    return SambaUserView(**vars(surveyed[0]))


@router.get("/status", response_model=SambaStatusView)
def read_status(runtime: PanelRuntime = Depends(get_runtime)) -> SambaStatusView:
    """Read who is connected and how full each share is.

    Args:
        runtime: The shared runtime.

    Returns:
        Live sessions and per-share disk usage.
    """
    reader = SambaStatusReader()
    config = runtime.samba()
    return SambaStatusView(
        is_active=runtime.services.status("samba").is_active,
        sessions=[SambaSessionView(**entry) for entry in reader.sessions()],
        disks=[SambaDiskView(**entry) for entry in reader.disk_usage(config)],
    )


def _write(runtime: PanelRuntime, config: SambaConfig) -> None:
    try:
        runtime.write_samba(config)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
