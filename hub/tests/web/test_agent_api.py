"""The agent-facing API: joining, beating, and leaving.

The registry is replaced with one held in memory, so what is exercised is the
request path — that a machine can introduce itself with a ticket, that a
heartbeat carries the desired features back, and that an agent saying goodbye
stops the panel treating the device as managed while keeping everything its
owner typed.
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.routers import agent as agent_router


class FakeRegistry:
    """A registry of one device, in memory."""

    instance = None

    def __init__(self):
        # The router builds its own registry per request, so state lives on
        # the class rather than the instance.
        FakeRegistry.instance = self

    @classmethod
    def reset(cls, device: ManagedDevice) -> None:
        cls.device = device

    def get(self, mac_address):
        if mac_address.lower() == FakeRegistry.device.mac_address:
            return FakeRegistry.device
        return ManagedDevice(mac_address=mac_address.lower())

    def find_by_client_token(self, token):
        stored = FakeRegistry.device.client.token
        return FakeRegistry.device if stored and stored == token else None

    def record_heartbeat(self, mac_address, *, version, seen_at):
        FakeRegistry.device.client.version = version
        FakeRegistry.device.client.last_seen = seen_at

    def set_feature(self, mac_address, feature, is_enabled):
        FakeRegistry.device.client.features[feature] = is_enabled
        return FakeRegistry.device

    def set_ai_key_id(self, mac_address, key_id):
        FakeRegistry.device.client.ai_key_id = key_id

    def annotate(self, mac_address, annotation):
        FakeRegistry.device.name = annotation.get("name")
        return FakeRegistry.device

    def issue_client_token(self, mac_address):
        FakeRegistry.device.client.token = "issued-token"
        return "issued-token"

    def forget_client(self, mac_address):
        client = FakeRegistry.device.client
        client.token = None
        client.version = None
        client.last_seen = None
        client.features = {}


class FakeRuntime:
    """Only the parts of the runtime these routes touch."""

    def __init__(self):
        self.client_metrics = {}
        self.client_features = {}
        self.client_platform = {}
        self.enrollments = {}
        self.settings = {"listen_port": 80}

    def take_client_commands(self, mac_address):
        return []

    def network(self):
        return _EmptyNetwork()


class _EmptyNetwork:
    lan_interfaces: list = []


@pytest.fixture()
def api(monkeypatch):
    device = ManagedDevice(
        mac_address="aa:bb:cc:dd:ee:ff",
        name="testbox",
        ssh={"host": "10.0.0.5", "username": "me"},
        client=DeviceClientInfo(
            token="device-token", last_seen="2026-01-01T00:00:00+00:00"
        ),
    )
    FakeRegistry.reset(device)
    monkeypatch.setattr(agent_router, "DeviceRegistry", FakeRegistry)
    # The catalog is read from the repo's manifests; a small fixed one keeps
    # the test about the protocol rather than about what ships today.
    monkeypatch.setattr(
        agent_router,
        "load_catalog",
        lambda: {"anydesk": {"name": "anydesk", "kind": "package"}},
    )

    app = FastAPI()
    app.include_router(agent_router.router)
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), runtime, device


def test_heartbeat_returns_desired_features_and_catalog(api):
    client, runtime, device = api
    device.client.features = {"anydesk": True}

    response = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "testbox",
            "client_version": "0.3.0",
            "metrics": {"cpu_percent": 4.0},
            "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
            "catalog_hash": "stale",
            "features": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["desired_features"]["anydesk"]["is_enabled"] is True
    # A stale hash gets the catalog; a matching one would not.
    assert body["catalog"] is not None
    assert runtime.client_metrics["aa:bb:cc:dd:ee:ff"]["cpu_percent"] == 4.0
    assert runtime.client_platform["aa:bb:cc:dd:ee:ff"]["arch"] == "amd64"


def test_heartbeat_applies_a_toggle_made_on_the_machine(api):
    client, _, device = api

    response = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "testbox",
            "client_version": "0.3.0",
            "feature_requests": {"anydesk": True},
        },
    )

    assert response.status_code == 200
    assert device.client.features["anydesk"] is True
    assert response.json()["desired_features"]["anydesk"]["is_enabled"] is True


def test_unknown_token_is_refused(api):
    client, _, _ = api
    response = client.post(
        "/api/agent/heartbeat",
        json={"token": "nonsense", "hostname": "x", "client_version": "0.3.0"},
    )
    assert response.status_code == 401


def test_leaving_drops_the_agent_but_keeps_the_device(api):
    client, runtime, device = api
    runtime.client_metrics["aa:bb:cc:dd:ee:ff"] = {"cpu_percent": 4.0}
    runtime.client_features["aa:bb:cc:dd:ee:ff"] = {"anydesk": {"state": "installed"}}

    response = client.post("/api/agent/leave", json={"token": "device-token"})

    assert response.status_code == 200
    assert device.client.token is None
    # What the owner gave it survives; only the agent is gone.
    assert device.name == "testbox"
    assert device.ssh == {"host": "10.0.0.5", "username": "me"}
    assert runtime.client_metrics == {}
    assert runtime.client_features == {}


def test_leaving_with_an_unknown_token_is_refused(api):
    client, _, device = api
    response = client.post("/api/agent/leave", json={"token": "nonsense"})
    assert response.status_code == 401
    assert device.client.token is not None


def test_enrolling_with_a_ticket_issues_a_token(api):
    client, runtime, device = api
    runtime.enrollments["ticket"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 600,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "ticket",
            "device_id": "abc123",
            "hostname": "laptop",
            "platform": {"os": "windows", "family": "", "arch": "amd64"},
        },
    )

    assert response.status_code == 200
    assert response.json()["token"] == "issued-token"
    # The ticket is single-use.
    assert "ticket" not in runtime.enrollments


def test_a_ticket_spent_twice_is_refused_the_second_time(api):
    client, runtime, _ = api
    runtime.enrollments["once"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 600,
    }
    body = {"enrollment_token": "once", "device_id": "abc123", "hostname": "laptop"}

    assert client.post("/api/agent/enroll", json=body).status_code == 200
    assert client.post("/api/agent/enroll", json=body).status_code == 401


def test_expired_ticket_is_refused(api):
    client, runtime, _ = api
    runtime.enrollments["old"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() - 1,
    }

    response = client.post(
        "/api/agent/enroll",
        json={"enrollment_token": "old", "device_id": "abc123"},
    )

    assert response.status_code == 401


def test_an_unbound_enrollment_lands_on_the_device_its_mac_names(api):
    """The machine reports its MACs, so an unbound link folds it into the row
    a scan or an SSH setup already made instead of minting a second record."""
    client, runtime, device = api
    runtime.enrollments["t1"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 60,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "t1",
            "device_id": "abc123",
            "mac_addresses": ["11:22:33:44:55:66", "AA:BB:CC:DD:EE:FF"],
        },
    )

    assert response.status_code == 200
    assert response.json()["mac_address"] == device.mac_address


def test_an_unknown_reported_mac_still_keys_by_mac(api):
    """A real MAC, even an unknown one, is what a later scan merges by."""
    client, runtime, _ = api
    runtime.enrollments["t2"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 60,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "t2",
            "device_id": "abc123",
            "mac_addresses": ["11:22:33:44:55:66"],
        },
    )

    assert response.json()["mac_address"] == "11:22:33:44:55:66"


def test_nothing_usable_reported_keys_by_machine_id(api):
    client, runtime, _ = api
    runtime.enrollments["t3"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 60,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "t3",
            "device_id": "abc123",
            "mac_addresses": ["not-a-mac"],
        },
    )

    assert response.json()["mac_address"] == "id:abc123"
