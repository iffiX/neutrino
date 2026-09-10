"""The NetBird tab: enrollment, the overlay, and the peers on it.

The gateway's way back in. Joining happens here with a one-time setup key;
the subnet routes that make the LAN reachable live on the management plane,
so the page derives the exact networks to put there and points at the
console. There is no leave button: pressed from abroad it is a lockout, and
a hand at a local shell has `netbird down`.
"""

import asyncio
import ipaddress
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.netbird.ops import NetbirdEnroller, NetbirdStatusReader
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import NetbirdJoinRequest, NetbirdPeerView, NetbirdView
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/netbird", tags=["netbird"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=NetbirdView)
def read_status(runtime: PanelRuntime = Depends(get_runtime)) -> NetbirdView:
    """Read the daemon's state and the peers it can see.

    Args:
        runtime: The shared runtime.

    Returns:
        Enrollment, connectivity, peers, and the LAN subnets whose routes
        belong on the management plane.
    """
    state = NetbirdStatusReader().survey()
    subnets = [
        str(ipaddress.ip_network(interface.lan.cidr, strict=False))
        for interface in runtime.network().lan_interfaces
    ]
    return NetbirdView(
        is_installed=state.is_installed,
        is_active=runtime.services.status("netbird").is_active,
        version=state.version,
        daemon_status=state.daemon_status,
        is_enrolled=state.is_enrolled,
        is_management_connected=state.is_management_connected,
        management_url=state.management_url,
        netbird_ip=state.netbird_ip,
        fqdn=state.fqdn,
        peers=[NetbirdPeerView(**vars(peer)) for peer in state.peers],
        lan_subnets=subnets,
    )


@router.post("/join", response_model=NetbirdView)
async def join(
    request: NetbirdJoinRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> NetbirdView:
    """Enroll the gateway with a setup key.

    The key is used once and never stored anywhere.

    Args:
        request: The key, and a management plane when self-hosting.
        runtime: The shared runtime.

    Returns:
        The state afterwards.

    Raises:
        HTTPException: 502 when the daemon or the management plane refuses.
    """
    try:
        await asyncio.to_thread(
            NetbirdEnroller().join,
            setup_key=request.setup_key,
            management_url=request.management_url,
        )
    except (subprocess.SubprocessError, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=command_failure_text(error),
        ) from error
    return read_status(runtime)
