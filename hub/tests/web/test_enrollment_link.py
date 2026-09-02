"""What a minted enrollment link carries: the agent channel, pinned.

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

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router

FINGERPRINT = "cd" * 32


class FakeRuntime:
    def __init__(self, *, settings=None, addresses=("192.168.8.1",)):
        self.settings = settings or {}
        self.enrollments = {}
        self._addresses = addresses

    def network(self):
        interfaces = [
            SimpleNamespace(lan=SimpleNamespace(address=address))
            for address in self._addresses
        ]
        return SimpleNamespace(lan_interfaces=interfaces)


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


def test_a_hub_without_a_certificate_mints_no_ticket(monkeypatch):
    def missing():
        raise FileNotFoundError("no certificate")

    monkeypatch.setattr(devices_router, "certificate_fingerprint", missing)
    runtime = FakeRuntime()

    answer = client_for(runtime).post("/api/devices/enrollment", json={"name": ""})

    assert answer.status_code == 409
    assert answer.json()["detail"] == {"code": "agent_tls_missing"}
    assert runtime.enrollments == {}
