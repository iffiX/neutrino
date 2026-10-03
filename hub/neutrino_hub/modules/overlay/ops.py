"""Running the overlays the configuration enables, and no other.

Converging is two acts that the caller keeps apart: the enabled engines are
started, each given a moment to hold an address, and the engines turned off
are stood down only when the caller says so, after it has handed every peer
the material that no longer names them. On macOS and Windows each engine
is a child of the hub's one service, driven through the process controller
by its key, and its device is found by the address it holds.
"""

import dataclasses
import ipaddress
import json
import socket
import time
from typing import Callable

from neutrino_hub.modules.easytier.ops import (
    EasyTierStatusReader,
    apply_stored_if_changed,
)
from neutrino_hub.modules.easytier.ops import console_device_names, devices_holding
from neutrino_hub.modules.easytier.ops import read_stored as read_easytier
from neutrino_hub.modules.easytier.provisioner import EasyTierProvisioner
from neutrino_hub.modules.netbird.ops import (
    NetbirdRouteSelector,
    NetbirdStatusReader,
)
from neutrino_hub.modules.netbird.provisioner import NetbirdProvisioner
from neutrino_hub.modules.overlay.config import enabled_providers
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_ADDRESS_POLL_S,
    OVERLAY_ADDRESS_WAIT_S,
    OVERLAY_EASYTIER,
    OVERLAY_ENGINES,
    OVERLAY_NETBIRD,
)
from neutrino_hub.modules.overlay.route_check import (
    OverlayRouteConflict,
    find_route_conflicts,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.platforms.detect import is_linux, process_controller
from neutrino_hub.system.provisioning import say
from neutrino_hub.utils.constants import is_dev_root_set
from neutrino_hub.utils.subprocess_run import run

# What installs each engine. An engine the table names but nothing here
# provisions is one this hub cannot run yet, and asking for it is refused
# rather than half-done.
OVERLAY_PROVISIONERS = {
    OVERLAY_NETBIRD: NetbirdProvisioner,
    OVERLAY_EASYTIER: EasyTierProvisioner,
}


def overlay_devices(network: RouterNetworkConfig) -> dict:
    """The devices each running overlay rides on, where they are found at run
    time.

    EasyTier in console mode is the one such overlay: its engine names its own
    interface, so the interface is the one holding the address the engine
    reports.

    Args:
        network: The parsed router configuration.

    Returns:
        Provider to device names, possibly none, for each overlay found this
        way; an overlay left out rides on its engine's own device.
    """
    devices = {}
    for overlay in network.enabled_overlays:
        if not is_linux():
            devices[overlay.provider] = engine_devices(overlay.provider)
            continue
        if overlay.provider != OVERLAY_EASYTIER:
            continue
        if _is_easytier_console_mode():
            devices[overlay.provider] = console_device_names()
    return devices


def engine_devices(provider: str) -> list:
    """The devices one engine rides on right now.

    Args:
        provider: A key of :data:`OVERLAY_ENGINES`.

    Returns:
        The device names; for EasyTier in console mode, and for every engine
        outside Linux, the ones holding the addresses the engine reports,
        possibly none.
    """
    if not is_linux():
        if provider == OVERLAY_EASYTIER:
            return console_device_names()
        address = NetbirdStatusReader().survey().netbird_ip
        return devices_holding(device_addresses(), [address]) if address else []
    if provider == OVERLAY_EASYTIER and _is_easytier_console_mode():
        return console_device_names()
    return [OVERLAY_ENGINES[provider].device_name]


def overlay_subnets(providers: list) -> dict:
    """The networks each overlay's addresses come from.

    Args:
        providers: Keys of :data:`OVERLAY_ENGINES`.

    Returns:
        Provider to networks: the one the product fixes, EasyTier's stored
        address's network in manual mode, and in console mode the networks
        of the addresses the running engine reports. An overlay none of
        these names maps to an empty list.
    """
    subnets = {}
    for provider in providers:
        engine = OVERLAY_ENGINES[provider]
        if engine.subnet:
            subnets[provider] = [engine.subnet]
        elif provider == OVERLAY_EASYTIER:
            subnets[provider] = _easytier_subnets()
        else:
            subnets[provider] = []
    return subnets


def is_unit_active(unit: str) -> bool:
    """Whether systemd runs one unit now.

    Args:
        unit: The unit's name.

    Returns:
        True when it is active.
    """
    return run(["systemctl", "is-active", "--quiet", unit], is_checked=False).is_success


def is_engine_active(provider: str) -> bool:
    """Whether one engine runs now.

    Args:
        provider: A key of :data:`OVERLAY_ENGINES`, which is also the name the
            process controller knows the engine by.

    Returns:
        True when its unit is active, or outside Linux its child runs.

    Raises:
        KeyError: If the process controller does not run the engine.
    """
    if not is_linux():
        return process_controller().is_active(provider)
    return is_unit_active(OVERLAY_ENGINES[provider].unit)


class OverlaySwitcher:
    """Starts the enabled overlays and stands the others down."""

    def __init__(
        self,
        *,
        address_wait_s: float = OVERLAY_ADDRESS_WAIT_S,
        address_poll_s: float = OVERLAY_ADDRESS_POLL_S,
    ):
        """
        Args:
            address_wait_s: How long an engine just started is given to hold
                an address.
            address_poll_s: How often its devices are read meanwhile.
        """
        self._address_wait_s = address_wait_s
        self._address_poll_s = address_poll_s
        # What the panel words: one ``{code, params}`` per engine change.
        self.changes: list[dict] = []

    def start(
        self,
        network: RouterNetworkConfig,
        *,
        report: Callable[[str], None] | None = None,
    ) -> list[str]:
        """Run every enabled overlay on what is stored for it.

        An engine that was not running is waited for until one of its devices
        holds an address, or for :data:`OVERLAY_ADDRESS_WAIT_S`. EasyTier is
        restarted only when what it would be started with changed.

        Args:
            network: The parsed router configuration.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            One note per engine that changed, for the apply summary.

        Raises:
            ValueError: For an EasyTier network whose stored secret or console
                address does not open.
            VaultLockedError: If there is no data key to open the stored
                EasyTier network.
            NotImplementedError: For an engine this hub does not run yet.
            subprocess.CalledProcessError: If installing or starting it fails.
        """
        notes = []
        started = []
        for provider in enabled_providers(network):
            engine = OVERLAY_ENGINES[provider]
            if not engine.is_integrated or provider not in OVERLAY_PROVISIONERS:
                raise NotImplementedError(f"this hub does not run {engine.title} yet")
            was_active = is_engine_active(provider)
            result = OVERLAY_PROVISIONERS[provider]().provision(report=report)
            if result.is_changed:
                notes.append(result.message)
                self._change("overlay_updated", engine.title)
            if provider == OVERLAY_EASYTIER:
                note = apply_stored_if_changed(hostname=socket.gethostname())
                if note:
                    say(report, note)
                    notes.append(f"{engine.title}: {note}")
                    self._change("overlay_updated", engine.title)
            # A development root drives no units, so nothing there is waited
            # for; design/install_and_dev.md. Outside Linux an engine the
            # hub's service is not running yet starts with the service.
            if was_active or is_dev_root_set():
                continue
            if is_linux() or is_engine_active(provider):
                started.append(provider)
        for provider in started:
            title = OVERLAY_ENGINES[provider].title
            if self._await_address(provider):
                notes.append(f"{title} started")
                self._change("overlay_started", title)
            else:
                notes.append(f"{title} started without an address yet")
                self._change("overlay_started_no_address", title)
        return notes

    def stop(
        self,
        network: RouterNetworkConfig,
        *,
        report: Callable[[str], None] | None = None,
    ) -> list[str]:
        """Stand down every overlay the configuration does not enable.

        Args:
            network: The parsed router configuration.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            One note per engine stopped.
        """
        # A development root drives no units at all; design/install_and_dev.md.
        if is_dev_root_set():
            return []
        enabled = set(enabled_providers(network))
        notes = []
        for key, engine in OVERLAY_ENGINES.items():
            if key in enabled:
                continue
            if not is_linux():
                if self._stand_down_supervised(key):
                    say(report, f"stopped {key}")
                    notes.append(f"{engine.title} stopped")
                    self._change("overlay_stopped", engine.title)
                continue
            if not self._is_standing(engine.unit):
                continue
            result = run(
                ["systemctl", "disable", "--now", engine.unit], is_checked=False
            )
            if result.is_success:
                say(report, f"stopped {engine.unit}")
                notes.append(f"{engine.title} stopped")
                self._change("overlay_stopped", engine.title)
        return notes

    def _change(self, code: str, title: str) -> None:
        """Keep one change for the panel, once."""
        change = {"code": code, "params": {"title": title}}
        if change not in self.changes:
            self.changes.append(change)

    def _stand_down_supervised(self, provider: str) -> bool:
        """Stop one engine the hub's service runs, and keep it stopped."""
        controller = process_controller()
        if not controller.is_active(provider) and not controller.is_enabled(provider):
            return False
        controller.disable(provider)
        return True

    def _is_standing(self, unit: str) -> bool:
        """Whether a unit is running or would start at boot."""
        if is_unit_active(unit):
            return True
        return run(
            ["systemctl", "is-enabled", "--quiet", unit], is_checked=False
        ).is_success

    def _await_address(self, provider: str) -> bool:
        """Wait until one of an engine's devices holds an address.

        Args:
            provider: The engine.

        Returns:
            True when one does within the wait.
        """
        deadline = time.monotonic() + self._address_wait_s
        while True:
            held = device_addresses()
            if any(held.get(name) for name in engine_devices(provider)):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self._address_poll_s)


def _is_easytier_console_mode() -> bool:
    """Whether the stored EasyTier network comes from the console."""
    try:
        return read_easytier().is_console_mode
    except ValueError:
        return False


class OverlayRouteGuard:
    """Reads the routes the running overlays installed and takes away the
    ones the hub does not accept."""

    def check(self, network: RouterNetworkConfig) -> list[OverlayRouteConflict]:
        """Find the refused routes, and withdraw the ones that can be.

        A default route is deleted from the kernel, and NetBird is told to
        stop using it; a NetBird route overlapping another network is
        deselected. EasyTier's routes come from its console or its peers and
        are only reported. Outside Linux the routes are not read and no
        conflict is reported.

        Args:
            network: The parsed router configuration.

        Returns:
            One conflict per refused route, ``is_withdrawn`` saying whether
            it was taken away.
        """
        if not is_linux():
            return []
        providers = enabled_providers(network)
        devices = {provider: engine_devices(provider) for provider in providers}
        routes = _kernel_routes(devices)
        conflicts = find_route_conflicts(
            {
                provider: [entry[0] for entry in found]
                for provider, found in routes.items()
            },
            overlay_subnets(providers),
            [cidr for cidr, _ in network.local_networks(device_addresses())],
        )
        return [self._withdraw(conflict, routes) for conflict in conflicts]

    def _withdraw(
        self, conflict: OverlayRouteConflict, routes: dict
    ) -> OverlayRouteConflict:
        """Take one refused route away where that is possible.

        Args:
            conflict: The route.
            routes: Provider to ``(destination, device, table)`` as the
                kernel holds them.

        Returns:
            The conflict, ``is_withdrawn`` set when it was taken away.
        """
        is_withdrawn = False
        if conflict.provider == OVERLAY_NETBIRD:
            is_withdrawn = NetbirdRouteSelector().deselect(conflict.route)
        if conflict.is_default:
            for destination, device, table in routes.get(conflict.provider, []):
                if _network_of(destination) != conflict.route:
                    continue
                result = run(
                    ["ip", "route", "del", conflict.route, "dev", device]
                    + (["table", table] if table else []),
                    is_checked=False,
                )
                is_withdrawn = result.is_success or is_withdrawn
        return dataclasses.replace(conflict, is_withdrawn=is_withdrawn)


def _kernel_routes(devices: dict) -> dict:
    """The IPv4 routes naming each overlay's devices, in every table.

    Args:
        devices: Provider to its device names.

    Returns:
        Provider to ``(destination, device, table)`` triples, the default
        route written ``0.0.0.0/0``; empty when the kernel cannot be read.
    """
    result = run(
        ["ip", "-4", "-json", "route", "show", "table", "all"], is_checked=False
    )
    if not result.is_success:
        return {}
    try:
        entries = json.loads(result.stdout or "[]")
    except ValueError:
        return {}
    owners = {name: provider for provider, names in devices.items() for name in names}
    routes: dict = {provider: [] for provider in devices}
    for entry in entries:
        device = str(entry.get("dev", ""))
        if device not in owners or entry.get("type", "unicast") != "unicast":
            continue
        destination = str(entry.get("dst", ""))
        if destination == "default":
            destination = "0.0.0.0/0"
        table = str(entry.get("table", "") or "")
        routes[owners[device]].append(
            (destination, device, "" if table == "main" else table)
        )
    return routes


def _easytier_subnets() -> list:
    """The networks EasyTier's addresses come from in its stored mode."""
    try:
        config = read_easytier()
    except ValueError:
        return []
    if config.is_console_mode:
        addresses = EasyTierStatusReader().addresses()
    else:
        addresses = [config.address] if config.address else []
    return [_network_of(address) for address in addresses]


def _network_of(cidr: str) -> str:
    """A CIDR in its normal form, or the text as given when it is not one."""
    try:
        return str(ipaddress.ip_network(cidr, strict=False))
    except ValueError:
        return cidr
