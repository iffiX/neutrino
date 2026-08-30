"""Sending Wake-on-LAN magic packets to LAN devices.

Waking a machine needs three things outside this module: the target's NIC must
keep Wake-on-LAN armed (``ethtool -s <iface> wol g``, persisted), its firmware
must allow it, and the packet must reach the target's link. The last one is why
the packet is broadcast on the LAN interface rather than sent to a unicast
address.
"""

import socket

from neutrino_hub.modules.devices.constants import DEVICE_WOL_PORT

MAGIC_PACKET_REPEAT_COUNT = 16


def send_magic_packet(mac_address: str, *, broadcast_address: str) -> None:
    """Broadcast a Wake-on-LAN magic packet.

    Args:
        mac_address: Target MAC, with or without separators.
        broadcast_address: LAN broadcast address, for example
            ``192.168.100.255``.

    Raises:
        ValueError: If the MAC address is malformed.
        OSError: If the packet cannot be sent.
    """
    payload = _build_magic_packet(mac_address)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, (broadcast_address, DEVICE_WOL_PORT))


def _build_magic_packet(mac_address: str) -> bytes:
    cleaned = mac_address.replace(":", "").replace("-", "").replace(".", "")
    if len(cleaned) != 12:
        raise ValueError(f"malformed MAC address {mac_address!r}")
    try:
        hardware_address = bytes.fromhex(cleaned)
    except ValueError as error:
        raise ValueError(f"malformed MAC address {mac_address!r}") from error
    return b"\xff" * 6 + hardware_address * MAGIC_PACKET_REPEAT_COUNT
