"""Every secret the hub keeps for somebody, sealed in one store.

One AES-256-GCM ciphertext per object in ``config/credentials/vault.json``,
under a random data key. Names, kinds and timestamps stay readable, so the
file says what it holds without saying what anything is; each object's AAD
binds its ciphertext to its id and kind, so two objects cannot be swapped.

The data key never sits in ``config/``. The store carries it wrapped under
the master passphrase (scrypt, then AES-256-GCM), so a backup of ``config/``
holds no unsealed secret; the working copy is state at
``/var/lib/neutrino/vault.key``, written by setup and by a successful
restore. With that state file missing the vault is locked, and every
operation that needs the key refuses with ``vault_locked``. Changing the
passphrase re-wraps the same data key; nothing sealed is touched.
"""

import base64
import hashlib
import json
import os
import secrets
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from neutrino_hub.modules.credentials.constants import (
    CREDENTIALS_SECRET_KINDS,
    CREDENTIALS_VAULT_PATH,
    CREDENTIALS_VAULT_STATE_KEY_NAME,
    CREDENTIALS_VAULT_VERSION,
)
from neutrino_hub.utils import constants
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)

VAULT_KEY_BYTES = 32
VAULT_NONCE_BYTES = 12
VAULT_WRAP_SALT_BYTES = 16
VAULT_WRAP_AAD = b"neutrino-vault-data-key"
VAULT_SCRYPT_N = 2**15
VAULT_SCRYPT_R = 8
VAULT_SCRYPT_P = 1
# scrypt needs 128 * r * n bytes; OpenSSL's default ceiling is exactly that.
VAULT_SCRYPT_MAXMEM = 2**26

VAULT_ERROR_LOCKED = "vault_locked"


class VaultError(ValueError):
    """Raised when the vault refuses an operation."""


class VaultPassphraseError(VaultError):
    """Raised when a passphrase does not open what it was offered."""


class VaultLockedError(VaultError):
    """Raised when the data key's state file is missing.

    Attributes:
        code: The machine name callers answer with.
    """

    code = VAULT_ERROR_LOCKED

    def __init__(self):
        super().__init__("the vault is locked: no data key on this box")


def wrap_data_key(passphrase: str, data_key: bytes) -> dict:
    """Wrap the data key under the master passphrase.

    Args:
        passphrase: The master passphrase.
        data_key: The random data key the store's objects are sealed with.

    Returns:
        The ``wrapped_key`` object: the scrypt parameters and the seal.
    """
    salt = secrets.token_bytes(VAULT_WRAP_SALT_BYTES)
    kek = _derive_wrap_key(
        passphrase, salt, VAULT_SCRYPT_N, VAULT_SCRYPT_R, VAULT_SCRYPT_P
    )
    nonce = secrets.token_bytes(VAULT_NONCE_BYTES)
    sealed = AESGCM(kek).encrypt(nonce, data_key, VAULT_WRAP_AAD)
    return {
        "kdf": "scrypt",
        "salt": base64.b64encode(salt).decode(),
        "n": VAULT_SCRYPT_N,
        "r": VAULT_SCRYPT_R,
        "p": VAULT_SCRYPT_P,
        "nonce": base64.b64encode(nonce).decode(),
        "data": base64.b64encode(sealed).decode(),
    }


def unwrap_data_key(passphrase: str, wrapped: dict | None = None) -> bytes:
    """Open a wrapped data key with the master passphrase.

    Args:
        passphrase: The master passphrase.
        wrapped: The ``wrapped_key`` object to open; None reads the store on
            this box.

    Returns:
        The data key.

    Raises:
        VaultPassphraseError: If the passphrase does not open it.
        VaultError: If there is no wrapped key, or the object is not a usable
            wrap. The parameters come from the object itself, so a hostile or
            corrupt value refuses rather than crashing or eating the box's
            memory.
    """
    if wrapped is None:
        wrapped = SecretVault().wrapped_key()
    if not isinstance(wrapped, dict):
        raise VaultError("the vault holds no wrapped key")
    try:
        if wrapped.get("kdf") != "scrypt":
            raise ValueError(f"unknown kdf {wrapped.get('kdf')!r}")
        salt = base64.b64decode(wrapped["salt"])
        nonce = base64.b64decode(wrapped["nonce"])
        sealed = base64.b64decode(wrapped["data"])
        factors = (int(wrapped["n"]), int(wrapped["r"]), int(wrapped["p"]))
    except (KeyError, TypeError, ValueError) as error:
        raise VaultError("the wrapped key is malformed") from error
    try:
        kek = _derive_wrap_key(passphrase, salt, *factors)
    except ValueError as error:
        raise VaultError("the wrapped key is malformed") from error
    try:
        return AESGCM(kek).decrypt(nonce, sealed, VAULT_WRAP_AAD)
    except InvalidTag as error:
        raise VaultPassphraseError("the passphrase does not open this vault") from error


def seal_bytes(data: bytes, aad: bytes) -> dict:
    """Seal a byte payload under the data key, bound to what it is for.

    Args:
        data: The payload to seal.
        aad: What binds the seal to its use, for example ``agent_tls:key``.

    Returns:
        A JSON-ready object holding the nonce and the ciphertext.

    Raises:
        VaultLockedError: If there is no data key on this box.
    """
    key = _read_state_key()
    nonce = secrets.token_bytes(VAULT_NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, data, aad)
    return {
        "nonce": base64.b64encode(nonce).decode(),
        "data": base64.b64encode(sealed).decode(),
    }


def unseal_bytes(sealed: dict, aad: bytes) -> bytes:
    """Open what :func:`seal_bytes` produced.

    Args:
        sealed: The sealed object.
        aad: The binding it was sealed under.

    Returns:
        The payload.

    Raises:
        VaultLockedError: If there is no data key on this box.
        VaultError: If the object is malformed or does not decrypt.
    """
    key = _read_state_key()
    try:
        nonce = base64.b64decode(sealed["nonce"])
        data = base64.b64decode(sealed["data"])
    except (KeyError, TypeError, ValueError) as error:
        raise VaultError("the sealed payload is malformed") from error
    try:
        return AESGCM(key).decrypt(nonce, data, aad)
    except (InvalidTag, ValueError) as error:
        raise VaultError(
            "the sealed payload does not decrypt: the data key is not the one "
            "it was sealed under, or it was modified"
        ) from error


def write_state_key(data_key: bytes) -> None:
    """Put the working data key on this box, unlocking the vault.

    Args:
        data_key: The unwrapped data key.
    """
    path = _state_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_key_material(path, data_key)


def _state_key_path() -> Path:
    # Resolved per call, against the state root as it is right now.
    return constants.UTILS_STATE_ROOT / CREDENTIALS_VAULT_STATE_KEY_NAME


def _read_state_key() -> bytes:
    path = _state_key_path()
    if not path.is_file():
        raise VaultLockedError()
    try:
        key = bytes.fromhex(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as error:
        raise VaultError(f"{path} does not hold a usable key") from error
    if len(key) != VAULT_KEY_BYTES:
        raise VaultError(f"{path} does not hold a usable key")
    return key


def _derive_wrap_key(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        passphrase.encode(),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=VAULT_SCRYPT_MAXMEM,
        dklen=VAULT_KEY_BYTES,
    )


def _aad(secret_id: str, kind: str) -> bytes:
    return f"{secret_id}:{kind}".encode()


def _write_key_material(path: Path, key: bytes) -> None:
    # Created with the final mode rather than widened then narrowed, so the
    # key is never briefly world-readable — and staged beside its target and
    # renamed into place, so a crash mid-write leaves the old key usable.
    staged = path.with_name(path.name + ".tmp")
    descriptor = os.open(
        staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(key.hex() + "\n")
        os.replace(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


@dataclass
class SecretRecord:
    """One sealed secret, without its material.

    Attributes:
        id: Stable identifier the rest of ``config/`` references.
        name: Human-chosen label.
        kind: One of :data:`CREDENTIALS_SECRET_KINDS`.
        meta: Plaintext annotations, for example a fingerprint.
        created_at: ISO timestamp of when it was added.
    """

    id: str
    name: str
    kind: str
    meta: dict
    created_at: str


# The config-wide lock, held across every read-modify-write of the store and
# the state key. The panel is one process with many threads, and both files
# are written whole.
_WRITE_LOCK = CONFIG_WRITE_LOCK


class SecretVault:
    """Seals, lists, opens, and re-wraps the stored secrets."""

    def initialize(self, passphrase: str) -> bool:
        """Give a fresh box its data key, wrapped under the passphrase.

        A store that already carries a wrapped key is unlocked instead: the
        passphrase opens it and the state key is rewritten, so an interrupted
        setup converges. A store with sealed secrets is never re-keyed here.

        Args:
            passphrase: The master passphrase.

        Returns:
            True when a fresh data key was minted.

        Raises:
            VaultPassphraseError: If the store holds secrets and the
                passphrase does not open its wrapped key.
        """
        with _WRITE_LOCK:
            store = self._read_store()
            if store.get("wrapped_key"):
                try:
                    write_state_key(unwrap_data_key(passphrase, store["wrapped_key"]))
                    return False
                except VaultPassphraseError:
                    if store["secrets"]:
                        raise
            data_key = secrets.token_bytes(VAULT_KEY_BYTES)
            store["wrapped_key"] = wrap_data_key(passphrase, data_key)
            self._write_store(store)
            write_state_key(data_key)
            return True

    def change_passphrase(self, passphrase: str) -> None:
        """Re-wrap the data key under a new passphrase; nothing sealed moves.

        Args:
            passphrase: The new master passphrase.

        Raises:
            VaultLockedError: If there is no data key on this box.
        """
        with _WRITE_LOCK:
            key = _read_state_key()
            store = self._read_store()
            store["wrapped_key"] = wrap_data_key(passphrase, key)
            self._write_store(store)

    def wrapped_key(self) -> dict | None:
        """Read the store's wrapped data key.

        Returns:
            The ``wrapped_key`` object, or None before setup wrote one.
        """
        return self._read_store().get("wrapped_key")

    def is_locked(self) -> bool:
        """Whether vault operations would refuse for want of the data key.

        Returns:
            True when no state key is on this box.
        """
        return not _state_key_path().is_file()

    def add(
        self, *, kind: str, name: str, secret: dict, meta: dict | None = None
    ) -> SecretRecord:
        """Seal a new secret.

        Args:
            kind: One of :data:`CREDENTIALS_SECRET_KINDS`.
            name: Human-chosen label.
            secret: The fields to seal, named as the kind demands.
            meta: Plaintext annotations to store beside the ciphertext.

        Returns:
            The stored record.

        Raises:
            VaultLockedError: If there is no data key on this box.
            VaultError: If the kind is unknown, the name is blank, or the
                secret's field names do not match the kind.
        """
        if kind not in CREDENTIALS_SECRET_KINDS:
            raise VaultError(f"unknown secret kind {kind!r}")
        if not name.strip():
            raise VaultError("a secret needs a name")
        self._validate_fields(kind, secret)
        with _WRITE_LOCK:
            key = _read_state_key()
            store = self._read_store()
            secret_id = uuid.uuid4().hex
            nonce, data = self._seal(key, secret_id, kind, secret)
            store["secrets"][secret_id] = {
                "name": name.strip(),
                "kind": kind,
                "meta": meta or {},
                "created_at": datetime.now(timezone.utc).isoformat(),
                "nonce": nonce,
                "data": data,
            }
            self._write_store(store)
            return self._to_record(secret_id, store["secrets"][secret_id])

    def get(self, secret_id: str) -> SecretRecord | None:
        """Read one secret's metadata.

        Args:
            secret_id: The secret's id.

        Returns:
            The record, or None when the id is unknown.
        """
        entry = self._read_store()["secrets"].get(secret_id)
        return self._to_record(secret_id, entry) if entry else None

    def list_records(self, kind: str | None = None) -> list[SecretRecord]:
        """Read every stored secret's metadata.

        Args:
            kind: When given, only secrets of this kind.

        Returns:
            One record per secret, newest first.

        Raises:
            VaultError: If the kind filter is not a known kind.
        """
        if kind is not None and kind not in CREDENTIALS_SECRET_KINDS:
            raise VaultError(f"unknown secret kind {kind!r}")
        records = [
            self._to_record(secret_id, entry)
            for secret_id, entry in self._read_store()["secrets"].items()
            if kind is None or entry.get("kind") == kind
        ]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records

    def open(self, secret_id: str) -> dict:
        """Decrypt one secret. The only method that returns secret material.

        Args:
            secret_id: The secret's id.

        Returns:
            The sealed fields, as they were given to :meth:`add`.

        Raises:
            VaultLockedError: If there is no data key on this box.
            VaultError: If the id is unknown or the ciphertext does not
                decrypt under the data key.
        """
        with _WRITE_LOCK:
            key = _read_state_key()
            entry = self._read_store()["secrets"].get(secret_id)
            if entry is None:
                raise VaultError(f"no secret with id {secret_id!r}")
            return self._unseal(key, secret_id, entry)

    def rename(self, secret_id: str, name: str) -> SecretRecord:
        """Change a secret's label.

        Args:
            secret_id: The secret's id.
            name: The new label.

        Returns:
            The record after the change.

        Raises:
            VaultError: If the id is unknown or the name is blank.
        """
        if not name.strip():
            raise VaultError("a secret needs a name")
        with _WRITE_LOCK:
            store = self._read_store()
            entry = store["secrets"].get(secret_id)
            if entry is None:
                raise VaultError(f"no secret with id {secret_id!r}")
            entry["name"] = name.strip()
            self._write_store(store)
            return self._to_record(secret_id, entry)

    def update_meta(self, secret_id: str, meta: dict) -> SecretRecord:
        """Replace a secret's plaintext annotations, leaving the seal alone.

        Args:
            secret_id: The secret's id.
            meta: The annotations to store in place of the current ones.

        Returns:
            The record after the change.

        Raises:
            VaultError: If the id is unknown.
        """
        with _WRITE_LOCK:
            store = self._read_store()
            entry = store["secrets"].get(secret_id)
            if entry is None:
                raise VaultError(f"no secret with id {secret_id!r}")
            entry["meta"] = meta
            self._write_store(store)
            return self._to_record(secret_id, entry)

    def replace(
        self, secret_id: str, *, secret: dict, meta: dict | None = None
    ) -> SecretRecord:
        """Seal new material under an existing id and kind.

        Args:
            secret_id: The secret's id.
            secret: The new fields to seal, named as the stored kind demands.
            meta: New plaintext annotations; None keeps the stored ones.

        Returns:
            The record after the change.

        Raises:
            VaultLockedError: If there is no data key on this box.
            VaultError: If the id is unknown or the secret's field names do
                not match the stored kind.
        """
        with _WRITE_LOCK:
            key = _read_state_key()
            store = self._read_store()
            entry = store["secrets"].get(secret_id)
            if entry is None:
                raise VaultError(f"no secret with id {secret_id!r}")
            self._validate_fields(entry["kind"], secret)
            entry["nonce"], entry["data"] = self._seal(
                key, secret_id, entry["kind"], secret
            )
            if meta is not None:
                entry["meta"] = meta
            self._write_store(store)
            return self._to_record(secret_id, entry)

    def delete(self, secret_id: str) -> None:
        """Remove a secret and its ciphertext.

        Args:
            secret_id: The secret's id.

        Raises:
            VaultError: If the id is unknown.
        """
        with _WRITE_LOCK:
            store = self._read_store()
            if secret_id not in store["secrets"]:
                raise VaultError(f"no secret with id {secret_id!r}")
            del store["secrets"][secret_id]
            self._write_store(store)

    def _validate_fields(self, kind: str, secret: dict) -> None:
        fields = CREDENTIALS_SECRET_KINDS[kind]
        required = set(fields["required"])
        allowed = required | set(fields["optional"])
        missing = required - set(secret)
        if missing:
            raise VaultError(f"a {kind} secret needs {', '.join(sorted(missing))}")
        extras = set(secret) - allowed
        if extras:
            raise VaultError(
                f"a {kind} secret does not take {', '.join(sorted(extras))}"
            )

    def _seal(
        self, key: bytes, secret_id: str, kind: str, secret: dict
    ) -> tuple[str, str]:
        nonce = secrets.token_bytes(VAULT_NONCE_BYTES)
        data = AESGCM(key).encrypt(
            nonce, json.dumps(secret).encode(), _aad(secret_id, kind)
        )
        return base64.b64encode(nonce).decode(), base64.b64encode(data).decode()

    def _unseal(self, key: bytes, secret_id: str, entry: dict) -> dict:
        try:
            nonce = base64.b64decode(entry["nonce"])
            data = base64.b64decode(entry["data"])
        except (KeyError, TypeError, ValueError) as error:
            raise VaultError(f"secret {secret_id!r} is not readable") from error
        try:
            plain = AESGCM(key).decrypt(
                nonce, data, _aad(secret_id, entry.get("kind", ""))
            )
        except InvalidTag as error:
            raise VaultError(
                f"secret {secret_id!r} does not decrypt: the data key is not "
                "the one it was sealed under, or the store was modified"
            ) from error
        return json.loads(plain)

    def _to_record(self, secret_id: str, entry: dict) -> SecretRecord:
        return SecretRecord(
            id=secret_id,
            name=entry.get("name", secret_id),
            kind=entry.get("kind", ""),
            meta=entry.get("meta", {}),
            created_at=entry.get("created_at", ""),
        )

    def _read_store(self) -> dict:
        try:
            data = read_config(CREDENTIALS_VAULT_PATH)
        except FileNotFoundError:
            data = {}
        version = data.get("version", CREDENTIALS_VAULT_VERSION)
        if version != CREDENTIALS_VAULT_VERSION:
            raise VaultError(f"vault version {version!r} is not supported")
        return {
            "version": CREDENTIALS_VAULT_VERSION,
            "wrapped_key": data.get("wrapped_key"),
            "secrets": data.get("secrets", {}),
        }

    def _write_store(self, store: dict) -> None:
        written = {
            "version": CREDENTIALS_VAULT_VERSION,
            "secrets": store.get("secrets", {}),
        }
        if store.get("wrapped_key"):
            written["wrapped_key"] = store["wrapped_key"]
        write_config(CREDENTIALS_VAULT_PATH, written)
