"""The git server's configuration: how it listens and who may sign up.

Deliberately thin. Gitea carries a complete admin UI of its own, so this
holds only the seams the hub owns: the port, the address clients are told
to use, whether strangers can register, and the machine secrets the hub
generated for this device.

Pure: parsing and validation only.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from neutrino_agent.modules.base import ModuleApplyError
from neutrino_agent.modules.gitea.constants import (
    GITEA_DEFAULT_PORT,
    GITEA_SECRET_NAMES,
)

# Ports the hub's own services listen on, which a git server on the hub box
# would fight over.
RESERVED_PORTS = (53, 80, 1080)

# What accounts may be called: the subset of Gitea's own rules that also
# survives a command line.
ADMIN_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,38}\Z")


@dataclass
class GiteaConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        listen_port: Port the web UI and clones-over-http answer on.
        root_url: Base URL Gitea writes into clone addresses and links.
            Empty derives ``http://<address>:<port>/``.
        is_registration_enabled: Whether the sign-up form works.
        address: This machine's address, as the hub composed it, for the
            derived root URL.
        secrets: The machine secrets by name.
    """

    listen_port: int = GITEA_DEFAULT_PORT
    root_url: str = ""
    is_registration_enabled: bool = False
    address: str = ""
    secrets: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "GiteaConfig":
        try:
            listen_port = int(data.get("listen_port", GITEA_DEFAULT_PORT))
        except (TypeError, ValueError):
            listen_port = 0
        secrets = data.get("secrets")
        return cls(
            listen_port=listen_port,
            root_url=str(data.get("root_url", "") or ""),
            is_registration_enabled=bool(data.get("is_registration_enabled", False)),
            address=str(data.get("address", "") or ""),
            secrets=dict(secrets) if isinstance(secrets, dict) else {},
        )

    def to_dict(self) -> dict:
        return {
            "listen_port": self.listen_port,
            "root_url": self.root_url,
            "is_registration_enabled": self.is_registration_enabled,
            "address": self.address,
            "secrets": dict(self.secrets),
        }

    @property
    def derived_root_url(self) -> str:
        """The root URL clients are told, from the override or the address."""
        return self.root_url or f"http://{self.address}:{self.listen_port}/"

    def validate(self) -> None:
        """Check the configuration holds together.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        if not 1 <= self.listen_port <= 65535:
            raise ModuleApplyError("port_invalid", {"port": self.listen_port})
        if self.listen_port in RESERVED_PORTS:
            raise ModuleApplyError("port_reserved", {"port": self.listen_port})
        if self.root_url and not self.root_url.startswith(("http://", "https://")):
            raise ModuleApplyError("root_url_invalid", {"root_url": self.root_url})
        if "\n" in self.root_url:
            raise ModuleApplyError("root_url_invalid", {"root_url": self.root_url})
        missing = [name for name in GITEA_SECRET_NAMES if not self.secrets.get(name)]
        if missing:
            raise ModuleApplyError("secrets_missing", {"names": missing})
