"""Which overlays carry the way back into this box.

Any of them, all at once or none. Whether an engine runs is stored where the
firewall already reads it — the overlay rows in ``config/router/network.json``
— so turning an engine on here and opening or closing it on the Network page
stay one fact rather than two that can disagree.
"""

import ipaddress
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.overlay.config import enabled_providers, set_enabled
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_DIRECT,
    OVERLAY_DIRECT_TITLE,
    OVERLAY_ENGINES,
    OVERLAY_RELAY,
    OVERLAY_RELAY_STATE_CONNECTED,
    OVERLAY_RELAY_TITLE,
)
from neutrino_hub.modules.overlay.direct_config import (
    OverlayDirectConfig,
    read_direct,
    write_direct,
)
from neutrino_hub.modules.overlay.ops import engine_devices, overlay_subnets
from neutrino_hub.modules.overlay.relay_config import (
    OverlayRelayConfig,
    read_relay,
    write_relay,
)
from neutrino_hub.modules.overlay.relay_ops import ssh_path
from neutrino_hub.modules.overlay.route_check import find_subnet_overlap
from neutrino_hub.modules.registry import MODULE_SPECS
from neutrino_hub.modules.services.constants import SERVICES_REACHED_DIRECT
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.system.machine import ANY_ARCHITECTURE, machine_architecture
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    OverlayChoiceRequest,
    OverlayChoiceView,
    OverlayKindView,
    OverlayRouteConflictView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/hub/overlay", tags=["overlay"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=OverlayChoiceView)
def read_choice(runtime: PanelRuntime = Depends(get_runtime)) -> OverlayChoiceView:
    """Read which overlays this box runs.

    Args:
        runtime: The shared runtime.

    Returns:
        One row per overlay engine this hub knows about.
    """
    return _view(runtime)


@router.post("/set", response_model=OverlayChoiceView)
async def update_choice(
    request: OverlayChoiceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> OverlayChoiceView:
    """Turn overlay engines on or off, and converge on the new set.

    Args:
        request: For each engine named, whether it runs from now on; an
            engine left out keeps what it has.
        runtime: The shared runtime.

    Returns:
        The state afterwards.

    Raises:
        HTTPException: 400 for an engine this hub does not run yet, that has
            no build for this machine, or whose network overlaps one this box
            is already on, and ``relay_ssh_missing`` for the relay on a
            machine with no OpenSSH client; 502 when the converge step that
            follows fails.
    """
    network = runtime.network()
    is_changed = False
    was_enabled = set(enabled_providers(network))
    for key, switch in _switches(request).items():
        engine = OVERLAY_ENGINES[key]
        if switch.is_enabled:
            if not engine.is_integrated:
                raise _bad_request("overlay_not_integrated", title=engine.title)
            if not _is_supported(key):
                raise _bad_request("overlay_not_supported", title=engine.title)
        is_changed = set_enabled(network, key, is_enabled=switch.is_enabled) or (
            is_changed
        )
    if set(enabled_providers(network)) - was_enabled:
        _refuse_overlap(network)
    relay = _relay_switched(request)
    direct = _direct_switched(request)
    # Written before the engines are touched: what the box is a member of is
    # the stored fact, and a daemon started against a configuration that was
    # never written is a machine on an overlay nothing records.
    if is_changed:
        runtime.write_network(network)
    if relay is not None:
        write_relay(relay)
    if direct is not None:
        write_direct(direct)
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
            "overlay_switch_failed", detail=command_failure_text(error)
        ) from error
    return _view(runtime)


def subnet_overlap_refusal(network, overlay_subnets_given: dict) -> None:
    """Refuse a set of overlays whose networks overlap.

    Args:
        network: The router configuration as it would be stored, for the
            networks this box is on.
        overlay_subnets_given: Provider to the networks its addresses come
            from.

    Raises:
        HTTPException: 400 with ``overlay_subnet_overlap {title, subnet,
            conflict}`` for the first overlap.
    """
    local = [cidr for cidr, _ in network.local_networks(device_addresses())]
    overlap = find_subnet_overlap(overlay_subnets_given, local)
    if overlap is not None:
        raise _bad_request(
            "overlay_subnet_overlap",
            title=OVERLAY_ENGINES[overlap.provider].title,
            subnet=overlap.subnet,
            conflict=overlap.conflict,
        )


def _refuse_overlap(network) -> None:
    """Refuse the enabled set when its networks overlap.

    Args:
        network: The router configuration as it would be stored.

    Raises:
        HTTPException: 400 with ``overlay_subnet_overlap`` for the first
            overlap.
    """
    subnet_overlap_refusal(network, overlay_subnets(enabled_providers(network)))


def _relay_switched(request: OverlayChoiceRequest) -> "OverlayRelayConfig | None":
    """The stored relay with the request's switch, when the switch moves it.

    Args:
        request: The switches.

    Returns:
        The relay to store, None when the request leaves it as it is.

    Raises:
        HTTPException: 400 ``relay_ssh_missing`` when it is turned on and
            this machine has no OpenSSH client.
    """
    if request.relay is None:
        return None
    relay = _stored_relay()
    if request.relay.is_enabled == relay.is_enabled:
        return None
    if request.relay.is_enabled and not ssh_path():
        raise _bad_request("relay_ssh_missing")
    relay.is_enabled = request.relay.is_enabled
    return relay


def _direct_switched(request: OverlayChoiceRequest) -> "OverlayDirectConfig | None":
    """The stored Direct settings with the request's switch, when it moves them.

    Args:
        request: The switches.

    Returns:
        The settings to store, None when the request leaves Direct as it is.
    """
    if request.direct is None:
        return None
    direct = stored_direct()
    if request.direct.is_enabled == direct.is_enabled:
        return None
    direct.is_enabled = request.direct.is_enabled
    return direct


def stored_direct() -> OverlayDirectConfig:
    """The stored Direct settings; a file that does not read is Direct off."""
    try:
        return read_direct()
    except ValueError:
        return OverlayDirectConfig()


def _stored_relay() -> OverlayRelayConfig:
    """The stored relay; a file that does not read is a relay never set."""
    try:
        return read_relay()
    except ValueError:
        return OverlayRelayConfig()


def _switches(request: OverlayChoiceRequest) -> dict:
    """The engines the request names, by key, in the engine table's order."""
    named = {key: getattr(request, key, None) for key in OVERLAY_ENGINES}
    return {key: switch for key, switch in named.items() if switch is not None}


def _view(runtime: PanelRuntime) -> OverlayChoiceView:
    """The switches' payload.

    Args:
        runtime: The shared runtime.

    Returns:
        Direct's row, the relay's, then a row per overlay engine in the engine
        table's order.
    """
    network = runtime.network()
    enabled = {overlay.provider for overlay in network.enabled_overlays}
    addresses = device_addresses()
    peers = [session.address for session in runtime.client_sessions.sessions()]
    kinds = [_direct_kind(runtime), _relay_kind(runtime, peers)]
    for key, engine in OVERLAY_ENGINES.items():
        is_installed, is_active = _unit_status(runtime, key)
        kinds.append(
            OverlayKindView(
                key=key,
                title=engine.title,
                is_enabled=key in enabled,
                is_integrated=engine.is_integrated,
                is_supported=_is_supported(key),
                is_installed=is_installed,
                is_active=is_active,
                client_count=(
                    _client_count(key, addresses, peers) if key in enabled else 0
                ),
            )
        )
    return OverlayChoiceView(
        kinds=kinds,
        route_conflicts=[
            OverlayRouteConflictView(
                code=(
                    "overlay_default_route_refused"
                    if conflict.is_default
                    else "overlay_route_overlap"
                ),
                params={
                    "title": OVERLAY_ENGINES[conflict.provider].title,
                    "route": conflict.route,
                    "conflict": conflict.conflict,
                },
                is_withdrawn=conflict.is_withdrawn,
            )
            for conflict in runtime.overlay_route_conflicts
        ],
    )


def _direct_kind(runtime: PanelRuntime) -> OverlayKindView:
    """Direct's row, the first.

    Args:
        runtime: The shared runtime, for how each client reached the hub.

    Returns:
        The row: always installed, active while it is on, and counting the
        online clients that reached the hub from outside its networks.
    """
    direct = stored_direct()
    online = set(runtime.client_sessions.keys())
    return OverlayKindView(
        key=OVERLAY_DIRECT,
        title=OVERLAY_DIRECT_TITLE,
        is_enabled=direct.is_enabled,
        is_integrated=True,
        is_supported=True,
        is_installed=True,
        is_active=direct.is_enabled,
        client_count=(
            sum(
                1
                for key, reached in runtime.client_reached.items()
                if reached == SERVICES_REACHED_DIRECT and key in online
            )
            if direct.is_enabled
            else 0
        ),
    )


def _relay_kind(runtime: PanelRuntime, peers: list) -> OverlayKindView:
    """The relay's row, after Direct's.

    Args:
        runtime: The shared runtime, for where the relay stands.
        peers: Where each online client's socket comes from.

    Returns:
        The row: installed when the system has an OpenSSH client, active
        while it is ``connected``, and counting the clients whose socket
        comes from loopback.
    """
    relay = _stored_relay()
    return OverlayKindView(
        key=OVERLAY_RELAY,
        title=OVERLAY_RELAY_TITLE,
        is_enabled=relay.is_enabled,
        is_integrated=True,
        is_supported=True,
        is_installed=bool(ssh_path()),
        is_active=runtime.relay_monitor.view()["state"]
        == OVERLAY_RELAY_STATE_CONNECTED,
        client_count=(
            sum(1 for peer in peers if _is_loopback(peer)) if relay.is_enabled else 0
        ),
    )


def _is_loopback(peer: str) -> bool:
    """Whether a socket's address is a loopback one."""
    try:
        return ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return False


def _client_count(provider: str, addresses: dict, peers: list) -> int:
    """How many online clients reach this hub through one engine.

    Args:
        provider: The engine.
        addresses: Device name to address with its prefix.
        peers: Where each online client's socket comes from.

    Returns:
        The clients whose address lies in a network one of the engine's
        devices holds an address in.
    """
    networks = []
    for name in engine_devices(provider):
        try:
            networks.append(ipaddress.ip_interface(addresses[name]).network)
        except (KeyError, ValueError):
            continue
    counted = 0
    for peer in peers:
        try:
            address = ipaddress.ip_address(peer)
        except ValueError:
            continue
        if any(address in network for network in networks):
            counted += 1
    return counted


def _unit_status(runtime: PanelRuntime, name: str) -> tuple:
    """Whether one engine's unit is there and running.

    Args:
        runtime: The shared runtime.
        name: The engine key, which is also its service name.

    Returns:
        ``(is_installed, is_active)``; both False for an engine systemd has
        never heard of, which is what an unintegrated one always is.
    """
    try:
        state = runtime.services.status(name)
    except (KeyError, OSError):
        return (False, False)
    return (state.is_installed, state.is_active)


def _is_supported(name: str) -> bool:
    """Whether this machine has a build of one engine.

    Args:
        name: The engine key, which is also its module name.

    Returns:
        True when the module declares this architecture, False when it
        declares another or when nothing installs it.
    """
    spec = MODULE_SPECS.get(name)
    if spec is None:
        return False
    return (
        ANY_ARCHITECTURE in spec.architectures
        or machine_architecture() in spec.architectures
    )


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
