"""The Credentials page: the SSH keys, logins and tokens the box holds.

All of them are secrets the gateway uses on somebody's behalf, and none comes
back out through the API — a listing says a secret is stored, never what it
is. Each reaches a device or a service through an id, so the material never
sits in a device's own configuration. A login is one account — a password
with an optional username — and devices and declared services both reference
the same collection; a token is one bare secret string, and AI providers
reference those.

A credential is added, referenced and deleted; nothing here edits one, not
even its name. Replacing a credential is adding the new one, pointing its
consumers at it, and deleting the old.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import KeyMaterialError, VaultLockedError
from neutrino_hub.modules.credentials.vault import (
    SecretRecord,
    SecretVault,
)
from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.devices.key_registry import KeyRecord, KeyRegistry
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK, read_config, write_config
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.models import (
    KeyCreate,
    KeyListView,
    KeyView,
    LoginCreate,
    LoginListView,
    LoginView,
    TokenCreate,
    TokenListView,
    TokenView,
)

LOGIN_KIND = "login"
TOKEN_KIND = "token"

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
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": error.code, "params": error.params},
        ) from error
    return _key_view(record, _device_counts())


@router.delete("/ssh_keys/{key_id}")
def delete_key(key_id: str) -> dict:
    """Remove a key and its material, clearing every device reference to it.

    Args:
        key_id: The key's identifier.

    Returns:
        Under ``cleared``, how many devices lost the key.
    """
    with CONFIG_WRITE_LOCK:
        device_count = _clear_key_on_devices(key_id)
        KeyRegistry().delete(key_id)
    return {"cleared": {"device_count": device_count}}


def _device_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for device in DeviceRegistry().all_stored():
        key_id = (device.ssh or {}).get("key_id")
        if key_id:
            counts[key_id] = counts.get(key_id, 0) + 1
    return counts


def _clear_key_on_devices(key_id: str) -> int:
    registry = DeviceRegistry()
    cleared = 0
    for device in registry.all_stored():
        ssh = device.ssh or {}
        if ssh.get("key_id") != key_id:
            continue
        registry.annotate(device.mac_address, {"ssh": {**ssh, "key_id": None}})
        cleared += 1
    return cleared


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
    """Read every stored login with how many devices use it.

    Returns:
        The logins, newest first, passwords withheld.
    """
    vault = SecretVault()
    device_counts = _login_device_counts()
    return LoginListView(
        logins=[
            _login_view(vault, record, device_counts)
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
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "login_refused", "params": {"detail": str(error)}},
        ) from error
    return _login_view(SecretVault(), record, _login_device_counts())


@router.delete("/logins/{login_id}")
def delete_login(login_id: str) -> dict:
    """Remove a login and its password, clearing every reference to it.

    A device naming it for its account loses that id.

    Args:
        login_id: The login's identifier.

    Returns:
        Under ``cleared``, how many devices lost the login.

    Raises:
        HTTPException: 404 when the id is unknown.
    """
    vault = SecretVault()
    record = vault.get(login_id)
    if record is None or record.kind != LOGIN_KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "unknown_login", "params": {}},
        )
    with CONFIG_WRITE_LOCK:
        device_count = _clear_login_on_devices(login_id)
        vault.delete(login_id)
    return {"cleared": {"device_count": device_count}}


def _login_secret(username: "str | None", password: str) -> dict:
    secret = {"password": password}
    if username and username.strip():
        secret["username"] = username.strip()
    return secret


def _login_device_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for device in DeviceRegistry().all_stored():
        login_id = (device.ssh or {}).get("login_id")
        if login_id:
            counts[login_id] = counts.get(login_id, 0) + 1
    return counts


def _clear_login_on_devices(login_id: str) -> int:
    registry = DeviceRegistry()
    cleared = 0
    for device in registry.all_stored():
        ssh = device.ssh or {}
        if ssh.get("login_id") != login_id:
            continue
        updated = dict(ssh)
        updated["login_id"] = None
        registry.annotate(device.mac_address, {"ssh": updated})
        cleared += 1
    return cleared


def _login_view(
    vault: SecretVault,
    record: SecretRecord,
    device_counts: dict[str, int],
) -> LoginView:
    try:
        username = vault.open(record.id).get("username") or None
    except VaultLockedError:
        raise
    except ValueError:
        # A ciphertext that will not open still deserves a row: the name and
        # the counts are what say it exists and what would notice a delete.
        username = None
    return LoginView(
        id=record.id,
        name=record.name,
        username=username,
        created_at=record.created_at,
        device_count=device_counts.get(record.id, 0),
    )


# --- Tokens ---


@router.get("/tokens", response_model=TokenListView)
def list_tokens() -> TokenListView:
    """Read every stored token with how many providers and nodes use it.

    Returns:
        The tokens, newest first, values withheld.
    """
    provider_counts = _provider_counts()
    node_counts = _node_counts()
    return TokenListView(
        tokens=[
            _token_view(record, provider_counts, node_counts)
            for record in SecretVault().list_records(kind=TOKEN_KIND)
        ]
    )


@router.post("/tokens", response_model=TokenView)
def create_token(request: TokenCreate) -> TokenView:
    """Seal a token under a name.

    Args:
        request: The name and the value.

    Returns:
        The stored token, without its value.

    Raises:
        HTTPException: 400 when the value is blank or the vault refuses.
    """
    if not request.value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "token_value_needed", "params": {}},
        )
    try:
        record = SecretVault().add(
            kind=TOKEN_KIND,
            name=request.name,
            secret={"value": request.value},
        )
    except VaultLockedError:
        raise
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "token_refused", "params": {"detail": str(error)}},
        ) from error
    return _token_view(record, _provider_counts(), _node_counts())


@router.delete("/tokens/{token_id}")
def delete_token(token_id: str, runtime: PanelRuntime = Depends(get_runtime)) -> dict:
    """Remove a token and its value, clearing every reference to it.

    A provider keyed with it loses its key reference; a node keyed with it
    loses its secret reference and is disabled, since it cannot serve.

    Args:
        token_id: The token's identifier.
        runtime: The shared runtime.

    Returns:
        Under ``cleared``, how many providers and nodes lost the token.

    Raises:
        HTTPException: 404 when the id is unknown.
    """
    vault = SecretVault()
    record = vault.get(token_id)
    if record is None or record.kind != TOKEN_KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "unknown_token", "params": {}},
        )
    with CONFIG_WRITE_LOCK:
        provider_count = _clear_token_on_providers(token_id)
        node_count = _clear_token_on_nodes(token_id)
        vault.delete(token_id)
    if node_count:
        runtime.is_config_dirty = True
    return {"cleared": {"provider_count": provider_count, "node_count": node_count}}


def _provider_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for provider in AiProviderRegistry().list_records():
        if provider.secret_id:
            counts[provider.secret_id] = counts.get(provider.secret_id, 0) + 1
    return counts


def _node_counts() -> dict[str, int]:
    try:
        node_list = XrayNodeList.from_dict(read_config("xray/nodes.json"))
    except FileNotFoundError:
        return {}
    counts: dict[str, int] = {}
    for node in node_list.nodes:
        if node.secret_id:
            counts[node.secret_id] = counts.get(node.secret_id, 0) + 1
    return counts


def _clear_token_on_providers(token_id: str) -> int:
    registry = AiProviderRegistry()
    cleared = 0
    for provider in registry.list_records():
        if provider.secret_id == token_id:
            registry.update(provider.id, secret_id=None)
            cleared += 1
    return cleared


def _clear_token_on_nodes(token_id: str) -> int:
    try:
        node_list = XrayNodeList.from_dict(read_config("xray/nodes.json"))
    except FileNotFoundError:
        return 0
    cleared = 0
    for node in node_list.nodes:
        if node.secret_id == token_id:
            node.secret_id = None
            node.is_enabled = False
            cleared += 1
    if cleared:
        write_config("xray/nodes.json", node_list.to_dict())
    return cleared


def _token_view(
    record: SecretRecord,
    provider_counts: dict[str, int],
    node_counts: dict[str, int],
) -> TokenView:
    return TokenView(
        id=record.id,
        name=record.name,
        created_at=record.created_at,
        provider_count=provider_counts.get(record.id, 0),
        node_count=node_counts.get(record.id, 0),
    )
