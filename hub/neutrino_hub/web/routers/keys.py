"""The Credentials page's SSH keys: what the gateway uses to reach devices."""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.devices.key_registry import (
    KeyMaterialError,
    KeyRecord,
    KeyRegistry,
)
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.models import KeyCreate, KeyListView, KeyRename, KeyView

router = APIRouter(
    prefix="/api/keys", tags=["keys"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=KeyListView)
def list_keys() -> KeyListView:
    """Read every stored key with how many devices use it.

    Returns:
        The keys, newest first, each with its device count so the tab can warn
        before a key still in use is deleted.
    """
    counts = _device_counts()
    return KeyListView(
        keys=[_to_view(record, counts) for record in KeyRegistry().list_records()]
    )


@router.post("", response_model=KeyView)
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
    return _to_view(record, _device_counts())


@router.put("/{key_id}", response_model=KeyView)
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
    return _to_view(record, _device_counts())


@router.delete("/{key_id}")
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


def _to_view(record: KeyRecord, counts: dict[str, int]) -> KeyView:
    return KeyView(
        id=record.id,
        name=record.name,
        key_type=record.key_type,
        fingerprint=record.fingerprint,
        has_passphrase=record.has_passphrase,
        created_at=record.created_at,
        device_count=counts.get(record.id, 0),
    )
