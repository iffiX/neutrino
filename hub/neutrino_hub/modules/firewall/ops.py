"""Opening the hub's own ports in the system firewall on macOS and Windows.

Each routing pass there renders what the firewall must allow from the
panel's settings, the AI gateway's port, the proxy's SOCKS ports, the
enabled overlays and the exposure of each interface and overlay, and hands
it to the system's applier; ``nhub reset all`` takes it away again. Linux
has its own nftables ruleset and never comes here.

Not pure: drives the appliers.
"""

import json

from neutrino_hub import edition
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_BINARY_PATH,
    CLIPROXYAPI_DEFAULT_PORT,
)
from neutrino_hub.modules.easytier.constants import EASYTIER_CORE_PATH
from neutrino_hub.modules.firewall.constants import (
    FIREWALL_GATEWAY_SETTINGS_FILE,
    FIREWALL_INTERFACES_PATH,
    FIREWALL_PANEL_SETTINGS_FILE,
    FIREWALL_SETTING_AGENT_PORT,
    FIREWALL_SETTING_GATEWAY_PORT,
    FIREWALL_SETTING_LISTEN_PORT,
)
from neutrino_hub.modules.firewall.darwin_applier import FirewallDarwinApplier
from neutrino_hub.modules.firewall.renderer import (
    render_pf_anchor,
    render_port_rules,
    render_programs,
)
from neutrino_hub.modules.firewall.windows_applier import FirewallWindowsApplier
from neutrino_hub.modules.overlay.config import enabled_providers
from neutrino_hub.modules.overlay.direct_config import direct_agent_port
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_EASYTIER,
    OVERLAY_ENGINES,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.platforms.constants import PLATFORM_OS_WINDOWS
from neutrino_hub.platforms.detect import hub_os, hub_platform
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.web.constants import (
    WEB_DEFAULT_AGENT_LISTEN_PORT,
    WEB_DEFAULT_HTTPS_LISTEN_PORT,
    WEB_DEFAULT_LISTEN_PORT,
    WEB_SETTING_HTTPS_PORT,
)


def converge_firewall(network: RouterNetworkConfig, *, routing: dict) -> tuple:
    """Make the system firewall answer what the hub serves where it is exposed.

    Args:
        network: The parsed router configuration, carrying the overlays'
            devices found at run time.
        routing: The proxy's routing options, for the SOCKS ports; empty
            in a tree without the proxy.

    Returns:
        The notes, one line per rule, program or anchor changed, empty when
        nothing changed; and the refusals, one ``{rule, detail}`` per rule
        Windows refused, always empty on macOS.

    Raises:
        OSError: When the firewall cannot be read or changed on Windows, or
            the anchor's rules cannot be written on macOS.
        subprocess.CalledProcessError: When ``socketfilterfw`` or ``pfctl``
            refuses.
        ValueError: When the panel's or the gateway's settings hold a port
            that is no number.
    """
    overlays = enabled_providers(network)
    present = list(device_addresses())
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
        exposed_interfaces=exposed_devices(network, present),
        exposed_overlays=[
            overlay.provider
            for overlay in network.enabled_overlays
            if overlay.is_exposed
        ],
        direct_interfaces=(
            enabled_devices(network, present) if direct_agent_port() is not None else []
        ),
    )
    if hub_os() == PLATFORM_OS_WINDOWS:
        notes, refused = FirewallWindowsApplier().apply(rules)
    else:
        applier = FirewallDarwinApplier()
        notes = applier.apply(_programs(overlays))
        notes += applier.load_anchor(render_pf_anchor(rules, interfaces=present))
        refused = []
    write_generated(FIREWALL_INTERFACES_PATH, json.dumps(sorted(present)))
    return notes, refused


def is_interface_set_moved() -> bool:
    """Whether the interfaces this box has differ from the last pass's.

    Returns:
        True when an interface came, went or was renamed since the firewall
        was last written, and when it never was.
    """
    try:
        scoped = json.loads(FIREWALL_INTERFACES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return scoped != sorted(device_addresses())


def reload_firewall() -> None:
    """Load the kept pf anchor again on macOS, as the service does at start.

    Windows keeps its rules across a restart, so nothing runs there.

    Raises:
        OSError: When ``pfctl`` cannot run.
        subprocess.CalledProcessError: When ``pfctl`` refuses.
    """
    if hub_os() == PLATFORM_OS_WINDOWS:
        return
    FirewallDarwinApplier().reload_anchor()


def exposed_devices(network: RouterNetworkConfig, present: list) -> list:
    """The devices the hub answers on, of the ones this box has now.

    Args:
        network: The parsed router configuration, carrying the overlays'
            devices found at run time.
        present: The devices this box has, as the system names them.

    Returns:
        Each present interface that is exposed, an interface the
        configuration does not name counting as exposed, then each present
        device of an exposed running overlay.
    """
    overlay_devices = set(network.overlay_device_names)
    interfaces = [
        name
        for name in present
        if name not in overlay_devices and network.interface_or_new(name).is_exposed
    ]
    overlays = [
        name for name in network.exposed_overlay_device_names if name in present
    ]
    return interfaces + overlays


def enabled_devices(network: RouterNetworkConfig, present: list) -> list:
    """The enabled interfaces of the ones this box has now, overlays aside.

    Args:
        network: The parsed router configuration, carrying the overlays'
            devices found at run time.
        present: The devices this box has, as the system names them.

    Returns:
        Each present interface that is not an overlay's device and that the
        configuration does not turn off.
    """
    overlay_devices = set(network.overlay_device_names)
    return [
        name
        for name in present
        if name not in overlay_devices and network.is_interface_enabled(name)
    ]


def hand_back_firewall() -> list:
    """Take away everything the hub opened in the system firewall.

    Returns:
        One line per rule, program or anchor removed.

    Raises:
        OSError: When the firewall cannot be read or changed on Windows.
        subprocess.CalledProcessError: When ``socketfilterfw`` refuses.
    """
    if hub_os() == PLATFORM_OS_WINDOWS:
        return FirewallWindowsApplier().remove()
    applier = FirewallDarwinApplier()
    return applier.remove(_programs(list(OVERLAY_ENGINES))) + applier.flush_anchor()


def _programs(overlays: list) -> list:
    """The programs macOS allows for these overlays."""
    return render_programs(
        hub_program=hub_platform().hub_command()[0],
        xray_program=edition.hook("proxy_program") or "",
        ai_gateway_program=str(CLIPROXYAPI_BINARY_PATH),
        overlay_programs={
            **dict(edition.hooks("overlay_programs")),
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
