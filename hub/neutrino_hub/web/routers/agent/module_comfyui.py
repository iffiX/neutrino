"""The ComfyUI block: where the module stands, its settings and the port it reports.

The module's file is ``config/devices/<id>/comfyui.json``, written by the
module's install with its token secret and its PyTorch build; the settings,
``{torch_build, idle_unload}``, change here (agent/modules/comfyui.md, "The
settings are the hub's"). The forwarder's port is the agent's to take, and
the page itself is opened from a client with a token, so the block holds no
link to it.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices import comfyui
from neutrino_hub.modules.devices.constants import (
    DEVICE_COMFYUI_IDLE_UNLOAD_KEY,
    DEVICE_COMFYUI_MODULE,
    DEVICE_COMFYUI_TORCH_BUILD_KEY,
)
from neutrino_hub.web.constants import WEB_CODE_BODY_INVALID
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    ComfyuiDeviceView,
    ComfyuiResourcesView,
    ComfyuiSettingsUpdate,
    DeviceGpuView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    machine_gpus,
    module_router,
    panel_details,
    store_config,
)

MODULE = DEVICE_COMFYUI_MODULE


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> ComfyuiDeviceView:
    """One device's ComfyUI: its row as last reported, its settings and the machine's GPUs.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The view, its port the forwarder's as the machine reports it.
    """
    platform = runtime.device_platform.get(context.key, {})
    builds = comfyui.entry_builds(platform)
    port = context.details.get("port")
    return ComfyuiDeviceView(
        **context.fields(),
        version=str(context.details.get("version", "") or ""),
        details=panel_details(context.details),
        port=int(port) if isinstance(port, int) and not isinstance(port, bool) else 0,
        **comfyui.settings(context.config, builds),
        torch_builds=builds,
        resources=ComfyuiResourcesView(
            gpus=[
                DeviceGpuView.model_validate(gpu)
                for gpu in machine_gpus(runtime.device_metrics.get(context.key))
            ]
        ),
        models_dir=comfyui.models_dir(platform),
    )


router: APIRouter = module_router(
    MODULE, view_model=ComfyuiDeviceView, build_view=device_view
)


@router.post("/set", response_model=ComfyuiDeviceView)
def update_settings(
    update: ComfyuiSettingsUpdate, runtime: PanelRuntime = Depends(get_runtime)
):
    """Store the settings after the agent checked them, and push them.

    A new build names its lock in the recipe, which the module installs with
    ComfyUI stopped; a new idle unload time restarts nothing.

    Raises:
        HTTPException: 400 ``body_invalid {fields}`` for a build the
            machine's entry has no lock of, and for a build on a Mac; 409
            ``agent_offline``; 400 with the agent's code when it refuses
            the settings; 500 ``config_unwritable``.
    """
    context = device_context(runtime, MODULE, update.device_id)
    builds = comfyui.entry_builds(runtime.device_platform.get(context.key, {}))
    is_known = update.torch_build in builds if builds else not update.torch_build
    if not is_known:
        raise _refusal(
            status.HTTP_400_BAD_REQUEST,
            WEB_CODE_BODY_INVALID,
            fields=DEVICE_COMFYUI_TORCH_BUILD_KEY,
        )
    config = {**context.config, DEVICE_COMFYUI_IDLE_UNLOAD_KEY: update.idle_unload}
    if builds:
        config[DEVICE_COMFYUI_TORCH_BUILD_KEY] = update.torch_build
    store_config(runtime, context, config)
    return device_view(runtime, context)


def _refusal(status_code: int, code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "params": dict(params)}
    )
