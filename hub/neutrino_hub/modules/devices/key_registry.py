"""The gateway's SSH keys, managed as named entities in one place.

A key is pasted once, named, and then referenced by devices — rather than each
device carrying its own copy of a path. That is what lets one key serve a fleet,
lets the Credentials page show what is stored and remove it, and keeps a device's config
free of secret material.

The private material is written to a file readable only by the gateway, because
asyncssh loads keys from disk and because a key sitting in a JSON config next to
everything else is a key waiting to be copied by accident. A manifest holds only
metadata plus the passphrase needed to use each key; both files stay outside
git.
"""

import os
import secrets
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import asyncssh

from neutrino_hub.utils.constants import UTILS_CONFIG_DIR
from neutrino_hub.utils.json_file import read_config, write_config

KEY_DIR = UTILS_CONFIG_DIR / "credentials" / "ssh_keys"
KEY_REGISTRY_PATH = "credentials/ssh_keys/registry.json"
KEY_ID_BYTES = 8
PRIVATE_KEY_MARKER = "-----BEGIN"
PUBLIC_KEY_PREFIXES = (
    "ssh-rsa",
    "ssh-ed25519",
    "ecdsa-sha2-",
    "sk-ecdsa-sha2-",
    "sk-ssh-ed25519",
)


class KeyMaterialError(ValueError):
    """Raised when pasted key material cannot be used."""


@dataclass
class KeyRecord:
    """One stored SSH key, without its private material.

    Attributes:
        id: Stable identifier devices reference.
        name: Human-chosen label.
        key_type: Algorithm, for example ``ssh-ed25519``.
        fingerprint: The key's SHA256 fingerprint.
        has_passphrase: Whether a passphrase is stored to unlock it.
        created_at: ISO timestamp of when it was added.
    """

    id: str
    name: str
    key_type: str
    fingerprint: str
    has_passphrase: bool
    created_at: str


class KeyRegistry:
    """Validates, stores, and lists the gateway's SSH keys."""

    def add(
        self, *, name: str, private_key: str, passphrase: str | None = None
    ) -> KeyRecord:
        """Validate a pasted key and store it under a name.

        Args:
            name: Label for the key. Falls back to the fingerprint if blank.
            private_key: The pasted key text.
            passphrase: Passphrase, when the key is encrypted.

        Returns:
            The stored record.

        Raises:
            KeyMaterialError: If the text is a public key, is not a key at all, is
                encrypted without a workable passphrase, or the gateway lacks
                the bcrypt support to open it. Each case gets its own message,
                because the fix differs.
        """
        loaded = self._validate(private_key, passphrase)
        key_id = secrets.token_hex(KEY_ID_BYTES)

        KEY_DIR.mkdir(parents=True, exist_ok=True)
        KEY_DIR.chmod(stat.S_IRWXU)
        self._write_material(self.path_for(key_id), private_key)

        record = KeyRecord(
            id=key_id,
            name=name.strip() or loaded.get_fingerprint(),
            key_type=self._algorithm_of(loaded),
            fingerprint=loaded.get_fingerprint(),
            has_passphrase=bool(passphrase),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        manifest = self._read_manifest()
        manifest[key_id] = {
            "name": record.name,
            "key_type": record.key_type,
            "fingerprint": record.fingerprint,
            "passphrase": passphrase,
            "created_at": record.created_at,
        }
        self._write_manifest(manifest)
        return record

    def list_records(self) -> list[KeyRecord]:
        """Read every stored key's metadata.

        Returns:
            One record per key, newest first.
        """
        records = [
            self._to_record(key_id, entry)
            for key_id, entry in self._read_manifest().items()
        ]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records

    def get(self, key_id: str) -> KeyRecord | None:
        """Read one key's metadata.

        Args:
            key_id: The key's identifier.

        Returns:
            The record, or None when the id is unknown.
        """
        entry = self._read_manifest().get(key_id)
        return self._to_record(key_id, entry) if entry else None

    def rename(self, key_id: str, name: str) -> KeyRecord:
        """Change a key's label.

        Args:
            key_id: The key's identifier.
            name: The new label.

        Returns:
            The updated record.

        Raises:
            KeyMaterialError: If the key is unknown or the name is blank.
        """
        if not name.strip():
            raise KeyMaterialError("a key needs a name")
        manifest = self._read_manifest()
        if key_id not in manifest:
            raise KeyMaterialError(f"no key with id {key_id!r}")
        manifest[key_id]["name"] = name.strip()
        self._write_manifest(manifest)
        return self._to_record(key_id, manifest[key_id])

    def delete(self, key_id: str) -> None:
        """Remove a key and its material.

        Args:
            key_id: The key's identifier. An unknown id is not an error.
        """
        manifest = self._read_manifest()
        manifest.pop(key_id, None)
        self._write_manifest(manifest)
        self.path_for(key_id).unlink(missing_ok=True)

    def path_for(self, key_id: str) -> Path:
        """Where a key's private material lives.

        Args:
            key_id: The key's identifier.

        Returns:
            The material path, whether or not it exists.
        """
        return KEY_DIR / key_id

    def passphrase_for(self, key_id: str) -> str | None:
        """Read the passphrase stored for a key.

        Args:
            key_id: The key's identifier.

        Returns:
            The passphrase, or None when the key has none or is unknown.
        """
        return self._read_manifest().get(key_id, {}).get("passphrase")

    def has_key(self, key_id: str) -> bool:
        """Whether a key with this id is stored.

        Args:
            key_id: The key's identifier.

        Returns:
            True when both the manifest entry and its material exist.
        """
        return key_id in self._read_manifest() and self.path_for(key_id).is_file()

    def _validate(self, private_key: str, passphrase: str | None):
        text = private_key.strip()
        if not text:
            raise KeyMaterialError("no key was pasted")
        if text.startswith(PUBLIC_KEY_PREFIXES):
            raise KeyMaterialError(
                "that is a public key. The gateway authenticates as the device's "
                "user, so it needs the matching private key — the file without "
                "the .pub suffix, beginning with '-----BEGIN'."
            )
        if PRIVATE_KEY_MARKER not in text:
            raise KeyMaterialError(
                "this does not look like a private key; it should begin with "
                "'-----BEGIN OPENSSH PRIVATE KEY-----' or similar"
            )
        try:
            return asyncssh.import_private_key(text, passphrase=passphrase)
        except asyncssh.KeyEncryptionError as error:
            if "bcrypt" in str(error).lower():
                raise KeyMaterialError(
                    "this gateway cannot open encrypted keys: the bcrypt "
                    "dependency is missing. Reinstall the panel environment, or "
                    "add a key with no passphrase."
                ) from error
            raise KeyMaterialError(
                "this key is passphrase-protected and the passphrase given does "
                "not open it"
            ) from error
        except asyncssh.KeyImportError as error:
            if "passphrase" in str(error).lower():
                raise KeyMaterialError(
                    "this key is passphrase-protected; enter its passphrase too"
                ) from error
            raise KeyMaterialError(f"the key could not be read: {error}") from error

    def _write_material(self, path: Path, text: str) -> None:
        # Create with the final mode rather than widening then narrowing, so the
        # key is never briefly world-readable.
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text.strip() + "\n")

    def _algorithm_of(self, loaded) -> str:
        algorithm = loaded.algorithm
        return algorithm.decode() if isinstance(algorithm, bytes) else str(algorithm)

    def _to_record(self, key_id: str, entry: dict) -> KeyRecord:
        return KeyRecord(
            id=key_id,
            name=entry.get("name", key_id),
            key_type=entry.get("key_type", "unknown"),
            fingerprint=entry.get("fingerprint", ""),
            has_passphrase=bool(entry.get("passphrase")),
            created_at=entry.get("created_at", ""),
        )

    def _read_manifest(self) -> dict:
        try:
            return read_config(KEY_REGISTRY_PATH).get("keys", {})
        except FileNotFoundError:
            return {}

    def _write_manifest(self, manifest: dict) -> None:
        write_config(KEY_REGISTRY_PATH, {"keys": manifest})
