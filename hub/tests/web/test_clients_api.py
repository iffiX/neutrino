"""The Clients page's routes: the list, the link, the switch, the delete.

The registry and the gateway config are real over a config root of their
own, so what is exercised is the whole write path — a link creating the
row before the program joins, a disable revoking the client's gateway key
and an enable minting one again, a delete taking key, record and socket —
and that every change says ``clients`` on the event bus.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier, load_config
from neutrino_hub.modules.devices.agent_sessions import AgentSessionRegistry
from neutrino_hub.modules.devices.constants import AGENT_SESSION_KIND_CLIENT
from neutrino_hub.web import client_channel
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import clients as clients_router
from neutrino_hub.web.routers import devices as devices_router
from tests.conftest import unlock_vault

FINGERPRINT = "SHA256:" + "ab" * 32


class RecordingEvents:
    def __init__(self):
        self.published: list = []

    def publish(self, event_type, key="", data=None):
        self.published.append(event_type)


class RecordingSessions(AgentSessionRegistry):
    """The client registry, remembering what was closed."""

    def __init__(self):
        super().__init__(kind=AGENT_SESSION_KIND_CLIENT)
        self.closed: list = []

    def close_from_thread(self, key, code, reason=""):
        self.closed.append((key, code, reason))


class FakeRuntime:
    def __init__(self):
        self.enrollments = {}
        self.events = RecordingEvents()
        self.client_sessions = RecordingSessions()
        self.client_catalog_host = {}
        self.pushed: list = []


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    monkeypatch.setattr(
        devices_router, "_agent_urls", lambda runtime: ["https://192.168.100.1:8443"]
    )
    monkeypatch.setattr(devices_router, "certificate_fingerprint", lambda: FINGERPRINT)
    runtime = FakeRuntime()
    monkeypatch.setattr(
        client_channel,
        "push_client_state",
        lambda given, client_id: given.pushed.append(client_id),
    )
    app = FastAPI()
    app.include_router(clients_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), runtime


def decoded_link(link: str) -> dict:
    import base64
    import json

    payload = link.removeprefix("neutrino://enroll/")
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_an_empty_hub_lists_no_clients(api):
    client, _ = api

    response = client.get("/api/clients")

    assert response.status_code == 200 and response.json() == {"clients": []}


def test_a_link_creates_the_row_and_carries_the_client_kind(api):
    client, runtime = api

    response = client.post("/api/clients/enrollment", json={"name": " alice "})

    assert response.status_code == 200
    body = response.json()
    payload = decoded_link(body["link"])
    assert payload["kind"] == "client" and payload["fp"] == FINGERPRINT
    assert payload["urls"] == ["https://192.168.100.1:8443"]
    ticket = runtime.enrollments[payload["token"]]
    rows = client.get("/api/clients").json()["clients"]
    assert len(rows) == 1
    assert ticket == {
        "kind": "client",
        "name": "alice",
        "client_id": rows[0]["id"],
        "expires_at": ticket["expires_at"],
    }
    assert body["expires_at"].endswith("+00:00")
    assert rows[0] == {
        "id": rows[0]["id"],
        "name": "alice",
        "hostname": "",
        "platform_os": "",
        "version": "",
        "is_online": False,
        "last_seen": None,
        "is_disabled": False,
    }
    assert runtime.events.published == ["clients"]


def test_a_blank_name_is_refused_and_a_new_link_replaces_only_client_tickets(api):
    client, runtime = api
    runtime.enrollments["dev"] = {"name": "", "mac_address": None, "expires_at": 9e12}

    refused = client.post("/api/clients/enrollment", json={"name": "  "})
    first = decoded_link(
        client.post("/api/clients/enrollment", json={"name": "a"}).json()["link"]
    )
    second = decoded_link(
        client.post("/api/clients/enrollment", json={"name": "b"}).json()["link"]
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == {"code": "client_name_required", "params": {}}
    assert set(runtime.enrollments) == {"dev", second["token"]}
    assert first["token"] != second["token"]


def test_disabling_revokes_the_key_and_enabling_mints_one_again(api):
    client, runtime = api
    client_id = ClientRegistry().create("alice")
    from neutrino_hub.modules.clients.ai_keys import ensure_client_key

    ensure_client_key(ClientRegistry(), ClientRegistry().get(client_id))
    first = load_config().client_keys[0].id
    runtime.events.published.clear()

    off = client.put(f"/api/clients/{client_id}", json={"is_disabled": True})

    assert off.status_code == 200
    assert off.json()["clients"][0]["is_disabled"] is True
    assert load_config().client_keys == []
    assert ClientRegistry().get(client_id).ai_key_id is None

    on = client.put(f"/api/clients/{client_id}", json={"is_disabled": False})

    assert on.json()["clients"][0]["is_disabled"] is False
    keys = load_config().client_keys
    assert len(keys) == 1 and keys[0].id != first
    assert ClientRegistry().get(client_id).ai_key_id == keys[0].id
    assert runtime.pushed == [client_id, client_id]
    assert runtime.events.published == ["clients", "clients"]


def test_deleting_takes_the_key_the_record_and_the_socket(api):
    client, runtime = api
    client_id = ClientRegistry().create("alice")
    from neutrino_hub.modules.clients.ai_keys import ensure_client_key

    ensure_client_key(ClientRegistry(), ClientRegistry().get(client_id))
    runtime.client_catalog_host[client_id] = "192.168.100.1"
    runtime.events.published.clear()

    response = client.delete(f"/api/clients/{client_id}")

    assert response.status_code == 200 and response.json() == {"clients": []}
    assert load_config().client_keys == []
    assert ClientRegistry().get(client_id) is None
    assert runtime.client_sessions.closed == [(client_id, 4401, "unknown_token")]
    assert client_id not in runtime.client_catalog_host
    assert runtime.events.published == ["clients"]


def test_an_unknown_client_is_a_coded_404(api):
    client, _ = api

    updated = client.put("/api/clients/nobody", json={"is_disabled": True})
    deleted = client.delete("/api/clients/nobody")

    assert updated.status_code == 404 and deleted.status_code == 404
    assert updated.json()["detail"] == {
        "code": "client_unknown",
        "params": {"client_id": "nobody"},
    }


def test_the_list_prefers_the_live_session_over_the_record(api):
    import asyncio

    from neutrino_hub.modules.devices.agent_sessions import AgentSession

    client, runtime = api
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.record_seen(
        client_id, hostname="old", platform={"os": "windows"}, version="0.1.0"
    )

    async def attach():
        await runtime.client_sessions.attach(
            AgentSession(
                key=client_id,
                kind=AGENT_SESSION_KIND_CLIENT,
                websocket=None,
                loop=asyncio.get_running_loop(),
                hostname="laptop",
                platform={"os": "linux"},
                version="0.2.0",
            )
        )

    asyncio.run(attach())

    row = client.get("/api/clients").json()["clients"][0]

    assert row["is_online"] is True
    assert (row["hostname"], row["platform_os"], row["version"]) == (
        "laptop",
        "linux",
        "0.2.0",
    )
