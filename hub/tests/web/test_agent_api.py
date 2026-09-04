"""The agent-facing API: joining, beating, and leaving.

The registry is replaced with one held in memory, so what is exercised is the
request path — that a machine can introduce itself with a ticket, that a
heartbeat carries the desired features back, and that an agent saying goodbye
stops the panel treating the device as managed while keeping everything its
owner typed.
"""

import hashlib
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.modules.cliproxyapi.ops import load_config as load_cliproxyapi_config
from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.routers import agent as agent_router
from tests.conftest import unlock_vault


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
        stored = FakeRegistry.device.client.token_sha256
        presented = hashlib.sha256(token.encode()).hexdigest()
        return FakeRegistry.device if stored and stored == presented else None

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
        FakeRegistry.device.client.token_sha256 = hashlib.sha256(
            b"issued-token"
        ).hexdigest()
        return "issued-token"

    def forget_client(self, mac_address):
        client = FakeRegistry.device.client
        client.token_sha256 = None
        client.version = None
        client.last_seen = None
        client.features = {}


class FakeRuntime:
    """Only the parts of the runtime these routes touch."""

    def __init__(self):
        self.client_metrics = {}
        self.client_features = {}
        self.client_platform = {}
        self.client_hostname = {}
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
            token_sha256=hashlib.sha256(b"device-token").hexdigest(),
            last_seen="2026-01-01T00:00:00+00:00",
        ),
    )
    FakeRegistry.reset(device)
    monkeypatch.setattr(agent_router, "DeviceRegistry", FakeRegistry)
    # Pinned so the version comparisons below are about the protocol, not
    # about what the checkout happens to be versioned.
    monkeypatch.setattr(agent_router, "HUB_VERSION", "1.2.3")
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


def test_a_dangling_ai_key_id_is_reissued_on_the_next_heartbeat(
    api, monkeypatch, tmp_path
):
    """A plaintext-era key is dropped on load, so the device gets a fresh one."""
    client, _, device = api
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    write_config(
        "cliproxyapi/cliproxyapi.json",
        {
            "listen_port": 8317,
            "client_keys": [{"id": "dropped", "name": "testbox", "key": "gone"}],
        },
    )
    device.client.ai_key_id = "dropped"
    device.client.features = {"ai_tools": True}

    response = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "testbox",
            "client_version": "0.3.0",
        },
    )

    assert response.status_code == 200
    config = response.json()["desired_features"]["ai_tools"]["config"]
    assert device.client.ai_key_id not in ("dropped", None)
    stored = load_cliproxyapi_config().client_keys
    assert [key.id for key in stored] == [device.client.ai_key_id]
    assert stored[0].open_key() == config["api_key"]
    assert config["api_key"] not in (
        tmp_path / "cliproxyapi/cliproxyapi.json"
    ).read_text(encoding="utf-8")

    # The reissue happens once: the next beat finds the key and touches nothing.
    reissued_id = device.client.ai_key_id
    response = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "testbox",
            "client_version": "0.3.0",
        },
    )
    assert response.status_code == 200
    assert device.client.ai_key_id == reissued_id
    assert [key.id for key in load_cliproxyapi_config().client_keys] == [reissued_id]


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
    assert device.client.token_sha256 is None
    # What the owner gave it survives; only the agent is gone.
    assert device.name == "testbox"
    assert device.ssh == {"host": "10.0.0.5", "username": "me"}
    assert runtime.client_metrics == {}
    assert runtime.client_features == {}


def test_leaving_with_an_unknown_token_is_refused(api):
    client, _, device = api
    response = client.post("/api/agent/leave", json={"token": "nonsense"})
    assert response.status_code == 401
    assert device.client.token_sha256 is not None


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
    a scan or an SSH setup already made instead of generating a second record."""
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


def test_replies_carry_the_hub_version(api):
    client, runtime, _ = api
    runtime.enrollments["ticket"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 600,
    }

    beaten = client.post(
        "/api/agent/heartbeat",
        json={"token": "device-token", "hostname": "x", "client_version": "1.2.3"},
    )
    enrolled = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "ticket",
            "device_id": "abc123",
            "client_version": "1.2.3",
        },
    )

    assert beaten.json()["hub_version"] == "1.2.3"
    assert enrolled.json()["hub_version"] == "1.2.3"


def test_a_newer_agent_is_turned_away_with_a_code(api):
    """A 409, never a 401: the token was fine, so the refusal must not feed
    the agent's self-unbind counter."""
    client, _, device = api

    refused = client.post(
        "/api/agent/heartbeat",
        json={"token": "device-token", "hostname": "x", "client_version": "1.3.0"},
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "agent_newer_than_hub",
        "params": {"hub_version": "1.2.3", "agent_version": "1.3.0"},
    }
    # The token survives, so a beat from a matching build still lands.
    assert device.client.token_sha256 == hashlib.sha256(b"device-token").hexdigest()
    accepted = client.post(
        "/api/agent/heartbeat",
        json={"token": "device-token", "hostname": "x", "client_version": "1.2.3"},
    )
    assert accepted.status_code == 200


def test_a_newer_agent_cannot_spend_an_enrollment_ticket(api):
    client, runtime, _ = api
    runtime.enrollments["ticket"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 600,
    }

    refused = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "ticket",
            "device_id": "abc123",
            "client_version": "2.0.0",
        },
    )

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "agent_newer_than_hub"
    # The link is still whole for the machine that will use it properly.
    assert "ticket" in runtime.enrollments


def test_an_older_agent_still_beats(api):
    client, _, _ = api

    response = client.post(
        "/api/agent/heartbeat",
        json={"token": "device-token", "hostname": "x", "client_version": "1.0.0"},
    )

    assert response.status_code == 200


def test_an_unparseable_version_refuses_nothing(api):
    client, _, _ = api

    response = client.post(
        "/api/agent/heartbeat",
        json={"token": "device-token", "hostname": "x", "client_version": "wat"},
    )

    assert response.status_code == 200


def test_the_package_endpoint_serves_the_bytes_and_their_digest(
    api, monkeypatch, tmp_path
):
    client, _, _ = api
    baked = tmp_path / "neutrino-agent_9.9.9_all.deb"
    baked.write_bytes(b"!<arch>agent-bytes")
    monkeypatch.setattr(agent_router, "agent_packages", lambda: {"deb": baked})

    response = client.post(
        "/api/agent/package", json={"token": "device-token", "family": "deb"}
    )

    assert response.status_code == 200
    assert response.content == b"!<arch>agent-bytes"
    expected = hashlib.sha256(b"!<arch>agent-bytes").hexdigest()
    assert response.headers["x-checksum-sha256"] == expected


def test_the_package_endpoint_refuses_an_unknown_token(api, monkeypatch, tmp_path):
    client, _, _ = api
    baked = tmp_path / "neutrino-agent_9.9.9_all.deb"
    baked.write_bytes(b"!<arch>agent-bytes")
    monkeypatch.setattr(agent_router, "agent_packages", lambda: {"deb": baked})

    response = client.post(
        "/api/agent/package", json={"token": "nonsense", "family": "deb"}
    )

    assert response.status_code == 401


def test_a_family_the_hub_has_no_package_for_is_a_coded_conflict(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(agent_router, "agent_packages", lambda: {})

    response = client.post(
        "/api/agent/package", json={"token": "device-token", "family": "rpm"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "agent_package_missing"}


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
