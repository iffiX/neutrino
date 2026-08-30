"""The git server's configuration: how it listens and who may sign up.

Deliberately thin. Gitea carries a complete admin UI of its own, so this
holds only the seams the gateway owns — the port, the address clients are
told to use, and whether strangers can register — and everything about
repositories stays in Gitea where it already lives.

Pure: parsing and validation only. Rendering is :mod:`neutrino_hub.modules.gitea.renderer`;
making it true on the box is :mod:`neutrino_hub.modules.gitea.ops`.
"""

from dataclasses import dataclass

from neutrino_hub.modules.gitea.constants import GITEA_DEFAULT_PORT


@dataclass
class GiteaConfig:
    """Everything ``config/gitea/gitea.json`` holds.

    Attributes:
        listen_port: Port the web UI and clones-over-http answer on.
        root_url: Base URL Gitea writes into clone addresses and links. Empty
            derives ``http://<primary LAN address>:<port>/``, which is right
            until an overlay gives the box a second name worth preferring.
        is_registration_enabled: Whether the sign-up form works. Off for a
            personal box: accounts are made by the administrator.
    """

    listen_port: int = GITEA_DEFAULT_PORT
    root_url: str = ""
    is_registration_enabled: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "GiteaConfig":
        return cls(
            listen_port=int(data.get("listen_port", GITEA_DEFAULT_PORT)),
            root_url=data.get("root_url", ""),
            is_registration_enabled=bool(data.get("is_registration_enabled", False)),
        )

    def to_dict(self) -> dict:
        return {
            "listen_port": self.listen_port,
            "root_url": self.root_url,
            "is_registration_enabled": self.is_registration_enabled,
        }

    def validate(self) -> None:
        """Check the configuration holds together.

        Raises:
            ValueError: Naming the first problem found.
        """
        if not 1 <= self.listen_port <= 65535:
            raise ValueError(f"listen_port {self.listen_port} is not a port")
        if self.listen_port in (53, 80, 1080):
            raise ValueError(
                f"port {self.listen_port} already belongs to the gateway "
                f"(DNS, the panel, or the SOCKS listener)"
            )
        if self.root_url and not self.root_url.startswith(("http://", "https://")):
            raise ValueError(
                f"root_url {self.root_url!r} must start with http:// or https://, "
                f"or be empty to derive it from the LAN address"
            )
        if "\n" in self.root_url:
            raise ValueError("root_url cannot span lines")
