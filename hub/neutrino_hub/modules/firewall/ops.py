"""The hub's ports in the system's firewall, on every system.

Each routing pass works out what the firewall answers from the panel's
settings, the proxy's SOCKS ports, the enabled overlays, each segment's
switch, Direct and the addresses the box holds now. On macOS and Windows it
hands the answer to the system's applier; on Linux the nftables ruleset
renders it, and where firewalld runs the pass writes it into firewalld too.
``nhub reset`` takes it away again.

Not pure: drives the appliers.
"""

import json
import subprocess

from neutrino_hub import edition
from neutrino_hub.modules.easytier.constants import EASYTIER_CORE_PATH
from neutrino_hub.modules.firewall.constants import (
    FIREWALL_FIREWALLD_RECORD_PATH,
    FIREWALL_NETWORKS_PATH,
    FIREWALL_PANEL_SETTINGS_FILE,
    FIREWALL_SETTING_AGENT_PORT,
    FIREWALL_SETTING_LISTEN_PORT,
)
from neutrino_hub.modules.firewall.darwin_applier import FirewallDarwinApplier
from neutrino_hub.modules.firewall.firewalld_applier import (
    FirewallFirewalldApplier,
    keyed,
)
from neutrino_hub.modules.firewall.renderer import (
    FirewallExposure,
    render_exposure,
    render_firewalld_rules,
    render_firewalld_setup_rules,
    render_pf_anchor,
    render_port_rules,
    render_programs,
    render_setup_port_rule,
)
from neutrino_hub.modules.firewall.windows_applier import FirewallWindowsApplier
from neutrino_hub.modules.netbird.constants import NETBIRD_BINARY_PATH
from neutrino_hub.modules.overlay.config import enabled_providers
from neutrino_hub.modules.overlay.direct_config import direct_agent_port
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_EASYTIER,
    OVERLAY_ENGINES,
    OVERLAY_NETBIRD,
)
from neutrino_hub.modules.router.constants import ROUTER_FAMILIES
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig, held_networks
from neutrino_hub.modules.router.link_status import device_held_addresses
from neutrino_hub.platforms.constants import PLATFORM_OS_WINDOWS
from neutrino_hub.platforms.detect import hub_os, hub_platform, is_linux
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.web.constants import (
    WEB_DEFAULT_AGENT_LISTEN_PORT,
    WEB_DEFAULT_HTTPS_LISTEN_PORT,
    WEB_DEFAULT_LISTEN_PORT,
    WEB_SETTING_HTTPS_PORT,
)


def firewall_exposure(
    network: RouterNetworkConfig, *, routing: dict, held: "dict | None" = None
) -> FirewallExposure:
    """What the hub's firewall answers now.

    Args:
        network: The parsed router configuration, carrying the overlays'
            devices found at run time.
        routing: The proxy's routing options, for the SOCKS ports; empty
            in a tree without the proxy.
        held: Device name to every address it holds; read from the system
            when None.

    Returns:
        The exposure.

    Raises:
        ValueError: When the panel's settings hold a port that is no number.
    """
    settings = _settings(FIREWALL_PANEL_SETTINGS_FILE)
    return render_exposure(
        network,
        held=device_held_addresses() if held is None else held,
        panel_http_port=int(
            settings.get(FIREWALL_SETTING_LISTEN_PORT, WEB_DEFAULT_LISTEN_PORT)
        ),
        panel_https_port=int(
            settings.get(WEB_SETTING_HTTPS_PORT, WEB_DEFAULT_HTTPS_LISTEN_PORT)
        ),
        agent_port=int(
            settings.get(FIREWALL_SETTING_AGENT_PORT, WEB_DEFAULT_AGENT_LISTEN_PORT)
        ),
        socks_ports=[
            entry["port"]
            for entry in routing.get("socks_ports", [])
            if isinstance(entry, dict) and entry.get("port")
        ],
        is_direct=direct_agent_port() is not None,
    )


def converge_firewall(network: RouterNetworkConfig, *, routing: dict) -> tuple:
    """Make the system firewall on macOS or Windows answer as the exposure says.

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
        ValueError: When the panel's settings hold a port that is no number.
    """
    held = device_held_addresses()
    exposure = firewall_exposure(network, routing=routing, held=held)
    if hub_os() == PLATFORM_OS_WINDOWS:
        notes, refused = FirewallWindowsApplier().apply(render_port_rules(exposure))
    else:
        applier = FirewallDarwinApplier()
        notes = applier.apply(_programs(enabled_providers(network)))
        notes += applier.load_anchor(render_pf_anchor(exposure))
        refused = []
    write_generated(FIREWALL_NETWORKS_PATH, json.dumps(device_networks(held)))
    return notes, refused


def converge_firewalld(exposure: FirewallExposure) -> list:
    """Make firewalld accept what the exposure answers, on Linux where it runs.

    Args:
        exposure: What the firewall answers.

    Returns:
        One line per zone whose rules changed; empty when firewalld does not
        run or held the rules already.

    Raises:
        subprocess.CalledProcessError: When firewall-cmd refuses.
        OSError: When it cannot run or the record cannot be written.
    """
    applier = FirewallFirewalldApplier()
    if not applier.is_running():
        write_generated(FIREWALL_FIREWALLD_RECORD_PATH, json.dumps(None))
        return []
    devices, default, held = applier.survey()
    wanted = render_firewalld_rules(exposure, zones=devices, default_zone=default)
    notes = applier.apply(wanted, held=held)
    write_generated(FIREWALL_FIREWALLD_RECORD_PATH, json.dumps(wanted))
    return notes


def open_setup_port(port: int) -> list:
    """Open the setup wizard's port to every sender in the system firewall.

    The hub's rules become this one rule: on Linux where firewalld runs, a
    rich rule in the zone of every device and in the default zone, runtime
    and permanent; on Windows, ``neutrino_hub_setup``. The first firewall
    pass after setup removes it as a rule it does not render, and a reset
    removes it with the hub's other rules. macOS opens nothing.

    Args:
        port: The port the wizard listens on.

    Returns:
        One line per zone or rule changed, and one per rule Windows refused;
        empty when nothing changed.

    Raises:
        OSError: When the firewall cannot be read or changed.
        subprocess.CalledProcessError: When firewall-cmd refuses.
    """
    if is_linux():
        applier = FirewallFirewalldApplier()
        if not applier.is_running():
            return []
        devices, default, held = applier.survey()
        wanted = render_firewalld_setup_rules(port, zones=devices, default_zone=default)
        return applier.apply(wanted, held=held)
    if hub_os() == PLATFORM_OS_WINDOWS:
        notes, refused = FirewallWindowsApplier().apply([render_setup_port_rule(port)])
        return notes + [entry["detail"] for entry in refused]
    return []


def is_firewalld_moved() -> bool:
    """Whether firewalld's runtime lost or changed the rules the last pass wrote.

    Returns:
        True on Linux while firewalld runs and holds other rules of the
        hub's than the last pass left, or the last pass found it stopped or
        left no record; False otherwise.
    """
    if not is_linux():
        return False
    applier = FirewallFirewalldApplier()
    if not applier.is_running():
        return False
    try:
        recorded = json.loads(
            FIREWALL_FIREWALLD_RECORD_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        recorded = None
    if not isinstance(recorded, dict):
        return True
    try:
        return keyed(applier.held()) != keyed(recorded)
    except (OSError, subprocess.SubprocessError):
        return False


def is_network_set_moved() -> bool:
    """Whether the networks the box's devices hold differ from the last pass's.

    Returns:
        True when a device came, went, was renamed or holds another network
        since the firewall was last written on macOS or Windows, and when it
        never was.
    """
    try:
        recorded = json.loads(FIREWALL_NETWORKS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return recorded != device_networks(device_held_addresses())


def device_networks(held: dict) -> dict:
    """The networks each device holds, both families.

    Args:
        held: Device name to every address it holds, with its prefix.

    Returns:
        Device name to its networks, sorted, a link-local IPv6 address as
        ``fe80::/64``: a temporary address that rotates within its network
        changes nothing here.
    """
    return {
        name: sorted(
            network
            for family in ROUTER_FAMILIES
            for network in held_networks(addresses, family, is_link=True)
        )
        for name, addresses in sorted(held.items())
    }


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


def hand_back_firewall() -> list:
    """Take away everything the hub opened in the system firewall.

    Returns:
        One line per rule, program, anchor or firewalld zone changed.

    Raises:
        OSError: When the firewall cannot be read or changed.
        subprocess.CalledProcessError: When ``socketfilterfw`` or
            firewall-cmd refuses.
    """
    if is_linux():
        notes = FirewallFirewalldApplier().remove()
        FIREWALL_FIREWALLD_RECORD_PATH.unlink(missing_ok=True)
        return notes
    if hub_os() == PLATFORM_OS_WINDOWS:
        return FirewallWindowsApplier().remove()
    applier = FirewallDarwinApplier()
    return applier.remove(_programs(list(OVERLAY_ENGINES))) + applier.flush_anchor()


def _programs(overlays: list) -> list:
    """The programs macOS allows for these overlays."""
    return render_programs(
        hub_program=hub_platform().hub_command()[0],
        xray_program=edition.hook("proxy_program") or "",
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
