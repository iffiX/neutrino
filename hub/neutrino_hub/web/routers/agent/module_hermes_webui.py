"""The Hermes WebUI block: where the module stands and the port it reports.

The module's file is ``config/devices/<id>/hermes_webui.json``, written by
the module's install with its token secret and the webui's password; the
forwarder's port is the agent's to take, and the page itself is opened from
a client with a token, so the block holds no link to it.
"""

from fastapi import APIRouter

from neutrino_hub.modules.devices.constants import DEVICE_HERMES_WEBUI_MODULE
from neutrino_hub.web.models import HermesWebuiDeviceView
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    module_router,
    panel_details,
)

MODULE = DEVICE_HERMES_WEBUI_MODULE


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> HermesWebuiDeviceView:
    """One device's Hermes WebUI as last reported.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The view, its port the forwarder's as the machine reports it.
    """
    port = context.details.get("port")
    return HermesWebuiDeviceView(
        **context.fields(),
        port=int(port) if isinstance(port, int) and not isinstance(port, bool) else 0,
        version=str(context.details.get("version", "") or ""),
        details=panel_details(context.details),
    )


router: APIRouter = module_router(
    MODULE, view_model=HermesWebuiDeviceView, build_view=device_view
)
