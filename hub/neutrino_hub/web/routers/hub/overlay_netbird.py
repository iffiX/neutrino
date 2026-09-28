"""The NetBird block of the Overlay page: joining, and the peers on it.

The gateway's way back in. Joining happens here with a setup key, which is
kept sealed for the clients the hub admits to the overlay; the subnet routes that make the LAN reachable live on the management plane,
so the page derives the exact networks to put there and points at the
console. There is no leave button: pressed from abroad it is a lockout, and
a hand at a local shell has `netbird down`.
"""

import asyncio
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.netbird.config import read_stored, write_stored
from neutrino_hub.modules.netbird.ops import NetbirdEnroller, NetbirdStatusReader
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web import channel_state
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    NetbirdJoinRequest,
    NetbirdPeerView,
    NetbirdSetupKeyRequest,
    NetbirdView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/hub/overlay", tags=["overlay"], dependencies=[Depends(require_session)]
)


@router.get("/netbird", response_model=NetbirdView)
def read_status(runtime: PanelRuntime = Depends(get_runtime)) -> NetbirdView:
    """Read the daemon's state and the peers it can see.

    Args:
        runtime: The shared runtime.

    Returns:
        Enrollment, connectivity, peers, and the subnets whose routes belong
        on the management plane.
    """
    state = NetbirdStatusReader().survey()
    # Every network this machine is on, not only the ones it serves: a box
    # that routes nothing is still a peer that can carry a route to its own
    # subnet, and which peer routes what is the management plane's to decide.
    subnets = [cidr for cidr, _ in runtime.network().local_networks(device_addresses())]
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
        has_setup_key=read_stored().has_setup_key,
    )


@router.post("/netbird/join", response_model=NetbirdView)
async def join(
    request: NetbirdJoinRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> NetbirdView:
    """Enroll the gateway with a setup key, and keep the key once it worked.

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
            detail={
                "code": "overlay_join_failed",
                "params": {"detail": command_failure_text(error)},
            },
        ) from error
    try:
        await _keep_setup_key(runtime, request.setup_key, request.management_url)
    except VaultLockedError:
        pass
    return read_status(runtime)


@router.post("/netbird/setup_key/set", response_model=NetbirdView)
async def set_setup_key(
    request: NetbirdSetupKeyRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> NetbirdView:
    """Replace the kept setup key, or forget it, without joining again.

    Args:
        request: The new key; empty forgets the kept one.
        runtime: The shared runtime.

    Returns:
        The state afterwards.

    Raises:
        VaultLockedError: If there is no data key to seal the key under.
    """
    config = read_stored()
    await _keep_setup_key(runtime, request.setup_key, config.management_url)
    return read_status(runtime)


async def _keep_setup_key(
    runtime: PanelRuntime, setup_key: str, management_url: str
) -> None:
    """Store the key, or forget it when empty, and push every client's state."""
    config = read_stored()
    if setup_key:
        config.set_setup_key(setup_key, management_url)
    else:
        config.clear_setup_key()
    write_stored(config)
    await asyncio.to_thread(channel_state.push_states, runtime, CHANNEL_ROLE_CLIENT)
