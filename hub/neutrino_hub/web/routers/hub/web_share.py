"""The Clients page's Web shares: make one, and destroy one.

A share offers one app's ``web`` entry to anyone who holds its link. Its
link is returned once, by the make; the hub keeps a hash of the ticket alone
and cannot show the link again. The list of shares is part of
``GET /api/hub/client`` (protocol.md, ``/api/hub/client``).
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.clients.constants import (
    WEB_SHARE_CODE_ENTRY_INVALID,
    WEB_SHARE_CODE_SITE_INVALID,
    WEB_SHARE_CODE_UNKNOWN,
    WEB_SHARE_DAYS,
)
from neutrino_hub.modules.clients.web_shares import (
    WebShareRegistry,
    make_share,
    share_link,
    taken_guest_accounts,
)
from neutrino_hub.modules.devices.constants import DEVICE_GUEST_LOGIN_GUEST_ACCOUNT
from neutrino_hub.modules.transport.ops import read_dtls_fingerprint
from neutrino_hub.web.constants import WEB_CODE_BODY_INVALID, WEB_EVENT_CLIENTS
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ClientListView,
    WebShareCreatedView,
    WebShareCreateRequest,
    WebShareDestroyRequest,
    WebShareView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.hub.client import list_clients
from neutrino_hub.web.web_share_access import (
    end_shares_where,
    entry_path,
    offerable_entries,
    push_guest_devices,
    push_shares_from_thread,
    share_address,
    share_site,
    share_views,
)

router = APIRouter(
    prefix="/api/hub/client/web_share",
    tags=["client"],
    dependencies=[Depends(require_session)],
)


@router.post("/create", response_model=WebShareCreatedView)
def create_share(
    request: WebShareCreateRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> WebShareCreatedView:
    """Make a share of one ``web`` entry and its link.

    Args:
        request: The name, the entry, the days and the site.
        runtime: The shared runtime.

    Returns:
        The link, given this once, and the share as the list draws it.

    Raises:
        HTTPException: 400 ``body_invalid`` for an empty name or a ``days``
            outside 1, 7, 30 and null; 400 ``web_share_site_invalid {site}``;
            400 ``web_share_entry_invalid {entry_id}`` for an entry no share
            can offer now; 400 ``no_reachable_address`` while the hub has no
            address a link can name; 409 ``transport_key_missing`` while the
            transport has made no DTLS certificate; 409 ``vault_locked``.
        OSError: When the shares file cannot be written.
    """
    name = request.name.strip()
    if not name:
        raise _refused(
            status.HTTP_400_BAD_REQUEST, WEB_CODE_BODY_INVALID, fields="name"
        )
    if request.days is not None and request.days not in WEB_SHARE_DAYS:
        raise _refused(
            status.HTTP_400_BAD_REQUEST, WEB_CODE_BODY_INVALID, fields="days"
        )
    site = share_site(request.site)
    if not site:
        raise _refused(
            status.HTTP_400_BAD_REQUEST, WEB_SHARE_CODE_SITE_INVALID, site=request.site
        )
    offered = next(
        (
            item
            for item in offerable_entries(runtime)
            if item["entry"]["id"] == request.entry_id
        ),
        None,
    )
    if offered is None:
        raise _refused(
            status.HTTP_400_BAD_REQUEST,
            WEB_SHARE_CODE_ENTRY_INVALID,
            entry_id=request.entry_id,
        )
    try:
        fingerprint = read_dtls_fingerprint()
    except (OSError, ValueError) as error:
        raise _refused(status.HTTP_409_CONFLICT, "transport_key_missing") from error
    ip, port = share_address(runtime)
    if not ip:
        raise _refused(status.HTTP_400_BAD_REQUEST, "no_reachable_address")
    entry = offered["entry"]
    device_id = str(entry.get("device_id", "") or "")
    try:
        share, share_secrets = make_share(
            name=name,
            app_id=offered["app"]["id"],
            app_title=str(offered["app"]["title"]),
            entry_id=entry["id"],
            device_id=device_id,
            module=offered["module"],
            days=request.days,
            taken_accounts=taken_guest_accounts(device_id),
            is_guest=offered["guest_login"] == DEVICE_GUEST_LOGIN_GUEST_ACCOUNT,
        )
    except VaultLockedError as error:
        raise _refused(status.HTTP_409_CONFLICT, VaultLockedError.code) from error
    WebShareRegistry().add(share)
    push_shares_from_thread(runtime)
    push_guest_devices(runtime, [share])
    runtime.events.publish(WEB_EVENT_CLIENTS)
    link = share_link(
        site,
        ip=ip,
        port=port,
        fingerprint=fingerprint,
        share=share,
        share_secrets=share_secrets,
        title=str(offered["app"]["title"]),
        path=entry_path(entry),
    )
    view = next(view for view in share_views(runtime) if view["id"] == share.id)
    return WebShareCreatedView(link=link, share=WebShareView(**view))


@router.post("/destroy", response_model=ClientListView)
def destroy_share(
    request: WebShareDestroyRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientListView:
    """End a share at once: its link stops working and its pages close.

    Args:
        request: The share.
        runtime: The shared runtime.

    Returns:
        The list, as a read answers.

    Raises:
        HTTPException: 404 ``web_share_unknown`` for no such share.
    """
    ended = end_shares_where(runtime, lambda share: share.id == request.share_id)
    if not ended:
        raise _refused(status.HTTP_404_NOT_FOUND, WEB_SHARE_CODE_UNKNOWN)
    return list_clients(runtime=runtime)


def _refused(status_code: int, code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "params": params}
    )
