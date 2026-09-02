"""The declared services: outside machines' Samba, HTTP and Docker endpoints.

A file of its own beside ``service_control.py`` because the declared entries
are a collection with a life of their own — added, edited, probed, deleted —
where that file drives systemd units. Both answer under ``/api/services``.

Errors carry ``{code, params}`` and never a sentence; the pages do the
wording.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.services.config import (
    DeclaredService,
    DeclaredServiceError,
    DeclaredServiceRegistry,
    DeclaredShare,
)
from neutrino_hub.modules.services.constants import (
    SERVICES_ERROR_INVALID,
    SERVICES_ERROR_UNKNOWN,
)
from neutrino_hub.modules.services.probe import DeclaredServiceHealth
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    DeclaredServiceCreate,
    DeclaredServiceProbeView,
    DeclaredServiceView,
    DeclaredShareView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.credentials import SERVICE_ACCOUNT_KIND

router = APIRouter(
    prefix="/api/services", tags=["services"], dependencies=[Depends(require_session)]
)


def declared_service_views(runtime: PanelRuntime) -> list[DeclaredServiceView]:
    """Read every declared service with its cached health.

    Args:
        runtime: The shared runtime holding the probe cache.

    Returns:
        One view per declared service, newest first.
    """
    records = DeclaredServiceRegistry().list_records()
    healths = {
        health.service_id: health for health in runtime.declared_probe.results(records)
    }
    return [_to_view(record, healths.get(record.id)) for record in records]


@router.post(
    "/declared", response_model=DeclaredServiceView, status_code=status.HTTP_201_CREATED
)
def add_declared_service(request: DeclaredServiceCreate) -> DeclaredServiceView:
    """Declare a new service.

    Args:
        request: The service's fields.

    Returns:
        The stored service, not yet probed.

    Raises:
        HTTPException: 400 with ``declared_service_invalid`` naming the field
            that was refused.
    """
    _require_known_accounts(request)
    try:
        record = DeclaredServiceRegistry().add(
            name=request.name,
            kind=request.kind,
            host=request.host,
            port=request.port,
            scheme=request.scheme,
            path=request.path,
            shares=_to_shares(request),
        )
    except DeclaredServiceError as error:
        raise _invalid(error) from error
    return _to_view(record, None)


@router.put("/declared/{service_id}", response_model=DeclaredServiceView)
def update_declared_service(
    service_id: str,
    request: DeclaredServiceCreate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> DeclaredServiceView:
    """Replace one declared service whole.

    Args:
        service_id: The service's id.
        request: The full record as it should be.
        runtime: The shared runtime.

    Returns:
        The service after the change, with its cached health.

    Raises:
        HTTPException: 404 with ``declared_service_unknown`` for an unknown
            id, 400 with ``declared_service_invalid`` for a refused field.
    """
    _require_known_accounts(request)
    try:
        record = DeclaredServiceRegistry().replace(
            service_id,
            name=request.name,
            kind=request.kind,
            host=request.host,
            port=request.port,
            scheme=request.scheme,
            path=request.path,
            shares=_to_shares(request),
        )
    except KeyError as error:
        raise _unknown() from error
    except DeclaredServiceError as error:
        raise _invalid(error) from error
    return _to_view(record, runtime.declared_probe.cached(service_id))


@router.delete("/declared/{service_id}")
def delete_declared_service(service_id: str) -> dict:
    """Remove a declared service.

    Args:
        service_id: The service's id.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 404 with ``declared_service_unknown`` for an unknown
            id.
    """
    try:
        DeclaredServiceRegistry().delete(service_id)
    except KeyError as error:
        raise _unknown() from error
    return {}


@router.post("/declared/{service_id}/probe", response_model=DeclaredServiceProbeView)
def probe_declared_service(
    service_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> DeclaredServiceProbeView:
    """Probe one declared service now, bypassing the cache.

    Args:
        service_id: The service's id.
        runtime: The shared runtime.

    Returns:
        The fresh measurement; it also replaces the cached one.

    Raises:
        HTTPException: 404 with ``declared_service_unknown`` for an unknown
            id.
    """
    record = DeclaredServiceRegistry().get(service_id)
    if record is None:
        raise _unknown()
    health = runtime.declared_probe.probe(record)
    return DeclaredServiceProbeView(
        is_healthy=health.is_healthy,
        checked_at=health.checked_at,
        detail_code=health.detail_code,
    )


def _require_known_accounts(request: DeclaredServiceCreate) -> None:
    """Refuse a share naming a service account the vault does not hold.

    Args:
        request: The submitted record.

    Raises:
        HTTPException: 400 with ``declared_service_invalid`` naming
            ``service_account_id``.
    """
    referenced = {
        share.service_account_id for share in request.shares if share.service_account_id
    }
    if not referenced:
        return
    stored = {
        record.id for record in SecretVault().list_records(kind=SERVICE_ACCOUNT_KIND)
    }
    if referenced - stored:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SERVICES_ERROR_INVALID,
                "params": {"field": "service_account_id"},
            },
        )


def _to_shares(request: DeclaredServiceCreate) -> list[DeclaredShare]:
    return [
        DeclaredShare(name=share.name, service_account_id=share.service_account_id)
        for share in request.shares
    ]


def _to_view(
    record: DeclaredService, health: DeclaredServiceHealth | None
) -> DeclaredServiceView:
    return DeclaredServiceView(
        id=record.id,
        name=record.name,
        kind=record.kind,
        host=record.host,
        port=record.port,
        scheme=record.scheme,
        path=record.path,
        shares=[
            DeclaredShareView(
                name=share.name, service_account_id=share.service_account_id
            )
            for share in record.shares
        ],
        created_at=record.created_at,
        probe=DeclaredServiceProbeView(
            is_healthy=health.is_healthy if health else None,
            checked_at=health.checked_at if health else None,
            detail_code=health.detail_code if health else None,
        ),
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
