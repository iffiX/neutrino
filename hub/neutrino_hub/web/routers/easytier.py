"""The EasyTier sections of the Overlay page.

A network here is a name and a secret this hub owns, so this is where they are
minted, stored and handed out. There is no console anywhere else to check them
against: whoever carries both is on the network.
"""

import asyncio
import socket
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.easytier.config import (
    EasyTierConfig,
    generated_address,
    generated_name,
    generated_secret,
    validate_address,
    validate_name,
    validate_network,
    validate_peer,
)
from neutrino_hub.modules.easytier.constants import (
    EASYTIER_CORE_PATH,
    EASYTIER_VERSION,
)
from neutrino_hub.modules.easytier.ops import (
    EASYTIER_CONFIG_NAME,
    EASYTIER_LINK_LOCAL,
    EasyTierConfigApplier,
    EasyTierStatusReader,
    read_stored,
)
from neutrino_hub.modules.router.constants import ROUTER_ROLE_WAN
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    EasyTierNetworkRequest,
    EasyTierNetworksRequest,
    EasyTierNodeView,
    EasyTierPeersRequest,
    EasyTierPeerView,
    EasyTierSecretView,
    EasyTierSuggestedNetwork,
    EasyTierSuggestionView,
    EasyTierView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/easytier", tags=["easytier"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=EasyTierView)
def read_state(runtime: PanelRuntime = Depends(get_runtime)) -> EasyTierView:
    """Read the network, what it exports, and who is on it.

    Args:
        runtime: The shared runtime.

    Returns:
        The EasyTier payload.
    """
    return _view(runtime, _config())


@router.put("", response_model=EasyTierView)
async def update_network(
    request: EasyTierNetworkRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> EasyTierView:
    """Store the network this box is a member of.

    Args:
        request: The name, the secret, and this box's address on it.
        runtime: The shared runtime.

    Returns:
        The state afterwards.

    Raises:
        HTTPException: 400 for a name or address that is not one, or a first
            network with no secret; 502 when the engine refuses what was
            written.
    """
    config = _config()
    try:
        validate_name(request.network_name)
    except ValueError as error:
        raise _bad_request(
            "easytier_name_invalid", name=request.network_name
        ) from error
    try:
        validate_address(request.address)
    except ValueError as error:
        raise _bad_request(
            "easytier_address_invalid", address=request.address
        ) from error
    if not request.network_secret and not config.secret_sealed:
        raise _bad_request("easytier_secret_missing")
    config.network_name = request.network_name
    config.address = request.address
    config.hostname = request.hostname
    if request.network_secret:
        config.set_secret(request.network_secret)
    return await _store(runtime, config)


@router.put("/peers", response_model=EasyTierView)
async def update_peers(
    request: EasyTierPeersRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> EasyTierView:
    """Store what this box connects to when it starts.

    Args:
        request: The addresses, in the order they are tried.
        runtime: The shared runtime.

    Returns:
        The state afterwards.

    Raises:
        HTTPException: 400 for an address the engine would not dial, 502 when
            the engine refuses what was written.
    """
    config = _config()
    peers = [entry.strip() for entry in request.peers if entry.strip()]
    for uri in peers:
        try:
            validate_peer(uri)
        except ValueError as error:
            raise _bad_request("easytier_peer_invalid", uri=uri) from error
    config.peers = peers
    return await _store(runtime, config)


@router.put("/networks", response_model=EasyTierView)
async def update_networks(
    request: EasyTierNetworksRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> EasyTierView:
    """Store the networks this box makes reachable to the others.

    Args:
        request: The CIDRs.
        runtime: The shared runtime.

    Returns:
        The state afterwards.

    Raises:
        HTTPException: 400 for a network that is not one, 502 when the engine
            refuses what was written.
    """
    config = _config()
    networks = [entry.strip() for entry in request.exported_networks if entry.strip()]
    for cidr in networks:
        try:
            validate_network(cidr)
        except ValueError as error:
            raise _bad_request("easytier_network_invalid", cidr=cidr) from error
    config.exported_networks = networks
    return await _store(runtime, config)


@router.post("/suggestion", response_model=EasyTierSuggestionView)
def suggest(runtime: PanelRuntime = Depends(get_runtime)) -> EasyTierSuggestionView:
    """A network nothing has stored yet, for an empty form to start from.

    Args:
        runtime: The shared runtime, for the networks this box already has.

    Returns:
        A name, a secret and an address, none of them stored.
    """
    taken = [cidr for cidr, _ in _machine_networks(runtime)]
    return EasyTierSuggestionView(
        network_name=generated_name(),
        network_secret=generated_secret(),
        address=generated_address(taken),
    )


@router.get("/secret", response_model=EasyTierSecretView)
def read_secret() -> EasyTierSecretView:
    """The network secret, for the person who has to paste it elsewhere.

    Returns:
        The secret, empty when no network is stored.

    Raises:
        HTTPException: 502 when the vault cannot open what is stored.
    """
    try:
        return EasyTierSecretView(network_secret=_config().secret())
    except (ValueError, OSError) as error:
        raise _bad_gateway(
            "easytier_apply_failed", detail=command_failure_text(error)
        ) from error


async def _store(runtime: PanelRuntime, config: EasyTierConfig) -> EasyTierView:
    """Write the configuration and make the engine run on it.

    Args:
        runtime: The shared runtime.
        config: What to store.

    Returns:
        The state afterwards.

    Raises:
        HTTPException: 502 when the engine refuses it.
    """
    write_config(EASYTIER_CONFIG_NAME, config.to_dict())
    try:
        await asyncio.to_thread(
            EasyTierConfigApplier().apply, config, hostname=socket.gethostname()
        )
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        raise _bad_gateway(
            "easytier_apply_failed", detail=command_failure_text(error)
        ) from error
    return _view(runtime, config)


def _config() -> EasyTierConfig:
    """What is stored for this box.

    Returns:
        The configuration, empty on a box that has never had one.
    """
    return read_stored()


def _view(runtime: PanelRuntime, config: EasyTierConfig) -> EasyTierView:
    """The payload the page draws.

    Args:
        runtime: The shared runtime.
        config: What is stored.

    Returns:
        The stored network, this machine's own networks, and the live peers.
    """
    peers = EasyTierStatusReader().peers()
    local = next(
        (peer for peer in peers if peer.link == EASYTIER_LINK_LOCAL),
        None,
    )
    status_ = runtime.services.status("easytier")
    return EasyTierView(
        is_installed=EASYTIER_CORE_PATH.is_file(),
        is_active=status_.is_active,
        version=EASYTIER_VERSION,
        network_name=config.network_name,
        is_secret_set=bool(config.secret_sealed),
        address=config.address,
        hostname=config.hostname,
        peers=list(config.peers),
        exported_networks=list(config.exported_networks),
        suggested_networks=[
            EasyTierSuggestedNetwork(cidr=cidr, interface=name)
            for cidr, name in _machine_networks(runtime)
        ],
        join_host=_join_host(runtime),
        node=(
            None
            if not config.is_configured
            else EasyTierNodeView(
                is_connected=any(
                    peer.is_connected and peer.link != EASYTIER_LINK_LOCAL
                    for peer in peers
                ),
                address=config.address,
                hostname=(local.hostname if local else config.hostname),
                nat_type=(local.nat_type if local else ""),
            )
        ),
        live_peers=[
            EasyTierPeerView(
                hostname=peer.hostname,
                address=peer.address,
                link=peer.link,
                protocol=peer.protocol,
                latency_ms=peer.latency_ms,
                loss_ratio=peer.loss_ratio,
                rx_bytes=peer.rx_bytes,
                tx_bytes=peer.tx_bytes,
                nat_type=peer.nat_type,
                version=peer.version,
                is_connected=peer.is_connected,
            )
            for peer in peers
            if peer.link != EASYTIER_LINK_LOCAL
        ],
    )


def _machine_networks(runtime: PanelRuntime) -> list:
    """Every network this machine is on, for the export checkboxes.

    Args:
        runtime: The shared runtime.

    Returns:
        ``(cidr, interface)`` pairs.
    """
    return runtime.network().local_networks(device_addresses())


def _join_host(runtime: PanelRuntime) -> str:
    """What another machine dials to reach this one.

    Args:
        runtime: The shared runtime.

    Returns:
        An address of this box, the uplink's first because a machine that is
        not on the LAN is the one that needs telling. Empty when this box
        holds no address at all.
    """
    addresses = device_addresses()
    network = runtime.network()
    overlays = set(network.overlay_device_names)
    uplinks = [
        interface.name
        for interface in network.interfaces
        if interface.role == ROUTER_ROLE_WAN
    ]
    for name in uplinks + sorted(addresses):
        if name in overlays or name not in addresses:
            continue
        return addresses[name].split("/")[0]
    return ""


def _bad_request(code: str, **params) -> HTTPException:
    """One 400 carrying the name of what happened.

    Args:
        code: What was refused.
        params: The values the panel's sentence names.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": params},
    )


def _bad_gateway(code: str, **params) -> HTTPException:
    """One 502 carrying the name of what happened.

    Args:
        code: What went wrong below the panel.
        params: The values the panel's sentence names.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": code, "params": params},
    )
