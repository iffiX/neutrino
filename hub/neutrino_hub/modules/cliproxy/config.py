"""The AI gateway's own settings: its port and the keys devices use.

Deliberately thin, like the git server's. The upstream providers live in the
credentials store — this holds only what CLIProxyAPI needs beyond them: where
to listen, and the client keys handed to devices.

Pure: parsing and validation only. Rendering is
:mod:`neutrino_hub.modules.cliproxy.renderer`; making it true on the box is
:mod:`neutrino_hub.modules.cliproxy.ops`.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neutrino_hub.modules.cliproxy.constants import (
    CLIPROXY_CLIENT_KEY_BYTES,
    CLIPROXY_DEFAULT_PORT,
    CLIPROXY_ID_BYTES,
)


@dataclass
class CliproxyClientKey:
    """One key a device presents to the AI gateway.

    Attributes:
        id: Stable identifier the panel manages it by.
        name: What the key is for — usually a device or a person.
        key: The secret itself.
        created_at: ISO timestamp of when it was minted.
    """

    id: str
    name: str
    key: str
    created_at: str = ""

    @classmethod
    def minted(cls, name: str) -> "CliproxyClientKey":
        """Mint a fresh key under a name.

        Args:
            name: What the key is for.

        Returns:
            The new key.
        """
        return cls(
            id=secrets.token_hex(CLIPROXY_ID_BYTES),
            name=name.strip() or "unnamed",
            key=secrets.token_urlsafe(CLIPROXY_CLIENT_KEY_BYTES),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "CliproxyClientKey":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            key=data.get("key", ""),
            created_at=data.get("created_at", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "key": self.key,
            "created_at": self.created_at,
        }


@dataclass
class CliproxyConfig:
    """Everything ``config/cliproxy/cliproxy.json`` holds.

    Attributes:
        listen_port: Port the AI gateway answers on, LAN- and overlay-wide.
        client_keys: The keys devices authenticate with.
    """

    listen_port: int = CLIPROXY_DEFAULT_PORT
    client_keys: list[CliproxyClientKey] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CliproxyConfig":
        return cls(
            listen_port=int(data.get("listen_port", CLIPROXY_DEFAULT_PORT)),
            client_keys=[
                CliproxyClientKey.from_dict(entry)
                for entry in data.get("client_keys", [])
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
