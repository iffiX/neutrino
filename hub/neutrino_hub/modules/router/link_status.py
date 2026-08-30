"""Reading the current state of the box's network interfaces.

Read-only: the panel draws this, nothing acts on it. It answers what the roles
in ``config/`` cannot — whether a cable is actually plugged in, which address
DHCP handed out, which network the radio joined and how well it hears it.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.utils.subprocess_run import run

# The interface kinds the Network page is about. Everything else NetworkManager
# knows of — loopback, wt0, bridges, tunnels — is machinery the gateway
# manages elsewhere and never assigns a role to. VLANs count: they are the
# gateway's own creations, but they hold roles exactly as a physical port does.
LINK_KIND_ETHERNET = "ethernet"
LINK_KIND_WIFI = "wifi"
LINK_KIND_VLAN = "vlan"
PHYSICAL_LINK_KINDS = (LINK_KIND_ETHERNET, LINK_KIND_WIFI)
ROLE_LINK_KINDS = (LINK_KIND_ETHERNET, LINK_KIND_WIFI, LINK_KIND_VLAN)


@dataclass
class LinkStatus:
    """Live state of one network interface.

    Attributes:
        name: Interface name, for example ``enp2s0``.
        kind: ``ethernet`` or ``wifi``.
        is_present: Whether the kernel has the interface at all.
        is_up: Whether the link is administratively up and carrying.
        ipv4_address: First IPv4 address with its prefix, or None.
        mac_address: Current (possibly cloned) hardware address.
        connection: Name of the NetworkManager connection in use, or None.
        ssid: Network the radio has joined, for a Wi-Fi interface.
        signal_percent: Signal strength of that network, 0 to 100.
        speed_mbps: Negotiated link speed, or None when the driver will not
            say. This describes the cable, not the line behind it — a gigabit
            port in front of a 300 Mbit connection still reads 1000 — so it is
            only ever a tie-breaker.
        is_ap_capable: Whether this interface can serve a network. A wired port
            always can; a radio can only if its chipset supports access-point
            mode, which many cheap ones do not. False is what greys out the LAN
            role in the panel, so it is only ever set when the card has
            positively said it cannot — an interface whose capabilities cannot
            be read is left offerable rather than blocked on a guess.
    """

    name: str
    kind: str = LINK_KIND_ETHERNET
    is_present: bool = False
    is_up: bool = False
    ipv4_address: str | None = None
    mac_address: str | None = None
    connection: str | None = None
    ssid: str | None = None
    signal_percent: int | None = None
    speed_mbps: int | None = None
    is_ap_capable: bool = True

    @property
    def is_wifi(self) -> bool:
        """Whether this is a wireless interface."""
        return self.kind == LINK_KIND_WIFI


class RouterLinkStatus:
    """Reports the state of every physical interface, and the default route."""

    def __init__(self):
        # What a radio can do does not change while the box is running, and
        # asking costs a process launch per interface per page read.
        self._ap_capability: dict[str, bool] = {}

    def all_links(self) -> list[LinkStatus]:
        """Read every ethernet, Wi-Fi and VLAN interface on the box.

        Returns:
            One entry per interface: ethernet first, then Wi-Fi, then VLANs,
            alphabetical within each — a stable order, so the Network page's
            row of tabs does not reshuffle itself between polls, and the
            virtual interfaces hang behind the physical ones they ride on.
        """
        order = {LINK_KIND_ETHERNET: 0, LINK_KIND_WIFI: 1, LINK_KIND_VLAN: 2}
        addresses = self._addresses()
        links = []
        for name, (kind, connection) in self._devices().items():
            if kind not in ROLE_LINK_KINDS:
                continue
            links.append(self._build(name, kind, connection, addresses.get(name)))
        links.sort(key=lambda link: (order.get(link.kind, 3), link.name))
        return links

    def link(self, name: str) -> LinkStatus:
        """Read one interface's state.

        Args:
            name: Interface name.

        Returns:
            Its status, or an absent one when the interface does not exist —
            a configured interface that has been unplugged should render as
            missing rather than raise.
        """
        for link in self.all_links():
            if link.name == name:
                return link
        return LinkStatus(name=name)

    def default_gateway(self) -> str | None:
        """Read the current default gateway address.

        Returns:
            The next-hop address of the lowest-metric default route, or None
            when the box has no upstream. A multipath route reports its first
            next hop, which is one of the uplinks actually in use.
        """
        routes = self._default_routes()
        if not routes:
            return None
        first = routes[0]
        gateway = first.get("gateway")
        if gateway:
            return str(gateway)
        for hop in first.get("nexthops", []):
            if hop.get("gateway"):
                return str(hop["gateway"])
        return None

    def default_routes(self) -> list[dict]:
        """Every default route the kernel holds, lowest metric first.

        Exposed rather than kept private because what the routing table
        actually says is the only reliable account of it. NetworkManager
        normally installs a route at the metric its connection asked for, but
        not always — a degraded activation has been seen to land one far higher
        — so anything the gateway installs below the uplinks has to be placed
        below where they really are, not where they were told to be.

        Returns:
            Parsed ``ip -json route show default`` entries. A multipath route
            carries a ``nexthops`` list; a plain one carries ``dev``.
        """
        return self._default_routes()

    def gateway_for(self, name: str) -> str | None:
        """Read the next hop an interface's own default route points at.

        Needed to build a multipath route: the kernel wants each next hop
        spelled out, and under DHCP only the interface's route knows it.

        Args:
            name: Interface name.

        Returns:
            The next-hop address, or None when the interface has no default
            route — which is what "this uplink is down" looks like.
        """
        for route in self._default_routes():
            if route.get("dev") == name and route.get("gateway"):
                return str(route["gateway"])
            for hop in route.get("nexthops", []):
                if hop.get("dev") == name and hop.get("gateway"):
                    return str(hop["gateway"])
        return None

    def _build(
        self, name: str, kind: str, connection: str | None, entry: dict | None
    ) -> LinkStatus:
        if entry is None:
            return LinkStatus(name=name, kind=kind, connection=connection)
        link = LinkStatus(
            name=name,
            kind=kind,
            is_present=True,
            is_up=entry.get("operstate") == "UP",
            ipv4_address=_first_ipv4(entry),
            mac_address=entry.get("address"),
            connection=connection,
        )
        if link.is_wifi:
            link.ssid, link.signal_percent = self._joined_network(name, connection)
            link.is_ap_capable = self._is_ap_capable(name)
            link.speed_mbps = self._wireless_speed(name)
        else:
            link.speed_mbps = self._wired_speed(name)
        return link

    def _wired_speed(self, name: str) -> int | None:
        """Read an ethernet interface's negotiated speed in Mbit/s.

        Returns:
            The speed, or None when the interface is down or the driver
            declines to say — a down port reports -1 rather than failing.
        """
        try:
            speed = int(Path(f"/sys/class/net/{name}/speed").read_text().strip())
        except (OSError, ValueError):
            return None
        return speed if speed > 0 else None

    def _wireless_speed(self, name: str) -> int | None:
        """Read a radio's current transmit rate in Mbit/s.

        This is the PHY rate, which overstates real throughput by roughly half.
        It is used only to separate two radios from each other, never to
        compare one against a wire, so the overstatement does not matter.

        Returns:
            The rate, or None when the radio is not associated.
        """
        result = run(["iw", "dev", name, "link"], is_checked=False)
        if not result.is_success:
            return None
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped.startswith("tx bitrate:"):
                continue
            for token in stripped.split():
                try:
                    return int(float(token))
                except ValueError:
                    continue
        return None

    def _is_ap_capable(self, name: str) -> bool:
        """Whether a radio's chipset can run as an access point.

        Asked of the driver rather than assumed, because a card that cannot do
        it fails only at the moment the access point is started — long after
        the person has typed in an SSID and a passphrase. Knowing beforehand is
        what lets the panel grey the option out and say why.

        Args:
            name: Wireless interface name.

        Returns:
            True when the driver lists AP among its interface modes, and also
            when the question cannot be answered at all: refusing to offer the
            role on a card that might well support it is the worse mistake.
        """
        if name in self._ap_capability:
            return self._ap_capability[name]
        self._ap_capability[name] = self._read_ap_capability(name)
        return self._ap_capability[name]

    def _read_ap_capability(self, name: str) -> bool:
        phy_path = Path(f"/sys/class/net/{name}/phy80211/name")
        try:
            phy = phy_path.read_text(encoding="utf-8").strip()
        except OSError:
            return True
        result = run(["iw", "phy", phy, "info"], is_checked=False)
        if not result.is_success:
            return True
        # The modes are an indented list under their own heading, and a second
        # "software interface modes" list may follow. Only the first block
        # describes what the hardware itself can do.
        is_in_block = False
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Supported interface modes"):
                is_in_block = True
                continue
            if not is_in_block:
                continue
            if not stripped.startswith("*"):
                break
            if stripped.lstrip("* ").strip() == "AP":
                return True
        return False

    def _joined_network(
        self, name: str, connection: str | None
    ) -> tuple[str | None, int | None]:
        """Read which network a radio joined, and how strongly it hears it.

        The name comes from the active connection rather than the scan list's
        own ACTIVE column, which a rescan blanks for a moment and would
        otherwise report a connected radio as connected to nothing. Strength
        still comes from the list, matched by name.
        """
        if connection is None:
            return None, None
        ssid = run(
            ["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", connection],
            is_checked=False,
        ).stdout.strip()
        if not ssid:
            return None, None
        return ssid, self._signal_for(name, ssid)

    def _signal_for(self, name: str, ssid: str) -> int | None:
        result = run(
            [
                "nmcli",
                "-t",
                "-f",
                "SIGNAL,SSID",
                "device",
                "wifi",
                "list",
                "ifname",
                name,
                "--rescan",
                "no",
            ],
            is_checked=False,
        )
        if not result.is_success:
            return None
        strengths = []
        for line in result.stdout.splitlines():
            signal, _, found = line.partition(":")
            if _unescape(found) == ssid:
                strength = _as_int(signal)
                if strength is not None:
                    strengths.append(strength)
        return max(strengths) if strengths else None

    def _devices(self) -> dict[str, tuple[str, str | None]]:
        result = run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,CONNECTION", "device", "status"],
            is_checked=False,
        )
        if not result.is_success:
            return {}
        devices = {}
        for line in result.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            device, kind, connection = parts
            connection = _unescape(connection)
            devices[device] = (
                kind,
                connection if connection and connection != "--" else None,
            )
        return devices

    def _addresses(self) -> dict[str, dict]:
        result = run(["ip", "-json", "addr", "show"], is_checked=False)
        if not result.is_success:
            return {}
        return {entry["ifname"]: entry for entry in json.loads(result.stdout or "[]")}

    def _default_routes(self) -> list[dict]:
        result = run(["ip", "-json", "route", "show", "default"], is_checked=False)
        if not result.is_success:
            return []
        routes = json.loads(result.stdout or "[]")
        routes.sort(key=lambda route: route.get("metric", 0))
        return routes


def _first_ipv4(entry: dict) -> str | None:
    for address in entry.get("addr_info", []):
        if address.get("family") == "inet":
            return f"{address['local']}/{address['prefixlen']}"
    return None


def _unescape(value: str) -> str:
    """Undo the backslash escaping ``nmcli -t`` applies to field separators."""
    return value.replace("\\:", ":").replace("\\\\", "\\")


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None
