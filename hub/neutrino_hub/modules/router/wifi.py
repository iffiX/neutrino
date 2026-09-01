"""Publishing an access point on a Wi-Fi radio, with hostapd.

A radio does one of two things and never both: it joins somebody's network, or
it publishes one. Joining is
:mod:`neutrino_hub.modules.router.supplicant`; this is the other half.

The gateway runs its own access point rather than asking a manager for one.
NetworkManager's AP mode comes with ``ipv4.method=shared``, which is not a
detail that can be turned off, and shared means a second dnsmasq of its own on
the access point's address: it holds port 53, so the gateway's own dnsmasq
cannot start and the wired LAN loses DHCP and DNS with it, and every name a
Wi-Fi client looks up is resolved outside the proxy — the one thing this box
exists to prevent.

So the radio is ours: hostapd runs the access point, the gateway's dnsmasq
serves it, and nftables carries the traffic, exactly as for a wired LAN.

Not pure: writes rendered files and drives systemd.
"""

from neutrino_hub.utils.json_file import write_generated
from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.router import links
from neutrino_hub.modules.router.constants import (
    ROUTER_HOSTAPD_UNIT,
    router_hostapd_address_path,
    router_hostapd_config_path,
)
from neutrino_hub.modules.router.hostapd_renderer import RouterHostapdRenderer
from neutrino_hub.modules.router.supplicant import RouterWifiClient

# WPA2 permits 8 to 63 characters. An access point with no passphrase would put
# an open route into the LAN, so the gateway does not offer one.
AP_PASSPHRASE_MIN_LENGTH = 8
AP_PASSPHRASE_MAX_LENGTH = 63
# How long hostapd gets to claim the radio and come up.
AP_START_TIMEOUT_S = 60


class RouterWifiAccessPoint:
    """Publishes a network on one wireless interface."""

    def __init__(self, *, interface: str):
        """
        Args:
            interface: Wireless interface name, for example ``wlp3s0``.
        """
        self._interface = interface

    @property
    def unit(self) -> str:
        """The systemd unit running the access point on this radio."""
        return ROUTER_HOSTAPD_UNIT.format(interface=self._interface)

    @property
    def is_running(self) -> bool:
        """Whether an access point is up on this radio."""
        return run(
            ["systemctl", "is-active", "--quiet", self.unit], is_checked=False
        ).is_success

    def publish(self, *, interface) -> bool:
        """Bring up an access point on this interface, and serve it ourselves.

        hostapd runs the radio; the address is put on by the unit; the
        gateway's own dnsmasq and nftables handle the rest, exactly as for a
        wired LAN.

        Args:
            interface: The interface holding the LAN role, carrying the
                access-point settings under ``wifi`` and the address under
                ``lan``.

        Returns:
            True when the access point had to be reconfigured or restarted,
            False when it was already publishing exactly this.

        Raises:
            CommandError: If the passphrase is unusable, or hostapd will not
                start — most often because the card has no access-point mode.
        """
        passphrase = interface.wifi.ap_passphrase
        if not AP_PASSPHRASE_MIN_LENGTH <= len(passphrase) <= AP_PASSPHRASE_MAX_LENGTH:
            raise CommandError(
                f"the access point passphrase must be "
                f"{AP_PASSPHRASE_MIN_LENGTH} to {AP_PASSPHRASE_MAX_LENGTH} characters"
            )

        renderer = RouterHostapdRenderer(
            interface=interface, country_code=regulatory_domain()
        )
        is_changed = _write_if_changed(
            router_hostapd_config_path(self._interface), renderer.render()
        )
        is_changed |= _write_if_changed(
            router_hostapd_address_path(self._interface), renderer.render_address()
        )
        if not is_changed and self.is_running:
            return False

        self._release_radio()
        run(["systemctl", "enable", self.unit], is_checked=False)
        result = run(
            ["systemctl", "restart", self.unit],
            timeout_s=AP_START_TIMEOUT_S,
            is_checked=False,
        )
        if not result.is_success:
            raise CommandError(
                f"could not start the access point on {self._interface}: "
                f"{(result.stderr or result.stdout).strip() or self._complaint()}"
            )
        return True

    def unpublish(self) -> bool:
        """Stop the access point and leave the radio idle.

        Returns:
            True when there was an access point running to stop.
        """
        was_running = self.is_running
        run(["systemctl", "disable", "--now", self.unit], is_checked=False)
        links.clear_addresses(self._interface)
        return was_running

    def _release_radio(self) -> None:
        """Take the radio off whatever else was using it.

        One radio cannot both join a network and publish one. The unit says so
        with `Conflicts=`, but stopping the supplicant here is what makes the
        order deliberate rather than a race systemd resolves.
        """
        RouterWifiClient(interface=self._interface).stop()

    def _complaint(self) -> str:
        """The last few journal lines, for a failure with no stderr."""
        result = run(
            ["journalctl", "-u", self.unit, "-n", "6", "--no-pager"], is_checked=False
        )
        return result.stdout.strip() or f"see `journalctl -u {self.unit}`"


def regulatory_domain() -> str | None:
    """The two-letter regulatory domain the kernel is using, when it has one.

    Returns:
        The country code, or None when it is unset — reported as ``00``, the
        world domain, which hostapd should not be handed as a country.
    """
    result = run(["iw", "reg", "get"], is_checked=False)
    if not result.is_success:
        return None
    for line in result.stdout.splitlines():
        if not line.strip().startswith("country"):
            continue
        code = line.split()[1].strip(":")
        return code if code.isalpha() and code != "00" else None
    return None


def _write_if_changed(path, text: str) -> bool:
    """Write a generated file only when its contents would differ.

    Args:
        path: Where it goes.
        text: What it should say.

    Returns:
        True when the file was written, which is the caller's signal that
        hostapd needs restarting.
    """
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    write_generated(path, text, mode=0o600)
    return True
