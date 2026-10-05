"""The Remote desktop block: the one switch that shares a machine's desktop.

On, the machine's agent runs its own copy of RustDesk under RustDesk's own
service names and the hub gives the device its seat password, generated
once; off, the agent's copy does not run and the machine's RustDesk is put
back as it was. The switch is ``remote_desktop.json`` in the device's
directory, off when absent, and the module's ``want`` in the state follows
it.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices.constants import DEVICE_REMOTE_DESKTOP_MODULE
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    RemoteDesktopConfigUpdate,
    RemoteDesktopDeviceView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    push_state,
    require_online,
)

MODULE = DEVICE_REMOTE_DESKTOP_MODULE
CODE_CONFIG_UNWRITABLE = "config_unwritable"


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> RemoteDesktopDeviceView:
    """One device's Remote desktop module: the switch and where it stands.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The switch as stored, the module's state as the machine last
        reported it, and the machine's system.
    """
    platform = runtime.device_platform.get(context.key, {})
    return RemoteDesktopDeviceView(
        **context.fields(),
        is_enabled=runtime.desired_states.remote_desktop(context.key)["is_enabled"],
        platform_os=str(platform.get("os", "") or ""),
    )


router: APIRouter = module_router(
    MODULE, view_model=RemoteDesktopDeviceView, build_view=device_view
)


@router.post("/set", response_model=RemoteDesktopDeviceView)
def update_switch(
    update: RemoteDesktopConfigUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> RemoteDesktopDeviceView:
    """Turn the machine's desktop share on or off.

    Turning it on gives the device its seat password when it holds none;
    a locked vault leaves that to the machine's next report.

    Args:
        update: The device and the switch.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``; 500 ``config_unwritable``.
    """
    context = device_context(runtime, MODULE, update.device_id)
    require_online(context)
    try:
        runtime.desired_states.set_remote_desktop(context.key, update.is_enabled)
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": CODE_CONFIG_UNWRITABLE,
                "params": {"detail": str(error)[:200]},
            },
        ) from error
    if update.is_enabled:
        runtime.desired_states.ensure_seat_password(context.key)
    push_state(runtime, context.key)
    context.config = runtime.desired_states.read(context.key, MODULE)
    return device_view(runtime, context)
