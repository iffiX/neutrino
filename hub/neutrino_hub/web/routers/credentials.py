"""The Credentials page: the SSH keys, passwords, service accounts and AI
providers the box holds.

All of them are secrets the gateway uses on somebody's behalf, and none comes
back out through the API — a listing says a secret is stored, never what it
is. Each reaches a device or a service through an id, so the material never
sits in a device's own configuration.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.credentials.registry import (
    AiProviderRecord,
    AiProviderRegistry,
)
from neutrino_hub.modules.credentials.vault import (
    SecretRecord,
    SecretVault,
    VaultError,
    VaultLockedError,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.devices.key_registry import (
    KeyMaterialError,
    KeyRecord,
    KeyRegistry,
)
from neutrino_hub.modules.services.config import DeclaredServiceRegistry
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
    PasswordCreate,
    PasswordListView,
    PasswordUpdate,
    PasswordView,
    ServiceAccountCreate,
    ServiceAccountListView,
    ServiceAccountUpdate,
    ServiceAccountView,
)

PASSWORD_KIND = "password"
SERVICE_ACCOUNT_KIND = "service_account"

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
        has_api_key=bool(record.secret_id),
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


# --- Passwords ---


@router.get("/passwords", response_model=PasswordListView)
def list_passwords() -> PasswordListView:
    """Read every stored password with how many devices use it.

    Returns:
        The passwords, newest first, material withheld.
    """
    counts = _password_device_counts()
    return PasswordListView(
        passwords=[
            _password_view(record, counts)
            for record in SecretVault().list_records(kind=PASSWORD_KIND)
        ]
    )


@router.post("/passwords", response_model=PasswordView)
def create_password(request: PasswordCreate) -> PasswordView:
    """Seal a password under a name.

    Args:
        request: The name and the password.

    Returns:
        The stored password, without its material.

    Raises:
        HTTPException: 400 when the name or the password is blank.
    """
    if not request.password.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="a password needs a value"
        )
    try:
        record = SecretVault().add(
            kind=PASSWORD_KIND,
            name=request.name,
            secret={"password": request.password},
        )
    except VaultLockedError:
        raise
    except VaultError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _password_view(record, _password_device_counts())


@router.put("/passwords/{password_id}", response_model=PasswordView)
def update_password(password_id: str, request: PasswordUpdate) -> PasswordView:
    """Change a password's label, its material, or both.

    Args:
        password_id: The password's identifier.
        request: The fields to change; a blank one is left alone.

    Returns:
        The password after the change.

    Raises:
        HTTPException: 404 when the id is unknown, 400 when the vault refuses
            the change.
    """
    vault = SecretVault()
    record = vault.get(password_id)
    if record is None or record.kind != PASSWORD_KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown password"
        )
    try:
        if request.name is not None and request.name.strip():
            record = vault.rename(password_id, request.name)
        if request.password is not None and request.password.strip():
            record = vault.replace(password_id, secret={"password": request.password})
    except VaultLockedError:
        raise
    except VaultError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _password_view(record, _password_device_counts())


@router.delete("/passwords/{password_id}")
def delete_password(password_id: str, force: bool = False) -> dict:
    """Remove a password and its material.

    Args:
        password_id: The password's identifier.
        force: Delete even when devices still reference it.

    Returns:
        An empty object.

    Raises:
        HTTPException: 409 when devices still use the password and ``force`` is
            not set, 404 when the id is unknown.
    """
    vault = SecretVault()
    record = vault.get(password_id)
    if record is None or record.kind != PASSWORD_KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown password"
        )
    count = _password_device_counts().get(password_id, 0)
    if count > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{count} device(s) still use this password; use force to delete",
        )
    vault.delete(password_id)
    return {}


def _password_device_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for device in DeviceRegistry().all_stored():
        ssh = device.ssh or {}
        # A device naming one password for both its login and its sudo counts
        # once.
        referenced = {ssh.get("password_id"), ssh.get("sudo_password_id")}
        for password_id in referenced:
            if password_id:
                counts[password_id] = counts.get(password_id, 0) + 1
    return counts


def _password_view(record: SecretRecord, counts: dict[str, int]) -> PasswordView:
    return PasswordView(
        id=record.id,
        name=record.name,
        created_at=record.created_at,
        device_count=counts.get(record.id, 0),
    )


# --- Service accounts ---


@router.get("/service_accounts", response_model=ServiceAccountListView)
def list_service_accounts() -> ServiceAccountListView:
    """Read every stored service account with how many services use it.

    Returns:
        The accounts, newest first, passwords withheld.
    """
    counts = _service_counts()
    return ServiceAccountListView(
        service_accounts=[
            _service_account_view(record, counts)
            for record in SecretVault().list_records(kind=SERVICE_ACCOUNT_KIND)
        ]
    )


@router.post("/service_accounts", response_model=ServiceAccountView)
def create_service_account(request: ServiceAccountCreate) -> ServiceAccountView:
    """Seal a service account's password under a name and a username.

    Args:
        request: The name, the username, and the password.

    Returns:
        The stored account, without its password.

    Raises:
        HTTPException: 400 when the name, the username or the password is
            blank.
    """
    if not request.username.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a service account needs a username",
        )
    if not request.password.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a service account needs a password",
        )
    try:
        record = SecretVault().add(
            kind=SERVICE_ACCOUNT_KIND,
            name=request.name,
            secret={"password": request.password},
            meta={"username": request.username.strip()},
        )
    except VaultLockedError:
        raise
    except VaultError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _service_account_view(record, _service_counts())


@router.put("/service_accounts/{account_id}", response_model=ServiceAccountView)
def update_service_account(
    account_id: str, request: ServiceAccountUpdate
) -> ServiceAccountView:
    """Change an account's label, username, password, or any of them.

    Args:
        account_id: The account's identifier.
        request: The fields to change; a blank one is left alone.

    Returns:
        The account after the change.

    Raises:
        HTTPException: 404 when the id is unknown, 400 when the vault refuses
            the change.
    """
    vault = SecretVault()
    record = vault.get(account_id)
    if record is None or record.kind != SERVICE_ACCOUNT_KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown service account"
        )
    try:
        if request.name is not None and request.name.strip():
            record = vault.rename(account_id, request.name)
        if request.username is not None and request.username.strip():
            record = vault.update_meta(
                account_id, {**record.meta, "username": request.username.strip()}
            )
        if request.password is not None and request.password.strip():
            record = vault.replace(account_id, secret={"password": request.password})
    except VaultLockedError:
        raise
    except VaultError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _service_account_view(record, _service_counts())


@router.delete("/service_accounts/{account_id}")
def delete_service_account(account_id: str, force: bool = False) -> dict:
    """Remove a service account and its password.

    Args:
        account_id: The account's identifier.
        force: Delete even when services still reference it.

    Returns:
        An empty object.

    Raises:
        HTTPException: 409 when services still use the account and ``force`` is
            not set, 404 when the id is unknown.
    """
    vault = SecretVault()
    record = vault.get(account_id)
    if record is None or record.kind != SERVICE_ACCOUNT_KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown service account"
        )
    count = _service_counts().get(account_id, 0)
    if count > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{count} service(s) still use this account; use force to delete",
        )
    vault.delete(account_id)
    return {}


def _service_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for service in DeclaredServiceRegistry().list_records():
        # A service naming one account on several shares counts once.
        referenced = {share.service_account_id for share in service.shares}
        for account_id in referenced:
            if account_id:
                counts[account_id] = counts.get(account_id, 0) + 1
    return counts


def _service_account_view(
    record: SecretRecord, counts: dict[str, int]
) -> ServiceAccountView:
    return ServiceAccountView(
        id=record.id,
        name=record.name,
        username=record.meta.get("username", ""),
        created_at=record.created_at,
        service_count=counts.get(record.id, 0),
    )
