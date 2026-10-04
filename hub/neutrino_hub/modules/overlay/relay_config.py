"""The relay's settings, as ``config/overlay/relay.json`` stores them.

The host and the account reach a command line that runs as root, so a value
that could be read as an option, or that would split into two words, is
refused before it is stored.
"""

from dataclasses import asdict, dataclass

from neutrino_hub.modules.overlay.constants import (
    OVERLAY_RELAY_CONFIG_NAME,
    OVERLAY_RELAY_DEFAULT_PUBLIC_PORT,
    OVERLAY_RELAY_DEFAULT_SSH_PORT,
)
from neutrino_hub.utils.json_file import read_config, write_config


@dataclass
class OverlayRelayConfig:
    """The reverse forward to a server the person owns.

    Attributes:
        is_enabled: Whether the relay runs.
        host: The server's name or address.
        ssh_port: Its sshd's port.
        account: The account the hub logs in as.
        key_id: The id of an SSH key on the Credentials page.
        public_port: The port the server listens on for peers.
    """

    is_enabled: bool = False
    host: str = ""
    ssh_port: int = OVERLAY_RELAY_DEFAULT_SSH_PORT
    account: str = ""
    key_id: str = ""
    public_port: int = OVERLAY_RELAY_DEFAULT_PUBLIC_PORT

    @classmethod
    def from_dict(cls, data: dict) -> "OverlayRelayConfig":
        """Read the stored file's object.

        Args:
            data: The parsed file; a missing key keeps its default.

        Returns:
            The settings.

        Raises:
            ValueError: If a port is not a number.
        """
        return cls(
            is_enabled=bool(data.get("is_enabled", False)),
            host=str(data.get("host", "") or ""),
            ssh_port=int(data.get("ssh_port", OVERLAY_RELAY_DEFAULT_SSH_PORT)),
            account=str(data.get("account", "") or ""),
            key_id=str(data.get("key_id", "") or ""),
            public_port=int(data.get("public_port", OVERLAY_RELAY_DEFAULT_PUBLIC_PORT)),
        )

    def to_dict(self) -> dict:
        """The object the file stores.

        Returns:
            Every field by its key.
        """
        return asdict(self)

    @property
    def has_settings(self) -> bool:
        """Whether the host, the account and the key are all named."""
        return bool(self.host and self.account and self.key_id)

    @property
    def url(self) -> str:
        """The address the relay adds to ``urls``; empty without a host.

        An IPv6 host is written in brackets.
        """
        if not self.host:
            return ""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"https://{host}:{self.public_port}"


def is_host_refused(host: str) -> bool:
    """Whether a host may not reach the start line.

    Args:
        host: The value given.

    Returns:
        True for an empty value, one holding whitespace, or one starting
        with ``-``.
    """
    return not host or any(char.isspace() for char in host) or host.startswith("-")


def is_account_refused(account: str) -> bool:
    """Whether an account may not reach the start line.

    Args:
        account: The value given.

    Returns:
        True for what :func:`is_host_refused` refuses, and for a value holding
        ``@``.
    """
    return is_host_refused(account) or "@" in account


def read_relay() -> OverlayRelayConfig:
    """The stored relay.

    Returns:
        The settings; a box with no file has a relay that is off and not
        configured.

    Raises:
        ValueError: If the file is there and is not JSON, or a port in it is
            not a number.
    """
    try:
        return OverlayRelayConfig.from_dict(read_config(OVERLAY_RELAY_CONFIG_NAME))
    except FileNotFoundError:
        return OverlayRelayConfig()


def write_relay(config: OverlayRelayConfig) -> None:
    """Store the relay.

    Args:
        config: The settings to keep.

    Raises:
        OSError: If the file cannot be written.
    """
    write_config(OVERLAY_RELAY_CONFIG_NAME, config.to_dict())
