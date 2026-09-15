"""Where a magic packet goes, whose MAC it carries, and what one refusal means.

A packet is broadcast on every served network, because which one the
sleeping device is on cannot be known while it sleeps. Never on an overlay: a
tunnel has no broadcast domain, and its device refuses the packet outright,
which must not stop the packet for the LAN. The packet names the MAC the
device's agent most recently ran its socket on, and a device that has never
reported one is refused.
"""

import pytest
from fastapi import HTTPException

from neutrino_hub.modules.devices.registry import ManagedDevice
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.web.routers import devices as devices_router

from tests.conftest import lan_entry, network_config, wan_entry

DEVICE = "device-one"
LINK_MAC = "aa:bb:cc:dd:ee:ff"


class FakeRuntime:
    def __init__(self, network: RouterNetworkConfig):
        self._network = network

    def network(self) -> RouterNetworkConfig:
        return self._network


class FakeRegistry:
    device: ManagedDevice

    def get(self, device_id: str):
        return FakeRegistry.device if device_id == FakeRegistry.device.id else None


@pytest.fixture(autouse=True)
def stored(monkeypatch):
    """One stored device whose agent last ran on the LAN MAC."""
    FakeRegistry.device = ManagedDevice(
        id=DEVICE, name="box", mac_addresses=[LINK_MAC], link_mac=LINK_MAC
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", FakeRegistry)


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
        lambda mac, *, broadcast_address: sent.append((mac, broadcast_address)),
    )

    result = devices_router.wake(DEVICE, runtime=gateway)

    assert result.is_sent is True
    assert sent == [(LINK_MAC, "192.168.100.255")]
    assert "10.126.126" not in result.message


def test_a_device_that_never_reported_a_mac_is_refused(gateway, monkeypatch):
    FakeRegistry.device.link_mac = ""
    monkeypatch.setattr(
        devices_router, "send_magic_packet", lambda mac, *, broadcast_address: None
    )

    with pytest.raises(HTTPException) as refused:
        devices_router.wake(DEVICE, runtime=gateway)

    assert refused.value.status_code == 409
    assert refused.value.detail == {
        "code": "wol_no_mac",
        "params": {"device_id": DEVICE},
    }


def test_an_unknown_device_is_refused_typed(gateway):
    with pytest.raises(HTTPException) as refused:
        devices_router.wake("nonsense", runtime=gateway)

    assert refused.value.status_code == 404
    assert refused.value.detail["code"] == "device_unknown"


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

    result = devices_router.wake(DEVICE, runtime=FakeRuntime(network))

    assert result.is_sent is True
    assert result.message == "magic packet sent to 192.168.101.255"


def test_every_domain_refusing_is_the_failure_it_says(monkeypatch):
    network = network_config(lan_entry("enp1s0", address="192.168.100.1"))
    monkeypatch.setattr(devices_router, "device_addresses", lambda: {})

    def send(mac, *, broadcast_address):
        raise OSError(126, "Required key not available")

    monkeypatch.setattr(devices_router, "send_magic_packet", send)

    result = devices_router.wake(DEVICE, runtime=FakeRuntime(network))

    assert result.is_sent is False
    assert "192.168.100.255" in result.message
    assert "Required key" in result.message
