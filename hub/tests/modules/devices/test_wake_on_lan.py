"""Where a magic packet is broadcast, and how it leaves.

A router or side gateway hub broadcasts on each network it serves; a server
hub on the network of each exposed interface that holds an IPv4 address; an
overlay never gets one. The packet goes to the network's own broadcast
address from a socket bound to the hub's address on that network, the same
calls on Linux, macOS and Windows.
"""

import socket

import pytest

from neutrino_hub.modules.devices import wake_on_lan
from neutrino_hub.modules.devices.wake_on_lan import (
    WakeTarget,
    send_magic_packet,
    wake_targets,
)
from tests.conftest import lan_entry, network_config, wan_entry

MAC = "aa:bb:cc:dd:ee:ff"


def exposed(name: str, *, is_exposed: bool = True) -> dict:
    """One interface of a server hub, which holds no role."""
    return {"name": name, "role": "disabled", "is_exposed": is_exposed}


def never_read():
    pytest.fail("a hub that serves its networks reads no live address")


def test_a_server_broadcasts_on_its_one_exposed_network():
    network = network_config(exposed("enp3s0"), overlays=[], mode="server")

    assert wake_targets(network, lambda: {"enp3s0": "192.168.1.54/24"}) == [
        WakeTarget(broadcast_address="192.168.1.255", source_address="192.168.1.54")
    ]


def test_a_server_broadcasts_on_each_exposed_network_and_no_closed_one():
    network = network_config(
        exposed("enp3s0"),
        exposed("wlp4s0"),
        exposed("enp5s0", is_exposed=False),
        overlays=[],
        mode="server",
    )
    addresses = {
        "enp3s0": "192.168.1.54/24",
        "wlp4s0": "10.20.0.7/16",
        "enp5s0": "172.16.9.2/24",
    }

    assert wake_targets(network, lambda: addresses) == [
        WakeTarget("192.168.1.255", "192.168.1.54"),
        WakeTarget("10.20.255.255", "10.20.0.7"),
    ]


def test_an_exposed_overlay_beside_a_lan_interface_gets_nothing():
    network = network_config(
        exposed("enp3s0"),
        overlays=[{"provider": "easytier", "is_exposed": True, "is_enabled": True}],
        mode="server",
    )
    (overlay,) = network.exposed_overlay_device_names
    addresses = {"enp3s0": "192.168.1.54/24", overlay: "10.126.126.1/24"}

    assert wake_targets(network, lambda: addresses) == [
        WakeTarget("192.168.1.255", "192.168.1.54")
    ]


def test_a_server_with_nothing_exposed_or_no_address_has_no_network():
    closed = network_config(exposed("enp3s0", is_exposed=False), mode="server")
    opened = network_config(exposed("enp3s0"), overlays=[], mode="server")

    assert wake_targets(closed, lambda: {"enp3s0": "192.168.1.54/24"}) == []
    assert wake_targets(opened, lambda: {}) == []
    assert wake_targets(opened, lambda: {"enp3s0": "198.51.100.1/31"}) == []


def test_a_router_broadcasts_on_its_served_networks_as_before():
    network = network_config(
        wan_entry("enp2s0", is_exposed=True),
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("wlp3s0", address="192.168.101.1", is_exposed=False),
        overlays=[{"provider": "easytier", "is_exposed": True, "is_enabled": True}],
    )

    assert wake_targets(network, never_read) == [
        WakeTarget("192.168.100.255", "192.168.100.1"),
        WakeTarget("192.168.101.255", "192.168.101.1"),
    ]


class RecordingSocket:
    """A UDP socket that records what is asked of it."""

    made: list = []

    def __init__(self, family, kind):
        self.calls = [("socket", family, kind)]
        RecordingSocket.made.append(self)

    def setsockopt(self, level, option, value):
        self.calls.append(("setsockopt", level, option, value))

    def bind(self, address):
        self.calls.append(("bind", address))

    def sendto(self, payload, address):
        self.calls.append(("sendto", len(payload), address))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sockets(monkeypatch) -> list:
    RecordingSocket.made = []
    monkeypatch.setattr(wake_on_lan.socket, "socket", RecordingSocket)
    return RecordingSocket.made


def expected_calls() -> list:
    return [
        ("socket", socket.AF_INET, socket.SOCK_DGRAM),
        ("setsockopt", socket.SOL_SOCKET, socket.SO_BROADCAST, 1),
        ("bind", ("192.168.1.54", 0)),
        ("sendto", 102, ("192.168.1.255", 9)),
    ]


def test_on_linux_the_packet_leaves_from_the_networks_own_address(sockets):
    send_magic_packet(
        MAC, broadcast_address="192.168.1.255", source_address="192.168.1.54"
    )

    (made,) = sockets
    assert made.calls == expected_calls()


def test_elsewhere_the_packet_leaves_the_same_way(elsewhere, sockets):
    send_magic_packet(
        MAC, broadcast_address="192.168.1.255", source_address="192.168.1.54"
    )

    (made,) = sockets
    assert made.calls == expected_calls()


def test_with_no_source_the_system_chooses(sockets):
    send_magic_packet(MAC, broadcast_address="192.168.1.255")

    (made,) = sockets
    assert [call[0] for call in made.calls] == ["socket", "setsockopt", "sendto"]


def test_a_malformed_mac_is_refused(sockets):
    with pytest.raises(ValueError):
        send_magic_packet("aa:bb", broadcast_address="192.168.1.255")
    assert sockets == []
