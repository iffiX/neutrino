"""The Credentials page's AI provider store.

SSH keys have their own router (``keys.py``) for historical reasons; both are
shown on the same page. Keys stored here never come back out through the API —
only whether one is stored does.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.credentials.registry import (
    AiProviderRecord,
    AiProviderRegistry,
)
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.models import (
    AiProviderCreate,
    AiProviderListView,
    AiProviderModelView,
    AiProviderUpdate,
    AiProviderView,
)

router = APIRouter(
    prefix="/api/credentials",
    tags=["credentials"],
    dependencies=[Depends(require_session)],
)


@router.get("/ai_providers", response_model=AiProviderListView)
def list_providers() -> AiProviderListView:
    """Read every stored AI provider.

    Returns:
        The providers, newest first, keys withheld.
    """
    return AiProviderListView(
        providers=[_to_view(r) for r in AiProviderRegistry().list_records()]
    )


@router.post("/ai_providers", response_model=AiProviderView)
def create_provider(request: AiProviderCreate) -> AiProviderView:
    """Store a new AI provider.

    Args:
        request: The provider's fields.

    Returns:
        The stored provider, key withheld.

    Raises:
        HTTPException: 400 when the kind is unknown or the name is empty.
    """
    try:
        record = AiProviderRegistry().add(
            name=request.name,
            kind=request.kind,
            base_url=request.base_url,
            api_key=request.api_key,
            models=[model.model_dump() for model in request.models],
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _to_view(record)


@router.put("/ai_providers/{provider_id}", response_model=AiProviderView)
def update_provider(provider_id: str, request: AiProviderUpdate) -> AiProviderView:
    """Change parts of a provider; a blank key keeps the stored one.

    Args:
        provider_id: The provider's id.
        request: The fields to change.

    Returns:
        The provider after the change.

    Raises:
        HTTPException: 404 for an unknown id, 400 for an unknown kind.
    """
    try:
        record = AiProviderRegistry().update(
            provider_id,
            name=request.name,
            kind=request.kind,
            base_url=request.base_url,
            api_key=request.api_key,
            is_enabled=request.is_enabled,
            models=(
                [model.model_dump() for model in request.models]
                if request.models is not None
                else None
            ),
        )
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown provider"
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _to_view(record)


@router.delete("/ai_providers/{provider_id}")
def delete_provider(provider_id: str) -> dict:
    """Remove a provider.

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


def _to_view(record: AiProviderRecord) -> AiProviderView:
    return AiProviderView(
        id=record.id,
        name=record.name,
        kind=record.kind,
        base_url=record.base_url,
        has_api_key=bool(record.api_key),
        is_enabled=record.is_enabled,
        models=[AiProviderModelView(**model) for model in record.models],
        created_at=record.created_at,
    )
