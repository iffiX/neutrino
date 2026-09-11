"""Which overlay carries the way back into this box.

One at a time, or none. The choice is stored where the firewall already reads
it — the overlay row in ``config/router/network.json`` — so picking an engine
here and opening or closing it on the Network page stay one fact rather than
two that can disagree.
"""

import asyncio
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.overlay.config import provider_of, set_provider
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_ENGINES,
    OVERLAY_NONE,
    OVERLAY_PROVIDERS,
)
from neutrino_hub.modules.overlay.ops import OverlaySwitcher
from neutrino_hub.modules.registry import MODULE_SPECS
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
    prefix="/api/overlay", tags=["overlay"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=OverlayChoiceView)
def read_choice(runtime: PanelRuntime = Depends(get_runtime)) -> OverlayChoiceView:
    """Read which overlay this box runs and what it could run instead.

    Args:
        runtime: The shared runtime.

    Returns:
        The stored provider and one row per overlay this hub knows about.
    """
    return _view(runtime)


@router.put("", response_model=OverlayChoiceView)
async def update_choice(
    request: OverlayChoiceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> OverlayChoiceView:
    """Put this box on one overlay, or on none.

    Args:
        request: The overlay to run from now on.
        runtime: The shared runtime.

    Returns:
        The state afterwards.

    Raises:
        HTTPException: 400 for an overlay that is not one of them, that this
            hub does not run yet, or that has no build for this machine; 502
            when installing or starting it fails, or when the ruleset that
            follows the change cannot be loaded.
    """
    provider = request.provider
    if provider not in OVERLAY_PROVIDERS:
        raise _bad_request("overlay_unknown_provider", provider=provider)
    engine = OVERLAY_ENGINES.get(provider)
    if engine is not None:
        if not engine.is_integrated:
            raise _bad_request("overlay_not_integrated", title=engine.title)
        if not _is_supported(provider):
            raise _bad_request("overlay_not_supported", title=engine.title)

    network = runtime.network()
    # Written before the engines are touched: what the box is a member of is
    # the stored fact, and a daemon started against a configuration that was
    # never written is a machine on an overlay nothing records.
    if set_provider(network, provider):
        runtime.write_network(network)
    try:
        await asyncio.to_thread(OverlaySwitcher().converge, provider)
    except (subprocess.SubprocessError, OSError, RuntimeError, ValueError) as error:
        raise _bad_gateway(
            "overlay_switch_failed", detail=command_failure_text(error)
        ) from error
    # The ruleset names the overlay's device and its peers' port, so it
    # follows the membership rather than waiting for the next network save.
    try:
        await runtime.apply_network(only=None)
    except (subprocess.SubprocessError, OSError, RuntimeError, ValueError) as error:
        raise _bad_gateway(
            "command_failed", detail=command_failure_text(error)
        ) from error
    return _view(runtime)


def _view(runtime: PanelRuntime) -> OverlayChoiceView:
    """The chooser's payload.

    Args:
        runtime: The shared runtime.

    Returns:
        The stored provider and a row per overlay, none first.
    """
    kinds = [
        OverlayKindView(
            key=OVERLAY_NONE,
            title="",
            is_integrated=True,
            is_supported=True,
            is_installed=True,
            is_active=True,
        )
    ]
    for key, engine in OVERLAY_ENGINES.items():
        status_ = _unit_status(runtime, key)
        kinds.append(
            OverlayKindView(
                key=key,
                title=engine.title,
                is_integrated=engine.is_integrated,
                is_supported=_is_supported(key),
                is_installed=status_[0],
                is_active=status_[1],
            )
        )
    return OverlayChoiceView(provider=provider_of(runtime.network()), kinds=kinds)


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
