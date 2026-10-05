"""Every address the hub answers the channel on.

The set is the firewall's: a served network at its configured address, any
other exposed interface at the address its live link holds, an unexposed
interface nowhere, and an exposed NetBird overlay by its address and, when
the daemon reports one, by its name. The port is the agent port from the
settings, and one address appears once.
"""

import pytest

from neutrino_hub.modules.overlay.direct_config import OverlayDirectConfig
from neutrino_hub.modules.overlay.relay_config import OverlayRelayConfig
from neutrino_hub.web import channel_addresses
from fastapi import HTTPException

from neutrino_hub.web.channel_addresses import (
    channel_urls,
    enrollment_link_parts,
    own_agent_urls,
)
from tests.conftest import lan_entry, network_config, wan_entry

LIVE = {
    "enp2s0": "203.0.113.7/24",
    "enp1s0": "192.168.8.1/24",
    "wt0": "100.88.178.129/16",
    "easytier": "10.0.0.1/24",
}


class FakeRuntime:
    def __init__(self, network, *, settings=None):
        self.settings = settings or {}
        self._network = network

    def network(self):
        return self._network


class NamedOverlay:
    """NetBird's part, its daemon reporting this box's overlay name."""

    fqdn = "neutrino.netbird.cloud"

    def name(self):
        return NamedOverlay.fqdn


class NamelessOverlay:
    def name(self):
        return ""


def _parts(part):
    """Stand a part in for NetBird's own."""

    def parts():
        return {"netbird": part}

    return parts


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(channel_addresses, "device_addresses", lambda: dict(LIVE))
    monkeypatch.setattr(channel_addresses, "overlay_parts", _parts(NamedOverlay))
    monkeypatch.setattr(channel_addresses, "read_relay", OverlayRelayConfig)
    monkeypatch.setattr(channel_addresses, "read_direct", OverlayDirectConfig)


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


@pytest.mark.feature("netbird")
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


@pytest.mark.feature("netbird")
def test_an_overlay_that_is_not_exposed_is_not_asked_for_its_name(live, monkeypatch):
    runtime = FakeRuntime(
        network_config(
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[{"provider": "netbird", "is_exposed": False}],
        )
    )

    def not_asked():
        raise AssertionError("the daemon was asked")

    monkeypatch.setattr(channel_addresses, "overlay_parts", _parts(not_asked))

    assert channel_urls(runtime) == ["https://192.168.8.1:8443"]


@pytest.mark.feature("netbird")
def test_a_daemon_with_no_name_adds_none(live, monkeypatch):
    monkeypatch.setattr(channel_addresses, "overlay_parts", _parts(NamelessOverlay))
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


@pytest.mark.feature("netbird")
def test_two_overlays_name_the_hub_in_each_network(live):
    """A client on either overlay reaches the hub at its address there, and
    one moving from one overlay to the other already holds both."""
    runtime = FakeRuntime(
        network_config(
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[
                {"provider": "netbird", "is_enabled": True},
                {"provider": "easytier", "is_enabled": True},
            ],
        )
    )

    assert channel_urls(runtime) == [
        "https://192.168.8.1:8443",
        "https://100.88.178.129:8443",
        "https://10.0.0.1:8443",
        "https://neutrino.netbird.cloud:8443",
    ]


@pytest.mark.feature("netbird")
def test_an_overlay_turned_off_is_named_nowhere(live):
    runtime = FakeRuntime(
        network_config(
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[
                {"provider": "netbird", "is_enabled": False},
                {"provider": "easytier", "is_enabled": True},
            ],
        )
    )

    assert channel_urls(runtime) == [
        "https://192.168.8.1:8443",
        "https://10.0.0.1:8443",
    ]


# --- the relay ---


def relay_box(monkeypatch, relay: OverlayRelayConfig, *, is_key_stored=True):
    monkeypatch.setattr(channel_addresses, "read_relay", lambda: relay)
    monkeypatch.setattr(
        channel_addresses, "is_relay_configured", lambda config: is_key_stored
    )
    return FakeRuntime(
        network_config(
            wan_entry("enp2s0"),
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[],
        )
    )


def test_the_relays_address_is_the_last_member_while_it_is_on(live, monkeypatch):
    runtime = relay_box(
        monkeypatch,
        OverlayRelayConfig(
            is_enabled=True, host="vps.example.org", account="r", key_id="k"
        ),
    )

    assert channel_urls(runtime) == [
        "https://192.168.8.1:8443",
        "https://vps.example.org:8443",
    ]


def test_an_ipv6_relay_host_is_written_in_brackets(live, monkeypatch):
    runtime = relay_box(
        monkeypatch,
        OverlayRelayConfig(
            is_enabled=True,
            host="2001:db8::5",
            account="r",
            key_id="k",
            public_port=18443,
        ),
    )

    assert channel_urls(runtime)[-1] == "https://[2001:db8::5]:18443"


def test_a_relay_that_is_off_or_not_configured_adds_nothing(live, monkeypatch):
    configured = OverlayRelayConfig(host="vps", account="r", key_id="k")
    off = relay_box(monkeypatch, configured)
    assert channel_urls(off) == ["https://192.168.8.1:8443"]

    unstored = relay_box(
        monkeypatch,
        OverlayRelayConfig(is_enabled=True, host="vps", account="r", key_id="k"),
        is_key_stored=False,
    )
    assert channel_urls(unstored) == ["https://192.168.8.1:8443"]


# --- Direct ---


@pytest.mark.parametrize("is_direct", [False, True])
@pytest.mark.parametrize("has_public", [False, True])
@pytest.mark.parametrize("is_relay", [False, True])
def test_urls_list_the_exposed_set_then_direct_then_its_public_address_then_the_relay(
    live, monkeypatch, is_direct, has_public, is_relay
):
    runtime = relay_box(
        monkeypatch,
        OverlayRelayConfig(
            is_enabled=is_relay, host="vps.example.org", account="r", key_id="k"
        ),
    )
    direct = OverlayDirectConfig(
        is_enabled=is_direct,
        public_host="hub.example.org" if has_public else "",
        public_port=443,
    )
    monkeypatch.setattr(channel_addresses, "read_direct", lambda: direct)

    expected = ["https://192.168.8.1:8443"]
    if is_direct:
        expected.append("https://203.0.113.7:8443")
        if has_public:
            expected.append("https://hub.example.org:443")
    if is_relay:
        expected.append("https://vps.example.org:8443")
    assert channel_urls(runtime) == expected


def test_direct_adds_no_interface_whose_role_is_disabled(live, monkeypatch):
    monkeypatch.setattr(
        channel_addresses, "read_direct", lambda: OverlayDirectConfig(is_enabled=True)
    )
    runtime = FakeRuntime(
        network_config(
            lan_entry("enp1s0", address="192.168.8.1"),
            {"name": "enp2s0", "role": "disabled", "is_exposed": False},
            overlays=[],
        )
    )

    assert channel_urls(runtime) == ["https://192.168.8.1:8443"]


def test_a_direct_file_that_does_not_read_is_direct_off(live, monkeypatch):
    def unreadable():
        raise ValueError("not JSON")

    monkeypatch.setattr(channel_addresses, "read_direct", unreadable)
    runtime = relay_box(monkeypatch, OverlayRelayConfig())

    assert channel_urls(runtime) == ["https://192.168.8.1:8443"]


def test_the_hubs_own_agent_is_given_loopback_before_direct(live, monkeypatch):
    monkeypatch.setattr(
        channel_addresses,
        "read_direct",
        lambda: OverlayDirectConfig(is_enabled=True, public_host="hub.example.org"),
    )
    runtime = relay_box(monkeypatch, OverlayRelayConfig())

    assert own_agent_urls(runtime) == [
        "https://127.0.0.1:8443",
        "https://192.168.8.1:8443",
        "https://203.0.113.7:8443",
        "https://hub.example.org:8443",
    ]


# --- the hub's own agent ---


def test_the_hubs_own_agent_is_given_loopback_alone_when_nothing_is_exposed(live):
    runtime = FakeRuntime(
        network_config(overlays=[]), settings={"agent_listen_port": 9443}
    )

    assert channel_urls(runtime) == []
    assert own_agent_urls(runtime) == ["https://127.0.0.1:9443"]


def test_the_hubs_own_agent_is_given_loopback_before_the_exposed_set(live):
    runtime = FakeRuntime(
        network_config(lan_entry("enp1s0", address="192.168.8.1"), overlays=[])
    )

    assert own_agent_urls(runtime) == [
        "https://127.0.0.1:8443",
        "https://192.168.8.1:8443",
    ]


def test_only_a_link_for_another_machine_is_refused_with_nothing_exposed(
    live, monkeypatch
):
    monkeypatch.setattr(channel_addresses, "certificate_fingerprint", lambda: "f" * 64)
    runtime = FakeRuntime(network_config(overlays=[]))

    urls, fingerprint = enrollment_link_parts(runtime, is_hub=True)
    with pytest.raises(HTTPException) as refused:
        enrollment_link_parts(runtime)

    assert urls == ["https://127.0.0.1:8443"]
    assert fingerprint == "f" * 64
    assert refused.value.detail["code"] == "no_reachable_address"
