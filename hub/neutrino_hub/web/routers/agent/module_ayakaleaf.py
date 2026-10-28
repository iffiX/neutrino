"""The Ayakaleaf block: where the module stands, the port it reports, and its AI model.

The module's file is ``config/devices/<id>/ayakaleaf.json``, written by the
module's install with its four secrets; the tab's one field, the AI model,
is ``model`` in it. The forwarder's port is the agent's to take, and the
page itself is opened from a client with a token, so the block holds no
link to it.
"""

from fastapi import APIRouter, Depends

from neutrino_hub.modules.clients.ai_keys import gateway_models
from neutrino_hub.modules.devices.constants import (
    DEVICE_AYAKALEAF_MODEL_KEY,
    DEVICE_AYAKALEAF_MODULE,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import AyakaleafDeviceView, AyakaleafModelUpdate
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    panel_details,
    push_state,
    require_online,
    write_module_config,
)

MODULE = DEVICE_AYAKALEAF_MODULE


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> AyakaleafDeviceView:
    """One device's Ayakaleaf as last reported, with the stored model and the gateway's.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The view, its port the forwarder's as the machine reports it.
    """
    port = context.details.get("port")
    models = gateway_models(runtime.served_models)
    return AyakaleafDeviceView(
        **context.fields(),
        port=int(port) if isinstance(port, int) and not isinstance(port, bool) else 0,
        model=str(context.config.get(DEVICE_AYAKALEAF_MODEL_KEY, "") or ""),
        models=models,
        is_gateway_serving=bool(models),
        version=str(context.details.get("version", "") or ""),
        details=panel_details(context.details),
    )


router: APIRouter = module_router(
    MODULE, view_model=AyakaleafDeviceView, build_view=device_view
)


@router.post("/set", response_model=AyakaleafDeviceView)
def set_model(
    update: AyakaleafModelUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> AyakaleafDeviceView:
    """Store the AI model the app uses, and push the state whose new environment restarts the app.

    Args:
        update: The device, and the model; empty for the gateway's first.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 404 ``device_unknown``, 409 ``agent_offline``, 500
            ``config_unwritable`` when the file cannot be written.
    """
    context = device_context(runtime, MODULE, update.device_id)
    require_online(context)
    with CONFIG_WRITE_LOCK:
        written = {
            **runtime.desired_states.read(context.key, MODULE),
            DEVICE_AYAKALEAF_MODEL_KEY: update.model.strip(),
        }
        write_module_config(runtime, context.key, MODULE, written)
    context.config = written
    push_state(runtime, context.key)
    return device_view(runtime, context)
