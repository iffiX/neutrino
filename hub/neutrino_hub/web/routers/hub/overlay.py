"""Which overlays carry the way back into this box.

Any of them, all at once or none. Whether an engine runs is stored where the
firewall already reads it — the overlay rows in ``config/router/network.json``
— so turning an engine on here and opening or closing it on the Network page
stay one fact rather than two that can disagree.
"""

import ipaddress
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.overlay.config import set_enabled
from neutrino_hub.modules.overlay.constants import OVERLAY_ENGINES
from neutrino_hub.modules.overlay.ops import engine_devices
from neutrino_hub.modules.registry import MODULE_SPECS
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.system.machine import ANY_ARCHITECTURE, machine_architecture
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    OverlayChoiceRequest,
    OverlayChoiceView,
    OverlayKindView,
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
        HTTPException: 400 for an engine this hub does not run yet, or that
            has no build for this machine; 502 when the converge step that
            follows fails.
    """
    network = runtime.network()
    is_changed = False
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
    # Written before the engines are touched: what the box is a member of is
    # the stored fact, and a daemon started against a configuration that was
    # never written is a machine on an overlay nothing records.
    if is_changed:
        runtime.write_network(network)
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


def _switches(request: OverlayChoiceRequest) -> dict:
    """The engines the request names, by key, in the engine table's order."""
    named = {key: getattr(request, key, None) for key in OVERLAY_ENGINES}
    return {key: switch for key, switch in named.items() if switch is not None}


def _view(runtime: PanelRuntime) -> OverlayChoiceView:
    """The switches' payload.

    Args:
        runtime: The shared runtime.

    Returns:
        A row per overlay engine, in the engine table's order.
    """
    network = runtime.network()
    enabled = {overlay.provider for overlay in network.enabled_overlays}
    addresses = device_addresses()
    peers = [session.address for session in runtime.client_sessions.sessions()]
    kinds = []
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
    return OverlayChoiceView(kinds=kinds)


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
