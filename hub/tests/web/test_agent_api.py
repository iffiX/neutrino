"""The agent-facing HTTP API: joining, leaving, and fetching packages.

The registry is replaced with one held in memory, so what is exercised is the
request path: a machine introducing itself with a ticket lands on the row
the ticket names, else on the row its machine id names, else on a new one;
both version gates stand in front of the ticket; an agent saying goodbye
stops the panel treating the device as managed while keeping everything its
owner typed; the package routes serve bytes with their digest. Everything
live rides the socket, which ``test_agent_ws`` drives.
"""

import hashlib
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.agent_module_cache import AgentModuleArtifact
from neutrino_hub.modules.devices.agent_package import AgentPackageCache
from neutrino_hub.modules.devices.constants import AGENT_WIRE_GENERATION
from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.routers import agent as agent_router
from tests.conftest import FakeChannelSessions

DEVICE = "device-one"
MACHINE = "machine-of-testbox"


def package_cache(root: Path) -> AgentPackageCache:
    """A cache over one directory, holding whatever was written into it.

    Args:
        root: The directory; a package dropped there is served the way a
            hand-pinned build is, with no manifest and nothing to fetch.

    Returns:
        The cache the runtime would hold.
    """
    return AgentPackageCache(
        root=root / "agent_cache",
        manifest_path=root / "agent_packages.json",
        pinned_dir=root,
    )


class FakeRegistry:
    """A registry held in memory: one stored device, plus what a join creates."""

    devices: dict

    @classmethod
    def reset(cls, device: ManagedDevice) -> None:
        cls.devices = {device.id: device}

    def get(self, device_id):
        return FakeRegistry.devices.get(device_id)

    def find_by_token(self, token):
        presented = hashlib.sha256(token.encode()).hexdigest()
        for device in FakeRegistry.devices.values():
            stored = device.client.token_sha256
            if stored and stored == presented:
                return device
        return None

    def find_by_machine_id(self, machine_id):
        for device in FakeRegistry.devices.values():
            if machine_id and device.machine_id == machine_id:
                return device
        return None

    def create(self, name, *, machine_id="", link_mac=""):
        device = ManagedDevice(
            id="created-id", name=name or None, machine_id=machine_id
        )
        FakeRegistry.devices[device.id] = device
        return device

    def annotate(self, device_id, annotation):
        device = FakeRegistry.devices[device_id]
        if "name" in annotation:
            device.name = annotation["name"]
        return device

    def note_machine(self, device_id, *, machine_id="", link_mac=""):
        device = FakeRegistry.devices[device_id]
        if machine_id:
            device.machine_id = machine_id
        return True

    def issue_token(self, device_id):
        FakeRegistry.devices[device_id].client.token_sha256 = hashlib.sha256(
            b"issued-token"
        ).hexdigest()
        return "issued-token"

    def drop_token(self, device_id):
        FakeRegistry.devices[device_id].client.token_sha256 = None


class StubModuleCache:
    """A cache that answers at once and never reaches a vendor."""

    def __init__(self):
        self.asked: list = []

    def artifact_for_key(self, artifact_key, *, sources, platform):
        self.asked.append((artifact_key, dict(platform)))
        return AgentModuleArtifact(
            key=artifact_key, path=Path("/nonexistent"), digest="d", package_kind="deb"
        )


class FakeRuntime:
    """Only the parts of the runtime these routes touch."""

    def __init__(self):
        self.device_metrics = {}
        self.device_address = {}
        self.device_modules = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_accounts = {}
        self.device_last_error = {}
        self.enrollments = {}
        self.agent_sessions = FakeChannelSessions()
        self.agent_modules = StubModuleCache()
        # A hub carrying nothing, which is what a case that does not seed one
        # wants; the cases that do replace it with :func:`package_cache`.
        self.agent_packages = package_cache(Path("/nonexistent"))
        self.forgotten: list = []

    def forget_device(self, device_id):
        self.forgotten.append(device_id)
        for held in (
            self.device_metrics,
            self.device_address,
            self.device_modules,
            self.device_platform,
            self.device_hostname,
            self.device_accounts,
            self.device_last_error,
        ):
            held.pop(device_id, None)


@pytest.fixture()
def api(monkeypatch):
    device = ManagedDevice(
        id=DEVICE,
        name="testbox",
        machine_id=MACHINE,
        ssh={"host": "10.0.0.5", "username": "me"},
        client=DeviceClientInfo(
            token_sha256=hashlib.sha256(b"device-token").hexdigest()
        ),
    )
    FakeRegistry.reset(device)
    monkeypatch.setattr(agent_router, "DeviceRegistry", FakeRegistry)
    # Pinned so the version comparisons below are about the protocol, not
    # about what the checkout happens to be versioned.
    monkeypatch.setattr(agent_router, "HUB_VERSION", "1.2.3")

    app = FastAPI()
    app.include_router(agent_router.router)
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), runtime, device


def ticket(runtime, name: str, *, device_id=None, expires_in_s: float = 600):
    runtime.enrollments[name] = {
        "name": "",
        "device_id": device_id,
        "expires_at": time.time() + expires_in_s,
    }


# --- the gates, judged as one ---


def test_a_newer_agent_is_refused_with_a_code():
    refusal = agent_router.version_refusal("9.9.9", AGENT_WIRE_GENERATION)

    assert refusal["code"] == "agent_newer_than_hub"
    assert refusal["params"]["agent_version"] == "9.9.9"


def test_another_wire_generation_is_refused_with_both_generations():
    refusal = agent_router.version_refusal("0.0.1", 1)

    assert refusal == {
        "code": "agent_wire_stale",
        "params": {"hub_wire": AGENT_WIRE_GENERATION, "agent_wire": 1},
    }


@pytest.mark.parametrize("version", ["0.0.1", "wat", ""])
def test_an_older_or_unparseable_version_on_the_right_wire_is_admitted(version):
    assert agent_router.version_refusal(version, AGENT_WIRE_GENERATION) is None


# --- POST /api/agent/enroll ---


def test_enrolling_with_a_ticket_issues_a_token(api):
    client, runtime, device = api
    ticket(runtime, "ticket")

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "ticket",
            "device_id": "abc123",
            "hostname": "laptop",
            "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
        },
    )

    assert response.status_code == 200
    assert response.json()["token"] == "issued-token"
    assert response.json()["hub_version"] == "1.2.3"
    # The ticket is single-use.
    assert "ticket" not in runtime.enrollments
    key = response.json()["device_id"]
    assert key == "created-id"
    created = FakeRegistry.devices[key]
    assert (created.name, created.machine_id) == ("laptop", "abc123")
    assert runtime.device_platform[key]["arch"] == "amd64"
    assert runtime.device_hostname[key] == "laptop"
    assert runtime.device_address[key] == "testclient"


def test_a_client_ticket_cannot_enroll_an_agent(api):
    client, runtime, _ = api
    runtime.enrollments["c1"] = {
        "kind": "client",
        "name": "alice",
        "client_id": "abc",
        "expires_at": time.time() + 600,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "c1",
            "device_id": "machine-1",
            "client_version": "1.2.3",
            "wire": AGENT_WIRE_GENERATION,
        },
    )

    assert response.status_code == 401
    assert "c1" not in runtime.enrollments


def test_a_ticket_spent_twice_is_refused_the_second_time(api):
    client, runtime, _ = api
    ticket(runtime, "once")
    body = {
        "wire": AGENT_WIRE_GENERATION,
        "enrollment_token": "once",
        "device_id": "abc123",
        "hostname": "laptop",
    }

    assert client.post("/api/agent/enroll", json=body).status_code == 200
    assert client.post("/api/agent/enroll", json=body).status_code == 401


def test_expired_ticket_is_refused(api):
    client, runtime, _ = api
    ticket(runtime, "old", expires_in_s=-1)

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "old",
            "device_id": "abc123",
        },
    )

    assert response.status_code == 401


def test_a_blank_ticket_lands_on_the_row_the_machine_id_names(api):
    """The machine id decides which row, so a rebuilt agent on a known
    machine is the device it always was, name and credentials kept."""
    client, runtime, device = api
    ticket(runtime, "t1")

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "t1",
            "device_id": MACHINE,
            "hostname": "rebuilt",
        },
    )

    assert response.status_code == 200
    assert response.json()["device_id"] == DEVICE
    assert set(FakeRegistry.devices) == {DEVICE}
    assert device.name == "testbox"
    assert device.client.token_sha256 == hashlib.sha256(b"issued-token").hexdigest()


def test_a_ticket_bound_to_a_device_lands_on_it_and_records_the_machine_id(api):
    client, runtime, device = api
    device.machine_id = ""
    ticket(runtime, "t2", device_id=DEVICE)

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "t2",
            "device_id": "machine-9",
        },
    )

    assert response.json()["device_id"] == DEVICE
    assert device.machine_id == "machine-9"
    assert set(FakeRegistry.devices) == {DEVICE}


def test_a_ticket_bound_to_a_forgotten_row_falls_back_to_the_machine_id(api):
    client, runtime, _ = api
    ticket(runtime, "t3", device_id="gone")

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "t3",
            "device_id": "machine-9",
        },
    )

    assert response.json()["device_id"] == "created-id"


def test_a_newer_agent_cannot_spend_an_enrollment_ticket(api):
    client, runtime, _ = api
    ticket(runtime, "ticket")

    refused = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "ticket",
            "device_id": "abc123",
            "wire": AGENT_WIRE_GENERATION,
            "client_version": "2.0.0",
        },
    )

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "agent_newer_than_hub"
    # The link is still whole for the machine that will use it properly.
    assert "ticket" in runtime.enrollments


def test_an_enrollment_from_another_wire_generation_is_refused(api):
    client, runtime, _ = api
    ticket(runtime, "ticket")

    reply = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "ticket",
            "device_id": "abc",
            "wire": 99,
            "client_version": "0.1.0",
        },
    )

    assert reply.status_code == 409
    assert reply.json()["detail"]["code"] == "agent_wire_stale"
    assert "ticket" in runtime.enrollments


# --- POST /api/agent/leave ---


def test_leaving_drops_the_agent_but_keeps_the_device(api):
    client, runtime, device = api
    runtime.device_metrics[DEVICE] = {"cpu_percent": 4.0}
    runtime.device_modules[DEVICE] = {"anydesk": {"state": "installed"}}
    runtime.device_accounts[DEVICE] = ["alice"]
    runtime.device_last_error[DEVICE] = {"code": "mount_failed", "params": {}}

    response = client.post("/api/agent/leave", json={"token": "device-token"})

    assert response.status_code == 200
    assert device.client.token_sha256 is None
    # What the owner gave it survives; only the agent is gone.
    assert device.name == "testbox"
    assert device.ssh == {"host": "10.0.0.5", "username": "me"}
    assert runtime.forgotten == [DEVICE]
    assert runtime.device_metrics == {}
    assert runtime.device_modules == {}
    assert runtime.device_accounts == {}
    assert runtime.device_last_error == {}


def test_leaving_with_an_unknown_token_is_refused(api):
    client, _, device = api

    response = client.post("/api/agent/leave", json={"token": "nonsense"})

    assert response.status_code == 401
    assert device.client.token_sha256 is not None


# --- POST /api/agent/package ---


def test_the_package_endpoint_serves_the_bytes_and_their_digest(api, tmp_path):
    client, runtime, _ = api
    (tmp_path / "neutrino-agent_9.9.9_amd64.deb").write_bytes(b"!<arch>agent-bytes")
    runtime.agent_packages = package_cache(tmp_path)

    response = client.post(
        "/api/agent/package",
        json={"token": "device-token", "family": "deb", "architecture": "amd64"},
    )

    assert response.status_code == 200
    assert response.content == b"!<arch>agent-bytes"
    expected = hashlib.sha256(b"!<arch>agent-bytes").hexdigest()
    assert response.headers["x-checksum-sha256"] == expected


def test_the_package_endpoint_refuses_an_unknown_token(api, tmp_path):
    client, runtime, _ = api
    (tmp_path / "neutrino-agent_9.9.9_amd64.deb").write_bytes(b"!<arch>agent-bytes")
    runtime.agent_packages = package_cache(tmp_path)

    response = client.post(
        "/api/agent/package",
        json={"token": "nonsense", "family": "deb", "architecture": "amd64"},
    )

    assert response.status_code == 401


def test_a_family_the_hub_has_no_package_for_is_a_coded_conflict(api, tmp_path):
    client, runtime, _ = api
    (tmp_path / "neutrino-agent_9.9.9_amd64.deb").write_bytes(b"!<arch>agent-bytes")
    runtime.agent_packages = package_cache(tmp_path)

    response = client.post(
        "/api/agent/package",
        json={"token": "device-token", "family": "rpm", "architecture": "amd64"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "agent_package_missing",
        "params": {"platform": "rpm-amd64"},
    }


def test_a_machine_the_hub_has_no_package_for_is_a_coded_conflict(api, tmp_path):
    """The hub carries the machine it was built for; a device of another one
    is refused by name, not handed the wrong build."""
    client, runtime, _ = api
    (tmp_path / "neutrino-agent_9.9.9_amd64.deb").write_bytes(b"!<arch>agent-bytes")
    runtime.agent_packages = package_cache(tmp_path)

    response = client.post(
        "/api/agent/package",
        json={"token": "device-token", "family": "deb", "architecture": "arm64"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "agent_package_missing",
        "params": {"platform": "deb-arm64"},
    }


def test_a_build_that_names_no_machine_is_answered_from_its_platform(api, tmp_path):
    """A build without the field is served from the platform the device last
    reported over its socket."""
    client, runtime, _ = api
    (tmp_path / "neutrino-agent_9.9.9_arm64.deb").write_bytes(b"!<arch>agent-bytes")
    runtime.agent_packages = package_cache(tmp_path)
    runtime.device_platform[DEVICE] = {"arch": "arm64"}

    response = client.post(
        "/api/agent/package", json={"token": "device-token", "family": "deb"}
    )

    assert response.status_code == 200
    assert response.content == b"!<arch>agent-bytes"


# --- POST /api/agent/module_package ---


def test_the_module_package_endpoint_hands_down_the_cached_bytes(api, tmp_path):
    client, runtime, _ = api
    artifact = tmp_path / "fakedesk.deb"
    artifact.write_bytes(b"!<arch>module-bytes")
    runtime.device_platform[DEVICE] = {"os": "linux", "family": "debian"}

    def artifact_for_key(artifact_key, *, sources, platform):
        runtime.agent_modules.asked.append((artifact_key, dict(platform)))
        return AgentModuleArtifact(
            key=artifact_key, path=artifact, digest="d", package_kind="deb"
        )

    runtime.agent_modules.artifact_for_key = artifact_for_key

    response = client.post(
        "/api/agent/module_package",
        json={"token": "device-token", "artifact_key": "fakedesk-key"},
    )

    assert response.status_code == 200
    assert response.content == b"!<arch>module-bytes"
    expected = hashlib.sha256(b"!<arch>module-bytes").hexdigest()
    assert response.headers["x-checksum-sha256"] == expected
    assert runtime.agent_modules.asked == [
        ("fakedesk-key", {"os": "linux", "family": "debian"})
    ]


def test_the_module_package_endpoint_refuses_an_unknown_token(api):
    client, _, _ = api

    response = client.post(
        "/api/agent/module_package",
        json={"token": "nonsense", "artifact_key": "fakedesk-key"},
    )

    assert response.status_code == 401
