"""AI provider credentials, stored once and referenced everywhere.

Every machine a developer touches needs the same endpoint and token for each
AI service, and pasting them into dotfiles on every box is how they end up
scattered and stale. They live here instead: named entries in one gitignored
file, which Dev Setup reads when wiring a device's tools.

The key never travels back to the browser — listings carry only whether one is
stored.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neutrino_hub.modules.credentials.constants import (
    CREDENTIALS_AI_PROVIDERS_PATH,
    CREDENTIALS_AI_PROVIDER_KINDS,
    CREDENTIALS_ID_BYTES,
)
from neutrino_hub.utils.json_file import read_config, write_config


@dataclass
class AiProviderRecord:
    """One stored AI provider.

    Attributes:
        id: Stable identifier other features reference.
        name: Human-chosen label.
        kind: One of :data:`CREDENTIALS_AI_PROVIDER_KINDS`.
        base_url: API endpoint; empty means the service's default.
        api_key: The secret itself.
        is_enabled: Whether the AI gateway forwards to this provider.
        models: Alias mappings, each ``{"name": real, "alias": served}`` —
            what relays that insist on their own model names need.
        created_at: ISO timestamp of when it was added.
    """

    id: str
    name: str
    kind: str
    base_url: str = ""
    api_key: str = ""
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
            api_key=data.get("api_key", ""),
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
            "api_key": self.api_key,
            "is_enabled": self.is_enabled,
            "models": self.models,
            "created_at": self.created_at,
        }


class AiProviderRegistry:
    """Reads and edits the stored AI providers."""

    def __init__(self):
        self._records = self._read()

    def list_records(self) -> list[AiProviderRecord]:
        """Read every provider, newest first.

        Returns:
            The stored records.
        """
        return sorted(self._records, key=lambda r: r.created_at, reverse=True)

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
        api_key: str,
        models: list | None = None,
    ) -> AiProviderRecord:
        """Store a new provider.

        Args:
            name: Human-chosen label.
            kind: One of :data:`CREDENTIALS_AI_PROVIDER_KINDS`.
            base_url: API endpoint; empty means the service's default.
            api_key: The secret.

        Returns:
            The stored record.

        Raises:
            ValueError: If the kind is unknown or the name is empty.
        """
        if kind not in CREDENTIALS_AI_PROVIDER_KINDS:
            raise ValueError(f"unknown provider kind {kind!r}")
        if not name.strip():
            raise ValueError("the provider needs a name")
        record = AiProviderRecord(
            id=secrets.token_hex(CREDENTIALS_ID_BYTES),
            name=name.strip(),
            kind=kind,
            base_url=base_url.strip(),
            api_key=api_key,
            models=models or [],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
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
        api_key: str | None = None,
        is_enabled: bool | None = None,
        models: list | None = None,
    ) -> AiProviderRecord:
        """Change parts of a provider.

        A blank or absent ``api_key`` keeps the stored one — the browser never
        holds the current key, so an untouched field must not erase it.

        Args:
            provider_id: The record's id.
            name: New label, when given.
            kind: New kind, when given.
            base_url: New endpoint, when given.
            api_key: New secret, when given and non-empty.

        Returns:
            The record after the change.

        Raises:
            KeyError: If the id is unknown.
            ValueError: If a new kind is not one of the known kinds.
        """
        record = self.get(provider_id)
        if record is None:
            raise KeyError(provider_id)
        if kind is not None and kind not in CREDENTIALS_AI_PROVIDER_KINDS:
            raise ValueError(f"unknown provider kind {kind!r}")
        if name is not None and name.strip():
            record.name = name.strip()
        if kind is not None:
            record.kind = kind
        if base_url is not None:
            record.base_url = base_url.strip()
        if api_key:
            record.api_key = api_key
        if is_enabled is not None:
            record.is_enabled = is_enabled
        if models is not None:
            record.models = models
        self._write()
        return record

    def delete(self, provider_id: str) -> None:
        """Remove a provider.

        Args:
            provider_id: The record's id.

        Raises:
            KeyError: If the id is unknown.
        """
        if self.get(provider_id) is None:
            raise KeyError(provider_id)
        self._records = [r for r in self._records if r.id != provider_id]
        self._write()

    def _read(self) -> list[AiProviderRecord]:
        try:
            data = read_config(CREDENTIALS_AI_PROVIDERS_PATH)
        except FileNotFoundError:
            return []
        return [
            AiProviderRecord.from_dict(entry) for entry in data.get("providers", [])
        ]

    def _write(self) -> None:
        write_config(
            CREDENTIALS_AI_PROVIDERS_PATH,
            {"providers": [record.to_dict() for record in self._records]},
        )
