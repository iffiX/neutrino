"""The file share's status: who is connected and how full each share is.

The share's configuration is its enabled accounts, served by the shared
account-layer router; this file holds the one read beside it, the live
parts of the machine's last report.
"""

from fastapi import APIRouter, Depends

from neutrino_hub.modules.devices.constants import DEVICE_SAMBA_MODULE
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import SambaDiskView, SambaSessionView, SambaStatusView
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import device_context

MODULE = DEVICE_SAMBA_MODULE

router = APIRouter(
    prefix=f"/api/agent/module/{MODULE}",
    tags=["module"],
    dependencies=[Depends(require_session)],
)


@router.get("/status", response_model=SambaStatusView)
def read_status(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> SambaStatusView:
    """Read who is connected and how full each share is, as last reported.

    Args:
        device_id: The device, from the query.
        runtime: The shared runtime.

    Returns:
        Whether the unit is active, the live sessions and per-share disk
        usage.

    Raises:
        HTTPException: 404 ``device_unknown``.
    """
    details = device_context(runtime, MODULE, device_id).details
    return SambaStatusView(
        is_active=bool(details.get("is_active")),
        sessions=[
            SambaSessionView(**entry)
            for entry in details.get("sessions") or []
            if isinstance(entry, dict)
        ],
        disks=[
            SambaDiskView(**entry)
            for entry in details.get("disk_usage") or []
            if isinstance(entry, dict)
        ],
    )
