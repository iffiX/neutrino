"""The Gitea page: which devices host a git server, and each one's seams.

Deliberately thin. Gitea carries its own complete admin UI, so this manages
only what must agree with the hub, the port, the advertised URL, the
sign-up switch, plus the one thing Gitea cannot do for itself: the first
administrator.
"""

from fastapi import APIRouter, Depends

from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    GiteaAdminCreate,
    GiteaConfigUpdate,
    GiteaDeviceView,
    GiteaPasswordUpdate,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.device_modules import (
    DeviceModuleContext,
    device_context,
    module_router,
    run_command,
    store_config,
)

MODULE = "gitea"
COMMAND_ADMIN = "gitea_admin"
COMMAND_PASSWORD = "gitea_password"
DEFAULT_PORT = 3000


def device_view(runtime: PanelRuntime, context: DeviceModuleContext) -> GiteaDeviceView:
    """One device's git server: the configuration and what it actually has.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The stored settings, plus installed-ness, liveness, version, the
        administrators and the URL that opens it.
    """
    details = context.details
    admins = [str(name) for name in details.get("admins") or []]
    config = context.config
    return GiteaDeviceView(
        **context.fields(),
        listen_port=int(config.get("listen_port", DEFAULT_PORT) or DEFAULT_PORT),
        root_url=str(config.get("root_url", "") or ""),
        is_registration_enabled=bool(config.get("is_registration_enabled", False)),
        is_installed=context.state == "installed",
        is_active=bool(details.get("is_running")),
        version=str(details.get("version", "") or ""),
        has_admin=bool(admins),
        admin_usernames=admins,
        url=str(details.get("url", "") or ""),
    )


router: APIRouter = module_router(
    MODULE, view_model=GiteaDeviceView, build_view=device_view
)


@router.put("/devices/{device_id}", response_model=GiteaDeviceView)
def update_settings(
    device_id: str,
    update: GiteaConfigUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> GiteaDeviceView:
    """Change the configuration.

    Args:
        device_id: The device.
        update: The new settings.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``, 400 with the agent's code when
            the configuration does not hold together.
    """
    context = device_context(runtime, MODULE, device_id)
    store_config(runtime, context, update.model_dump())
    return device_view(runtime, context)


@router.post("/devices/{device_id}/admin", response_model=GiteaDeviceView)
def create_admin(
    device_id: str,
    request: GiteaAdminCreate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> GiteaDeviceView:
    """Create the first administrator account on the device.

    Args:
        device_id: The device.
        request: Name, password and address for the account.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``, 502 with the agent's code:
            ``admin_exists`` when one already exists, ``username_invalid``
            for an unusable name, ``command_failed`` when Gitea refuses.
    """
    context = device_context(runtime, MODULE, device_id)
    run_command(runtime, context, COMMAND_ADMIN, request.model_dump())
    return device_view(runtime, context)


@router.post(
    "/devices/{device_id}/admin/{username}/password", response_model=GiteaDeviceView
)
def reset_admin_password(
    device_id: str,
    username: str,
    update: GiteaPasswordUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> GiteaDeviceView:
    """Reset an administrator's password on the device.

    Args:
        device_id: The device.
        username: An existing administrator.
        update: The new password.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``, 502 with the agent's code:
            ``admin_unknown`` for a name that is not an administrator,
            ``command_failed`` when Gitea refuses.
    """
    context = device_context(runtime, MODULE, device_id)
    run_command(
        runtime,
        context,
        COMMAND_PASSWORD,
        {"username": username, "password": update.password},
    )
    return device_view(runtime, context)
