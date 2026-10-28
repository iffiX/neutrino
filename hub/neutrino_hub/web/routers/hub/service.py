"""The Services page: the apps the hub publishes, and the entries of no app.

Module apps are read-only rows; declared apps are created and deleted here,
and every write answers with the whole refreshed list. The page holds no
``ssh`` entry and no row for a machine's SSH server, which is no app
(protocol.md, "Apps"). Every payload host is
resolved for the scope the asking browser's address falls in, the same
resolution a client gets; a browser on no served network, or one the
transport names no address for, is in the ``link`` scope with the panel
host it reached.

Errors carry ``{code, params}`` and never a sentence; the pages do the
wording.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from neutrino_hub.exceptions import ServiceFieldInvalidError
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.services.collector import catalog_entries
from neutrino_hub.modules.services.config import DeclaredAppRegistry
from neutrino_hub.modules.services.constants import (
    SERVICES_APP_SOURCE_ORDER,
    SERVICES_ERROR_INVALID,
    SERVICES_ERROR_SHARE_SCAN,
    SERVICES_ERROR_UNKNOWN,
    SERVICES_TYPE_SSH,
)
from neutrino_hub.modules.services.host_scope import scope_of
from neutrino_hub.modules.services.ops import list_shares
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    AppEntryView,
    AppView,
    DeclaredAppCreate,
    DeclaredAppRequest,
    PublishedServiceView,
    ServiceListView,
    ServiceShareListView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.web_share_access import end_app_shares, entry_guest_login

router = APIRouter(
    prefix="/api/hub/service", tags=["service"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=ServiceListView)
def list_services(
    request: Request, runtime: PanelRuntime = Depends(get_runtime)
) -> ServiceListView:
    """Read every app and every entry of no app.

    Args:
        request: The incoming request, whose peer address settles the scope
            every payload host is resolved for.
        runtime: The shared runtime.

    Returns:
        The apps, a module's first, then the declared, then the manual,
        each group by title; and the entries of no app. No ``ssh`` entry is
        in either.
    """
    return _list_view(request, runtime)


@router.get("/share", response_model=ServiceShareListView)
def list_host_shares(host: str) -> ServiceShareListView:
    """List what one SMB server exports, so a share is picked and not typed.

    Args:
        host: The server to ask.

    Returns:
        Its share names, administrative ones dropped.

    Raises:
        HTTPException: 400 with ``declared_service_invalid`` for a blank
            host, or ``share_scan_failed`` whose ``reason`` says whether the
            server did not answer, refused the anonymous listing, or this
            hub has no smbclient.
    """
    if not host.strip():
        raise _invalid(
            ServiceFieldInvalidError(SERVICES_ERROR_INVALID, {"field": "host"})
        )
    listing = list_shares(host.strip())
    if listing.error_code is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SERVICES_ERROR_SHARE_SCAN,
                "params": {"reason": listing.error_code},
            },
        )
    return ServiceShareListView(shares=listing.names)


@router.post("/declaration/add", response_model=ServiceListView)
def add_declared_app(
    request: Request,
    body: DeclaredAppCreate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ServiceListView:
    """Declare one app with its entries.

    Args:
        request: The incoming request.
        body: The app's name, host, description and entries.
        runtime: The shared runtime.

    Returns:
        The list with the new app, not yet probed.

    Raises:
        HTTPException: 400 with ``declared_service_invalid`` naming the field
            that was refused, ``name``, ``host``, ``entries`` or
            ``entries.<n>.<field>``.
    """
    try:
        DeclaredAppRegistry().add(
            name=body.name,
            host=body.host,
            entries=[entry.model_dump() for entry in body.entries],
            description=body.description,
        )
    except ServiceFieldInvalidError as error:
        raise _invalid(error) from error
    runtime.published_services.expire()
    return _list_view(request, runtime)


@router.post("/declaration/remove", response_model=ServiceListView)
def delete_declared_app(
    request: Request,
    body: DeclaredAppRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ServiceListView:
    """Remove a declared app, every entry it published with it, and its row
    from every client permission.

    Args:
        request: The incoming request.
        body: The app's id.
        runtime: The shared runtime.

    Returns:
        The list without it.

    Raises:
        HTTPException: 404 with ``declared_service_unknown`` for an unknown
            id.
    """
    try:
        DeclaredAppRegistry().delete(body.app_id)
    except KeyError as error:
        raise _unknown() from error
    ClientRegistry().forget_permission_rows([body.app_id])
    end_app_shares(runtime, body.app_id)
    runtime.published_services.expire()
    return _list_view(request, runtime)


@router.post("/declaration/probe", response_model=ServiceListView)
def probe_declared_app(
    request: Request,
    body: DeclaredAppRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ServiceListView:
    """Probe each entry of one declared app now, bypassing the cache.

    Args:
        request: The incoming request.
        body: The app's id.
        runtime: The shared runtime.

    Returns:
        The list with the fresh measurements folded in.

    Raises:
        HTTPException: 404 with ``declared_service_unknown`` for an unknown
            id.
    """
    app = DeclaredAppRegistry().get(body.app_id)
    if app is None:
        raise _unknown()
    runtime.declared_probe.probe(app)
    runtime.published_services.expire()
    return _list_view(request, runtime)


def _list_view(request: Request, runtime: PanelRuntime) -> ServiceListView:
    peer_host = request.client.host if request.client is not None else ""
    scope = scope_of(
        peer_host, request.url.hostname or "127.0.0.1", runtime.host_scopes()
    )
    entries = runtime.published_services.entries_for(scope)
    names = runtime.device_names()
    manifests = load_module_manifests()
    by_app: dict = {}
    loose = []
    for entry in entries:
        if entry.get("type") == SERVICES_TYPE_SSH:
            continue
        if entry.get("app_id"):
            by_app.setdefault(entry["app_id"], []).append(entry)
        else:
            loose.append(entry)
    apps = []
    for app in runtime.published_services.apps():
        held = by_app.get(app["id"])
        if not held:
            continue
        apps.append(
            AppView(
                id=app["id"],
                title=app["title"],
                source=app["source"],
                device_id=app["device_id"],
                device_name=app["device_name"] or names.get(app["device_id"], ""),
                local_name=app["local_name"],
                description=app["description"],
                entries=[
                    AppEntryView(
                        id=entry["id"],
                        name=entry["name"],
                        type=entry["type"],
                        payload=entry["payload"],
                        is_healthy=entry["is_healthy"],
                        local_port=int(entry.get("local_port") or 0),
                        detail_code=entry.get("detail_code"),
                        guest_login=entry_guest_login(entry, manifests)[0],
                    )
                    for entry in held
                ],
            )
        )
    apps.sort(key=lambda app: (_source_rank(app.source), app.title.lower()))
    return ServiceListView(
        apps=apps,
        services=[
            PublishedServiceView(
                **catalog,
                detail_code=entry.get("detail_code"),
                device_id=entry.get("device_id") or "",
                device_name=names.get(entry.get("device_id") or "", ""),
            )
            for entry, catalog in zip(loose, catalog_entries(loose))
        ],
    )


def _source_rank(source: str) -> int:
    """A module's apps first, then the declared, then the manual."""
    try:
        return SERVICES_APP_SOURCE_ORDER.index(source)
    except ValueError:
        return len(SERVICES_APP_SOURCE_ORDER)


def _invalid(error: ServiceFieldInvalidError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": error.code, "params": error.params},
    )


def _unknown() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": SERVICES_ERROR_UNKNOWN, "params": {}},
    )
