"""The relay section of the Access page.

The relay is a reverse SSH forward to a server the person owns. Its settings
are stored in ``config/overlay/relay.json`` and made true by the converge
step; where it stands is read from the runtime's monitor.
"""

import asyncio
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.overlay.constants import (
    OVERLAY_RELAY_PORT_MAX,
    OVERLAY_RELAY_PORT_MIN,
)
from neutrino_hub.modules.overlay.relay_config import (
    OverlayRelayConfig,
    is_account_refused,
    is_host_refused,
    read_relay,
    write_relay,
)
from neutrino_hub.modules.overlay.relay_ops import (
    forget_host_key,
    is_key_stored,
    is_relay_configured,
)
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import RelaySetRequest, RelayView
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/hub/overlay", tags=["overlay"], dependencies=[Depends(require_session)]
)


@router.get("/relay", response_model=RelayView)
def read_state(runtime: PanelRuntime = Depends(get_runtime)) -> RelayView:
    """Read the relay's settings and where it stands.

    Args:
        runtime: The shared runtime.

    Returns:
        The relay's view.
    """
    return relay_view(runtime)


@router.post("/relay/set", response_model=RelayView)
async def update_settings(
    request: RelaySetRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> RelayView:
    """Store the relay's settings and converge on them.

    A different host or SSH port deletes the recorded host key, so the next
    connection records the new server's key.

    Args:
        request: The settings.
        runtime: The shared runtime.

    Returns:
        The relay's view afterwards.

    Raises:
        HTTPException: 400 ``relay_host_invalid {host}``,
            ``relay_account_invalid {account}``, ``unknown_credential
            {field}`` or ``port_out_of_range {minimum, maximum, value}``;
            502 ``relay_apply_failed {detail}`` when the converge step fails.
    """
    host = request.host.strip()
    account = request.account.strip()
    if is_host_refused(host):
        raise _bad_request("relay_host_invalid", host=request.host)
    if is_account_refused(account):
        raise _bad_request("relay_account_invalid", account=request.account)
    for value in (request.ssh_port, request.public_port):
        if not OVERLAY_RELAY_PORT_MIN <= value <= OVERLAY_RELAY_PORT_MAX:
            raise _bad_request(
                "port_out_of_range",
                minimum=OVERLAY_RELAY_PORT_MIN,
                maximum=OVERLAY_RELAY_PORT_MAX,
                value=value,
            )
    if not is_key_stored(request.key_id):
        raise _bad_request("unknown_credential", field="key_id")
    stored = _stored()
    if (host, request.ssh_port) != (stored.host, stored.ssh_port):
        forget_host_key()
    write_relay(
        OverlayRelayConfig(
            is_enabled=stored.is_enabled,
            host=host,
            ssh_port=request.ssh_port,
            account=account,
            key_id=request.key_id,
            public_port=request.public_port,
        )
    )
    await _converge(runtime)
    return relay_view(runtime)


@router.post("/relay/host_key/remove", response_model=RelayView)
async def remove_host_key(runtime: PanelRuntime = Depends(get_runtime)) -> RelayView:
    """Forget the recorded host key and start the relay again.

    Args:
        runtime: The shared runtime.

    Returns:
        The relay's view afterwards.

    Raises:
        HTTPException: 502 ``relay_apply_failed {detail}`` when the relay
            cannot be started again.
    """
    forget_host_key()
    try:
        await asyncio.to_thread(runtime.apply_relay, is_restarted=True)
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        raise _bad_gateway(
            "relay_apply_failed", detail=command_failure_text(error)
        ) from error
    return relay_view(runtime)


def relay_view(runtime: PanelRuntime) -> RelayView:
    """The relay's settings beside where it stands.

    Args:
        runtime: The shared runtime.

    Returns:
        The view.
    """
    config = _stored()
    seen = runtime.relay_monitor.view()
    return RelayView(
        is_enabled=config.is_enabled,
        host=config.host,
        ssh_port=config.ssh_port,
        account=config.account,
        key_id=config.key_id,
        public_port=config.public_port,
        url=config.url if is_relay_configured(config) else "",
        state=seen["state"],
        host_key_fingerprint=seen["host_key_fingerprint"],
        last_error=seen["last_error"],
        checked_at=seen["checked_at"],
    )


def _stored() -> OverlayRelayConfig:
    """The stored relay; a file that does not read is a relay never set."""
    try:
        return read_relay()
    except ValueError:
        return OverlayRelayConfig()


async def _converge(runtime: PanelRuntime) -> None:
    """Run the converge step, its failure as ``relay_apply_failed``."""
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
            "relay_apply_failed", detail=command_failure_text(error)
        ) from error


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
