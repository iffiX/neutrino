"""The client channel's socket, driven end to end through the test client.

The test plays the client: it connects, says hello, reads the welcome, the
catalog and the credential, asks, and is answered. What these pin is the
wire the client package must match — the hello gate and its close codes,
the welcome, the catalog handed only when the hash differs and again when
the published list moves, the credential and its null while disabled, the
one ask, the replaced-socket close, and a socket ending taking the client
offline with a stamp.
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier, load_config
from neutrino_hub.modules.devices.agent_sessions import AgentSessionRegistry
from neutrino_hub.modules.devices.constants import AGENT_SESSION_KIND_CLIENT
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.web import client_channel
from neutrino_hub.web.routers import agent as agent_router
from neutrino_hub.web.routers import agent_ws, client_ws
from tests.conftest import unlock_vault

MAC = "aa:bb:cc:dd:ee:ff"
ENTRY = {
    "id": "web_gitea",
    "type": "web",
    "title": "Gitea",
    "payload": {"url": "http://192.168.100.1:3000"},
    "is_healthy": True,
    "source": "module",
    "description": "",
    "record_id": None,
    "detail_code": None,
}


class RecordingEvents:
    def __init__(self):
        self.published: list = []

    def publish(self, event_type, key="", data=None):
        self.published.append(event_type)


class StubPublishedServices:
    """Answers one list for every host, and can say it moved."""

    def __init__(self):
        self.entries = [ENTRY]
        self.hosts: list = []
        self.on_fingerprint_change = None

    def entries_for(self, target_host):
        self.hosts.append(target_host)
        return list(self.entries)


class StubDesiredStates:
    def seat_password(self, key):
        return "seat-pass" if key == MAC else ""


class StubServedModels:
    def first_model(self, *, port, client_key):
        return "claude-x"


class _EmptyNetwork:
    lan_interfaces: list = []


class FakeRuntime:
    """Only the parts of the runtime the socket touches."""

    def __init__(self):
        self.events = RecordingEvents()
        self.client_sessions = AgentSessionRegistry(kind=AGENT_SESSION_KIND_CLIENT)
        self.client_sessions.on_presence_change = self._presence
        self.client_catalog_host = {}
        self.published_services = StubPublishedServices()
        self.published_services.on_fingerprint_change = self._services_changed
        self.device_shares = DeviceShareRegistry()
        self.desired_states = StubDesiredStates()
        self.served_models = StubServedModels()

    def network(self):
        return _EmptyNetwork()

    def _presence(self):
        self.events.publish("clients")

    def _services_changed(self):
        client_channel.push_catalogs(self)


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    monkeypatch.setattr(client_channel, "HUB_VERSION", "1.2.3")
    monkeypatch.setattr(agent_router, "HUB_VERSION", "1.2.3")
    monkeypatch.setattr(agent_ws, "AGENT_WS_HELLO_TIMEOUT_S", 0.3)
    app = FastAPI()
    app.include_router(client_ws.router)
    runtime = FakeRuntime()
    app.state.runtime = runtime
    registry = ClientRegistry()
    client_id = registry.create("alice")
    token = registry.issue_token(client_id)
    with TestClient(app) as client:
        yield client, runtime, client_id, token


def hello(token: str, **fields) -> dict:
    body = {
        "type": "hello",
        "kind": "client",
        "token": token,
        "client_version": "1.2.3",
        "hostname": "laptop",
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
        "catalog_hash": "",
    }
    body.update(fields)
    return body


def closed_with(socket) -> tuple:
    message = socket.receive()
    assert message["type"] == "websocket.close"
    return message["code"], message.get("reason", "")


def welcomed(client, token: str, **fields):
    """A socket past its hello, with the welcome read."""
    socket = client.websocket_connect("/api/client/ws")
    socket.__enter__()
    socket.send_json(hello(token, **fields))
    return socket, socket.receive_json()


def wait_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def expected_catalog(is_disabled: bool = False) -> dict:
    from neutrino_hub.modules.clients.asks import catalog_frame
    from neutrino_hub.modules.services.collector import catalog_entries

    return catalog_frame(catalog_entries([ENTRY]), is_disabled=is_disabled)


# --- the hello gate ---


def test_a_late_hello_closes_the_socket(api):
    client, *_ = api

    with client.websocket_connect("/api/client/ws") as socket:
        assert closed_with(socket) == (4400, "bad_hello")


def test_a_hello_that_is_not_a_client_closes_the_socket(api):
    client, _, _, token = api

    with client.websocket_connect("/api/client/ws") as socket:
        socket.send_json(hello(token, kind="agent"))
        assert closed_with(socket) == (4400, "bad_hello")


def test_an_unknown_or_dropped_token_closes_with_its_own_code(api):
    client, _, client_id, token = api

    with client.websocket_connect("/api/client/ws") as socket:
        socket.send_json(hello("nonsense"))  # scan: allow
        assert closed_with(socket) == (4401, "unknown_token")

    ClientRegistry().drop_token(client_id)
    with client.websocket_connect("/api/client/ws") as socket:
        socket.send_json(hello(token))
        assert closed_with(socket) == (4401, "unknown_token")


def test_a_newer_client_is_refused_with_the_code_and_no_wire_is_asked(api):
    client, _, _, token = api

    with client.websocket_connect("/api/client/ws") as socket:
        socket.send_json(hello(token, client_version="9.9.9"))
        assert closed_with(socket) == (4409, "client_newer_than_hub")

    with client.websocket_connect("/api/client/ws") as socket:
        socket.send_json(hello(token, client_version="0.0.1"))
        assert socket.receive_json()["type"] == "welcome"


# --- what comes down after the hello ---


def test_the_welcome_then_the_catalog_then_the_credential(api):
    client, runtime, client_id, token = api

    socket, welcome = welcomed(client, token)
    catalog = socket.receive_json()
    credential = socket.receive_json()
    socket.__exit__(None, None, None)

    assert welcome == {
        "type": "welcome",
        "hub_version": "1.2.3",
        "client_id": client_id,
        "is_disabled": False,
    }
    assert catalog == expected_catalog()
    assert set(catalog["services"][0]) == {
        "id",
        "type",
        "title",
        "payload",
        "is_healthy",
        "source",
        "description",
    }
    port = load_config().listen_port
    assert credential == {
        "type": "ai",
        "credential": {
            "base_url": f"http://testserver:{port}",
            "api_key": load_config().client_keys[0].open_key(),
            "model": "claude-x",
        },
    }
    assert runtime.published_services.hosts == ["testserver"]
    assert load_config().client_keys[0].name == "client/alice"
    assert ClientRegistry().get(client_id).ai_key_id == load_config().client_keys[0].id


def test_a_hello_carrying_the_current_hash_is_handed_no_catalog(api):
    client, _, _, token = api

    socket, _ = welcomed(client, token, catalog_hash=expected_catalog()["hash"])
    frame = socket.receive_json()
    socket.__exit__(None, None, None)

    assert frame["type"] == "ai"


def test_the_hello_lands_the_client_online_with_what_it_said(api):
    client, runtime, client_id, token = api

    socket, _ = welcomed(client, token)
    session = runtime.client_sessions.get(client_id)
    stored = ClientRegistry().get(client_id)
    socket.__exit__(None, None, None)

    assert session is not None
    assert (session.hostname, session.version) == ("laptop", "1.2.3")
    assert session.platform["os"] == "linux"
    assert (stored.hostname, stored.version) == ("laptop", "1.2.3")
    assert runtime.client_catalog_host[client_id] == "testserver"
    assert "clients" in runtime.events.published


def test_the_published_list_moving_hands_every_client_the_new_catalog(api):
    client, runtime, _, token = api
    socket, _ = welcomed(client, token)
    socket.receive_json()
    socket.receive_json()

    runtime.published_services.entries = []
    runtime.published_services.on_fingerprint_change()
    frame = socket.receive_json()
    # The same list again composes the same hash and is not re-sent.
    runtime.published_services.on_fingerprint_change()
    runtime.published_services.entries = [ENTRY]
    runtime.published_services.on_fingerprint_change()
    again = socket.receive_json()
    socket.__exit__(None, None, None)

    assert frame == {
        "type": "catalog",
        "hash": expected_catalog(is_disabled=True)["hash"],
        "services": [],
    }
    assert again == expected_catalog()


def test_a_disabled_client_keeps_its_socket_and_gets_nothing(api):
    client, runtime, client_id, token = api
    ClientRegistry().set_disabled(client_id, True)

    socket, welcome = welcomed(client, token)
    catalog = socket.receive_json()
    credential = socket.receive_json()
    socket.send_json(
        {"type": "ask", "id": "1", "kind": "rdp_connect", "args": {"service_id": "x"}}
    )
    answer = socket.receive_json()
    socket.__exit__(None, None, None)

    assert welcome["is_disabled"] is True
    assert catalog["services"] == []
    assert credential == {"type": "ai", "credential": None}
    assert answer == {
        "type": "answer",
        "id": "1",
        "code": "client_disabled",
        "params": {},
    }
    assert load_config().client_keys == []


def test_a_toggle_pushes_the_switch_the_credential_and_the_catalog(api):
    client, runtime, client_id, token = api
    socket, _ = welcomed(client, token)
    socket.receive_json()
    socket.receive_json()

    ClientRegistry().set_disabled(client_id, True)
    client_channel.push_client_state(runtime, client_id)
    frames = [socket.receive_json() for _ in range(3)]
    ClientRegistry().set_disabled(client_id, False)
    client_channel.push_client_state(runtime, client_id)
    back = [socket.receive_json() for _ in range(3)]
    socket.__exit__(None, None, None)

    assert frames[0] == {"type": "disabled", "is_disabled": True}
    assert frames[1] == {"type": "ai", "credential": None}
    assert frames[2]["type"] == "catalog" and frames[2]["services"] == []
    assert back[0] == {"type": "disabled", "is_disabled": False}
    assert back[1]["type"] == "ai" and back[1]["credential"]["model"] == "claude-x"
    assert back[2] == expected_catalog()


# --- asks ---


def test_rdp_connect_is_answered_from_the_share_and_the_seat_password(api):
    client, runtime, _, token = api
    runtime.device_shares.declare(
        mac_address=MAC,
        share_id="s1",
        hostname="desk",
        host="192.168.100.7",
        port=21118,
    )
    socket, _ = welcomed(client, token)
    socket.receive_json()
    socket.receive_json()

    socket.send_json(
        {
            "type": "ask",
            "id": "a1",
            "kind": "rdp_connect",
            "args": {"service_id": "rdp_s1"},
        }
    )
    answered = socket.receive_json()
    socket.send_json(
        {
            "type": "ask",
            "id": "a2",
            "kind": "rdp_connect",
            "args": {"service_id": "rdp_s2"},
        }
    )
    refused = socket.receive_json()
    socket.__exit__(None, None, None)

    assert answered == {
        "type": "answer",
        "id": "a1",
        "result": {
            "host": "192.168.100.7",
            "port": 21118,
            "password": "seat-pass",
        },  # scan: allow
    }
    assert refused["code"] == "rdp_not_shared" and refused["id"] == "a2"


def test_a_frame_that_is_no_ask_is_ignored(api):
    client, _, _, token = api
    socket, _ = welcomed(client, token)
    socket.receive_json()
    socket.receive_json()

    socket.send_text("not json")
    socket.send_json({"type": "report"})
    socket.send_json({"type": "ask", "id": "z", "kind": "teleport"})
    answer = socket.receive_json()
    socket.__exit__(None, None, None)

    assert answer["id"] == "z" and answer["code"] == "ask_unknown"


# --- presence ---


def test_a_newer_socket_replaces_the_older_one(api):
    client, runtime, client_id, token = api
    first, _ = welcomed(client, token)
    first.receive_json()
    first.receive_json()

    second, _ = welcomed(client, token)

    assert closed_with(first) == (4410, "replaced")
    first.__exit__(None, None, None)
    assert runtime.client_sessions.is_online(client_id)
    second.__exit__(None, None, None)


def test_a_socket_ending_takes_the_client_offline_with_a_stamp(api):
    client, runtime, client_id, token = api
    socket, _ = welcomed(client, token)
    socket.receive_json()
    socket.receive_json()
    runtime.events.published.clear()

    socket.__exit__(None, None, None)

    assert wait_until(lambda: not runtime.client_sessions.is_online(client_id))
    assert runtime.client_sessions.last_seen_at(client_id)
    assert runtime.client_sessions.version_of(client_id) == "1.2.3"
    assert wait_until(lambda: "clients" in runtime.events.published)
