"""Driving the Wi-Fi radio through NetworkManager.

A wireless interface can play either role, and the two need different
machinery: joining a network means scanning, picking, and handing over a
passphrase, while serving one means publishing an access point with a static
address for dnsmasq to bind. Both live here.

Not pure: every function changes the system or asks it a question. The settings
these act on come from :mod:`neutrino_hub.modules.router.interfaces`.
"""

from dataclasses import dataclass

from neutrino_hub.utils.json_file import write_generated
from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.router import network_manager
from neutrino_hub.modules.router.constants import (
    ROUTER_HOSTAPD_UNIT,
    ROUTER_NM_AP_CONNECTION_PREFIX,
    router_hostapd_address_path,
    router_hostapd_config_path,
)
from neutrino_hub.modules.router.hostapd_renderer import RouterHostapdRenderer

# A scan takes a few seconds of radio time, and associating with a network can
# take considerably longer than the default command timeout allows for.
SCAN_TIMEOUT_S = 45
JOIN_WAIT_S = 40
JOIN_TIMEOUT_S = 75

WIFI_CONNECTION_TYPE = "802-11-wireless"

# WPA2 permits 8 to 63 characters. An access point with no passphrase would put
# an open route into the LAN, so the gateway does not offer one.
AP_PASSPHRASE_MIN_LENGTH = 8
AP_PASSPHRASE_MAX_LENGTH = 63


@dataclass
class WifiNetwork:
    """One network the radio can see.

    Attributes:
        ssid: The network name.
        signal_percent: Signal strength, 0 to 100.
        security: Security as nmcli reports it, for example ``WPA2``. Empty
            for an open network.
        is_active: Whether this interface is currently joined to it.
        is_saved: Whether NetworkManager already holds a profile for it, and
            so already has the passphrase.
    """

    ssid: str
    signal_percent: int
    security: str
    is_active: bool
    is_saved: bool

    @property
    def is_open(self) -> bool:
        """Whether the network takes no passphrase."""
        return self.security.strip() == ""


class RouterWifiRadio:
    """Scans, joins, and publishes networks on one wireless interface."""

    def __init__(self, *, interface: str):
        """
        Args:
            interface: Wireless interface name, for example ``wlp3s0``.
        """
        self._interface = interface

    @property
    def access_point_connection(self) -> str:
        """The NetworkManager profile an older version of this gateway made.

        The access point is hostapd's now. This name survives only so that
        profile can be recognised and removed: left behind it would autoconnect
        the radio into NetworkManager's shared mode and start a second dnsmasq
        on the address, which is the very thing hostapd is here to avoid.

        Returns:
            The legacy connection name.
        """
        return f"{ROUTER_NM_AP_CONNECTION_PREFIX}{self._interface}"

    def scan(self) -> list[WifiNetwork]:
        """Scan for networks in range.

        Returns:
            Networks sorted by signal strength, strongest first, with each SSID
            appearing once — a mesh publishing the same name from three radios
            is one choice to the person picking, not three.

        Raises:
            CommandError: If the scan fails, which normally means the radio is
                down or the interface is not wireless.
        """
        result = run(
            [
                "nmcli",
                "-t",
                "-f",
                "ACTIVE,SIGNAL,SECURITY,SSID",
                "device",
                "wifi",
                "list",
                "ifname",
                self._interface,
                "--rescan",
                "yes",
            ],
            timeout_s=SCAN_TIMEOUT_S,
        )
        saved = self._saved_ssids()
        # Which network is joined comes from the active connection, not from
        # the scan's own ACTIVE column: a rescan rebuilds the access-point list
        # and clears that column for a moment, so reading it here would report
        # a connected radio as connected to nothing.
        joined = self.joined_ssid()
        strongest: dict[str, WifiNetwork] = {}
        for line in result.stdout.splitlines():
            network = self._parse_scan_line(line, saved=saved, joined=joined)
            if network is None:
                continue
            previous = strongest.get(network.ssid)
            if previous is None or network.signal_percent > previous.signal_percent:
                strongest[network.ssid] = network
        return sorted(
            strongest.values(),
            key=lambda network: network.signal_percent,
            reverse=True,
        )

    def joined_ssid(self) -> str | None:
        """The network this interface is currently associated with.

        Returns:
            Its name, or None when the radio is idle or serving an access
            point of its own.
        """
        connection = network_manager.connection_for_device(self._interface)
        if connection is None or connection == self.access_point_connection:
            return None
        return network_manager.read_property(connection, "802-11-wireless.ssid") or None

    def join(self, *, ssid: str, passphrase: str | None) -> str:
        """Join a network, waiting for the association to finish.

        Args:
            ssid: The network to join.
            passphrase: Its passphrase, or None to reuse the one
                NetworkManager already holds for a saved network.

        Returns:
            The name of the connection now active on the interface.

        Raises:
            CommandError: If the association fails — a wrong passphrase, a
                network out of range, or a saved profile that is not there.
        """
        # The access point and a joined network both want the radio, so the
        # access point has to let go before the association will start. And a
        # radio that has been publishing, or sitting idle, has a scan list that
        # holds either its own network or nothing at all — asking it to connect
        # in that state fails with "no network with that SSID found" for a
        # network that is plainly in range. So look again first.
        self.unpublish()
        run(
            [
                "nmcli",
                "device",
                "wifi",
                "list",
                "ifname",
                self._interface,
                "--rescan",
                "yes",
            ],
            timeout_s=SCAN_TIMEOUT_S,
            is_checked=False,
        )
        command = [
            "nmcli",
            "--wait",
            str(JOIN_WAIT_S),
            "device",
            "wifi",
            "connect",
            ssid,
            "ifname",
            self._interface,
        ]
        if passphrase:
            command += ["password", passphrase]
        result = run(command, timeout_s=JOIN_TIMEOUT_S, is_checked=False)
        if not result.is_success:
            raise CommandError(_readable_join_error(result.stderr or result.stdout))
        return network_manager.connection_for_device(self._interface) or ssid

    def publish(self, *, interface) -> bool:
        """Bring up an access point on this interface, and serve it ourselves.

        hostapd runs the radio; the address is put on by the unit; the
        gateway's own dnsmasq and nftables handle the rest, exactly as for a
        wired LAN. NetworkManager is told to let go of the interface first,
        because two things configuring one radio is one too many.

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
        config = renderer.render()
        address = renderer.render_address()
        config_path = router_hostapd_config_path(self._interface)
        address_path = router_hostapd_address_path(self._interface)

        is_changed = _write_if_changed(config_path, config)
        is_changed |= _write_if_changed(address_path, address)
        unit = ROUTER_HOSTAPD_UNIT.format(interface=self._interface)
        is_running = run(
            ["systemctl", "is-active", "--quiet", unit], is_checked=False
        ).is_success
        if not is_changed and is_running:
            return False

        self._release_radio()
        run(["systemctl", "enable", unit], is_checked=False)
        result = run(["systemctl", "restart", unit], timeout_s=60, is_checked=False)
        if not result.is_success:
            raise CommandError(
                f"could not start the access point on {self._interface}: "
                f"{(result.stderr or result.stdout).strip() or _hostapd_complaint(unit)}"
            )
        return True

    def unpublish(self) -> bool:
        """Stop the access point and hand the interface back.

        Returns:
            True when there was an access point running to stop.
        """
        unit = ROUTER_HOSTAPD_UNIT.format(interface=self._interface)
        was_running = run(
            ["systemctl", "is-active", "--quiet", unit], is_checked=False
        ).is_success
        run(["systemctl", "disable", "--now", unit], is_checked=False)
        run(["ip", "address", "flush", "dev", self._interface], is_checked=False)
        self._forget_legacy_connection()
        # Managed again, so the radio can be scanned and joined as a client.
        network_manager.set_unmanaged(self._interface, False)
        return was_running

    def _forget_legacy_connection(self) -> None:
        """Delete the NetworkManager access-point profile, if one is left.

        An older version of the gateway published the access point through
        NetworkManager. Left behind, that profile autoconnects the radio into
        shared mode and starts a second dnsmasq on the address — which is the
        whole reason the access point is hostapd's now.
        """
        name = self.access_point_connection
        if network_manager.connection_exists(name):
            run(["nmcli", "connection", "delete", name], is_checked=False)

    def _release_radio(self) -> None:
        """Take the interface off NetworkManager so hostapd can own it.

        Durably, not just for this boot: a radio NetworkManager reclaims at
        startup is one it will fight hostapd for, and the loser is whichever
        got there second.
        """
        self._release_client_profiles()
        self._forget_legacy_connection()
        network_manager.set_unmanaged(self._interface, True)
        run(["nmcli", "device", "disconnect", self._interface], is_checked=False)

    def stand_down(self) -> None:
        """Give up the radio entirely: no access point, no autoconnect.

        Used when the interface's role becomes ``disabled``. Simply
        disconnecting is not enough — NetworkManager would reconnect a saved
        profile within seconds.
        """
        self.unpublish()
        self._release_client_profiles()

    def _release_client_profiles(self) -> None:
        """Stop saved networks reclaiming the radio from the access point."""
        access_point = self.access_point_connection
        for name in network_manager.connections_of_type(WIFI_CONNECTION_TYPE):
            if name == access_point:
                continue
            network_manager.modify_if_needed(name, {"connection.autoconnect": "no"})

    def _parse_scan_line(
        self, line: str, *, saved: set[str], joined: str | None
    ) -> WifiNetwork | None:
        # SSID goes last because it is the only field that may contain the
        # separator; nmcli escapes those, and unescape puts them back.
        _, _, rest = line.partition(":")
        signal, _, rest = rest.partition(":")
        security, _, ssid = rest.partition(":")
        ssid = network_manager.unescape(ssid)
        if not ssid:
            return None
        try:
            strength = int(signal)
        except ValueError:
            strength = 0
        return WifiNetwork(
            ssid=ssid,
            signal_percent=strength,
            security=network_manager.unescape(security),
            is_active=ssid == joined,
            is_saved=ssid in saved,
        )

    def _saved_ssids(self) -> set[str]:
        saved = set()
        for name in network_manager.connections_of_type(WIFI_CONNECTION_TYPE):
            if name == self.access_point_connection:
                continue
            ssid = network_manager.read_property(name, "802-11-wireless.ssid")
            if ssid:
                saved.add(ssid)
        return saved


def _readable_join_error(message: str) -> str:
    text = message.strip() or "the connection failed"
    lowered = text.lower()
    if "secrets were required" in lowered or "no secrets provided" in lowered:
        return "wrong or missing passphrase"
    if "not found" in lowered:
        return "that network is no longer in range"
    return text


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

    Returns:
        True when the file was written, which is the caller's signal that
        hostapd needs restarting.
    """
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    write_generated(path, text, mode=0o600)
    return True


def _hostapd_complaint(unit: str) -> str:
    """The last few journal lines for a unit, for an error with no stderr."""
    result = run(["journalctl", "-u", unit, "-n", "6", "--no-pager"], is_checked=False)
    return result.stdout.strip() or "see `journalctl -u " + unit + "`"
