"""The OpenFrp section of the Access page.

The account is signed in through OpenFrp's browser login, whose
``Authorization`` is stored sealed in ``config/overlay/openfrp.json``; the
tunnel list and the pick are SakuraFrp's, against OpenFrp.
"""

import asyncio

from fastapi import APIRouter, Depends

from neutrino_hub.exceptions import FrpVendorError
from neutrino_hub.modules.frp.config import read_frp, write_frp
from neutrino_hub.modules.frp.constants import FRP_OPENFRP
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    FrpTunnelListView,
    FrpTunnelSetRequest,
    OpenFrpLoginView,
    OpenFrpView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.hub.overlay_sakurafrp import (
    converge,
    frp_refusal,
    frp_view_fields,
    tunnel_list,
    tunnel_set,
)

router = APIRouter(
    prefix="/api/hub/overlay", tags=["overlay"], dependencies=[Depends(require_session)]
)


@router.get("/openfrp", response_model=OpenFrpView)
def read_state(runtime: PanelRuntime = Depends(get_runtime)) -> OpenFrpView:
    """Read OpenFrp's settings, its login and where it stands, calling nobody.

    Args:
        runtime: The shared runtime.

    Returns:
        The view.
    """
    return openfrp_view(runtime)


@router.post("/openfrp/login/start", response_model=OpenFrpView)
async def start_login(runtime: PanelRuntime = Depends(get_runtime)) -> OpenFrpView:
    """Ask OpenFrp for an authorization URL and wait for the person in the
    background, replacing any login in progress.

    Args:
        runtime: The shared runtime.

    Returns:
        The view, its login ``waiting`` with the URL to open.

    Raises:
        HTTPException: 502 ``frp_vendor_unreachable {title, detail}``.
    """
    try:
        await asyncio.to_thread(runtime.openfrp_login.start)
    except FrpVendorError as error:
        raise frp_refusal(error) from error
    return openfrp_view(runtime)


@router.post("/openfrp/logout", response_model=OpenFrpView)
async def log_out(runtime: PanelRuntime = Depends(get_runtime)) -> OpenFrpView:
    """Forget the ``Authorization`` and the picked tunnel, without calling OpenFrp.

    Args:
        runtime: The shared runtime.

    Returns:
        The view afterwards.

    Raises:
        HTTPException: 502 ``overlay_switch_failed {detail}`` when the
            converge step fails.
    """
    runtime.openfrp_login.end()
    runtime.openfrp_login.is_expired = False
    config = read_frp(FRP_OPENFRP)
    config.forget()
    write_frp(config)
    await converge(runtime)
    return openfrp_view(runtime)


@router.get("/openfrp/tunnel", response_model=FrpTunnelListView)
async def list_tunnels(
    runtime: PanelRuntime = Depends(get_runtime),
) -> FrpTunnelListView:
    """List the account's tunnels the hub can run, with each node's latency.

    Args:
        runtime: The shared runtime.

    Returns:
        The list.

    Raises:
        HTTPException: 409 ``frp_not_signed_in {title}``, also once OpenFrp
            answered 401; 502 ``frp_vendor_unreachable {title, detail}``.
    """
    return await tunnel_list(runtime, FRP_OPENFRP)


@router.post("/openfrp/tunnel/set", response_model=OpenFrpView)
async def set_tunnel(
    request: FrpTunnelSetRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> OpenFrpView:
    """Pick a tunnel: fetch its node's config, write frpc's file, store it,
    converge.

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
    await tunnel_set(runtime, FRP_OPENFRP, request.tunnel_id)
    return openfrp_view(runtime)


def openfrp_view(runtime: PanelRuntime) -> OpenFrpView:
    """OpenFrp's view: the frp fields, whether its login expired, and the login.

    Args:
        runtime: The shared runtime.

    Returns:
        The view.
    """
    return OpenFrpView(
        **frp_view_fields(runtime, FRP_OPENFRP),
        is_login_expired=runtime.openfrp_login.is_expired,
        login=OpenFrpLoginView(**runtime.openfrp_login.view()),
    )
