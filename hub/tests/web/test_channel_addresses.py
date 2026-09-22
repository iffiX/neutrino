"""Every address the hub answers the channel on.

The set is the firewall's: a served network at its configured address, any
other exposed interface at the address its live link holds, an unexposed
interface nowhere, and an exposed NetBird overlay by its address and, when
the daemon reports one, by its name. The port is the agent port from the
settings, and one address appears once.
"""

import pytest

from neutrino_hub.modules.netbird.ops import NetbirdState
from neutrino_hub.web import channel_addresses
from neutrino_hub.web.channel_addresses import channel_urls
from tests.conftest import lan_entry, network_config, wan_entry

LIVE = {
    "enp2s0": "203.0.113.7/24",
    "enp1s0": "192.168.8.1/24",
    "wt0": "100.88.178.129/16",
}


class FakeRuntime:
    def __init__(self, network, *, settings=None):
        self.settings = settings or {}
        self._network = network

    def network(self):
        return self._network


class NamedOverlay:
    """A NetBird daemon reporting this box's overlay name."""

    fqdn = "neutrino.netbird.cloud"

    def survey(self):
        return NetbirdState(is_installed=True, fqdn=NamedOverlay.fqdn)


class NamelessOverlay:
    def survey(self):
        return NetbirdState(is_installed=False)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(channel_addresses, "device_addresses", lambda: dict(LIVE))
    monkeypatch.setattr(channel_addresses, "NetbirdStatusReader", NamedOverlay)


def test_a_served_network_is_named_by_its_configured_address(live):
    runtime = FakeRuntime(
        network_config(
            wan_entry("enp2s0"),
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[],
        ),
        settings={"agent_listen_port": 9443},
    )

    assert channel_urls(runtime) == ["https://192.168.8.1:9443"]


def test_an_exposed_uplink_is_named_by_its_live_address_and_an_unexposed_lan_not(
    live,
):
    runtime = FakeRuntime(
        network_config(
            wan_entry("enp2s0", is_exposed=True),
            lan_entry("enp1s0", address="192.168.8.1", is_exposed=False),
            overlays=[],
        )
    )

    assert channel_urls(runtime) == ["https://203.0.113.7:8443"]


def test_an_exposed_overlay_is_named_by_its_address_and_its_name(live):
    runtime = FakeRuntime(
        network_config(
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[{"provider": "netbird", "is_exposed": True}],
        )
    )

    assert channel_urls(runtime) == [
        "https://192.168.8.1:8443",
        "https://100.88.178.129:8443",
        "https://neutrino.netbird.cloud:8443",
    ]


def test_an_overlay_that_is_not_exposed_is_not_asked_for_its_name(live, monkeypatch):
    runtime = FakeRuntime(
        network_config(
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[{"provider": "netbird", "is_exposed": False}],
        )
    )

    def not_asked():
        raise AssertionError("the daemon was asked")

    monkeypatch.setattr(channel_addresses, "NetbirdStatusReader", not_asked)

    assert channel_urls(runtime) == ["https://192.168.8.1:8443"]


def test_a_daemon_with_no_name_adds_none(live, monkeypatch):
    monkeypatch.setattr(channel_addresses, "NetbirdStatusReader", NamelessOverlay)
    runtime = FakeRuntime(
        network_config(
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[{"provider": "netbird", "is_exposed": True}],
        )
    )

    assert channel_urls(runtime) == [
        "https://192.168.8.1:8443",
        "https://100.88.178.129:8443",
    ]


def test_an_interface_with_no_address_yet_is_left_out(live, monkeypatch):
    monkeypatch.setattr(channel_addresses, "device_addresses", lambda: {})
    runtime = FakeRuntime(
        network_config(
            wan_entry("enp2s0", is_exposed=True),
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[],
        )
    )

    assert channel_urls(runtime) == ["https://192.168.8.1:8443"]
