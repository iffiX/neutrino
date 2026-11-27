"""The panel's HTTP port in a file every local account reads.

``web/settings.json`` is root's alone. The ``Neutrino Hub`` entry runs as
the person who opened it and reads the port it probes from this file.
"""

from neutrino_hub.platforms.detect import hub_platform
from neutrino_hub.utils.json_file import write_generated
from neutrino_hub.web.constants import WEB_DEFAULT_LISTEN_PORT, WEB_PANEL_PORT_PATH


def write_panel_port(port: int) -> None:
    """Write the panel's HTTP port, readable by every local account.

    Args:
        port: The panel's HTTP port.

    Raises:
        OSError: When the file cannot be written or its permissions set.
    """
    write_generated(WEB_PANEL_PORT_PATH, f"{int(port)}\n", mode=0o644)
    hub_platform().make_readable_by_all(WEB_PANEL_PORT_PATH)


def read_panel_port() -> int:
    """The panel's HTTP port, from its file or the default.

    Returns:
        The port; the default when the file is missing, unreadable or holds
        no port.
    """
    try:
        return int(WEB_PANEL_PORT_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return WEB_DEFAULT_LISTEN_PORT
