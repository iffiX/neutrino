"""What rides an agent's and a client's socket after the welcome.

The test plays the peer over a socket past its hello. What these pin is
the frame sequence both packages must match: a report recorded by id with
its link address, the state pushed on the first report whose hash differs
and never again while the hub's copy stands, a peer-opened ``package``
stream served under credit with the sha256 in its close, a ``service``
stream closed with the entry's material, an unknown kind closed
``kind_unknown``, and a socket ending taking the binding offline.
"""

import hashlib
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
    CHANNEL_STREAM_CREDIT_BYTES,
    PROTOCOL,
)
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.web import channel_serve, identity
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.routers import channel as channel_router
from tests.conftest import StubDesiredStates

LINK_MAC = "aa:bb:cc:dd:ee:ff"
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}
ENTRY = {
    "id": "web_gitea",
    "type": "web",
    "title": "Gitea",
    "payload": {"url": "http://192.168.100.1:3000"},
    "is_healthy": True,
    "source": "module",
    "description": "",
    "description_code": "gitea_module",
    "description_params": {"host": "192.168.100.1"},
    "record_id": None,
    "detail_code": None,
}
RDP_ENTRY = {
    **ENTRY,
    "id": "rdp_s1",
    "type": "rdp",
    "title": "desk",
    "payload": {"host": "192.168.100.7", "port": 21118},
}


class RecordingEvents:
    def __init__(self):
        self.published: list = []

    def publish(self, event_type, key="", data=None):
        self.published.append((event_type, key))


class StubPublishedServices:
    """Answers one list for every host, counts the recomposes asked for."""

    def __init__(self):
        self.entries = [ENTRY]
        self.hosts: list = []
        self.refreshes = 0

    def entries_for(self, target_host):
        self.hosts.append(target_host)
        return list(self.entries)

    def schedule_refresh(self) -> None:
        self.refreshes += 1


class SeatPasswords(StubDesiredStates):
    def seat_password(self, key):
        return "seat-pass"  # scan: allow


class StubServedModels:
    def first_model(self, *, port, client_key):
        return "claude-x"


class StubPackages:
    """The agent package cache: one file for one platform."""

    def __init__(self, path: Path):
        self.path = path
        self.asked: list = []

    def package(self, *, family, architecture):
        from neutrino_hub.exceptions import AgentArtifactFetchError

        self.asked.append((family, architecture))
        if family != "deb":
            raise AgentArtifactFetchError("agent_package_missing", platform=family)
        return self.path


class StubModules:
    """The module cache: one artifact for one module."""

    def __init__(self, path: Path):
        self.path = path
        self.asked: list = []

    def artifact(self, *, name, manifest, platform):
        from types import SimpleNamespace

        self.asked.append((name, dict(platform)))
        return SimpleNamespace(path=self.path)


class _EmptyNetwork:
    lan_interfaces: list = []


class FakeRuntime:
    def __init__(self, tmp_path: Path):
        self.events = RecordingEvents()
        self.enrollments: dict = {}
        self.device_metrics = {}
        self.device_modules = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_accounts = {}
        self.device_interfaces = {}
        self.device_address = {}
        self.device_hub_host = {}
        self.device_last_error = {}
        self.client_catalog_host = {}
        self.device_shares = DeviceShareRegistry()
        self.published_services = StubPublishedServices()
        self.desired_states = SeatPasswords()
        self.served_models = StubServedModels()
        self.agent_module_orders = AgentModuleController(
            cache=None, locks=DeviceInstallLocks()
        )
        self.agent_sessions = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.package_path = tmp_path / "agent.deb"
        self.package_path.write_bytes(b"agent package bytes " * 3000)
        self.agent_packages = StubPackages(self.package_path)
        self.agent_modules = StubModules(self.package_path)
        self.state_requests = 0
        self.desired = ("h1", {"modules": {}, "desktop": {"seat_password": ""}})
        self.pushed: list = []

    def network(self):
        return _EmptyNetwork()

    def desired_state_for(self, device):
        self.state_requests += 1
        return self.desired

    def push_desired_state(self, key):
        self.pushed.append(key)


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    identity.ensure_hub_identity()
    monkeypatch.setattr(channel_router, "HUB_VERSION", "1.2.3")
    monkeypatch.setattr(
        channel_serve,
        "load_module_manifests",
        lambda: {"samba": {"name": "samba", "platforms": {}}},
    )
    app = FastAPI()
    app.include_router(channel_router.router)
    runtime = FakeRuntime(tmp_path)
    app.state.runtime = runtime
    with TestClient(app) as client:
        yield client, runtime


def bound_device(name: str = "testbox") -> tuple:
    device = DeviceRegistry().create(name, machine_id="m1")
    return device.id, DeviceRegistry().issue_token(device.id)


def bound_client(name: str = "alice") -> tuple:
    registry = ClientRegistry()
    client_id = registry.create(name)
    return client_id, registry.issue_token(client_id)


def hello(binding_id: str, token: str, role: str = "agent") -> dict:
    return {
        "type": "hello",
        "protocol": PROTOCOL,
        "role": role,
        "id": binding_id,
        "name": "box",
        "software": f"neutrino_{role}/1.2.3",
        "token": token,
    }


def report(**sections) -> dict:
    body = {
        "type": "report",
        "state_hash": "",
        "machine": {
            "hostname": "box",
            "platform": PLATFORM,
            "accounts": ["alice"],
            "metrics": {"cpu_percent": 4.0},
        },
        "network": {
            "link": {
                "interface": "enp1s0",
                "mac": LINK_MAC,
                "address": "192.168.100.7",
            },
            "interfaces": [
                {"name": "enp1s0", "mac": LINK_MAC, "addresses": ["192.168.100.7"]}
            ],
        },
        "modules": {"rustdesk": {"state": "installed", "is_active": False}},
        "desktop": {"is_shared": False},
        "error": None,
    }
    body.update(sections)
    return body


def welcomed(client, binding_id: str, token: str, role: str = "agent"):
    socket = client.websocket_connect("/api/channel/socket")
    socket.__enter__()
    socket.send_json(hello(binding_id, token, role))
    assert socket.receive_json()["type"] == "welcome"
    return socket


def closed_with(socket) -> tuple:
    message = socket.receive()
    assert message["type"] == "websocket.close"
    return message["code"], message.get("reason", "")


def wait_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def frames_until(socket, kind: str, limit: int = 20) -> list:
    """Every frame up to and including the next one of this type."""
    frames = []
    for _ in range(limit):
        frame = socket.receive()
        frames.append(frame)
        if frame.get("text") and f'"type": "{kind}"' in frame["text"]:
            return frames
    raise AssertionError(f"no {kind} frame among {frames}")


def text_frames(frames: list) -> list:
    import json

    return [json.loads(frame["text"]) for frame in frames if frame.get("text")]


# --- the agent's reports ---


def test_the_first_report_lands_by_id_and_is_handed_the_state(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report())

        state = socket.receive_json()
        assert state == {
            "type": "state",
            "hash": "h1",
            "modules": {},
            "desktop": {"seat_password": ""},
        }
        assert runtime.device_address[device_id] == "192.168.100.7"
        assert runtime.device_hostname[device_id] == "box"
        assert runtime.device_platform[device_id] == PLATFORM
        assert runtime.device_metrics[device_id] == {"cpu_percent": 4.0}
        assert runtime.device_modules[device_id]["rustdesk"]["state"] == "installed"
        assert DeviceRegistry().get(device_id).link_mac == LINK_MAC
        assert runtime.agent_sessions.get(device_id).report_serial == 1
        assert ("device_report", device_id) in runtime.events.published
        assert ("metrics", device_id) in runtime.events.published
        assert runtime.state_requests == 1
    finally:
        socket.__exit__(None, None, None)


def test_a_report_naming_no_address_records_the_socket_peer(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(network={"link": {}, "interfaces": []}))
        socket.receive_json()

        assert runtime.device_address[device_id] == "testclient"
    finally:
        socket.__exit__(None, None, None)


def test_the_state_is_pushed_only_when_the_hash_differs(api):
    """One push on the first report whose hash differs, none while the
    hashes agree, and none again for later reports that still differ."""
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(state_hash="h1"))
        socket.send_json(report(state_hash="stale"))
        socket.send_json(report(state_hash="stale", modules={}))
        assert wait_until(
            lambda: runtime.agent_sessions.get(device_id).report_serial == 3
        )
        socket.send_json({"type": "credit", "stream": 99, "bytes": 1})
        socket.send_json({"type": "open", "stream": 1, "kind": "nonsense"})

        closed = socket.receive_json()
        assert closed["code"] == "kind_unknown"
        assert runtime.state_requests == 1
    finally:
        socket.__exit__(None, None, None)


def test_a_report_whose_modules_moved_recomposes_the_published_list(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report())
        socket.receive_json()
        assert wait_until(lambda: runtime.published_services.refreshes == 1)

        socket.send_json(report())
        socket.send_json(report(modules={"samba": {"state": "running"}}))

        assert wait_until(lambda: runtime.published_services.refreshes == 2)
        assert runtime.published_services.refreshes == 2
    finally:
        socket.__exit__(None, None, None)


def test_a_socket_ending_takes_the_device_offline_and_withdraws_its_share(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    socket.send_json(report(desktop={"is_shared": True, "share_id": "s1"}))
    socket.receive_json()
    assert wait_until(lambda: runtime.device_shares.live())

    socket.__exit__(None, None, None)

    assert wait_until(lambda: not runtime.agent_sessions.is_online(device_id))
    assert runtime.agent_sessions.last_seen_at(device_id)
    assert wait_until(lambda: runtime.device_shares.live() == [])


# --- streams the agent opens ---


def test_a_package_stream_is_served_under_credit_with_its_digest_in_the_close(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report())
        socket.receive_json()
        expected = runtime.package_path.read_bytes()

        socket.send_json({"type": "open", "stream": 1, "kind": "package"})
        assert socket.receive_json() == {
            "type": "credit",
            "stream": 1,
            "bytes": CHANNEL_STREAM_CREDIT_BYTES,
        }
        socket.send_json({"type": "credit", "stream": 1, "bytes": 1000})
        received = b""
        first = socket.receive_bytes()
        assert first[:4] == (1).to_bytes(4, "big")
        received += first[4:]
        assert len(received) == 1000
        socket.send_json({"type": "credit", "stream": 1, "bytes": len(expected)})
        while len(received) < len(expected):
            received += socket.receive_bytes()[4:]
        close = socket.receive_json()

        assert received == expected
        assert close == {
            "type": "close",
            "stream": 1,
            "code": "",
            "params": {"sha256": hashlib.sha256(expected).hexdigest()},
        }
        assert runtime.agent_packages.asked == [("deb", "amd64")]
    finally:
        socket.__exit__(None, None, None)


def test_a_package_stream_naming_a_module_is_served_from_the_module_cache(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report())
        socket.receive_json()
        expected = runtime.package_path.read_bytes()

        socket.send_json(
            {"type": "open", "stream": 3, "kind": "package", "module": "samba"}
        )
        socket.receive_json()
        socket.send_json({"type": "credit", "stream": 3, "bytes": len(expected)})
        received = b""
        while len(received) < len(expected):
            received += socket.receive_bytes()[4:]
        close = socket.receive_json()

        assert close["params"] == {"sha256": hashlib.sha256(expected).hexdigest()}
        assert runtime.agent_modules.asked == [("samba", PLATFORM)]
    finally:
        socket.__exit__(None, None, None)


def test_a_package_the_hub_cannot_produce_is_closed_with_the_typed_reason(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(machine={"platform": {"family": "arch"}}))
        socket.receive_json()

        socket.send_json({"type": "open", "stream": 1, "kind": "package"})
        socket.send_json(
            {"type": "open", "stream": 3, "kind": "package", "module": "nope"}
        )

        frames = [socket.receive_json() for _ in range(4)]
        closes = {
            frame["stream"]: frame for frame in frames if frame["type"] == "close"
        }
        assert [frame["type"] for frame in frames].count("credit") == 2
        assert closes[1]["code"] == "agent_package_missing"
        assert closes[3] == {
            "type": "close",
            "stream": 3,
            "code": "module_unknown",
            "params": {"name": "nope"},
        }
    finally:
        socket.__exit__(None, None, None)


def test_a_kind_the_hub_does_not_serve_is_closed_kind_unknown(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json({"type": "open", "stream": 5, "kind": "service"})

        assert socket.receive_json() == {
            "type": "close",
            "stream": 5,
            "code": "kind_unknown",
            "params": {"kind": "service"},
        }
        assert runtime.agent_sessions.is_online(device_id)
    finally:
        socket.__exit__(None, None, None)


# --- the client's socket ---


def client_report(state_hash: str = "") -> dict:
    return {
        "type": "report",
        "state_hash": state_hash,
        "machine": {"hostname": "laptop", "platform": PLATFORM},
    }


def test_a_clients_first_report_is_handed_the_published_list(api):
    client, runtime = api
    client_id, token = bound_client()
    socket = welcomed(client, client_id, token, role="client")
    try:
        socket.send_json(client_report())

        state = socket.receive_json()
        assert state["type"] == "state"
        assert state["is_disabled"] is False
        assert [entry["id"] for entry in state["services"]] == ["web_gitea"]
        assert set(state["services"][0]) == {
            "id",
            "type",
            "title",
            "payload",
            "is_healthy",
            "source",
            "description",
            "description_code",
            "description_params",
        }
        assert runtime.published_services.hosts == ["testserver"]
        stored = ClientRegistry().get(client_id)
        assert (stored.hostname, stored.version) == ("laptop", "1.2.3")
        assert stored.platform == PLATFORM

        socket.send_json(client_report(state["hash"]))
        socket.send_json({"type": "open", "stream": 1, "kind": "package"})
        assert socket.receive_json()["code"] == "kind_unknown"
    finally:
        socket.__exit__(None, None, None)
    assert wait_until(lambda: not runtime.client_sessions.is_online(client_id))


def test_a_disabled_client_keeps_its_socket_and_is_handed_an_empty_list(api):
    client, runtime = api
    client_id, token = bound_client()
    ClientRegistry().set_disabled(client_id, True)
    socket = welcomed(client, client_id, token, role="client")
    try:
        socket.send_json(client_report())

        state = socket.receive_json()
        assert (state["is_disabled"], state["services"]) == (True, [])
        socket.send_json({"type": "open", "stream": 1, "kind": "service", "id": "x"})
        assert socket.receive_json()["type"] == "credit"
        closed = socket.receive_json()
        assert closed["code"] == "client_disabled"
        assert runtime.client_sessions.is_online(client_id)
    finally:
        socket.__exit__(None, None, None)


def test_a_service_stream_closes_with_the_desktops_material(api):
    client, runtime = api
    runtime.published_services.entries = [RDP_ENTRY]
    runtime.device_shares.declare(
        device_id="dev",
        share_id="s1",
        hostname="desk",
        host="192.168.100.7",
        port=21118,
    )
    client_id, token = bound_client()
    socket = welcomed(client, client_id, token, role="client")
    try:
        socket.send_json(
            {"type": "open", "stream": 1, "kind": "service", "id": "rdp_s1"}
        )
        socket.receive_json()

        close = socket.receive_json()
        assert close == {
            "type": "close",
            "stream": 1,
            "code": "",
            "params": {
                "host": "192.168.100.7",
                "port": 21118,
                "password": "seat-pass",  # scan: allow
            },
        }
        socket.send_json(
            {"type": "open", "stream": 3, "kind": "service", "id": "rdp_s2"}
        )
        socket.receive_json()
        assert socket.receive_json()["code"] == "service_unknown"
    finally:
        socket.__exit__(None, None, None)


def test_a_service_stream_closes_with_the_gateways_material(api, monkeypatch):
    client, runtime = api
    runtime.published_services.entries = [
        {**ENTRY, "id": "ai", "type": "ai", "payload": {"endpoint": "http://x"}}
    ]
    monkeypatch.setattr(
        "neutrino_hub.modules.clients.services.client_credential",
        lambda registry, held, *, hub_host, served_models: {
            "base_url": f"http://{hub_host}:8317",
            "api_key": "key-one",  # scan: allow
            "model": served_models.first_model(port=8317, client_key="k"),
        },
    )
    client_id, token = bound_client()
    socket = welcomed(client, client_id, token, role="client")
    try:
        socket.send_json({"type": "open", "stream": 1, "kind": "service", "id": "ai"})
        socket.receive_json()

        close = socket.receive_json()
        assert close["params"] == {
            "base_url": "http://testserver:8317",
            "api_key": "key-one",  # scan: allow
            "model": "claude-x",
        }
    finally:
        socket.__exit__(None, None, None)
