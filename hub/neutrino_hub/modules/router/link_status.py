"""Reading the current state of the box's network interfaces.

Read-only: the panel draws this, nothing acts on it. It answers what the roles
in ``config/`` cannot — whether a cable is actually plugged in, which address
DHCP handed out, which network the radio joined and how well it hears it.

Asked of the kernel, through `ip` and `iw`, and never of a network manager.
A machine the hub does not address runs whatever it runs and may have no
manager the hub knows; its ports still have to be drawn, because the panel
shows them and offers to take them over.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.utils.subprocess_run import run

# The interface kinds the Network page is about. Everything else the kernel
# holds — loopback, wt0, bridges, tunnels, veth — is machinery the gateway
# manages elsewhere and never assigns a role to. VLANs count: they are the
# gateway's own creations, but they hold roles exactly as a physical port does.
LINK_KIND_ETHERNET = "ethernet"
LINK_KIND_WIFI = "wifi"
LINK_KIND_MODEM = "modem"
LINK_KIND_VLAN = "vlan"
PHYSICAL_LINK_KINDS = (LINK_KIND_ETHERNET, LINK_KIND_WIFI, LINK_KIND_MODEM)
ROLE_LINK_KINDS = PHYSICAL_LINK_KINDS + (LINK_KIND_VLAN,)

# What the kernel calls an interface's hardware type: the number in
# `/sys/class/net/<name>/type`. Ethernet is the only one the hub drives, and
# that is the whole rule — a 4G card in MBIM or ECM mode reports it and takes
# a lease like any wired port, while a CAN adapter (280), a PPP session (512),
# an 802.15.4 radio (804), an InfiniBand card (32) and a modem handing up bare
# IP (519, 65534) do not. What is and is not driven is in design/network.md.
LINK_ARPHRD_ETHER = 1
# systemd's predictable naming gives every WWAN interface this prefix. What it
# separates is a cellular card from a wired port, both of which speak ethernet
# and take a lease: the card is an uplink and nothing else, because a carrier
# hands up one address with no network to serve behind it.
LINK_MODEM_PREFIX = "ww"
# Where the kernel publishes what it knows about each interface. Named rather
# than written out at each use so a test can point it somewhere it may write.
LINK_SYSFS_ROOT = Path("/sys/class/net")


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
        for name, kind in self._devices().items():
            links.append(self._build(name, kind, addresses.get(name)))
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

    def _build(self, name: str, kind: str, entry: dict | None) -> LinkStatus:
        if entry is None:
            return LinkStatus(name=name, kind=kind)
        link = LinkStatus(
            name=name,
            kind=kind,
            is_present=True,
            is_up=entry.get("operstate") == "UP",
            ipv4_address=_first_ipv4(entry),
            mac_address=entry.get("address"),
        )
        if link.is_wifi:
            link.ssid, link.signal_percent, link.speed_mbps = self._radio(name)
            link.is_ap_capable = self._is_ap_capable(name)
        elif link.kind == LINK_KIND_MODEM:
            # A carrier hands up one address on a point-to-point link. There
            # is nothing to serve a network on and nothing to bridge to it.
            link.is_ap_capable = False
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
            speed = int((LINK_SYSFS_ROOT / name / "speed").read_text().strip())
        except (OSError, ValueError):
            return None
        return speed if speed > 0 else None

    def _radio(self, name: str) -> tuple[str | None, int | None, int | None]:
        """What a radio is associated with, how well it hears it, how fast.

        One `iw` call for all three, because the page reads them together on
        every poll and asking separately costs a process launch each.

        The rate is the PHY rate, which overstates real throughput by roughly
        half. It is used only to separate two radios from each other, never to
        compare one against a wire, so the overstatement does not matter.

        Args:
            name: Wireless interface name.

        Returns:
            SSID, signal as a percentage, and transmit rate in Mbit/s. All
            three are None when the radio is not associated with anything.
        """
        result = run(["iw", "dev", name, "link"], is_checked=False)
        if not result.is_success:
            return None, None, None
        ssid = None
        signal_percent = None
        speed_mbps = None
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("SSID:"):
                ssid = stripped[len("SSID:") :].strip() or None
            elif stripped.startswith("signal:"):
                signal_percent = _signal_percent(stripped)
            elif stripped.startswith("tx bitrate:"):
                speed_mbps = _first_number(stripped)
        return ssid, signal_percent, speed_mbps

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
        phy_path = LINK_SYSFS_ROOT / name / "phy80211" / "name"
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

    def _devices(self) -> dict[str, str]:
        """Every interface a role can be assigned to, and what kind it is.

        Returns:
            Interface name to kind. Loopback, bridges, tunnels, veth pairs and
            the overlay are left out: they are not ports anybody gives a role
            to, and nothing here has to name them one by one to exclude them.
        """
        result = run(["ip", "-d", "-json", "link", "show"], is_checked=False)
        if not result.is_success:
            return {}
        kinds = {}
        for entry in json.loads(result.stdout or "[]"):
            name = str(entry.get("ifname", ""))
            kind = _kind_of(name, entry)
            if name and kind is not None:
                kinds[name] = kind
        return kinds

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


def device_addresses() -> dict[str, str]:
    """Every device on the box holding an IPv4 address.

    Wider than :meth:`RouterLinkStatus.all_links`, which answers what the
    Network page draws. This answers where the box can be reached, so it
    counts the interfaces the hub assigns no role to: an overlay's tun is not
    a port anybody plugged in, and it is still an address devices come in on.

    Returns:
        Device name to address with its prefix, loopback left out.
    """
    result = run(["ip", "-json", "addr", "show"], is_checked=False)
    if not result.is_success:
        return {}
    found = {}
    for entry in json.loads(result.stdout or "[]"):
        name = entry.get("ifname", "")
        address = _first_ipv4(entry)
        if name and name != "lo" and address:
            found[name] = address
    return found


def _first_ipv4(entry: dict) -> str | None:
    for address in entry.get("addr_info", []):
        if address.get("family") == "inet":
            return f"{address['local']}/{address['prefixlen']}"
    return None


def _kind_of(name: str, entry: dict) -> str | None:
    """Which kind an interface is, or None for one the hub does not drive.

    A whitelist of three, plus the VLANs the gateway builds itself. Everything
    else a machine may carry gets no role: docker's and podman's bridges, a
    container's veth, the overlay's tun, a bond, a dialer's PPP session,
    Bluetooth tethering, a CAN adapter, an InfiniBand card.
    Half-driving something is worse than leaving it alone, and a list of what
    is refused does not have to keep up with what the world adds.

    The order matters:

    1. **Every interface the kernel synthesised names itself**, in
       ``info_kind``. Only `vlan` among them is the gateway's.
    2. **A port has hardware behind it.** No `device`, no role.
    3. **A radio has a `phy80211`.**
    4. **The hardware type has to be ethernet.** A 4G or 5G card in MBIM or
       ECM mode reports it and takes a lease like any wired port; one in
       raw-IP mode does not, and neither does a bus.
    5. **The name separates a cellular card from a wire**, which changes only
       what it may be used for.

    Args:
        name: Interface name.
        entry: One entry of ``ip -d -json link show``.

    Returns:
        The kind, or None to leave the interface out.
    """
    info_kind = entry.get("linkinfo", {}).get("info_kind")
    if info_kind is not None:
        return LINK_KIND_VLAN if info_kind == LINK_KIND_VLAN else None
    if not (LINK_SYSFS_ROOT / name / "device").exists():
        return None
    if (LINK_SYSFS_ROOT / name / "phy80211").exists():
        return LINK_KIND_WIFI
    if _arphrd(name) != LINK_ARPHRD_ETHER:
        return None
    if name.startswith(LINK_MODEM_PREFIX):
        return LINK_KIND_MODEM
    return LINK_KIND_ETHERNET


def _arphrd(name: str) -> int:
    """The kernel's hardware type for an interface.

    Args:
        name: Interface name.

    Returns:
        The ARPHRD number. Ethernet when it cannot be read: the interface got
        this far by having hardware behind it, and hiding a port because one
        sysfs file would not open is the worse way to be wrong.
    """
    try:
        return int((LINK_SYSFS_ROOT / name / "type").read_text().strip())
    except (OSError, ValueError):
        return LINK_ARPHRD_ETHER


def _signal_percent(line: str) -> int | None:
    """Turn `signal: -52 dBm` into the percentage the panel draws.

    Twice the strength above -100 dBm, capped at both ends: the mapping every
    desktop uses, where -50 reads full and -100 reads empty. It says how a
    person should read the bar rather than stating a physical quantity.

    Args:
        line: The `signal:` line of ``iw dev <name> link``.

    Returns:
        0 to 100, or None when the line carries no number.
    """
    dbm = _first_number(line)
    if dbm is None:
        return None
    return max(0, min(100, 2 * (dbm + 100)))


def _first_number(line: str) -> int | None:
    """The first token of a line that reads as a number.

    Args:
        line: One line of `iw` output.

    Returns:
        It as an integer, or None when the line holds no number.
    """
    for token in line.split():
        try:
            return int(float(token))
        except ValueError:
            continue
    return None
