"""Discovering devices on the LAN.

Two sources are merged: an active ``arp-scan`` sweep finds devices that answer
ARP right now, and the kernel neighbour table remembers ones seen recently. A
device that has gone to sleep still shows up from the neighbour table, which is
what makes the Wake-on-LAN button useful.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.devices.constants import DEVICE_LAN_SCAN_TIMEOUT_S

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
    """

    mac_address: str
    ipv4_address: str
    vendor: str
    is_online: bool


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
    if not served:
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


class LanScanner:
    """Sweeps the gateway's own networks for devices."""

    def __init__(self, *, lan_interfaces: list[str]):
        """
        Args:
            lan_interfaces: Interfaces to scan, for example ``["enp1s0"]``.
                Every interface with the LAN role is swept, so a laptop on the
                gateway's Wi-Fi appears alongside one on the wire.
        """
        self._lan_interfaces = lan_interfaces

    def scan(self, *, is_active: bool = True) -> list[DiscoveredDevice]:
        """Discover devices on the gateway's networks.

        Args:
            is_active: Whether to run an ``arp-scan`` sweep. The sweep finds
                devices that answer right now but sends broadcast traffic and
                takes a few seconds, so the panel's background refresh passes
                False and reads only the kernel neighbour table, which is
                instant and silent.

        Returns:
            One entry per device, sorted by address. Devices answering the
            active sweep are marked online; the rest come from the neighbour
            table and are marked offline. A device seen on two interfaces
            appears once, under the interface swept last.
        """
        devices: dict[str, DiscoveredDevice] = {}
        for interface in self._lan_interfaces:
            for device in self._read_neighbours(interface):
                devices[device.mac_address] = device
        if is_active:
            for interface in self._lan_interfaces:
                for device in self._run_arp_scan(interface):
                    devices[device.mac_address] = device
        return sorted(devices.values(), key=_address_sort_key)

    def _run_arp_scan(self, interface: str) -> list[DiscoveredDevice]:
        result = run(
            ["arp-scan", "--localnet", f"--interface={interface}"],
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
        result = run(["ip", "neigh", "show", "dev", interface], is_checked=False)
        if not result.is_success:
            return []
        devices = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 4 or "lladdr" not in fields:
                continue
            address = fields[0]
            mac_address = fields[fields.index("lladdr") + 1].lower()
            devices.append(
                DiscoveredDevice(
                    mac_address=mac_address,
                    ipv4_address=address,
                    vendor="",
                    is_online=fields[-1] in ("REACHABLE", "DELAY", "PROBE"),
                )
            )
        return devices


def _address_sort_key(device: DiscoveredDevice) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in device.ipv4_address.split("."))
    except ValueError:
        return (999, 999, 999, 999)
