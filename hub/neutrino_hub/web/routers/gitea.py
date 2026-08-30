"""The Gitea tab: the seams the gateway owns, and a door into the rest.

Deliberately thin. Gitea carries its own complete admin UI, so this manages
only what must agree with the gateway — the port, the advertised URL, the
sign-up switch — plus the one thing Gitea cannot do for itself: the first
administrator, without whom a registration-closed Gitea can never be entered.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.gitea.config import GiteaConfig
from neutrino_hub.modules.gitea.ops import GiteaAdminManager
from neutrino_hub.utils.subprocess_run import CommandError
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ApplyResult,
    GiteaAdminCreate,
    GiteaConfigUpdate,
    GiteaPasswordUpdate,
    GiteaSettingsView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/gitea", tags=["gitea"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=GiteaSettingsView)
def read_settings(runtime: PanelRuntime = Depends(get_runtime)) -> GiteaSettingsView:
    """Read the configuration and what the box actually has.

    Args:
        runtime: The shared runtime.

    Returns:
        The stored settings, plus installed-ness, liveness, version, and
        whether an administrator exists yet.
    """
    config = runtime.gitea()
    state = GiteaAdminManager().survey()
    return GiteaSettingsView(
        **config.to_dict(),
        is_installed=state.is_installed,
        is_active=runtime.services.status("gitea").is_active,
        version=state.version,
        has_admin=state.has_admin,
        admin_usernames=state.admin_usernames,
    )


@router.put("", response_model=GiteaSettingsView)
def update_settings(
    update: GiteaConfigUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> GiteaSettingsView:
    """Change the configuration.

    Args:
        update: The new settings.
        runtime: The shared runtime.

    Returns:
        The stored settings.

    Raises:
        HTTPException: 400 when the configuration does not hold together.
    """
    config = GiteaConfig.from_dict(update.model_dump())
    try:
        runtime.write_gitea(config)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return read_settings(runtime)


@router.post("/apply", response_model=ApplyResult)
async def apply(runtime: PanelRuntime = Depends(get_runtime)) -> ApplyResult:
    """Render ``app.ini`` from the stored configuration and load it.

    Args:
        runtime: The shared runtime.

    Returns:
        Whether the apply succeeded and what was done. A failure is reported
        rather than raised, so the panel shows the reason beside the button.
    """
    try:
        message = await runtime.apply_gitea()
    except (CommandError, ValueError, FileNotFoundError) as error:
        return ApplyResult(is_applied=False, message=str(error))
    return ApplyResult(is_applied=True, message=message)


@router.post("/admin", response_model=GiteaSettingsView)
def create_admin(
    request: GiteaAdminCreate, runtime: PanelRuntime = Depends(get_runtime)
) -> GiteaSettingsView:
    """Create the first administrator account.

    Args:
        request: Name, password and address for the account.
        runtime: The shared runtime.

    Returns:
        The settings view afterwards, with ``has_admin`` flipped.

    Raises:
        HTTPException: 409 when an administrator already exists — later
            accounts are made inside Gitea, where managing them belongs —
            400 for an unusable name, and 502 when Gitea refuses.
    """
    manager = GiteaAdminManager()
    if manager.survey().has_admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an administrator already exists; add more in Gitea",
        )
    try:
        manager.create_admin(
            username=request.username,
            password=request.password,
            email=request.email,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    except CommandError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error
    return read_settings(runtime)


@router.post("/admin/{username}/password", response_model=GiteaSettingsView)
def reset_admin_password(
    username: str,
    update: GiteaPasswordUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> GiteaSettingsView:
    """Reset an administrator's password.

    The recovery door: a forgotten admin password cannot be fixed inside
    Gitea, because fixing it requires the login it replaces. Renaming stays
    in Gitea's own UI — reachable again once the password is.

    Args:
        username: An existing administrator.
        update: The new password.
        runtime: The shared runtime.

    Returns:
        The settings view afterwards.

    Raises:
        HTTPException: 404 for a name that is not an administrator, 502 when
            Gitea refuses.
    """
    manager = GiteaAdminManager()
    if username not in manager.survey().admin_usernames:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{username!r} is not an administrator",
        )
    try:
        manager.change_password(username=username, password=update.password)
    except CommandError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error
    return read_settings(runtime)
