"""The client-facing HTTP API: joining with a ticket, and leaving.

The registry is real over a config root of its own; what is exercised is
the request path — the version gate in front of the ticket, a ticket of
the wrong kind refused, a spent or lapsed one refused, the record filled
from what the program said, and a leave that drops the token and keeps
the row.
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.agent_sessions import AgentSessionRegistry
from neutrino_hub.modules.devices.constants import AGENT_SESSION_KIND_CLIENT
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.routers import agent as agent_router
from neutrino_hub.web.routers import client as client_router


class RecordingEvents:
    def __init__(self):
        self.published: list = []

    def publish(self, event_type, key="", data=None):
        self.published.append(event_type)


class FakeRuntime:
    def __init__(self):
        self.enrollments = {}
        self.events = RecordingEvents()
        self.client_sessions = AgentSessionRegistry(kind=AGENT_SESSION_KIND_CLIENT)


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(agent_router, "HUB_VERSION", "1.2.3")
    monkeypatch.setattr(client_router, "HUB_VERSION", "1.2.3")
    app = FastAPI()
    app.include_router(client_router.router)
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    client_id = ClientRegistry().create("alice")
    return TestClient(app), runtime, client_id


def ticket(runtime, token: str, client_id: str, *, expires_in_s: float = 600) -> None:
    runtime.enrollments[token] = {
        "kind": "client",
        "name": "alice",
        "client_id": client_id,
        "expires_at": time.time() + expires_in_s,
    }


def enroll(client, token: str, **fields):
    body = {
        "enrollment_token": token,
        "hostname": "laptop",
        "platform": {"os": "linux", "arch": "amd64", "family": "debian"},
        "client_version": "1.2.3",
    }
    body.update(fields)
    return client.post("/api/client/enroll", json=body)


def test_enrolling_with_a_ticket_issues_a_token_and_fills_the_row(api):
    client, runtime, client_id = api
    ticket(runtime, "t1", client_id)

    response = enroll(client, "t1")

    assert response.status_code == 200
    body = response.json()
    assert body["client_id"] == client_id and body["hub_version"] == "1.2.3"
    stored = ClientRegistry().find_by_token(body["token"])
    assert stored is not None and stored.id == client_id
    assert (stored.hostname, stored.version) == ("laptop", "1.2.3")
    assert stored.platform["os"] == "linux"
    assert "t1" not in runtime.enrollments
    assert runtime.events.published == ["clients"]


def test_an_unknown_spent_or_lapsed_ticket_is_refused_with_the_code(api):
    client, runtime, client_id = api
    ticket(runtime, "t1", client_id)
    ticket(runtime, "old", client_id, expires_in_s=-1)
    assert enroll(client, "t1").status_code == 200

    for token in ("t1", "old", "nonsense"):  # scan: allow
        response = enroll(client, token)
        assert response.status_code == 401
        assert response.json()["detail"] == {"code": "enrollment_unknown", "params": {}}


def test_a_device_ticket_cannot_enroll_a_client_and_the_other_way_round(api):
    client, runtime, client_id = api
    runtime.enrollments["dev"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 600,
    }

    response = enroll(client, "dev")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "enrollment_unknown"
    assert ClientRegistry().get(client_id).token_sha256 is None


def test_a_ticket_for_a_deleted_client_is_refused(api):
    client, runtime, client_id = api
    ticket(runtime, "t1", client_id)
    ClientRegistry().forget(client_id)

    response = enroll(client, "t1")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "enrollment_unknown"


def test_a_newer_client_is_refused_before_the_ticket_is_spent(api):
    client, runtime, client_id = api
    ticket(runtime, "t1", client_id)

    response = enroll(client, "t1", client_version="9.9.9")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "client_newer_than_hub",
        "params": {"hub_version": "1.2.3", "client_version": "9.9.9"},
    }
    assert "t1" in runtime.enrollments


def test_leaving_drops_the_token_and_keeps_the_row(api):
    client, runtime, client_id = api
    ticket(runtime, "t1", client_id)
    token = enroll(client, "t1").json()["token"]
    runtime.events.published.clear()

    response = client.post("/api/client/leave", json={"token": token})

    assert response.status_code == 200 and response.json() == {}
    assert ClientRegistry().find_by_token(token) is None
    assert ClientRegistry().get(client_id).name == "alice"
    assert runtime.events.published == ["clients"]


def test_leaving_with_an_unknown_token_is_refused(api):
    client, _, _ = api

    response = client.post("/api/client/leave", json={"token": "nope"})  # scan: allow

    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "client_unknown", "params": {}}
