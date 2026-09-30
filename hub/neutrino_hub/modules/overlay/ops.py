"""Running the overlays the configuration enables, and no other.

Converging is two acts that the caller keeps apart: the enabled engines are
started, each given a moment to hold an address, and the engines turned off
are stood down only when the caller says so, after it has handed every peer
the material that no longer names them.
"""

import socket
import time
from typing import Callable

from neutrino_hub.modules.easytier.ops import apply_stored_if_changed
from neutrino_hub.modules.easytier.ops import console_device_names
from neutrino_hub.modules.easytier.ops import read_stored as read_easytier
from neutrino_hub.modules.easytier.provisioner import EasyTierProvisioner
from neutrino_hub.modules.netbird.provisioner import NetbirdProvisioner
from neutrino_hub.modules.overlay.config import enabled_providers
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_ADDRESS_POLL_S,
    OVERLAY_ADDRESS_WAIT_S,
    OVERLAY_EASYTIER,
    OVERLAY_ENGINES,
    OVERLAY_NETBIRD,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import device_addresses
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
        The device names; for EasyTier in console mode the ones holding the
        addresses the engine reports, possibly none.
    """
    if provider == OVERLAY_EASYTIER and _is_easytier_console_mode():
        return console_device_names()
    return [OVERLAY_ENGINES[provider].device_name]


def is_unit_active(unit: str) -> bool:
    """Whether systemd runs one unit now.

    Args:
        unit: The unit's name.

    Returns:
        True when it is active.
    """
    return run(["systemctl", "is-active", "--quiet", unit], is_checked=False).is_success


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
            was_active = is_unit_active(engine.unit)
            result = OVERLAY_PROVISIONERS[provider]().provision(report=report)
            if result.is_changed:
                notes.append(result.message)
            if provider == OVERLAY_EASYTIER:
                note = apply_stored_if_changed(hostname=socket.gethostname())
                if note:
                    say(report, note)
                    notes.append(f"{engine.title}: {note}")
            # A development root drives no units, so nothing there is waited
            # for; design/install_and_dev.md.
            if not was_active and not is_dev_root_set():
                started.append(provider)
        for provider in started:
            title = OVERLAY_ENGINES[provider].title
            if self._await_address(provider):
                notes.append(f"{title} started")
            else:
                notes.append(f"{title} started without an address yet")
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
            if key in enabled or not self._is_standing(engine.unit):
                continue
            result = run(
                ["systemctl", "disable", "--now", engine.unit], is_checked=False
            )
            if result.is_success:
                say(report, f"stopped {engine.unit}")
                notes.append(f"{engine.title} stopped")
        return notes

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
