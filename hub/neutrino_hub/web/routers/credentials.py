"""The Credentials page: the SSH keys and logins the box holds.

All of them are secrets the gateway uses on somebody's behalf, and none comes
back out through the API — a listing says a secret is stored, never what it
is. Each reaches a device or a service through an id, so the material never
sits in a device's own configuration. A login is one account — a password
with an optional username — and devices and declared services both reference
the same collection.
"""

from fastapi import APIRouter, Depends, HTTPException, status

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
    KeyCreate,
    KeyListView,
    KeyRename,
    KeyView,
    LoginCreate,
    LoginListView,
    LoginUpdate,
    LoginView,
)

LOGIN_KIND = "login"

router = APIRouter(
    prefix="/api/credentials",
    tags=["credentials"],
    dependencies=[Depends(require_session)],
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


# --- Logins ---


@router.get("/logins", response_model=LoginListView)
def list_logins() -> LoginListView:
    """Read every stored login with how many devices and services use it.

    Returns:
        The logins, newest first, passwords withheld.
    """
    vault = SecretVault()
    device_counts = _login_device_counts()
    service_counts = _service_counts()
    return LoginListView(
        logins=[
            _login_view(vault, record, device_counts, service_counts)
            for record in vault.list_records(kind=LOGIN_KIND)
        ]
    )


@router.post("/logins", response_model=LoginView)
def create_login(request: LoginCreate) -> LoginView:
    """Seal a login under a name; the username is optional.

    Args:
        request: The name, the optional username, and the password.

    Returns:
        The stored login, without its password.

    Raises:
        HTTPException: 400 when the password is blank or the vault refuses.
    """
    if not request.password.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "login_password_needed", "params": {}},
        )
    try:
        record = SecretVault().add(
            kind=LOGIN_KIND,
            name=request.name,
            secret=_login_secret(request.username, request.password),
        )
    except VaultLockedError:
        raise
    except VaultError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _login_view(SecretVault(), record, _login_device_counts(), _service_counts())


@router.put("/logins/{login_id}", response_model=LoginView)
def update_login(login_id: str, request: LoginUpdate) -> LoginView:
    """Change a login's label, username, password, or any of them.

    The username lives inside the seal, so changing either sealed field
    re-seals both; a blank or absent field keeps what is stored.

    Args:
        login_id: The login's identifier.
        request: The fields to change; a blank one is left alone.

    Returns:
        The login after the change.

    Raises:
        HTTPException: 404 when the id is unknown, 400 when the vault refuses
            the change.
    """
    vault = SecretVault()
    record = vault.get(login_id)
    if record is None or record.kind != LOGIN_KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "unknown_login", "params": {}},
        )
    try:
        if request.name is not None and request.name.strip():
            record = vault.rename(login_id, request.name)
        username = (request.username or "").strip()
        password = (request.password or "").strip()
        if username or password:
            stored = vault.open(login_id)
            record = vault.replace(
                login_id,
                secret=_login_secret(
                    username or stored.get("username", ""),
                    password or stored["password"],
                ),
            )
    except VaultLockedError:
        raise
    except VaultError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _login_view(vault, record, _login_device_counts(), _service_counts())


@router.delete("/logins/{login_id}")
def delete_login(login_id: str, force: bool = False) -> dict:
    """Remove a login and its password.

    Args:
        login_id: The login's identifier.
        force: Delete even when devices or services still reference it.

    Returns:
        An empty object.

    Raises:
        HTTPException: 409 when something still uses the login and ``force``
            is not set, 404 when the id is unknown.
    """
    vault = SecretVault()
    record = vault.get(login_id)
    if record is None or record.kind != LOGIN_KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "unknown_login", "params": {}},
        )
    device_count = _login_device_counts().get(login_id, 0)
    service_count = _service_counts().get(login_id, 0)
    if (device_count or service_count) and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "login_in_use",
                "params": {
                    "device_count": device_count,
                    "service_count": service_count,
                },
            },
        )
    vault.delete(login_id)
    return {}


def _login_secret(username: str, password: str) -> dict:
    secret = {"password": password}
    if username.strip():
        secret["username"] = username.strip()
    return secret


def _login_device_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for device in DeviceRegistry().all_stored():
        ssh = device.ssh or {}
        # A device naming one login for both its account and its sudo counts
        # once.
        referenced = {ssh.get("password_id"), ssh.get("sudo_password_id")}
        for login_id in referenced:
            if login_id:
                counts[login_id] = counts.get(login_id, 0) + 1
    return counts


def _service_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for service in DeclaredServiceRegistry().list_records():
        # A service naming one login on several shares counts once.
        referenced = {share.login_id for share in service.shares}
        for login_id in referenced:
            if login_id:
                counts[login_id] = counts.get(login_id, 0) + 1
    return counts


def _login_view(
    vault: SecretVault,
    record: SecretRecord,
    device_counts: dict[str, int],
    service_counts: dict[str, int],
) -> LoginView:
    try:
        username = vault.open(record.id).get("username", "")
    except VaultLockedError:
        raise
    except VaultError:
        # A ciphertext that will not open still deserves a row: the name and
        # the counts are what say it exists and what would notice a delete.
        username = ""
    return LoginView(
        id=record.id,
        name=record.name,
        username=username,
        created_at=record.created_at,
        device_count=device_counts.get(record.id, 0),
        service_count=service_counts.get(record.id, 0),
    )
