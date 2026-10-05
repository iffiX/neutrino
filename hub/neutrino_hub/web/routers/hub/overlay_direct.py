"""The Direct section of the Access page.

Direct opens the agent port alone on every enabled interface; the panel, the
AI gateway and every other listener keep the exposure the Network page gives
them. Its settings are stored in ``config/overlay/direct.json`` and made true
by the converge step; its switch is on ``POST /api/hub/overlay/set``.
"""

import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.overlay.constants import (
    OVERLAY_DIRECT_PORT_MAX,
    OVERLAY_DIRECT_PORT_MIN,
)
from neutrino_hub.modules.overlay.direct_config import (
    OverlayDirectConfig,
    is_public_host_refused,
    write_direct,
)
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.channel_addresses import direct_interface_state, direct_urls
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import DirectSetRequest, DirectView
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.hub.overlay import stored_direct

router = APIRouter(
    prefix="/api/hub/overlay", tags=["overlay"], dependencies=[Depends(require_session)]
)


@router.get("/direct", response_model=DirectView)
def read_state(runtime: PanelRuntime = Depends(get_runtime)) -> DirectView:
    """Read Direct's settings and the addresses it gives clients.

    Args:
        runtime: The shared runtime.

    Returns:
        Direct's view.
    """
    return direct_view(runtime)


@router.post("/direct/set", response_model=DirectView)
async def update_settings(
    request: DirectSetRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> DirectView:
    """Store the public address the person states for the hub, and converge.

    Args:
        request: The host, empty for none, and its port.
        runtime: The shared runtime.

    Returns:
        Direct's view afterwards.

    Raises:
        HTTPException: 400 ``direct_host_invalid {host}`` for a value that is
            neither an address nor a host name, ``port_out_of_range {minimum,
            maximum, value}``; 502 ``direct_apply_failed {detail}`` when the
            converge step fails.
    """
    host = request.public_host.strip()
    if is_public_host_refused(host):
        raise _bad_request("direct_host_invalid", host=request.public_host)
    if not OVERLAY_DIRECT_PORT_MIN <= request.public_port <= OVERLAY_DIRECT_PORT_MAX:
        raise _bad_request(
            "port_out_of_range",
            minimum=OVERLAY_DIRECT_PORT_MIN,
            maximum=OVERLAY_DIRECT_PORT_MAX,
            value=request.public_port,
        )
    write_direct(
        OverlayDirectConfig(
            is_enabled=stored_direct().is_enabled,
            public_host=host,
            public_port=request.public_port,
        )
    )
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
            "direct_apply_failed", detail=command_failure_text(error)
        ) from error
    return direct_view(runtime)


def direct_view(runtime: PanelRuntime) -> DirectView:
    """Direct's settings beside the addresses it adds to ``urls``.

    Args:
        runtime: The shared runtime.

    Returns:
        The view; ``urls`` is what Direct adds whether it is on or off, so
        the page shows what turning it on gives.
    """
    config = stored_direct()
    return DirectView(
        is_enabled=config.is_enabled,
        public_host=config.public_host,
        public_port=config.public_port,
        urls=direct_urls(runtime, config),
        interface_state=direct_interface_state(runtime),
    )


def _bad_request(code: str, **params) -> HTTPException:
    """One 400 carrying the name of what was refused."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": params},
    )


def _bad_gateway(code: str, **params) -> HTTPException:
    """One 502 carrying the name of what went wrong below the panel."""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": code, "params": params},
    )
