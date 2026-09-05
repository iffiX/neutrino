"""The Services tab: the typed list of what the hub publishes.

Module-declared entries are read-only rows; manual declarations are created
and deleted here, and every write answers with the whole refreshed list. A
payload host that is the hub's own is shown as the address the asking
browser reaches the panel on, the same substitution each device gets at
heartbeat time.

Errors carry ``{code, params}`` and never a sentence; the pages do the
wording.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from neutrino_hub.modules.services.config import (
    DeclaredServiceError,
    DeclaredServiceRegistry,
    DeclaredShare,
)
from neutrino_hub.modules.services.constants import (
    SERVICES_ERROR_INVALID,
    SERVICES_ERROR_SHARE_SCAN,
    SERVICES_ERROR_UNKNOWN,
    SERVICES_KIND_SAMBA,
    SERVICES_TYPE_TO_KIND,
)
from neutrino_hub.modules.services.ops import list_shares
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    DeclaredServiceCreate,
    PublishedServiceView,
    ServiceListView,
    ServiceShareListView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/services", tags=["services"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=ServiceListView)
def list_services(
    request: Request, runtime: PanelRuntime = Depends(get_runtime)
) -> ServiceListView:
    """Read every published entry.

    Args:
        request: The incoming request, whose host is what hub-self payload
            hosts resolve to for display.
        runtime: The shared runtime.

    Returns:
        The typed list, module entries first.
    """
    return _list_view(request, runtime)


@router.get("/shares", response_model=ServiceShareListView)
def list_host_shares(host: str) -> ServiceShareListView:
    """List what one SMB server exports, so a share is picked and not typed.

    Args:
        host: The server to ask.

    Returns:
        Its share names, administrative ones dropped.

    Raises:
        HTTPException: 400 with ``declared_service_invalid`` for a blank
            host, or ``share_scan_failed`` whose ``reason`` says whether the
            server did not answer or this hub has no smbclient.
    """
    if not host.strip():
        raise _invalid(DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "host"}))
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


@router.post(
    "/declared", response_model=ServiceListView, status_code=status.HTTP_201_CREATED
)
def add_declared_service(
    request: Request,
    body: DeclaredServiceCreate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ServiceListView:
    """Declare a new service.

    Args:
        request: The incoming request.
        body: The declaration's fields; its ``kind`` is a service type.
        runtime: The shared runtime.

    Returns:
        The list with the new entry, not yet probed.

    Raises:
        HTTPException: 400 with ``declared_service_invalid`` naming the field
            that was refused.
    """
    kind = SERVICES_TYPE_TO_KIND.get(body.kind)
    if kind is None:
        raise _invalid(DeclaredServiceError(SERVICES_ERROR_INVALID, {"field": "kind"}))
    shares = []
    if kind == SERVICES_KIND_SAMBA:
        shares = [DeclaredShare(name=name) for name in (body.shares or [])]
    try:
        DeclaredServiceRegistry().add(
            name=body.name,
            kind=kind,
            host=body.host,
            port=body.port,
            scheme=body.scheme,
            path=body.path,
            shares=shares,
            description=body.description,
        )
    except DeclaredServiceError as error:
        raise _invalid(error) from error
    runtime.published_services.expire()
    return _list_view(request, runtime)


@router.delete("/declared/{service_id}", response_model=ServiceListView)
def delete_declared_service(
    request: Request, service_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ServiceListView:
    """Remove a declared service, every entry it published with it.

    Args:
        request: The incoming request.
        service_id: The declared record's id.
        runtime: The shared runtime.

    Returns:
        The list without it.

    Raises:
        HTTPException: 404 with ``declared_service_unknown`` for an unknown
            id.
    """
    try:
        DeclaredServiceRegistry().delete(service_id)
    except KeyError as error:
        raise _unknown() from error
    runtime.published_services.expire()
    return _list_view(request, runtime)


@router.post("/declared/{service_id}/probe", response_model=ServiceListView)
def probe_declared_service(
    request: Request, service_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ServiceListView:
    """Probe one declared service now, bypassing the cache.

    Args:
        request: The incoming request.
        service_id: The declared record's id.
        runtime: The shared runtime.

    Returns:
        The list with the fresh measurement folded in.

    Raises:
        HTTPException: 404 with ``declared_service_unknown`` for an unknown
            id.
    """
    record = DeclaredServiceRegistry().get(service_id)
    if record is None:
        raise _unknown()
    runtime.declared_probe.probe(record)
    runtime.published_services.expire()
    return _list_view(request, runtime)


def _list_view(request: Request, runtime: PanelRuntime) -> ServiceListView:
    panel_host = request.url.hostname or "127.0.0.1"
    entries = runtime.published_services.entries_for(panel_host)
    return ServiceListView(
        services=[PublishedServiceView(**entry) for entry in entries]
    )


def _invalid(error: DeclaredServiceError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": error.code, "params": error.params},
    )


def _unknown() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": SERVICES_ERROR_UNKNOWN},
    )
