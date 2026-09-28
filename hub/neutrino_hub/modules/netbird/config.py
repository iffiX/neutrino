"""The NetBird setup key this box joined with, kept for the clients it admits.

A reusable setup key admits any machine that presents it, so it is sealed
under the vault's data key and ``config/netbird/netbird.json`` carries no key
material. Parsing and storage only; joining is
:mod:`neutrino_hub.modules.netbird.ops`.
"""

from dataclasses import dataclass, field

from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.modules.netbird.constants import (
    NETBIRD_CONFIG_NAME,
    NETBIRD_SETUP_KEY_AAD,
)
from neutrino_hub.utils.json_file import read_config, write_config


def read_stored() -> "NetbirdConfig":
    """The kept setup key, as stored.

    Returns:
        The configuration, empty on a box that has kept none.

    Raises:
        ValueError: If the file is there and is not JSON.
    """
    try:
        return NetbirdConfig.from_dict(read_config(NETBIRD_CONFIG_NAME))
    except FileNotFoundError:
        return NetbirdConfig()


def write_stored(config: "NetbirdConfig") -> None:
    """Write the configuration to ``config/``.

    Args:
        config: What to store.
    """
    write_config(NETBIRD_CONFIG_NAME, config.to_dict())


@dataclass
class NetbirdConfig:
    """The setup key and the management plane it belongs to.

    Attributes:
        setup_key_sealed: The setup key, sealed under the vault's data key.
            Empty when none is kept.
        management_url: The management plane the key belongs to; empty for
            NetBird's own.
    """

    setup_key_sealed: dict = field(default_factory=dict)
    management_url: str = ""

    @property
    def has_setup_key(self) -> bool:
        """Whether a setup key is kept."""
        return bool(self.setup_key_sealed)

    def setup_key(self) -> str:
        """The setup key in the clear.

        Returns:
            The key, empty when none is kept.

        Raises:
            VaultLockedError: If there is no data key on this box.
            ValueError: If what is stored does not decrypt.
        """
        if not self.setup_key_sealed:
            return ""
        return unseal_bytes(self.setup_key_sealed, NETBIRD_SETUP_KEY_AAD).decode()

    def set_setup_key(self, setup_key: str, management_url: str) -> None:
        """Keep a setup key.

        Args:
            setup_key: The key.
            management_url: The management plane it belongs to.

        Raises:
            ValueError: If the key is empty.
            VaultLockedError: If there is no data key on this box.
        """
        if not setup_key:
            raise ValueError("a setup key cannot be empty")
        self.setup_key_sealed = seal_bytes(setup_key.encode(), NETBIRD_SETUP_KEY_AAD)
        self.management_url = management_url

    def clear_setup_key(self) -> None:
        """Forget the setup key."""
        self.setup_key_sealed = {}

    @classmethod
    def from_dict(cls, data: dict) -> "NetbirdConfig":
        """Parse the stored file.

        Args:
            data: The parsed ``config/netbird/netbird.json``.

        Returns:
            The configuration, with anything unreadable left at its default.
        """
        sealed = data.get("setup_key_sealed")
        return cls(
            setup_key_sealed=sealed if isinstance(sealed, dict) else {},
            management_url=str(data.get("management_url", "")),
        )

    def to_dict(self) -> dict:
        """Serialize the whole configuration.

        Returns:
            What belongs in ``config/netbird/netbird.json``.
        """
        return {
            "setup_key_sealed": self.setup_key_sealed,
            "management_url": self.management_url,
        }
