"""Opening the hub's own ports in the system firewall on macOS and Windows.

Each routing pass there renders what the firewall must allow from the
panel's settings, the AI gateway's port, the proxy's SOCKS ports and the
enabled overlays, and
hands it to the system's applier; ``nhub reset all`` takes it away again.
Linux has its own nftables ruleset and never comes here.

Not pure: drives the appliers.
"""

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_BINARY_PATH,
    CLIPROXYAPI_DEFAULT_PORT,
)
from neutrino_hub.modules.easytier.constants import EASYTIER_CORE_PATH
from neutrino_hub.modules.firewall.constants import (
    FIREWALL_GATEWAY_SETTINGS_FILE,
    FIREWALL_PANEL_SETTINGS_FILE,
    FIREWALL_SETTING_AGENT_PORT,
    FIREWALL_SETTING_GATEWAY_PORT,
    FIREWALL_SETTING_LISTEN_PORT,
)
from neutrino_hub.modules.firewall.darwin_applier import FirewallDarwinApplier
from neutrino_hub.modules.firewall.renderer import render_port_rules, render_programs
from neutrino_hub.modules.firewall.windows_applier import FirewallWindowsApplier
from neutrino_hub.modules.netbird.constants import NETBIRD_BINARY_PATH
from neutrino_hub.modules.overlay.config import enabled_providers
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_EASYTIER,
    OVERLAY_ENGINES,
    OVERLAY_NETBIRD,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.xray.constants import XRAY_BINARY
from neutrino_hub.platforms.constants import PLATFORM_OS_WINDOWS
from neutrino_hub.platforms.detect import hub_os, hub_platform
from neutrino_hub.utils.json_file import read_config
from neutrino_hub.web.constants import (
    WEB_DEFAULT_AGENT_LISTEN_PORT,
    WEB_DEFAULT_HTTPS_LISTEN_PORT,
    WEB_DEFAULT_LISTEN_PORT,
    WEB_SETTING_HTTPS_PORT,
)


def converge_firewall(network: RouterNetworkConfig, *, routing: dict) -> list:
    """Make the system firewall allow what the hub serves now.

    Args:
        network: The parsed router configuration, for the enabled overlays.
        routing: Parsed ``config/xray/routing.json``, for the SOCKS ports.

    Returns:
        One line per rule or program changed; empty when nothing changed.

    Raises:
        OSError: When the firewall cannot be read or changed on Windows.
        subprocess.CalledProcessError: When ``socketfilterfw`` refuses.
        ValueError: When the panel's or the gateway's settings hold a port
            that is no number.
    """
    overlays = enabled_providers(network)
    if hub_os() != PLATFORM_OS_WINDOWS:
        return FirewallDarwinApplier().apply(_programs(overlays))
    settings = _settings(FIREWALL_PANEL_SETTINGS_FILE)
    gateway = _settings(FIREWALL_GATEWAY_SETTINGS_FILE)
    rules = render_port_rules(
        panel_http_port=int(
            settings.get(FIREWALL_SETTING_LISTEN_PORT, WEB_DEFAULT_LISTEN_PORT)
        ),
        panel_https_port=int(
            settings.get(WEB_SETTING_HTTPS_PORT, WEB_DEFAULT_HTTPS_LISTEN_PORT)
        ),
        agent_port=int(
            settings.get(FIREWALL_SETTING_AGENT_PORT, WEB_DEFAULT_AGENT_LISTEN_PORT)
        ),
        ai_gateway_port=int(
            gateway.get(FIREWALL_SETTING_GATEWAY_PORT, CLIPROXYAPI_DEFAULT_PORT)
        ),
        socks_ports=[
            entry["port"]
            for entry in routing.get("socks_ports", [])
            if isinstance(entry, dict) and entry.get("port")
        ],
        overlays=overlays,
    )
    return FirewallWindowsApplier().apply(rules)


def hand_back_firewall() -> list:
    """Take away everything the hub opened in the system firewall.

    Returns:
        One line per rule or program removed.

    Raises:
        OSError: When the firewall cannot be read or changed on Windows.
        subprocess.CalledProcessError: When ``socketfilterfw`` refuses.
    """
    if hub_os() == PLATFORM_OS_WINDOWS:
        return FirewallWindowsApplier().remove()
    return FirewallDarwinApplier().remove(_programs(list(OVERLAY_ENGINES)))


def _programs(overlays: list) -> list:
    """The programs macOS allows for these overlays."""
    return render_programs(
        hub_program=hub_platform().hub_command()[0],
        xray_program=XRAY_BINARY,
        ai_gateway_program=str(CLIPROXYAPI_BINARY_PATH),
        overlay_programs={
            OVERLAY_NETBIRD: str(NETBIRD_BINARY_PATH),
            OVERLAY_EASYTIER: str(EASYTIER_CORE_PATH),
        },
        overlays=overlays,
    )


def _settings(name: str) -> dict:
    """One stored settings file; empty before setup wrote it."""
    try:
        return read_config(name)
    except FileNotFoundError:
        return {}
