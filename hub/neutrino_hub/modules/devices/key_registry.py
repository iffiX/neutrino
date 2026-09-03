"""The gateway's SSH keys, managed as named entities in one place.

A key is pasted once, named, and then referenced by devices — rather than each
device carrying its own copy. That is what lets one key serve a fleet, lets the
Credentials page show what is stored and remove it, and keeps a device's config
free of secret material.

The material is sealed in the credential vault under the ``ssh_key`` kind. What
stays readable beside the ciphertext is what the panel lists: the key type, the
fingerprint, and whether a passphrase was sealed with it.
"""

from dataclasses import dataclass

import asyncssh

from neutrino_hub.modules.credentials.vault import (
    SecretRecord,
    SecretVault,
    VaultError,
    VaultLockedError,
)

KEY_KIND = "ssh_key"
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
        has_passphrase: Whether a passphrase is sealed to unlock it.
        created_at: ISO timestamp of when it was added.
    """

    id: str
    name: str
    key_type: str
    fingerprint: str
    has_passphrase: bool
    created_at: str


class KeyRegistry:
    """Validates, seals, and lists the gateway's SSH keys."""

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
        secret = {"private_key": private_key.strip()}
        if passphrase:
            secret["passphrase"] = passphrase
        return self._to_record(
            SecretVault().add(
                kind=KEY_KIND,
                name=name.strip() or loaded.get_fingerprint(),
                secret=secret,
                meta={
                    "key_type": self._algorithm_of(loaded),
                    "fingerprint": loaded.get_fingerprint(),
                    "has_passphrase": bool(passphrase),
                },
            )
        )

    def list_records(self) -> list[KeyRecord]:
        """Read every stored key's metadata.

        Returns:
            One record per key, newest first.
        """
        return [
            self._to_record(record)
            for record in SecretVault().list_records(kind=KEY_KIND)
        ]

    def get(self, key_id: str) -> KeyRecord | None:
        """Read one key's metadata.

        Args:
            key_id: The key's identifier.

        Returns:
            The record, or None when the id is unknown or names another kind
            of secret.
        """
        record = SecretVault().get(key_id)
        if record is None or record.kind != KEY_KIND:
            return None
        return self._to_record(record)

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
        if self.get(key_id) is None:
            raise KeyMaterialError(f"no key with id {key_id!r}")
        try:
            return self._to_record(SecretVault().rename(key_id, name))
        except VaultLockedError:
            raise
        except VaultError as error:
            raise KeyMaterialError(str(error)) from error

    def delete(self, key_id: str) -> None:
        """Remove a key and its material.

        Args:
            key_id: The key's identifier. An unknown id is not an error.
        """
        if self.get(key_id) is None:
            return
        SecretVault().delete(key_id)

    def material_for(self, key_id: str) -> tuple[str, str | None]:
        """Open a key's sealed material.

        Args:
            key_id: The key's identifier.

        Returns:
            The private key text and its passphrase, None when it has none.

        Raises:
            KeyMaterialError: If the id is unknown or the vault cannot open it.
        """
        try:
            secret = SecretVault().open(key_id)
        except VaultLockedError:
            raise
        except VaultError as error:
            raise KeyMaterialError(str(error)) from error
        return secret["private_key"], secret.get("passphrase")

    def has_key(self, key_id: str) -> bool:
        """Whether a key with this id is stored.

        Args:
            key_id: The key's identifier.

        Returns:
            True when the vault holds a key under this id.
        """
        return self.get(key_id) is not None

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

    def _algorithm_of(self, loaded) -> str:
        algorithm = loaded.algorithm
        return algorithm.decode() if isinstance(algorithm, bytes) else str(algorithm)

    def _to_record(self, record: SecretRecord) -> KeyRecord:
        return KeyRecord(
            id=record.id,
            name=record.name,
            key_type=record.meta.get("key_type", "unknown"),
            fingerprint=record.meta.get("fingerprint", ""),
            has_passphrase=bool(record.meta.get("has_passphrase")),
            created_at=record.created_at,
        )
