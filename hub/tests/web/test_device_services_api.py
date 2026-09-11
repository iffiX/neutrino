"""The drawer's Services block: what it reads, and what it may ask.

The asks are the page's own verbs and nothing wider: a body outside the
verb set is refused typed before anything runs, and a fresh mount must say
whom it is for. An ask runs as one command over the device's socket, and a
device with no socket takes none.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router
from tests.conftest import FakeAgentSessions

MAC = "aa:bb:cc:dd:ee:ff"


class FakeRegistry:
    device: ManagedDevice

    def get(self, mac_address: str) -> ManagedDevice:
        return FakeRegistry.device


class StubCatalog:
    """Answers the same composed catalog the agent would be served."""

    def __init__(self):
        self.asked = []

    def catalog(self, *, device_host: str, platform: dict):
        self.asked.append((device_host, dict(platform)))
        entries = [
            {"id": "hub_share_media", "type": "file", "title": "Media"},
            {"id": "web_gitea", "type": "web", "title": "Gitea"},
        ]
        return {"modules": {}, "services": entries}, "hash"


class FakeRuntime:
    def __init__(self):
        self.client_accounts = {}
        self.client_address = {}
        self.client_device_host = {}
        self.client_platform = {}
        self.device_catalog = StubCatalog()
        self.agent_sessions = FakeAgentSessions(online=[MAC])


@pytest.fixture
def api(monkeypatch):
    FakeRegistry.device = ManagedDevice(
        mac_address=MAC,
        name="testbox",
        client=DeviceClientInfo(token_sha256="t" * 64),
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", FakeRegistry)
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_a_device_that_never_beat_reads_empty_rather_than_erroring(api):
    client, _runtime = api

    answer = client.get(f"/api/devices/{MAC}/services").json()

    assert answer == {
        "accounts": [],
        "entries": [],
        "ai_targets": {},
        "ai_states": {},
        "mounts": [],
        "rdp": {},
        "mount_location_shape": "path",
        "mount_location_suggestion": "",
    }


def test_the_view_is_the_devices_own_catalog(api):
    client, runtime = api
    runtime.client_device_host[MAC] = "192.168.100.1"
    runtime.client_platform[MAC] = {"os": "linux"}
    runtime.client_accounts[MAC] = ["pat", "sam"]

    answer = client.get(f"/api/devices/{MAC}/services").json()

    assert [entry["id"] for entry in answer["entries"]] == [
        "hub_share_media",
        "web_gitea",
    ]
    assert answer["accounts"] == ["pat", "sam"]
    # The catalog is composed for the address the device itself reaches the
    # hub on, so entry URLs match what the machine's own page shows.
    assert runtime.device_catalog.asked == [("192.168.100.1", {"os": "linux"})]


def test_an_ai_apply_runs_as_the_pages_own_verb(api):
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/ai",
        json={"body": {"targets": {"pat": True, "sam": False}}},
    )

    assert answer.status_code == 200
    command_id = answer.json()["command_id"]
    assert command_id.startswith("service-ai-")
    assert runtime.agent_sessions.commands == [
        (
            MAC,
            "service",
            {"service_type": "ai", "body": {"targets": {"pat": True, "sam": False}}},
        )
    ]


def test_a_fresh_mount_must_say_whom_it_is_for(api):
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/file",
        json={"body": {"action": "mount", "id": "hub_share_media", "path": "/mnt"}},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {"code": "no_target_user", "params": {}}
    assert runtime.agent_sessions.commands == []


def test_a_remount_by_record_needs_no_account(api):
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/file",
        json={"body": {"action": "mount", "record_id": "r1"}},
    )

    assert answer.status_code == 200
    assert len(runtime.agent_sessions.commands) == 1


def test_a_share_runs_with_its_account_and_password(api):
    """The access password rides inside the one ask, the way a mount's
    credentials do; nothing hub-side keeps it."""
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/rdp",
        json={"body": {"action": "share", "account": "pat", "password": "pw"}},
    )

    assert answer.status_code == 200
    ((_mac, _action, args),) = runtime.agent_sessions.commands
    assert args["body"] == {
        "action": "share",
        "account": "pat",
        "password": "pw",  # scan: allow
    }


def test_an_unshare_is_within_the_verb_set(api):
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/rdp", json={"body": {"action": "unshare"}}
    )

    assert answer.status_code == 200
    assert len(runtime.agent_sessions.commands) == 1


def test_a_type_outside_the_verb_set_is_refused_typed(api):
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/web", json={"body": {"action": "open"}}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {"code": "unknown_request", "params": {}}
    assert runtime.agent_sessions.commands == []


def test_a_device_without_a_socket_takes_no_ask(api):
    client, runtime = api
    runtime.agent_sessions.online.clear()

    answer = client.post(
        f"/api/devices/{MAC}/services/ai", json={"body": {"targets": {"pat": True}}}
    )

    assert answer.status_code == 409
    assert answer.json()["detail"] == {"code": "agent_offline", "params": {}}
    assert runtime.agent_sessions.commands == []
