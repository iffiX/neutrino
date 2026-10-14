"""Discovering devices on the hub's exposed IPv4 segments, in every mode.

Two sources are merged: an active ``arp-scan`` sweep finds devices that answer
ARP right now, and the kernel's IPv4 neighbour table remembers ones seen
recently, a sleeping one included, which the Wake-on-LAN button needs. Both
are Linux's; on macOS and Windows a scan finds nothing.
"""

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.platforms.detect import is_linux
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.devices.constants import (
    DEVICE_LAN_SCAN_PREFIX_MIN,
    DEVICE_LAN_SCAN_TIMEOUT_S,
)

# The neighbour states the kernel keeps for an address nothing answered at.
NEIGHBOUR_STATES_GONE = ("FAILED", "INCOMPLETE")

# The kernel's IPv4 neighbour table, as a file. Counting from here costs a read
# where `ip neigh` would cost a process, and the count is wanted on every
# statistics frame.
PROC_NET_ARP = Path("/proc/net/arp")

ARP_SCAN_LINE = re.compile(
    r"^(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?P<mac>[0-9a-f:]{17})\s*(?P<vendor>.*)$",
    re.IGNORECASE,
)


@dataclass
class DiscoveredDevice:
    """One device seen on the LAN.

    Attributes:
        mac_address: Normalized lower-case MAC, the identity used everywhere.
        ipv4_address: Address it currently holds.
        vendor: Vendor string from the OUI database, empty when unknown.
        is_online: Whether it answered this scan, as opposed to only appearing
            in the neighbour table.
        is_neighbour: Whether the kernel's neighbour table holds it in a
            state other than FAILED or INCOMPLETE, STALE included.
    """

    mac_address: str
    ipv4_address: str
    vendor: str
    is_online: bool
    is_neighbour: bool = False


@dataclass(frozen=True)
class LanScanRange:
    """One IPv4 network a scan covers.

    Attributes:
        device: The interface the network is on.
        network: The network.
        source_address: The hub's own address in it, which the sweep's
            requests carry.
    """

    device: str
    network: ipaddress.IPv4Network
    source_address: str


def count_lan_neighbours(lan_interfaces: list[str]) -> int:
    """Count the devices the kernel currently has in its neighbour table.

    Read straight out of ``/proc/net/arp`` rather than by running ``ip``,
    because this is wanted on every statistics frame — a couple of times a
    second — and a file read costs nothing where a process launch would add up.

    Args:
        lan_interfaces: The interfaces holding the LAN role. Neighbours on any
            other interface are the upstream network's business, not the
            gateway's.

    Returns:
        How many devices with a resolved hardware address sit on those
        interfaces.
    """
    served = set(lan_interfaces)
    if not served or not is_linux():
        return 0
    try:
        lines = PROC_NET_ARP.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    count = 0
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 6 or fields[5] not in served:
            continue
        # Flag bit 0x2 is ATF_COM: the entry has a hardware address, as opposed
        # to being an unanswered probe for one.
        try:
            flags = int(fields[2], 16)
        except ValueError:
            continue
        if flags & 0x2:
            count += 1
    return count


def lan_scan_ranges(exposed: list[tuple[str, str]]) -> list[LanScanRange]:
    """The networks a scan covers.

    Args:
        exposed: ``(device, address/prefix)`` pairs, the hub's own addresses
            in its exposed IPv4 segments, as
            :meth:`neutrino_hub.modules.router.interfaces.RouterNetworkConfig.exposed_ipv4_addresses`
            reads them.

    Returns:
        One range per pair, in their order: the pair's network when it holds
        at most 256 addresses, else the /24 that holds the hub's address. A
        pair that is not an IPv4 address gives none, and a network is
        covered once per device.
    """
    ranges: list[LanScanRange] = []
    for device, text in exposed:
        try:
            interface = ipaddress.ip_interface(text)
        except ValueError:
            continue
        if interface.version != 4:
            continue
        network = interface.network
        if network.prefixlen < DEVICE_LAN_SCAN_PREFIX_MIN:
            network = ipaddress.ip_network(
                f"{interface.ip}/{DEVICE_LAN_SCAN_PREFIX_MIN}", strict=False
            )
        if any(
            covered.device == device and covered.network == network
            for covered in ranges
        ):
            continue
        ranges.append(
            LanScanRange(
                device=device, network=network, source_address=str(interface.ip)
            )
        )
    return ranges


class LanScanner:
    """Sweeps the hub's exposed IPv4 segments for devices."""

    def __init__(self, *, network, read_held):
        """
        Args:
            network: The router configuration, a
                :class:`neutrino_hub.modules.router.interfaces.RouterNetworkConfig`.
            read_held: Called with nothing for device name to every address
                it holds with its prefix, as
                :func:`neutrino_hub.modules.router.link_status.device_held_addresses`
                reads them.
        """
        self._network = network
        self._read_held = read_held

    def scan(self, *, is_active: bool = True) -> list[DiscoveredDevice]:
        """Discover devices in the ranges of :func:`lan_scan_ranges`.

        Args:
            is_active: Whether to run an ``arp-scan`` sweep. The sweep finds
                devices that answer right now but sends broadcast traffic and
                takes a few seconds, so the panel's background refresh passes
                False and reads only the kernel neighbour table, which is
                instant and silent.

        Returns:
            One entry per device inside a range, sorted by address. Devices
            answering the active sweep are marked online; the rest come from
            the IPv4 neighbour table of the range's interface and are marked
            offline. A device seen in two ranges appears once, under the
            range swept last.
        """
        if not is_linux():
            return []
        ranges = lan_scan_ranges(
            self._network.exposed_ipv4_addresses(self._read_held())
        )
        devices: dict[str, DiscoveredDevice] = {}
        for interface in dict.fromkeys(covered.device for covered in ranges):
            networks = [
                covered.network for covered in ranges if covered.device == interface
            ]
            for device in self._read_neighbours(interface):
                if _is_inside(device.ipv4_address, networks):
                    devices[device.mac_address] = device
        if is_active:
            for covered in ranges:
                for device in self._run_arp_scan(covered):
                    devices[device.mac_address] = device
        return sorted(devices.values(), key=_address_sort_key)

    def _run_arp_scan(self, covered: LanScanRange) -> list[DiscoveredDevice]:
        result = run(
            [
                "arp-scan",
                f"--interface={covered.device}",
                f"--arpspa={covered.source_address}",
                str(covered.network),
            ],
            is_checked=False,
            timeout_s=DEVICE_LAN_SCAN_TIMEOUT_S,
        )
        if not result.is_success:
            return []
        devices = []
        for line in result.stdout.splitlines():
            match = ARP_SCAN_LINE.match(line.strip())
            if not match:
                continue
            devices.append(
                DiscoveredDevice(
                    mac_address=match.group("mac").lower(),
                    ipv4_address=match.group("ip"),
                    vendor=match.group("vendor").strip(),
                    is_online=True,
                )
            )
        return devices

    def _read_neighbours(self, interface: str) -> list[DiscoveredDevice]:
        result = run(["ip", "-4", "neigh", "show", "dev", interface], is_checked=False)
        if not result.is_success:
            return []
        devices = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 4 or "lladdr" not in fields:
                continue
            if fields[-1] in NEIGHBOUR_STATES_GONE:
                continue
            address = fields[0]
            mac_address = fields[fields.index("lladdr") + 1].lower()
            devices.append(
                DiscoveredDevice(
                    mac_address=mac_address,
                    ipv4_address=address,
                    vendor="",
                    is_online=fields[-1] in ("REACHABLE", "DELAY", "PROBE"),
                    is_neighbour=True,
                )
            )
        return devices


def _is_inside(address: str, networks: list) -> bool:
    """Whether an IPv4 address lies in one of the networks."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in networks)


def _address_sort_key(device: DiscoveredDevice) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in device.ipv4_address.split("."))
    except ValueError:
        return (999, 999, 999, 999)
