"""Where a magic packet goes, and what one refusal means for the rest.

A packet is broadcast on every served network, because which one the
sleeping device is on cannot be known while it sleeps. Never on an overlay: a
tunnel has no broadcast domain, and its device refuses the packet outright,
which must not stop the packet for the LAN.
"""

import pytest

from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.web.routers import devices as devices_router

from tests.conftest import lan_entry, network_config, wan_entry


class FakeRuntime:
    def __init__(self, network: RouterNetworkConfig):
        self._network = network

    def network(self) -> RouterNetworkConfig:
        return self._network


@pytest.fixture
def gateway(monkeypatch):
    """A router with one served network and an exposed overlay on it."""
    network = network_config(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        overlays=[{"provider": "easytier", "is_exposed": True}],
    )
    monkeypatch.setattr(
        devices_router, "device_addresses", lambda: {"easytier": "10.126.126.2/24"}
    )
    return FakeRuntime(network)


def test_the_packet_goes_to_the_served_network_and_never_the_overlay(
    gateway, monkeypatch
):
    sent = []
    monkeypatch.setattr(
        devices_router,
        "send_magic_packet",
        lambda mac, *, broadcast_address: sent.append(broadcast_address),
    )

    result = devices_router.wake("aa:bb:cc:dd:ee:ff", runtime=gateway)

    assert result.is_sent is True
    assert sent == ["192.168.100.255"]
    assert "10.126.126" not in result.message


def test_the_overlay_still_counts_for_reaching_the_hub(gateway):
    assert devices_router._facing_cidrs(gateway) == [
        "192.168.100.1/24",
        "10.126.126.2/24",
    ]
    assert devices_router._facing_cidrs(gateway, is_overlay_included=False) == [
        "192.168.100.1/24"
    ]


def test_one_domain_refusing_does_not_stop_the_others(monkeypatch):
    network = network_config(
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("wlp3s0", address="192.168.101.1"),
    )
    monkeypatch.setattr(devices_router, "device_addresses", lambda: {})

    def send(mac, *, broadcast_address):
        if broadcast_address.startswith("192.168.100."):
            raise OSError(126, "Required key not available")

    monkeypatch.setattr(devices_router, "send_magic_packet", send)

    result = devices_router.wake("aa:bb:cc:dd:ee:ff", runtime=FakeRuntime(network))

    assert result.is_sent is True
    assert result.message == "magic packet sent to 192.168.101.255"


def test_every_domain_refusing_is_the_failure_it_says(monkeypatch):
    network = network_config(lan_entry("enp1s0", address="192.168.100.1"))
    monkeypatch.setattr(devices_router, "device_addresses", lambda: {})

    def send(mac, *, broadcast_address):
        raise OSError(126, "Required key not available")

    monkeypatch.setattr(devices_router, "send_magic_packet", send)

    result = devices_router.wake("aa:bb:cc:dd:ee:ff", runtime=FakeRuntime(network))

    assert result.is_sent is False
    assert "192.168.100.255" in result.message
    assert "Required key" in result.message
