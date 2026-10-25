"""The Hermes WebUI block: the port the module's forwarder serves the page on.

The module's file is ``config/devices/<id>/hermes_webui.json``; setting the
port writes it, generating the token secret and the webui's password when
the file holds none, and pushes the device's state. The page itself is
opened from a client with a token, so the block holds no link to it.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices.constants import DEVICE_HERMES_WEBUI_MODULE
from neutrino_hub.modules.devices.hermes_webui import (
    ensure_config,
    is_port_valid,
    stored_port,
)
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import HermesWebuiConfigUpdate, HermesWebuiDeviceView
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    panel_details,
    push_state,
    require_online,
)

MODULE = DEVICE_HERMES_WEBUI_MODULE
CODE_PORT_INVALID = "port_invalid"
CODE_CONFIG_UNWRITABLE = "config_unwritable"


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> HermesWebuiDeviceView:
    """One device's Hermes WebUI: the stored port and the module as last reported.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The view.
    """
    return HermesWebuiDeviceView(
        **context.fields(),
        port=stored_port(context.config),
        version=str(context.details.get("version", "") or ""),
        details=panel_details(context.details),
    )


router: APIRouter = module_router(
    MODULE, view_model=HermesWebuiDeviceView, build_view=device_view
)


@router.post("/set", response_model=HermesWebuiDeviceView)
def update_port(
    update: HermesWebuiConfigUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> HermesWebuiDeviceView:
    """Store the forwarder's port and push the device's state.

    Args:
        update: The device and the port.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 400 ``port_invalid {port}`` for a port outside 1024
            to 65535; 409 ``agent_offline``; 500 ``config_unwritable``.
        VaultLockedError: When a secret is missing and the vault has no
            data key to seal one under.
    """
    context = device_context(runtime, MODULE, update.device_id)
    if not is_port_valid(update.port):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": CODE_PORT_INVALID, "params": {"port": update.port}},
        )
    require_online(context)
    try:
        context.config = ensure_config(
            runtime.desired_states, context.key, port=update.port
        )
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": CODE_CONFIG_UNWRITABLE,
                "params": {"detail": str(error)[:200]},
            },
        ) from error
    push_state(runtime, context.key)
    runtime.published_services.schedule_refresh()
    return device_view(runtime, context)
