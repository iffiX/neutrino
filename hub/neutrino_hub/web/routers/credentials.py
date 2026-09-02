"""The Credentials page: the SSH keys and the AI providers the box holds.

Both are secrets the gateway uses on somebody's behalf, and neither comes back
out through the API — a listing says a key is stored, never what it is. The
keys reach devices through an id, so the material never sits in a device's
own configuration.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.credentials.registry import (
    AiProviderRecord,
    AiProviderRegistry,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.devices.key_registry import (
    KeyMaterialError,
    KeyRecord,
    KeyRegistry,
)
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.models import (
    AiProviderCreate,
    AiProviderListView,
    AiProviderModelView,
    AiProviderUpdate,
    AiProviderView,
    KeyCreate,
    KeyListView,
    KeyRename,
    KeyView,
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
        providers=[_provider_view(r) for r in AiProviderRegistry().list_records()]
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
    return _provider_view(record)


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
    return _provider_view(record)


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


def _provider_view(record: AiProviderRecord) -> AiProviderView:
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


# --- SSH keys ---


@router.get("/ssh_keys", response_model=KeyListView)
def list_keys() -> KeyListView:
    """Read every stored key with how many devices use it.

    Returns:
        The keys, newest first, each with its device count so the tab can warn
        before a key still in use is deleted.
    """
    counts = _device_counts()
    return KeyListView(
        keys=[_key_view(record, counts) for record in KeyRegistry().list_records()]
    )


@router.post("/ssh_keys", response_model=KeyView)
def create_key(request: KeyCreate) -> KeyView:
    """Store a pasted key under a name.

    Args:
        request: The name, key text, and optional passphrase.

    Returns:
        The stored key, without its material.

    Raises:
        HTTPException: 400 when the key cannot be used. The message names the
            specific problem, since pasting a public key by mistake is easy and
            its fix differs from a bad passphrase.
    """
    try:
        record = KeyRegistry().add(
            name=request.name,
            private_key=request.private_key,
            passphrase=request.passphrase,
        )
    except KeyMaterialError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _key_view(record, _device_counts())


@router.put("/ssh_keys/{key_id}", response_model=KeyView)
def rename_key(key_id: str, request: KeyRename) -> KeyView:
    """Change a key's label.

    Args:
        key_id: The key's identifier.
        request: The new label.

    Returns:
        The updated key.

    Raises:
        HTTPException: 404 when the key is unknown, 400 when the name is blank.
    """
    try:
        record = KeyRegistry().rename(key_id, request.name)
    except KeyMaterialError as error:
        code = (
            status.HTTP_404_NOT_FOUND
            if "no key" in str(error)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(error)) from error
    return _key_view(record, _device_counts())


@router.delete("/ssh_keys/{key_id}")
def delete_key(key_id: str, force: bool = False) -> dict:
    """Remove a key and its material.

    Args:
        key_id: The key's identifier.
        force: Delete even when devices still reference it.

    Returns:
        An empty object.

    Raises:
        HTTPException: 409 when devices still use the key and ``force`` is not
            set, so a key is not pulled out from under a device by accident.
    """
    count = _device_counts().get(key_id, 0)
    if count > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{count} device(s) still use this key; use force to delete",
        )
    KeyRegistry().delete(key_id)
    return {}


def _device_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for device in DeviceRegistry().all_stored():
        key_id = (device.ssh or {}).get("key_id")
        if key_id:
            counts[key_id] = counts.get(key_id, 0) + 1
    return counts


def _key_view(record: KeyRecord, counts: dict[str, int]) -> KeyView:
    return KeyView(
        id=record.id,
        name=record.name,
        key_type=record.key_type,
        fingerprint=record.fingerprint,
        has_passphrase=record.has_passphrase,
        created_at=record.created_at,
        device_count=counts.get(record.id, 0),
    )
