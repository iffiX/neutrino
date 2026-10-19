"""The SakuraFrp section of the Access page, and what OpenFrp's shares with it.

The account's access key is checked with SakuraFrp and stored sealed in
``config/overlay/sakurafrp.json``; the tunnel list and the pick call the
vendor; the view reads the file and the running frpc and calls nobody.
"""

import asyncio
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import FrpVendorError
from neutrino_hub.modules.frp.config import read_frp, write_frp
from neutrino_hub.modules.frp.constants import (
    FRP_CODE_CONFIG_UNUSABLE,
    FRP_CODE_NOT_SIGNED_IN,
    FRP_CODE_VENDOR_UNREACHABLE,
    FRP_OPENFRP,
    FRP_OPENFRP_CONSOLE_URL,
    FRP_SAKURAFRP,
    FRP_SAKURAFRP_CONSOLE_URL,
    FRP_TITLES,
)
from neutrino_hub.modules.frp.ops import (
    account_tunnels,
    find_tunnel,
    listed_tunnels,
    store_tunnel,
    tunnel_file_text,
    vendor_api,
    write_frpc_file,
)
from neutrino_hub.modules.frp.vendor_api import SakuraFrpApi
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.constants import WEB_DEFAULT_AGENT_LISTEN_PORT
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    FrpAccessKeySetRequest,
    FrpTunnelListView,
    FrpTunnelSetRequest,
    FrpTunnelView,
    FrpView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/hub/overlay", tags=["overlay"], dependencies=[Depends(require_session)]
)

# Each vendor's console, where a tunnel is created.
FRP_CONSOLE_URLS = {
    FRP_SAKURAFRP: FRP_SAKURAFRP_CONSOLE_URL,
    FRP_OPENFRP: FRP_OPENFRP_CONSOLE_URL,
}
# The status each coded refusal answers with.
FRP_STATUS_OF = {
    FRP_CODE_NOT_SIGNED_IN: status.HTTP_409_CONFLICT,
    FRP_CODE_VENDOR_UNREACHABLE: status.HTTP_502_BAD_GATEWAY,
    FRP_CODE_CONFIG_UNUSABLE: status.HTTP_502_BAD_GATEWAY,
}


@router.get("/sakurafrp", response_model=FrpView)
def read_state(runtime: PanelRuntime = Depends(get_runtime)) -> FrpView:
    """Read SakuraFrp's settings and where it stands, calling nobody.

    Args:
        runtime: The shared runtime.

    Returns:
        The view.
    """
    return FrpView(**frp_view_fields(runtime, FRP_SAKURAFRP))


@router.post("/sakurafrp/access_key/set", response_model=FrpView)
async def set_access_key(
    request: FrpAccessKeySetRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> FrpView:
    """Check an access key with SakuraFrp and store it, or forget the stored one.

    Args:
        request: The key; empty forgets the stored one and the picked tunnel.
        runtime: The shared runtime.

    Returns:
        The view afterwards.

    Raises:
        HTTPException: 400 ``frp_credential_refused {title}`` for a key
            SakuraFrp refuses; 502 ``frp_vendor_unreachable {title, detail}``.
    """
    access_key = request.access_key.strip()
    config = read_frp(FRP_SAKURAFRP)
    if not access_key:
        config.forget()
    else:
        try:
            await asyncio.to_thread(SakuraFrpApi(access_key).user_info)
        except FrpVendorError as error:
            raise frp_refusal(error) from error
        config.set_credential(access_key)
    write_frp(config)
    await converge(runtime)
    return FrpView(**frp_view_fields(runtime, FRP_SAKURAFRP))


@router.get("/sakurafrp/tunnel", response_model=FrpTunnelListView)
async def list_tunnels(
    runtime: PanelRuntime = Depends(get_runtime),
) -> FrpTunnelListView:
    """List the account's tunnels the hub can run, with each node's latency.

    Args:
        runtime: The shared runtime.

    Returns:
        The list.

    Raises:
        HTTPException: 409 ``frp_not_signed_in {title}``; 400
            ``frp_credential_refused {title}``; 502 ``frp_vendor_unreachable
            {title, detail}``.
    """
    return await tunnel_list(runtime, FRP_SAKURAFRP)


@router.post("/sakurafrp/tunnel/set", response_model=FrpView)
async def set_tunnel(
    request: FrpTunnelSetRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> FrpView:
    """Pick a tunnel: fetch its config, write frpc's file, store it, converge.

    Args:
        request: The tunnel's id.
        runtime: The shared runtime.

    Returns:
        The view afterwards.

    Raises:
        HTTPException: 400 ``frp_tunnel_unknown {title, tunnel_id}``; 409
            ``frp_not_signed_in {title}``; 502 ``frp_vendor_unreachable
            {title, detail}`` or ``frp_config_unusable {title}``.
    """
    await tunnel_set(runtime, FRP_SAKURAFRP, request.tunnel_id)
    return FrpView(**frp_view_fields(runtime, FRP_SAKURAFRP))


def frp_view_fields(runtime: PanelRuntime, vendor: str) -> dict:
    """One vendor's view, from its file and its monitor.

    Args:
        runtime: The shared runtime.
        vendor: ``sakurafrp`` or ``openfrp``.

    Returns:
        The fields of :class:`FrpView`.
    """
    config = read_frp(vendor)
    seen = runtime.frp_monitors[vendor].view()
    return {
        "is_enabled": config.is_enabled,
        "is_signed_in": config.is_signed_in,
        "tunnel_id": config.tunnel_id,
        "node_name": config.node_name,
        "local_port": config.local_port,
        "url": config.url,
        "state": seen["state"],
        "last_error": seen["last_error"],
        "checked_at": seen["checked_at"],
        "console_url": FRP_CONSOLE_URLS[vendor],
    }


async def tunnel_list(runtime: PanelRuntime, vendor: str) -> FrpTunnelListView:
    """One vendor's tunnel list, read from the vendor now.

    Args:
        runtime: The shared runtime.
        vendor: ``sakurafrp`` or ``openfrp``.

    Returns:
        The listed tunnels, the picked one marked.

    Raises:
        HTTPException: As :func:`list_tunnels`.
    """
    config = read_frp(vendor)
    api = _signed_in_api(runtime, vendor)
    try:
        rows = await asyncio.to_thread(
            listed_tunnels, api, vendor, agent_port=_agent_port(runtime)
        )
    except FrpVendorError as error:
        raise _vendor_refusal(runtime, error) from error
    return FrpTunnelListView(
        tunnels=[
            FrpTunnelView(
                tunnel_id=row.tunnel_id,
                name=row.name,
                node_name=row.node_name,
                region=row.region,
                latency_ms=latency,
                is_picked=row.tunnel_id == config.tunnel_id,
            )
            for row, latency in rows
        ]
    )


async def tunnel_set(runtime: PanelRuntime, vendor: str, tunnel_id: str) -> None:
    """Pick one of a vendor's listed tunnels and run frpc for it.

    frpc's file is written from the tunnel's config, the tunnel is stored,
    frpc starts again on the file, and the converge step hands every peer
    the new ``urls``.

    Args:
        runtime: The shared runtime.
        vendor: ``sakurafrp`` or ``openfrp``.
        tunnel_id: The tunnel.

    Raises:
        HTTPException: As :func:`set_tunnel`.
    """
    api = _signed_in_api(runtime, vendor)

    def fetch() -> tuple:
        rows = account_tunnels(api, vendor, agent_port=_agent_port(runtime))
        tunnel = find_tunnel(rows, vendor, tunnel_id)
        return tunnel, tunnel_file_text(api, vendor, tunnel)

    try:
        tunnel, text = await asyncio.to_thread(fetch)
    except FrpVendorError as error:
        raise _vendor_refusal(runtime, error) from error
    write_frpc_file(vendor, text)
    config = read_frp(vendor)
    store_tunnel(config, tunnel)
    try:
        await asyncio.to_thread(runtime.apply_frp, vendor, is_restarted=True)
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        raise _bad_gateway(
            "overlay_switch_failed", detail=command_failure_text(error)
        ) from error
    await converge(runtime)


async def converge(runtime: PanelRuntime) -> None:
    """Run the converge step, its failure as ``overlay_switch_failed``.

    Args:
        runtime: The shared runtime.

    Raises:
        HTTPException: 502 ``overlay_switch_failed {detail}``.
    """
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


def frp_refusal(error: FrpVendorError) -> HTTPException:
    """The HTTP refusal of a coded vendor refusal.

    Args:
        error: The refusal.

    Returns:
        400 by default, 409 for ``frp_not_signed_in``, 502 for a vendor that
        did not answer as one, carrying ``{code, params}``.
    """
    return HTTPException(
        status_code=FRP_STATUS_OF.get(error.code, status.HTTP_400_BAD_REQUEST),
        detail={"code": error.code, "params": error.params},
    )


def _signed_in_api(runtime: PanelRuntime, vendor: str):
    """The vendor's API under the stored credential.

    Raises:
        HTTPException: 409 ``frp_not_signed_in {title}`` with no credential,
            or with an OpenFrp login OpenFrp answered 401 to.
    """
    config = read_frp(vendor)
    is_expired = vendor == FRP_OPENFRP and runtime.openfrp_login.is_expired
    if not config.is_signed_in or is_expired:
        raise frp_refusal(
            FrpVendorError(FRP_CODE_NOT_SIGNED_IN, title=FRP_TITLES[vendor])
        )
    try:
        return vendor_api(config)
    except FrpVendorError as error:
        raise frp_refusal(error) from error


def _vendor_refusal(runtime: PanelRuntime, error: FrpVendorError) -> HTTPException:
    """A vendor's refusal, OpenFrp's 401 marking its login expired."""
    if error.code == FRP_CODE_NOT_SIGNED_IN:
        runtime.openfrp_login.is_expired = True
    return frp_refusal(error)


def _agent_port(runtime: PanelRuntime) -> int:
    """The connection port."""
    return int(runtime.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT))


def _bad_gateway(code: str, **params) -> HTTPException:
    """One 502 carrying the name of what went wrong below the panel."""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": code, "params": params},
    )
