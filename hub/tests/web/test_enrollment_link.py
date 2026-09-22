"""What a generated enrollment link carries: the agent channel, pinned.

The link is the one thing that crosses to a machine before any trust exists,
so its payload has to hold everything a first connection needs: every
address the agent port answers on, and the fingerprint that decides whether
the answer is the hub at all. The address set is the firewall's: every
exposed interface, whatever its role, and every exposed overlay.
"""

import base64
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.netbird.ops import NetbirdState
from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer
from neutrino_hub.web import channel_addresses
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import device as devices_router
from tests.conftest import lan_entry, network_config, wan_entry

FINGERPRINT = "cd" * 32
ROUTING_DIRECT = {"is_proxy_enabled": False, "is_local_proxy_enabled": False}


class FakeRuntime:
    def __init__(self, network, *, settings=None):
        self.events = PanelEventBus()
        self.settings = settings or {}
        self.enrollments = {}
        self._network = network

    def network(self):
        return self._network


def client_for(runtime) -> TestClient:
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def decoded(link: str) -> dict:
    payload_text = link.removeprefix("neutrino://enroll/")
    padded = payload_text + "=" * (-len(payload_text) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def urls_of(runtime) -> list:
    answer = client_for(runtime).post(
        "/api/hub/device/enrollment/create", json={"name": ""}
    )
    assert answer.status_code == 200
    return decoded(answer.json()["link"])["urls"]


class NamelessOverlay:
    """A NetBird daemon that reports no name of its own."""

    def survey(self):
        return NetbirdState(is_installed=True, fqdn="")


@pytest.fixture
def fingerprinted(monkeypatch):
    monkeypatch.setattr(
        channel_addresses, "certificate_fingerprint", lambda: FINGERPRINT
    )


@pytest.fixture
def live_addresses(monkeypatch):
    """What the links hold right now, by kernel device."""
    addresses = {
        "enp2s0": "203.0.113.7/24",
        "enp1s0": "192.168.8.1/24",
        "enp3s0": "192.168.100.7/24",
        "wt0": "100.88.178.129/16",
    }
    monkeypatch.setattr(channel_addresses, "device_addresses", lambda: addresses)
    monkeypatch.setattr(channel_addresses, "NetbirdStatusReader", NamelessOverlay)
    return addresses


def test_the_link_points_at_the_agent_port_over_tls(fingerprinted, live_addresses):
    runtime = FakeRuntime(
        network_config(
            wan_entry("enp2s0"),
            lan_entry("enp1s0", address="192.168.8.1"),
            lan_entry("wlp3s0", address="10.0.0.1"),
            overlays=[],
        ),
        settings={"agent_listen_port": 9443},
    )

    answer = client_for(runtime).post(
        "/api/hub/device/enrollment/create", json={"name": ""}
    )

    assert answer.status_code == 200
    payload = decoded(answer.json()["link"])
    assert payload["urls"] == ["https://192.168.8.1:9443", "https://10.0.0.1:9443"]
    assert payload["fp"] == FINGERPRINT
    assert payload["role"] == "agent"


def test_the_agent_port_defaults_beside_the_panel_port(fingerprinted, live_addresses):
    runtime = FakeRuntime(
        network_config(lan_entry("enp1s0", address="192.168.8.1"), overlays=[])
    )

    assert urls_of(runtime) == ["https://192.168.8.1:8443"]


def test_an_exposed_uplink_is_in_the_link_and_an_unexposed_lan_is_not(
    fingerprinted, live_addresses
):
    """Exposure is the only control plane: a WAN somebody exposed answers
    the agent port at its live address, and a served network nobody exposed
    is not where a machine can be told to join."""
    runtime = FakeRuntime(
        network_config(
            wan_entry("enp2s0", is_exposed=True),
            lan_entry("enp1s0", address="192.168.8.1", is_exposed=False),
            overlays=[],
        )
    )

    assert urls_of(runtime) == ["https://203.0.113.7:8443"]


def test_a_server_generates_from_its_exposed_ports_live_address(
    fingerprinted, live_addresses
):
    runtime = FakeRuntime(
        network_config(
            {"name": "enp3s0", "role": "disabled", "is_exposed": True},
            overlays=[],
            mode="server",
        )
    )

    assert urls_of(runtime) == ["https://192.168.100.7:8443"]


def test_the_link_carries_the_overlay_a_remote_machine_is_the_only_one_on(
    fingerprinted, live_addresses
):
    """A machine that reaches this hub only over the overlay has no other
    address to be told, and the link is the whole of what it is told."""
    runtime = FakeRuntime(
        network_config(
            lan_entry("enp1s0", address="192.168.8.1"),
            overlays=[{"provider": "netbird", "is_exposed": True}],
        )
    )

    assert urls_of(runtime) == [
        "https://192.168.8.1:8443",
        "https://100.88.178.129:8443",
    ]


def test_the_links_address_set_is_the_firewalls_open_set(fingerprinted, live_addresses):
    """One test asserts the two are one set: what the ruleset accepts on
    is what the link names, exposed interfaces of every role and exposed
    overlays alike."""
    network = network_config(
        wan_entry("enp2s0", is_exposed=True),
        lan_entry("enp1s0", address="192.168.8.1", is_exposed=True),
        lan_entry("wlp3s0", address="10.0.0.1", is_exposed=False),
        overlays=[{"provider": "netbird", "is_exposed": True}],
    )
    ruleset = RouterNftRenderer(
        network=network, routing=ROUTING_DIRECT, xray_uid=999
    ).render()

    urls = urls_of(FakeRuntime(network))

    assert network.exposed_interfaces == ["enp2s0", "enp1s0", "wt0"]
    assert 'iifname { "enp2s0", "enp1s0", "wt0" } accept' in ruleset
    assert urls == [
        "https://203.0.113.7:8443",
        "https://192.168.8.1:8443",
        "https://100.88.178.129:8443",
    ]
    assert len(urls) == len(network.exposed_interfaces)


def test_generating_again_replaces_the_outstanding_ticket(
    fingerprinted, live_addresses
):
    runtime = FakeRuntime(
        network_config(lan_entry("enp1s0", address="192.168.8.1"), overlays=[])
    )
    client = client_for(runtime)

    first = client.post("/api/hub/device/enrollment/create", json={"name": "one"})
    second = client.post("/api/hub/device/enrollment/create", json={"name": "two"})

    assert first.status_code == 200 and second.status_code == 200
    assert len(runtime.enrollments) == 1
    token = decoded(second.json()["link"])["token"]
    assert runtime.enrollments[token]["name"] == "two"


def test_a_hub_without_a_certificate_generates_no_ticket(monkeypatch, live_addresses):
    def missing():
        raise FileNotFoundError("no certificate")

    monkeypatch.setattr(channel_addresses, "certificate_fingerprint", missing)
    runtime = FakeRuntime(
        network_config(lan_entry("enp1s0", address="192.168.8.1"), overlays=[])
    )

    answer = client_for(runtime).post(
        "/api/hub/device/enrollment/create", json={"name": ""}
    )

    assert answer.status_code == 409
    assert answer.json()["detail"] == {"code": "agent_tls_missing", "params": {}}
    assert runtime.enrollments == {}


def test_a_box_with_nothing_exposed_has_no_link_to_give(fingerprinted, live_addresses):
    runtime = FakeRuntime(
        network_config(
            lan_entry("enp1s0", address="192.168.8.1", is_exposed=False), overlays=[]
        )
    )

    answer = client_for(runtime).post(
        "/api/hub/device/enrollment/create", json={"name": ""}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "no_reachable_address"
