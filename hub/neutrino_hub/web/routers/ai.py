"""The AI providers the gateway forwards to.

One provider is one endpoint and one credential reference: ``secret_id``
names a ``token`` the Credentials page holds, the gateway's own renderer
resolves it, and a device's Dev Setup is pointed at what the providers
serve. No key material passes through these routes in either direction.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.ai.registry import (
    AiProviderRecord,
    AiProviderRegistry,
)
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.models import (
    AiProviderCreate,
    AiProviderListView,
    AiProviderModelView,
    AiProviderUpdate,
    AiProviderView,
)

TOKEN_KIND = "token"

router = APIRouter(
    prefix="/api/ai",
    tags=["ai"],
    dependencies=[Depends(require_session)],
)


@router.get("/providers", response_model=AiProviderListView)
def list_providers() -> AiProviderListView:
    """Read every stored AI provider.

    Returns:
        The providers, newest first.
    """
    return AiProviderListView(
        providers=[_provider_view(r) for r in AiProviderRegistry().list_records()]
    )


@router.post("/providers", response_model=AiProviderView)
def create_provider(request: AiProviderCreate) -> AiProviderView:
    """Store a new AI provider.

    Args:
        request: The provider's fields; ``secret_id`` names a stored token,
            or nothing.

    Returns:
        The stored provider.

    Raises:
        HTTPException: 400 when the kind is unknown, the name is empty, or
            ``secret_id`` names no stored token.
    """
    if request.secret_id is not None:
        _require_stored_token(request.secret_id)
    try:
        record = AiProviderRegistry().add(
            name=request.name,
            kind=request.kind,
            base_url=request.base_url,
            secret_id=request.secret_id,
            models=[model.model_dump() for model in request.models],
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _provider_view(record)


@router.put("/providers/{provider_id}", response_model=AiProviderView)
def update_provider(provider_id: str, request: AiProviderUpdate) -> AiProviderView:
    """Change parts of a provider.

    ``secret_id`` sent as null clears the reference; left out of the body, it
    stays as stored.

    Args:
        provider_id: The provider's id.
        request: The fields to change.

    Returns:
        The provider after the change.

    Raises:
        HTTPException: 404 for an unknown id, 400 for an unknown kind or a
            ``secret_id`` naming no stored token.
    """
    changes = {}
    if "secret_id" in request.model_fields_set:
        if request.secret_id is not None:
            _require_stored_token(request.secret_id)
        changes["secret_id"] = request.secret_id
    try:
        record = AiProviderRegistry().update(
            provider_id,
            name=request.name,
            kind=request.kind,
            base_url=request.base_url,
            is_enabled=request.is_enabled,
            models=(
                [model.model_dump() for model in request.models]
                if request.models is not None
                else None
            ),
            **changes,
        )
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown provider"
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _provider_view(record)


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: str) -> dict:
    """Remove a provider; the token it referenced stays in the vault.

    Args:
        provider_id: The provider's id.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 404 for an unknown id.
    """
    try:
        AiProviderRegistry().delete(provider_id)
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown provider"
        ) from error
    return {}


def _require_stored_token(secret_id: str) -> None:
    """Refuse a reference the vault does not hold as a token.

    Args:
        secret_id: The submitted reference.

    Raises:
        HTTPException: 400 with ``unknown_credential`` naming ``secret_id``.
    """
    record = SecretVault().get(secret_id)
    if record is None or record.kind != TOKEN_KIND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unknown_credential", "params": {"field": "secret_id"}},
        )


def _provider_view(record: AiProviderRecord) -> AiProviderView:
    return AiProviderView(
        id=record.id,
        name=record.name,
        kind=record.kind,
        base_url=record.base_url,
        secret_id=record.secret_id,
        is_enabled=record.is_enabled,
        models=[AiProviderModelView(**model) for model in record.models],
        created_at=record.created_at,
    )
