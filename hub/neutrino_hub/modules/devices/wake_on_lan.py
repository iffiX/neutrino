"""Sending Wake-on-LAN magic packets to LAN devices.

Waking a machine needs three things outside this module: the target's NIC must
keep Wake-on-LAN armed (``ethtool -s <iface> wol g``, persisted), its firmware
must allow it, and the packet must reach the target's link. The last one is why
the packet is broadcast on a network the hub is on rather than sent to a
unicast address.

A router or side gateway hub sends to each network it serves, a server hub to
each network it is exposed on. The packet goes to that network's own
broadcast address, from the hub's own address on that network.
"""

import ipaddress
import socket
from dataclasses import dataclass

from neutrino_hub.modules.devices.constants import DEVICE_WOL_PORT
from neutrino_hub.modules.router.constants import ROUTER_MODE_SERVER

MAGIC_PACKET_REPEAT_COUNT = 16
# The longest prefix whose network has a broadcast address of its own.
BROADCAST_PREFIX_MAX = 30


@dataclass(frozen=True)
class WakeTarget:
    """One network a magic packet is broadcast on.

    Attributes:
        broadcast_address: The network's broadcast address.
        source_address: The hub's own address on that network, which the
            packet leaves from.
    """

    broadcast_address: str
    source_address: str


def wake_targets(network, read_addresses) -> list[WakeTarget]:
    """Every network a magic packet is broadcast on, one per network.

    Args:
        network: The router configuration, a
            :class:`neutrino_hub.modules.router.interfaces.RouterNetworkConfig`.
        read_addresses: Called with nothing for device name to the address
            with its prefix the box holds, as
            :func:`neutrino_hub.modules.router.link_status.device_addresses`
            reads them; called for a server hub alone.

    Returns:
        For a server hub, the network of each exposed interface holding an
        IPv4 address, an interface the configuration does not name read as
        :meth:`RouterNetworkConfig.exposed_device_names_on` reads it; for a
        router or side gateway hub, each served network. Never an overlay's: a tunnel has no broadcast domain, and its device
        refuses the packet rather than dropping it.
    """
    held: list = []
    if network.mode == ROUTER_MODE_SERVER:
        overlays = set(network.overlay_device_names)
        addresses = read_addresses()
        for name in network.exposed_device_names_on(list(addresses)):
            if name not in overlays:
                held.append(str(addresses.get(name, "") or ""))
    else:
        held = [
            f"{interface.lan.address}/{_prefix_of(interface.lan.cidr)}"
            for interface in network.lan_interfaces
            if interface.lan.address
        ]
    targets: list[WakeTarget] = []
    for text in held:
        try:
            interface = ipaddress.ip_interface(text)
        except ValueError:
            continue
        if interface.version != 4 or interface.network.prefixlen > BROADCAST_PREFIX_MAX:
            continue
        target = WakeTarget(
            broadcast_address=str(interface.network.broadcast_address),
            source_address=str(interface.ip),
        )
        if all(
            held_target.broadcast_address != target.broadcast_address
            for held_target in targets
        ):
            targets.append(target)
    return targets


def send_magic_packet(
    mac_address: str, *, broadcast_address: str, source_address: str = ""
) -> None:
    """Broadcast a Wake-on-LAN magic packet on one network.

    Args:
        mac_address: Target MAC, with or without separators.
        broadcast_address: The network's broadcast address, for example
            ``192.168.100.255``.
        source_address: The hub's own address on that network, which the
            socket is bound to; empty leaves the choice to the system.

    Raises:
        ValueError: If the MAC address is malformed.
        OSError: If the packet cannot be sent.
    """
    payload = _build_magic_packet(mac_address)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if source_address:
            sock.bind((source_address, 0))
        sock.sendto(payload, (broadcast_address, DEVICE_WOL_PORT))


def _prefix_of(cidr: str) -> str:
    """The prefix length a served network's CIDR names, empty when it names none."""
    try:
        return str(ipaddress.ip_network(cidr, strict=False).prefixlen)
    except ValueError:
        return ""


def _build_magic_packet(mac_address: str) -> bytes:
    cleaned = mac_address.replace(":", "").replace("-", "").replace(".", "")
    if len(cleaned) != 12:
        raise ValueError(f"malformed MAC address {mac_address!r}")
    try:
        hardware_address = bytes.fromhex(cleaned)
    except ValueError as error:
        raise ValueError(f"malformed MAC address {mac_address!r}") from error
    return b"\xff" * 6 + hardware_address * MAGIC_PACKET_REPEAT_COUNT
