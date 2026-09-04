"""The AI gateway's own settings: its port and the keys devices use.

Deliberately thin, like the git server's. The upstream providers live in the
credentials store — this holds only what CLIProxyAPI needs beyond them: where
to listen, and the client keys handed to devices.

Parsing and validation, plus the seal a client key is stored under: the
material never sits in the file, so a backup of ``config/`` carries none.
Rendering is :mod:`neutrino_hub.modules.cliproxyapi.renderer`; making it true
on the box is :mod:`neutrino_hub.modules.cliproxyapi.ops`.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_CLIENT_KEY_AAD,
    CLIPROXYAPI_CLIENT_KEY_BYTES,
    CLIPROXYAPI_DEFAULT_PORT,
    CLIPROXYAPI_ID_BYTES,
)
from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes


def _has_seal(entry) -> bool:
    """Whether a stored client key record carries key material to open.

    Args:
        entry: One entry of the stored ``client_keys`` list.

    Returns:
        True when the record holds a sealed object.
    """
    if not isinstance(entry, dict):
        return False
    sealed = entry.get("key_sealed")
    return isinstance(sealed, dict) and bool(sealed.get("nonce") and sealed.get("data"))


@dataclass
class CliproxyApiClientKey:
    """One key a device presents to the AI gateway.

    Attributes:
        id: Stable identifier the panel manages it by.
        name: What the key is for — usually a device or a person.
        key_sealed: The secret, sealed under the vault's data key.
        created_at: ISO timestamp of when it was generated.
    """

    id: str
    name: str
    key_sealed: dict
    created_at: str = ""

    @classmethod
    def generated(cls, name: str) -> "CliproxyApiClientKey":
        """Generate a fresh key under a name, sealed and ready to store.

        Args:
            name: What the key is for.

        Returns:
            The new key.

        Raises:
            VaultLockedError: If there is no data key to seal it under.
        """
        key = secrets.token_urlsafe(CLIPROXYAPI_CLIENT_KEY_BYTES)
        return cls(
            id=secrets.token_hex(CLIPROXYAPI_ID_BYTES),
            name=name.strip() or "unnamed",
            key_sealed=seal_bytes(key.encode(), CLIPROXYAPI_CLIENT_KEY_AAD),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "CliproxyApiClientKey":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            key_sealed=data.get("key_sealed", {}),
            created_at=data.get("created_at", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "key_sealed": self.key_sealed,
            "created_at": self.created_at,
        }

    def open_key(self) -> str:
        """Unseal the key material.

        Returns:
            The secret the gateway authenticates callers by.

        Raises:
            VaultLockedError: If there is no data key on this box.
            VaultError: If the seal is malformed or does not decrypt.
        """
        return unseal_bytes(self.key_sealed, CLIPROXYAPI_CLIENT_KEY_AAD).decode()


@dataclass
class CliproxyApiConfig:
    """Everything ``config/cliproxyapi/cliproxyapi.json`` holds.

    Attributes:
        listen_port: Port the AI gateway answers on, LAN- and overlay-wide.
        client_keys: The keys devices authenticate with. A stored record
            without a seal is dropped on load, and whatever held it is issued
            a fresh key.
    """

    listen_port: int = CLIPROXYAPI_DEFAULT_PORT
    client_keys: list[CliproxyApiClientKey] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CliproxyApiConfig":
        return cls(
            listen_port=int(data.get("listen_port", CLIPROXYAPI_DEFAULT_PORT)),
            client_keys=[
                CliproxyApiClientKey.from_dict(entry)
                for entry in data.get("client_keys", [])
                if _has_seal(entry)
            ],
        )

    def to_dict(self) -> dict:
        return {
            "listen_port": self.listen_port,
            "client_keys": [key.to_dict() for key in self.client_keys],
        }

    def validate(self) -> None:
        """Check the configuration holds together.

        Raises:
            ValueError: Naming the first problem found.
        """
        if not 1 <= self.listen_port <= 65535:
            raise ValueError(f"listen_port {self.listen_port} is not a port")
        if self.listen_port in (53, 80, 1080, 3000):
            raise ValueError(f"port {self.listen_port} already belongs to the gateway")
