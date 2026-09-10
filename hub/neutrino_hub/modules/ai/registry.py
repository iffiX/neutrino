"""AI providers, each pointing at a credential the vault already holds.

Every machine a developer touches needs the same endpoint and key for each AI
service, and pasting them into dotfiles on every box is how they end up
scattered and stale. They live here instead: named entries in one file, which
Dev Setup reads when wiring a device's tools.

A provider carries no key of its own: ``secret_id`` references a ``token``
object in the vault, added and deleted on the Credentials page. Deleting a
provider leaves the token where it is — its lifecycle belongs to that page —
and a reference whose object is gone reads as no key.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neutrino_hub.modules.ai.constants import (
    AI_PROVIDERS_PATH,
    AI_PROVIDER_KINDS,
)
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)

# Tells an untouched update field apart from an explicit None, which clears
# the reference.
_UNSET = object()


@dataclass
class AiProviderRecord:
    """One stored AI provider.

    Attributes:
        id: Stable identifier other features reference.
        name: Human-chosen label.
        kind: One of :data:`AI_PROVIDER_KINDS`.
        base_url: API endpoint; empty means the service's default.
        secret_id: The vault ``token`` object holding the key, None when the
            provider names none.
        is_enabled: Whether the AI gateway forwards to this provider.
        models: Alias mappings, each ``{"name": real, "alias": served}`` —
            what relays that insist on their own model names need.
        created_at: ISO timestamp of when it was added.
    """

    id: str
    name: str
    kind: str
    base_url: str = ""
    secret_id: str | None = None
    is_enabled: bool = True
    models: list = field(default_factory=list)
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "AiProviderRecord":
        """Build from a stored entry.

        Args:
            data: The stored object.

        Returns:
            The parsed record.
        """
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            kind=data.get("kind", "custom"),
            base_url=data.get("base_url", ""),
            secret_id=data.get("secret_id") or None,
            is_enabled=data.get("is_enabled", True),
            models=data.get("models", []),
            created_at=data.get("created_at", ""),
        )

    def to_dict(self) -> dict:
        """Serialize for storage.

        Returns:
            A JSON-ready object.
        """
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "base_url": self.base_url,
            "secret_id": self.secret_id,
            "is_enabled": self.is_enabled,
            "models": self.models,
            "created_at": self.created_at,
        }


# The config-wide lock: a mutation re-reads the file under it, and an
# operation that also touches another store nests under the same lock.
_WRITE_LOCK = CONFIG_WRITE_LOCK


class AiProviderRegistry:
    """Reads and edits the stored AI providers."""

    def __init__(self):
        self._records = self._read()
        self._vault = SecretVault()

    def list_records(self) -> list[AiProviderRecord]:
        """Read every provider, in served order.

        The record order in the file is the order the gateway serves them
        in: the renderer, the model a device is told to ask for, and the
        panel's list all follow it. Reordering is :meth:`reorder`.

        Returns:
            The stored records.
        """
        return list(self._records)

    def get(self, provider_id: str) -> AiProviderRecord | None:
        """Look one provider up.

        Args:
            provider_id: The record's id.

        Returns:
            The record, or None when unknown.
        """
        return next((r for r in self._records if r.id == provider_id), None)

    def add(
        self,
        *,
        name: str,
        kind: str,
        base_url: str,
        secret_id: str | None = None,
        models: list | None = None,
    ) -> AiProviderRecord:
        """Store a new provider.

        Args:
            name: Human-chosen label.
            kind: One of :data:`AI_PROVIDER_KINDS`.
            base_url: API endpoint; empty means the service's default.
            secret_id: The vault ``token`` the provider forwards with, None
                for a provider stored without a key.
            models: Alias mappings, empty when the provider needs none.

        Returns:
            The stored record.

        Raises:
            ValueError: If the kind is unknown or the name is empty.
        """
        if kind not in AI_PROVIDER_KINDS:
            raise ValueError(f"unknown provider kind {kind!r}")
        if not name.strip():
            raise ValueError("the provider needs a name")
        record = AiProviderRecord(
            id=uuid.uuid4().hex,
            name=name.strip(),
            kind=kind,
            base_url=base_url.strip(),
            secret_id=secret_id or None,
            models=models or [],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with _WRITE_LOCK:
            self._records = self._read()
            self._records.append(record)
            self._write()
        return record

    def update(
        self,
        provider_id: str,
        *,
        name: str | None = None,
        kind: str | None = None,
        base_url: str | None = None,
        secret_id=_UNSET,
        is_enabled: bool | None = None,
        models: list | None = None,
    ) -> AiProviderRecord:
        """Change parts of a provider.

        Args:
            provider_id: The record's id.
            name: New label, when given.
            kind: New kind, when given.
            base_url: New endpoint, when given.
            secret_id: New ``token`` reference, when given — None clears it;
                left out, the stored reference stays.
            is_enabled: New forwarding state, when given.
            models: New alias mappings, when given.

        Returns:
            The record after the change.

        Raises:
            KeyError: If the id is unknown.
            ValueError: If a new kind is not one of the known kinds.
        """
        with _WRITE_LOCK:
            self._records = self._read()
            record = self.get(provider_id)
            if record is None:
                raise KeyError(provider_id)
            if kind is not None and kind not in AI_PROVIDER_KINDS:
                raise ValueError(f"unknown provider kind {kind!r}")
            if name is not None and name.strip():
                record.name = name.strip()
            if kind is not None:
                record.kind = kind
            if base_url is not None:
                record.base_url = base_url.strip()
            if secret_id is not _UNSET:
                record.secret_id = secret_id or None
            if is_enabled is not None:
                record.is_enabled = is_enabled
            if models is not None:
                record.models = models
            self._write()
            return record

    def reorder(self, provider_ids: list[str]) -> list[AiProviderRecord]:
        """Store a new served order.

        Args:
            provider_ids: Every stored id exactly once, in the new order.

        Returns:
            The records, reordered.

        Raises:
            ValueError: If the ids are not a permutation of what is stored.
        """
        with _WRITE_LOCK:
            self._records = self._read()
            stored = {record.id: record for record in self._records}
            if sorted(provider_ids) != sorted(stored):
                raise ValueError("the ids are not a permutation of the stored ones")
            self._records = [stored[provider_id] for provider_id in provider_ids]
            self._write()
            return list(self._records)

    def delete(self, provider_id: str) -> None:
        """Remove a provider; the token it referenced stays in the vault.

        Args:
            provider_id: The record's id.

        Raises:
            KeyError: If the id is unknown.
        """
        with _WRITE_LOCK:
            self._records = self._read()
            if self.get(provider_id) is None:
                raise KeyError(provider_id)
            self._records = [r for r in self._records if r.id != provider_id]
            self._write()

    def open_api_key(self, record: AiProviderRecord) -> str:
        """Read one provider's key material out of the vault.

        Args:
            record: The provider.

        Returns:
            The decrypted key, empty when the provider names none or the
            referenced object is gone.

        Raises:
            ValueError: If the stored ciphertext does not decrypt.
        """
        if not record.secret_id:
            return ""
        # A reference whose object is gone reads as no key rather than
        # refusing the whole render: the other providers still deserve to be
        # served. A ciphertext that will not decrypt still raises.
        if self._vault.get(record.secret_id) is None:
            return ""
        return self._vault.open(record.secret_id).get("value", "")

    def _read(self) -> list[AiProviderRecord]:
        try:
            data = read_config(AI_PROVIDERS_PATH)
        except FileNotFoundError:
            return []
        return [
            AiProviderRecord.from_dict(entry) for entry in data.get("providers", [])
        ]

    def _write(self) -> None:
        write_config(
            AI_PROVIDERS_PATH,
            {"providers": [record.to_dict() for record in self._records]},
        )
