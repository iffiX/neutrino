"""Running the overlay the configuration names, and only that one.

Switching is two acts in one order: the engines that are not chosen are stood
down first, because every one of them wants the same tunnel device, the same
peer port and — where two are the same product — the same state file, and a
box running two is a box whose address depends on which came up last.
"""

import socket
from typing import Callable

from neutrino_hub.modules.easytier.ops import apply_stored as apply_easytier
from neutrino_hub.modules.easytier.ops import console_device_names
from neutrino_hub.modules.easytier.ops import read_stored as read_easytier
from neutrino_hub.modules.easytier.provisioner import EasyTierProvisioner
from neutrino_hub.modules.netbird.provisioner import NetbirdProvisioner
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_EASYTIER,
    OVERLAY_ENGINES,
    OVERLAY_NONE,
    OVERLAY_PROVIDERS,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.system.provisioning import say
from neutrino_hub.utils.constants import is_dev_root_set
from neutrino_hub.utils.subprocess_run import run

# What installs each engine. An engine the table names but nothing here
# provisions is one this hub cannot run yet, and asking for it is refused
# rather than half-done.
OVERLAY_PROVISIONERS = {
    "netbird": NetbirdProvisioner,
    "easytier": EasyTierProvisioner,
}


def overlay_devices(network: RouterNetworkConfig) -> dict:
    """The devices each overlay rides on, where they are found at run time.

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
    for overlay in network.overlays:
        if overlay.provider != OVERLAY_EASYTIER:
            continue
        try:
            is_console_mode = read_easytier().is_console_mode
        except ValueError:
            is_console_mode = False
        if is_console_mode:
            devices[overlay.provider] = console_device_names()
    return devices


class OverlaySwitcher:
    """Puts the machine on one overlay, or on none."""

    def converge(
        self, provider: str, *, report: Callable[[str], None] | None = None
    ) -> str:
        """Run the named overlay and stand every other one down.

        Args:
            provider: A member of :data:`OVERLAY_PROVIDERS`.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What the engine reported, empty when there is nothing to run.

        Raises:
            ValueError: For a provider that is not one of them, or an EasyTier
                network whose stored secret or console address does not
                open.
            VaultLockedError: If there is no data key to open the stored
                EasyTier network.
            NotImplementedError: For an engine this hub does not run yet.
            subprocess.CalledProcessError: If installing or starting it fails.
        """
        if provider not in OVERLAY_PROVIDERS:
            raise ValueError(f"there is no overlay called {provider}")
        for key, engine in OVERLAY_ENGINES.items():
            if key == provider:
                continue
            self._stand_down(engine.unit, report=report)
        if provider == OVERLAY_NONE:
            return ""
        engine = OVERLAY_ENGINES[provider]
        if not engine.is_integrated or provider not in OVERLAY_PROVISIONERS:
            raise NotImplementedError(f"this hub does not run {engine.title} yet")
        say(report, f"starting {engine.title}")
        message = OVERLAY_PROVISIONERS[provider]().provision(report=report).message
        # Provisioning EasyTier installs and enables its unit; the network
        # stored in config/ is what starts it.
        if provider == OVERLAY_EASYTIER:
            say(report, apply_easytier(hostname=socket.gethostname()))
        return message

    def _stand_down(self, unit: str, *, report: Callable[[str], None] | None) -> None:
        """Stop and disable one engine's unit, if this machine has it.

        Args:
            unit: The systemd unit.
            report: Sink for progress lines, if anyone is watching.
        """
        # A development root drives no units at all; design/install_and_dev.md.
        if is_dev_root_set():
            return
        result = run(["systemctl", "disable", "--now", unit], is_checked=False)
        if result.is_success:
            say(report, f"stopped {unit}")
