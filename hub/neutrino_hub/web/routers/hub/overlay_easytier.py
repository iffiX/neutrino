"""The EasyTier sections of the Overlay page.

The network comes from one of two modes. In manual mode it is a name and a
secret this hub owns, so this is where they are minted, stored and handed
out: whoever carries both is on the network. In console mode EasyTier's own
console pushes the network, this page keeps only the console's address, and
what the engine then runs is read back and shown.
"""

import ipaddress
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.easytier.config import (
    EasyTierConfig,
    generated_address,
    generated_name,
    generated_secret,
    validate_address,
    validate_config_server,
    validate_mode,
    validate_name,
    validate_network,
    validate_peer,
)
from neutrino_hub.modules.easytier.constants import (
    EASYTIER_CORE_PATH,
    EASYTIER_MODE_CONSOLE,
    EASYTIER_VERSION,
)
from neutrino_hub.modules.easytier.ops import (
    EASYTIER_CONFIG_NAME,
    EASYTIER_LINK_LOCAL,
    EasyTierStatusReader,
    read_stored,
)
from neutrino_hub.modules.overlay.config import enabled_providers
from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER
from neutrino_hub.modules.overlay.ops import overlay_subnets
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.channel_overlay import easytier_join_host
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    EasyTierInstanceView,
    EasyTierNodeView,
    EasyTierPeerView,
    EasyTierSecretView,
    EasyTierSettingsRequest,
    EasyTierSuggestedNetwork,
    EasyTierSuggestionView,
    EasyTierView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.hub.overlay import subnet_overlap_refusal

router = APIRouter(
    prefix="/api/hub/overlay", tags=["overlay"], dependencies=[Depends(require_session)]
)


@router.get("/easytier", response_model=EasyTierView)
def read_state(runtime: PanelRuntime = Depends(get_runtime)) -> EasyTierView:
    """Read the network, what it exports, and who is on it.

    Args:
        runtime: The shared runtime.

    Returns:
        The EasyTier payload.
    """
    return _view(runtime, _config())


@router.post("/easytier/set", response_model=EasyTierView)
async def update_settings(
    request: EasyTierSettingsRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> EasyTierView:
    """Store every EasyTier setting at once, and converge on them.

    Args:
        request: The mode, the console's address and secure mode, and the
            manual network: its name, its secret, this box's address on it,
            the peers dialled at start and the networks exported to it.
        runtime: The shared runtime.

    Returns:
        The state afterwards.

    Raises:
        HTTPException: 400 for a mode, a console address, a name, an address,
            a peer or a network that is not one, a first manual network with
            no secret, or, while EasyTier runs, an address whose network
            overlaps another overlay's or one this box is on; 502 when the
            converge step that follows fails.
        VaultLockedError: If there is no data key to seal a secret or a
            console address under.
    """
    try:
        validate_mode(request.mode)
    except ValueError as error:
        raise _bad_request("easytier_mode_unknown", mode=request.mode) from error
    config = _config()
    is_manual = request.mode != EASYTIER_MODE_CONSOLE
    if request.network_name or is_manual:
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
    if is_manual and not request.network_secret and not config.secret_sealed:
        raise _bad_request("easytier_secret_missing")
    peers = [entry.strip() for entry in request.peers if entry.strip()]
    for uri in peers:
        try:
            validate_peer(uri)
        except ValueError as error:
            raise _bad_request("easytier_peer_invalid", uri=uri) from error
    networks = [entry.strip() for entry in request.exported_networks if entry.strip()]
    for cidr in networks:
        try:
            validate_network(cidr)
        except ValueError as error:
            raise _bad_request("easytier_network_invalid", cidr=cidr) from error
    if is_manual and request.address:
        _refuse_overlap(runtime, request.address)
    config_server = (
        None if request.config_server is None else request.config_server.strip()
    )
    if config_server:
        try:
            validate_config_server(config_server)
        except ValueError as error:
            raise _bad_request("easytier_config_server_invalid") from error
    config.mode = request.mode
    if config_server:
        config.set_config_server(config_server)
    elif config_server is not None:
        config.clear_config_server()
    config.is_secure_mode = request.is_secure_mode
    config.network_name = request.network_name
    config.address = request.address
    config.hostname = request.hostname
    if request.network_secret:
        config.set_secret(request.network_secret)
    config.peers = peers
    config.exported_networks = networks
    return await _store(runtime, config)


@router.post("/easytier/suggestion/create", response_model=EasyTierSuggestionView)
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


@router.get("/easytier/secret", response_model=EasyTierSecretView)
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
    """Write the configuration and converge on it.

    Args:
        runtime: The shared runtime.
        config: What to store.

    Returns:
        The state afterwards.

    Raises:
        HTTPException: 502 when the converge step fails.
    """
    write_config(EASYTIER_CONFIG_NAME, config.to_dict())
    try:
        await runtime.converge_network()
    except (
        subprocess.SubprocessError,
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
    ) as error:
        raise _bad_gateway(
            "easytier_apply_failed", detail=command_failure_text(error)
        ) from error
    return _view(runtime, config)


def _refuse_overlap(runtime: PanelRuntime, address: str) -> None:
    """Refuse a manual address whose network overlaps another, while EasyTier
    runs.

    Args:
        runtime: The shared runtime.
        address: This box's address on the network, with its prefix.

    Raises:
        HTTPException: 400 with ``overlay_subnet_overlap`` for the first
            overlap.
    """
    network = runtime.network()
    enabled = enabled_providers(network)
    if OVERLAY_EASYTIER not in enabled:
        return
    subnets = overlay_subnets([key for key in enabled if key != OVERLAY_EASYTIER])
    subnets[OVERLAY_EASYTIER] = [str(ipaddress.ip_interface(address).network)]
    subnet_overlap_refusal(network, subnets)


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
    reader = EasyTierStatusReader()
    peers = reader.peers()
    local = next(
        (peer for peer in peers if peer.link == EASYTIER_LINK_LOCAL),
        None,
    )
    instances = reader.instances() if config.is_console_mode else []
    status_ = runtime.services.status("easytier")
    return EasyTierView(
        is_installed=EASYTIER_CORE_PATH.is_file(),
        is_active=status_.is_active,
        version=EASYTIER_VERSION,
        mode=config.mode,
        has_config_server=config.has_config_server,
        is_secure_mode=config.is_secure_mode,
        instances=[
            EasyTierInstanceView(
                instance_name=instance.instance_name,
                network_name=instance.network_name,
                address=instance.address,
                hostname=instance.hostname,
                subnet_routes=list(instance.subnet_routes),
                withheld=list(instance.withheld),
            )
            for instance in instances
        ],
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
        join_host=easytier_join_host(runtime),
        node=(
            None
            if not config.is_configured
            else EasyTierNodeView(
                is_connected=any(
                    peer.is_connected and peer.link != EASYTIER_LINK_LOCAL
                    for peer in peers
                ),
                address=(
                    (instances[0].address if instances else "")
                    if config.is_console_mode
                    else config.address
                ),
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
