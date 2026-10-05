"""Direct's settings, as ``config/overlay/direct.json`` stores them.

Direct opens the agent port alone on every enabled interface and adds those
interfaces' addresses, and the public address the person states for the hub,
to ``urls``. Nothing here touches the system: the firewall renderers read
:func:`direct_agent_port`, and the converge step makes it true.
"""

import ipaddress
import re
from dataclasses import asdict, dataclass

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_PANEL_SETTINGS_FILE,
    FIREWALL_SETTING_AGENT_PORT,
)
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_DIRECT_CONFIG_NAME,
    OVERLAY_DIRECT_DEFAULT_PUBLIC_PORT,
    OVERLAY_DIRECT_HOST_MAX,
)
from neutrino_hub.utils.json_file import read_config, write_config
from neutrino_hub.web.constants import WEB_DEFAULT_AGENT_LISTEN_PORT

# One label of a host name: letters, digits and hyphens, no hyphen at either
# end, at most 63 characters.
DIRECT_HOST_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


@dataclass
class OverlayDirectConfig:
    """The agent port opened on every enabled interface.

    Attributes:
        is_enabled: Whether Direct is on.
        public_host: The host name or address the person states for the hub;
            empty for none.
        public_port: The port at that address.
    """

    is_enabled: bool = False
    public_host: str = ""
    public_port: int = OVERLAY_DIRECT_DEFAULT_PUBLIC_PORT

    @classmethod
    def from_dict(cls, data: dict) -> "OverlayDirectConfig":
        """Read the stored file's object.

        Args:
            data: The parsed file; a missing key keeps its default.

        Returns:
            The settings.

        Raises:
            ValueError: If the port is not a number.
        """
        return cls(
            is_enabled=bool(data.get("is_enabled", False)),
            public_host=str(data.get("public_host", "") or ""),
            public_port=int(
                data.get("public_port", OVERLAY_DIRECT_DEFAULT_PUBLIC_PORT)
            ),
        )

    def to_dict(self) -> dict:
        """The object the file stores.

        Returns:
            Every field by its key.
        """
        return asdict(self)


def is_public_host_refused(host: str) -> bool:
    """Whether a stated public host is neither an address nor a host name.

    Args:
        host: The value given; empty states none and is not refused.

    Returns:
        True for a value that is neither an IP address nor a host name of
        letters, digits, hyphens and dots.
    """
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return False
    if len(host) > OVERLAY_DIRECT_HOST_MAX:
        return True
    labels = host.removesuffix(".").split(".")
    return not all(DIRECT_HOST_LABEL.match(label) for label in labels)


def read_direct() -> OverlayDirectConfig:
    """The stored Direct settings.

    Returns:
        The settings; a box with no file has Direct off and no public
        address.

    Raises:
        ValueError: If the file is there and is not JSON, or its port is not
            a number.
    """
    try:
        return OverlayDirectConfig.from_dict(read_config(OVERLAY_DIRECT_CONFIG_NAME))
    except FileNotFoundError:
        return OverlayDirectConfig()


def write_direct(config: OverlayDirectConfig) -> None:
    """Store the Direct settings.

    Args:
        config: The settings to keep.

    Raises:
        OSError: If the file cannot be written.
    """
    write_config(OVERLAY_DIRECT_CONFIG_NAME, config.to_dict())


def direct_agent_port() -> "int | None":
    """The port Direct opens, while it is on.

    Returns:
        The agent channel's port from the panel's settings while Direct is on;
        None while it is off, its file does not read, or the box is not set up.
    """
    try:
        if not read_direct().is_enabled:
            return None
        settings = read_config(FIREWALL_PANEL_SETTINGS_FILE)
        return int(
            settings.get(FIREWALL_SETTING_AGENT_PORT, WEB_DEFAULT_AGENT_LISTEN_PORT)
        )
    except (FileNotFoundError, ValueError):
        return None
