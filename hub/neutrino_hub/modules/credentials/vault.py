"""Every secret the hub keeps for somebody, sealed in one store.

One AES-256-GCM ciphertext per object in ``config/credentials/vault.json``,
under the master key in ``config/credentials/vault.key``. Names, kinds and
timestamps stay readable, so the file says what it holds without saying what
anything is; each object's AAD binds its ciphertext to its id and kind, so two
objects cannot be swapped. The key lives beside the store because backing up
``config/`` must reproduce the appliance and the panel must decrypt with
nobody at the keyboard; a copy that leaves the box carries the key sealed
under a passphrase instead, via :func:`wrap_master_key`.

A rekey writes the fresh key to ``vault.key.new``, rewrites the store under
it, and renames it over ``vault.key`` last. In every crash window a key that
opens the store is on disk: the old key until the store is rewritten,
``vault.key.new`` after. A leftover ``vault.key.new`` is settled on the next
use — renamed into place when it opens the store, discarded when the old key
still does.
"""

import base64
import hashlib
import json
import os
import secrets
import stat
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from neutrino_hub.modules.credentials.constants import (
    CREDENTIALS_SECRET_KINDS,
    CREDENTIALS_VAULT_CIPHER,
    CREDENTIALS_VAULT_KEY_PATH,
    CREDENTIALS_VAULT_PATH,
    CREDENTIALS_VAULT_VERSION,
)
from neutrino_hub.utils import json_file
from neutrino_hub.utils.json_file import read_config, write_config

VAULT_KEY_BYTES = 32
VAULT_NONCE_BYTES = 12
VAULT_WRAP_SALT_BYTES = 16
VAULT_SCRYPT_N = 2**15
VAULT_SCRYPT_R = 8
VAULT_SCRYPT_P = 1
# scrypt needs 128 * r * n bytes; OpenSSL's default ceiling is exactly that.
VAULT_SCRYPT_MAXMEM = 2**26


class VaultError(ValueError):
    """Raised when the vault refuses an operation."""


def wrap_master_key(key_bytes: bytes, passphrase: str) -> dict:
    """Seal the master key under a passphrase, for a copy that leaves the box.

    Args:
        key_bytes: The raw master key.
        passphrase: What the copy is protected with.

    Returns:
        A JSON-ready object naming the scrypt parameters, salt, nonce and
        ciphertext.
    """
    salt = secrets.token_bytes(VAULT_WRAP_SALT_BYTES)
    kek = _derive_wrap_key(
        passphrase, salt, VAULT_SCRYPT_N, VAULT_SCRYPT_R, VAULT_SCRYPT_P
    )
    nonce = secrets.token_bytes(VAULT_NONCE_BYTES)
    data = AESGCM(kek).encrypt(nonce, key_bytes, None)
    return {
        "kdf": "scrypt",
        "salt": base64.b64encode(salt).decode(),
        "n": VAULT_SCRYPT_N,
        "r": VAULT_SCRYPT_R,
        "p": VAULT_SCRYPT_P,
        "nonce": base64.b64encode(nonce).decode(),
        "data": base64.b64encode(data).decode(),
    }


def unwrap_master_key(wrapped: dict, passphrase: str) -> bytes:
    """Open a wrapped master key.

    Args:
        wrapped: What :func:`wrap_master_key` produced.
        passphrase: The passphrase it was sealed under.

    Returns:
        The raw master key.

    Raises:
        VaultError: If the object is not a usable wrap or the passphrase does
            not open it.
    """
    if wrapped.get("kdf") != "scrypt":
        raise VaultError(f"unknown key wrap kdf {wrapped.get('kdf')!r}")
    try:
        salt = base64.b64decode(wrapped["salt"])
        nonce = base64.b64decode(wrapped["nonce"])
        data = base64.b64decode(wrapped["data"])
        factors = (int(wrapped["n"]), int(wrapped["r"]), int(wrapped["p"]))
    except (KeyError, TypeError, ValueError) as error:
        raise VaultError("the wrapped key is malformed") from error
    try:
        kek = _derive_wrap_key(passphrase, salt, *factors)
    except ValueError as error:
        # A restore reads these factors from the tarball, so a hostile or
        # corrupt value must refuse, not crash or eat the box's memory.
        raise VaultError("the wrapped key is malformed") from error
    try:
        return AESGCM(kek).decrypt(nonce, data, None)
    except InvalidTag as error:
        raise VaultError("the passphrase does not open this key") from error


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


def _key_path() -> Path:
    # Resolved per call, against the same root read_config uses right now.
    return json_file.UTILS_CONFIG_DIR / CREDENTIALS_VAULT_KEY_PATH


def _key_new_path() -> Path:
    path = _key_path()
    return path.with_name(path.name + ".new")


def _write_key_material(path: Path, key: bytes) -> None:
    # Create with the final mode rather than widening then narrowing, so the
    # key is never briefly world-readable.
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(key.hex() + "\n")


@dataclass
class SecretRecord:
    """One sealed secret, without its material.

    Attributes:
        id: Stable identifier the rest of ``config/`` references.
        name: Human-chosen label.
        kind: One of :data:`CREDENTIALS_SECRET_KINDS`.
        meta: Plaintext annotations, for example a fingerprint or username.
        created_at: ISO timestamp of when it was added.
    """

    id: str
    name: str
    kind: str
    meta: dict
    created_at: str


# Held across every read-modify-write of the store and the key files. The
# panel is one process with many threads, and both files are written whole.
_WRITE_LOCK = threading.RLock()


class SecretVault:
    """Seals, lists, opens, and re-keys the stored secrets."""

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
            VaultError: If the kind is unknown, the name is blank, or the
                secret's field names do not match the kind.
        """
        if kind not in CREDENTIALS_SECRET_KINDS:
            raise VaultError(f"unknown secret kind {kind!r}")
        if not name.strip():
            raise VaultError("a secret needs a name")
        self._validate_fields(kind, secret)
        with _WRITE_LOCK:
            key = self._master_key()
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
            VaultError: If the id is unknown or the ciphertext does not
                decrypt under the current master key.
        """
        with _WRITE_LOCK:
            key = self._master_key()
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
            VaultError: If the id is unknown or the secret's field names do
                not match the stored kind.
        """
        with _WRITE_LOCK:
            key = self._master_key()
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

    def rekey(self) -> int:
        """Re-encrypt every secret under a fresh master key.

        Returns:
            How many secrets were re-sealed.

        Raises:
            VaultError: If a stored secret does not decrypt under the current
                key; nothing is changed then.
        """
        with _WRITE_LOCK:
            old_key = self._master_key()
            store = self._read_store()
            opened = {
                secret_id: self._unseal(old_key, secret_id, entry)
                for secret_id, entry in store["secrets"].items()
            }
            new_key = secrets.token_bytes(VAULT_KEY_BYTES)
            _write_key_material(_key_new_path(), new_key)
            for secret_id, entry in store["secrets"].items():
                entry["nonce"], entry["data"] = self._seal(
                    new_key, secret_id, entry["kind"], opened[secret_id]
                )
            self._write_store(store)
            os.replace(_key_new_path(), _key_path())
            return len(opened)

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

    def _master_key(self) -> bytes:
        with _WRITE_LOCK:
            path = _key_path()
            if _key_new_path().is_file():
                self._settle_rekey(path, _key_new_path())
            if not path.is_file():
                key = secrets.token_bytes(VAULT_KEY_BYTES)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.parent.chmod(stat.S_IRWXU)
                _write_key_material(path, key)
                return key
            return self._read_key(path)

    def _settle_rekey(self, path: Path, new_path: Path) -> None:
        try:
            new_key = self._read_key(new_path)
        except VaultError:
            # The crash came while the new key was being written; the store
            # was never rewritten under it.
            new_path.unlink()
            return
        store = self._read_store()
        if store["secrets"] and self._key_opens(new_key, store):
            os.replace(new_path, path)
        else:
            new_path.unlink()

    def _key_opens(self, key: bytes, store: dict) -> bool:
        try:
            for secret_id, entry in store["secrets"].items():
                self._unseal(key, secret_id, entry)
        except VaultError:
            return False
        return True

    def _read_key(self, path: Path) -> bytes:
        try:
            key = bytes.fromhex(path.read_text(encoding="utf-8").strip())
        except ValueError as error:
            raise VaultError(f"{path} does not hold a usable key") from error
        if len(key) != VAULT_KEY_BYTES:
            raise VaultError(f"{path} does not hold a usable key")
        return key

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
                f"secret {secret_id!r} does not decrypt: the master key is not "
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
        cipher = data.get("cipher", CREDENTIALS_VAULT_CIPHER)
        if cipher != CREDENTIALS_VAULT_CIPHER:
            raise VaultError(f"vault cipher {cipher!r} is not supported")
        return {
            "version": CREDENTIALS_VAULT_VERSION,
            "cipher": CREDENTIALS_VAULT_CIPHER,
            "secrets": data.get("secrets", {}),
        }

    def _write_store(self, store: dict) -> None:
        write_config(CREDENTIALS_VAULT_PATH, store)
