"""What a generated enrollment link carries: the agent channel, pinned.

The link is the one thing that crosses to a machine before any trust exists,
so its payload has to hold everything a first connection needs — every served
address on the agent's TLS port, and the fingerprint that decides whether the
answer is the hub at all.
"""

import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router

FINGERPRINT = "cd" * 32


class FakeRuntime:
    def __init__(self, *, settings=None, addresses=("192.168.8.1",), overlays=()):
        self.events = PanelEventBus()
        self.settings = settings or {}
        self.enrollments = {}
        self._addresses = addresses
        self._overlays = overlays

    def network(self):
        interfaces = [
            SimpleNamespace(
                is_lan=True,
                device_name=f"lan{index}",
                lan=SimpleNamespace(address=address, cidr=f"{address}/24"),
            )
            for index, address in enumerate(self._addresses)
        ]
        return SimpleNamespace(
            device_facing_interfaces=interfaces,
            exposed_overlay_device_names=list(self._overlays),
        )


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


@pytest.fixture
def fingerprinted(monkeypatch):
    monkeypatch.setattr(devices_router, "certificate_fingerprint", lambda: FINGERPRINT)


def test_the_link_points_at_the_agent_port_over_tls(fingerprinted):
    runtime = FakeRuntime(
        settings={"agent_listen_port": 9443},
        addresses=("192.168.8.1", "", "10.0.0.1"),
    )

    answer = client_for(runtime).post("/api/devices/enrollment", json={"name": ""})

    assert answer.status_code == 200
    payload = decoded(answer.json()["link"])
    assert payload["urls"] == ["https://192.168.8.1:9443", "https://10.0.0.1:9443"]
    assert payload["fp"] == FINGERPRINT


def test_the_agent_port_defaults_beside_the_panel_port(fingerprinted):
    runtime = FakeRuntime()

    answer = client_for(runtime).post("/api/devices/enrollment", json={"name": ""})

    assert decoded(answer.json()["link"])["urls"] == ["https://192.168.8.1:8443"]


def test_a_server_generates_from_its_exposed_ports_live_address(
    fingerprinted, monkeypatch
):
    runtime = FakeRuntime(addresses=())
    exposed = SimpleNamespace(is_lan=False, device_name="enp1s0", lan=None)
    runtime.network = lambda: SimpleNamespace(
        device_facing_interfaces=[exposed], exposed_overlay_device_names=[]
    )

    class FakeReader:
        def link(self, name):
            assert name == "enp1s0"
            return SimpleNamespace(ipv4_address="192.168.100.7/24")

    monkeypatch.setattr(devices_router, "RouterLinkStatus", FakeReader)

    answer = client_for(runtime).post("/api/devices/enrollment", json={"name": ""})

    assert answer.status_code == 200
    assert decoded(answer.json()["link"])["urls"] == ["https://192.168.100.7:8443"]


def test_the_link_carries_the_overlay_a_remote_machine_is_the_only_one_on(
    fingerprinted, monkeypatch
):
    """A machine that reaches this hub only over the overlay has no other
    address to be told, and the link is the whole of what it is told."""
    runtime = FakeRuntime(overlays=["wt0"])
    monkeypatch.setattr(
        devices_router,
        "device_addresses",
        lambda: {"enp1s0": "192.168.8.1/24", "wt0": "100.88.178.129/16"},
    )

    answer = client_for(runtime).post("/api/devices/enrollment", json={"name": ""})

    assert decoded(answer.json()["link"])["urls"] == [
        "https://192.168.8.1:8443",
        "https://100.88.178.129:8443",
    ]


def test_generating_again_replaces_the_outstanding_ticket(fingerprinted):
    runtime = FakeRuntime()
    client = client_for(runtime)

    first = client.post("/api/devices/enrollment", json={"name": "one"})
    second = client.post("/api/devices/enrollment", json={"name": "two"})

    assert first.status_code == 200 and second.status_code == 200
    assert len(runtime.enrollments) == 1
    token = decoded(second.json()["link"])["token"]
    assert runtime.enrollments[token]["name"] == "two"


def test_a_hub_without_a_certificate_generates_no_ticket(monkeypatch):
    def missing():
        raise FileNotFoundError("no certificate")

    monkeypatch.setattr(devices_router, "certificate_fingerprint", missing)
    runtime = FakeRuntime()

    answer = client_for(runtime).post("/api/devices/enrollment", json={"name": ""})

    assert answer.status_code == 409
    assert answer.json()["detail"] == {"code": "agent_tls_missing", "params": {}}
    assert runtime.enrollments == {}
