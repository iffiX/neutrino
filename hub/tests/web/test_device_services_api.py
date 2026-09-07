"""The drawer's Services block: what it reads, and what it may ask.

The asks are the page's own verbs and nothing wider: a body outside the
verb set is refused typed before anything is queued, and a fresh mount must
say whom it is for. A share's access password rides inside the one ask, the
way a mount's credentials do, and nothing hub-side keeps it.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router

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
        self.client_ai_targets = {}
        self.client_service_state = {}
        self.client_device_host = {}
        self.client_platform = {}
        self.device_catalog = StubCatalog()
        self.queued = []

    def queue_client_command(self, mac_address: str, command: dict) -> None:
        self.queued.append((mac_address, command))


def beating(seconds_ago: float) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return stamp.isoformat()


@pytest.fixture
def api(monkeypatch):
    FakeRegistry.device = ManagedDevice(
        mac_address=MAC,
        name="testbox",
        client=DeviceClientInfo(token_sha256="t" * 64, last_seen=beating(2)),
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
    }


def test_the_view_is_the_beats_rows_over_the_devices_own_catalog(api):
    client, runtime = api
    runtime.client_device_host[MAC] = "192.168.100.1"
    runtime.client_platform[MAC] = {"os": "linux"}
    runtime.client_accounts[MAC] = ["pat", "sam"]
    runtime.client_ai_targets[MAC] = {"pat": True}
    runtime.client_service_state[MAC] = {
        "mounts": [{"record_id": "r1", "path": "/home/pat/nas", "account": "pat"}],
        "ai_states": {"pat": {"state": "active"}},
    }

    answer = client.get(f"/api/devices/{MAC}/services").json()

    assert [entry["id"] for entry in answer["entries"]] == [
        "hub_share_media",
        "web_gitea",
    ]
    assert answer["accounts"] == ["pat", "sam"]
    assert answer["ai_targets"] == {"pat": True}
    assert answer["mounts"][0]["record_id"] == "r1"
    # The catalog is composed for the address the device itself reaches the
    # hub on, so entry URLs match what the machine's own page shows.
    assert runtime.device_catalog.asked == [("192.168.100.1", {"os": "linux"})]


def test_an_ai_apply_is_queued_as_the_pages_own_verb(api):
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/ai",
        json={"body": {"targets": {"pat": True, "sam": False}}},
    )

    assert answer.status_code == 200
    command_id = answer.json()["command_id"]
    assert command_id.startswith("service-ai-")
    ((mac, command),) = runtime.queued
    assert mac == MAC
    assert command == {
        "id": command_id,
        "action": "service",
        "args": {
            "service_type": "ai",
            "body": {"targets": {"pat": True, "sam": False}},
        },
    }


def test_a_fresh_mount_must_say_whom_it_is_for(api):
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/file",
        json={"body": {"action": "mount", "id": "hub_share_media", "path": "/mnt"}},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {"code": "no_target_user"}
    assert runtime.queued == []


def test_a_remount_by_record_needs_no_account(api):
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/file",
        json={"body": {"action": "mount", "record_id": "r1"}},
    )

    assert answer.status_code == 200
    assert len(runtime.queued) == 1


def test_a_share_is_queued_with_its_account_and_password(api):
    """The access password rides inside the one ask, the way a mount's
    credentials do; nothing hub-side keeps it."""
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/rdp",
        json={"body": {"action": "share", "account": "pat", "password": "pw"}},
    )

    assert answer.status_code == 200
    ((_mac, command),) = runtime.queued
    assert command["args"]["body"] == {
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
    assert len(runtime.queued) == 1


def test_a_type_outside_the_verb_set_is_refused_typed(api):
    client, runtime = api

    answer = client.post(
        f"/api/devices/{MAC}/services/web", json={"body": {"action": "open"}}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {"code": "unknown_request"}
    assert runtime.queued == []


def test_a_quiet_agent_takes_no_ask(api):
    """A command queued for an agent that never collects it is a change
    nobody made and a result that never comes."""
    client, runtime = api
    FakeRegistry.device.client.last_seen = beating(3600)

    answer = client.post(
        f"/api/devices/{MAC}/services/ai", json={"body": {"targets": {"pat": True}}}
    )

    assert answer.status_code == 409
    assert answer.json()["detail"] == {"code": "agent_offline"}
    assert runtime.queued == []
