"""One frp vendor's settings, as ``config/overlay/<vendor>.json`` stores them.

The credential, SakuraFrp's access key or OpenFrp's ``Authorization``, is
sealed under the vault's data key and never sits in the file in the clear.

Parsing only. Running frpc is :mod:`neutrino_hub.modules.frp.ops`.
"""

from dataclasses import dataclass, field

from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.modules.frp.constants import (
    FRP_CONFIG_NAMES,
    FRP_CREDENTIAL_AAD,
    FRP_VENDORS,
)
from neutrino_hub.utils.json_file import read_config, write_config


@dataclass
class FrpConfig:
    """One vendor's way in.

    Attributes:
        vendor: ``sakurafrp`` or ``openfrp``; not stored, the file names it.
        is_enabled: Whether the way in is on.
        credential_sealed: The access key or the ``Authorization``, sealed;
            empty for none.
        tunnel_id: The vendor's id of the picked tunnel, empty for none.
        node_name: The picked tunnel's node name, as the apply read it.
        local_port: The picked tunnel's local port at the vendor.
        public_host: The host of the tunnel's public address.
        public_port: The port of the tunnel's public address.
    """

    vendor: str
    is_enabled: bool = False
    credential_sealed: dict = field(default_factory=dict)
    tunnel_id: str = ""
    node_name: str = ""
    local_port: int = 0
    public_host: str = ""
    public_port: int = 0

    @classmethod
    def from_dict(cls, vendor: str, data: dict) -> "FrpConfig":
        """Read the stored file's object.

        Args:
            vendor: The vendor the file is for.
            data: The parsed file; a missing key keeps its default.

        Returns:
            The settings.

        Raises:
            ValueError: If a port is not a number.
        """
        sealed = data.get("credential")
        return cls(
            vendor=vendor,
            is_enabled=bool(data.get("is_enabled", False)),
            credential_sealed=sealed if isinstance(sealed, dict) else {},
            tunnel_id=str(data.get("tunnel_id", "") or ""),
            node_name=str(data.get("node_name", "") or ""),
            local_port=int(data.get("local_port", 0) or 0),
            public_host=str(data.get("public_host", "") or ""),
            public_port=int(data.get("public_port", 0) or 0),
        )

    def to_dict(self) -> dict:
        """The object the file stores.

        Returns:
            Every key network.md names.
        """
        return {
            "is_enabled": self.is_enabled,
            "credential": self.credential_sealed,
            "tunnel_id": self.tunnel_id,
            "node_name": self.node_name,
            "local_port": self.local_port,
            "public_host": self.public_host,
            "public_port": self.public_port,
        }

    @property
    def is_signed_in(self) -> bool:
        """Whether a credential is stored."""
        return bool(self.credential_sealed)

    @property
    def has_tunnel(self) -> bool:
        """Whether a credential is stored and a tunnel is picked."""
        return self.is_signed_in and bool(self.tunnel_id)

    @property
    def url(self) -> str:
        """The picked tunnel's public address; empty while none is picked.

        An IPv6 host is written in brackets.
        """
        if not self.has_tunnel or not self.public_host:
            return ""
        host = f"[{self.public_host}]" if ":" in self.public_host else self.public_host
        return f"https://{host}:{self.public_port}"

    def credential(self) -> str:
        """The credential in the clear.

        Returns:
            The access key or the ``Authorization``; empty when none is
            stored.

        Raises:
            VaultLockedError: If the vault is locked.
            ValueError: If the sealed value does not open.
        """
        if not self.credential_sealed:
            return ""
        return unseal_bytes(
            self.credential_sealed, FRP_CREDENTIAL_AAD[self.vendor]
        ).decode()

    def set_credential(self, credential: str) -> None:
        """Seal a credential in place of the stored one.

        Args:
            credential: The access key or the ``Authorization``.

        Raises:
            VaultLockedError: If the vault is locked.
        """
        self.credential_sealed = seal_bytes(
            credential.encode(), FRP_CREDENTIAL_AAD[self.vendor]
        )

    def forget(self) -> None:
        """Clear every key but ``is_enabled``."""
        self.credential_sealed = {}
        self.clear_tunnel()

    def clear_tunnel(self) -> None:
        """Forget the picked tunnel."""
        self.tunnel_id = ""
        self.node_name = ""
        self.local_port = 0
        self.public_host = ""
        self.public_port = 0


def read_frp(vendor: str) -> FrpConfig:
    """One vendor's stored settings.

    Args:
        vendor: ``sakurafrp`` or ``openfrp``.

    Returns:
        The settings; a box with no file, or a file that does not read, has
        the way in off and signed out.
    """
    try:
        return FrpConfig.from_dict(vendor, read_config(FRP_CONFIG_NAMES[vendor]))
    except (FileNotFoundError, ValueError):
        return FrpConfig(vendor=vendor)


def write_frp(config: FrpConfig) -> None:
    """Store one vendor's settings.

    Args:
        config: The settings to keep.

    Raises:
        OSError: If the file cannot be written.
    """
    write_config(FRP_CONFIG_NAMES[config.vendor], config.to_dict())


def frp_switches() -> dict:
    """Whether each vendor's way in is on.

    Returns:
        Vendor to its stored ``is_enabled``.
    """
    return {vendor: read_frp(vendor).is_enabled for vendor in FRP_VENDORS}
