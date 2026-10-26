"""The person's acceptance of Microsoft's terms for VS Code on one machine.

The module opens on a machine only once the person has accepted the terms
for it, recorded as ``terms_accepted_at`` in the device's ``vscode.json``
beside the enabled accounts the shared router keeps there. The press that opens
the terms records the acceptance; a false withdraws it.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from neutrino_hub.modules.devices.constants import (
    DEVICE_VSCODE_MODULE,
    DEVICE_VSCODE_TERMS_KEY,
)
from neutrino_hub.modules.devices.module_table import module_row
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import EnabledAccountsView, VscodeTermsUpdate
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    device_context,
    write_module_config,
)
from neutrino_hub.web.routers.agent.module_instances import device_view

MODULE = DEVICE_VSCODE_MODULE

router = APIRouter(
    prefix=f"/api/agent/module/{MODULE}",
    tags=["module"],
    dependencies=[Depends(require_session)],
)


@router.post("/terms/set", response_model=EnabledAccountsView)
def update_terms(
    update: VscodeTermsUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> EnabledAccountsView:
    """Record or withdraw the person's acceptance of the terms on one machine.

    An acceptance already recorded keeps its first time.

    Args:
        update: The device, and whether the terms are accepted.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 404 ``device_unknown`` when no managed device has the
            id, 500 ``config_unwritable {detail}`` when the device's
            directory cannot be written.
    """
    context = device_context(runtime, MODULE, update.device_id)
    stored = dict(context.config)
    if not update.is_accepted:
        stored.pop(DEVICE_VSCODE_TERMS_KEY, None)
    elif not stored.get(DEVICE_VSCODE_TERMS_KEY):
        stored[DEVICE_VSCODE_TERMS_KEY] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
    write_module_config(runtime, context.key, MODULE, stored)
    context.config = stored
    return device_view(module_row(MODULE), runtime, context)
