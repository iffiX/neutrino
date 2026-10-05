"""What rides an agent's and a client's socket after the welcome.

The test plays the peer over a socket past its hello. What these pin is
the frame sequence both packages must match: a report recorded by id with
its link address, the state pushed on the first report whose hash differs
and never again while the hub's copy stands, a peer-opened ``package``
stream served under credit with the sha256 in its close and its download
and sending written into the module's task, a ``log`` stream
becoming the task the panel follows, ending with the module's state and
the failure's code, a ``service`` stream closed with the entry's material,
an unknown kind closed ``kind_unknown``, a client's ``is_refresh`` report
answered with its whole state whatever the hash, and a socket ending taking the
binding offline.
"""

import hashlib
import os
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.channel.port_guard import ChannelPortGuard
from neutrino_hub.modules.channel.tickets import ChannelTicketRegistry
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CHUNK_BYTES,
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
    CHANNEL_STREAM_CREDIT_BYTES,
    PROTOCOL,
)
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.web import channel_serve, channel_state, identity
from neutrino_hub.web.auth import PanelTokenStore
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.routers import channel as channel_router
from neutrino_hub.web.task_stream import TaskStreamRegistry
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
    """Answers one list for every scope, counts the recomposes asked for."""

    def __init__(self):
        self.entries = [ENTRY]
        self.scopes: list = []
        self.refreshes = 0

    def entries_for(self, scope):
        self.scopes.append(scope)
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

    def artifact(self, *, name, manifest, platform, on_progress=None):
        from types import SimpleNamespace

        self.asked.append((name, dict(platform)))
        if on_progress is not None:
            on_progress(f"hub: downloading {name}, 1.0 / 1.0 MB")
        return SimpleNamespace(path=self.path)


class FakeRuntime:
    def __init__(self, tmp_path: Path):
        self.events = RecordingEvents()
        self.tasks = TaskStreamRegistry()
        self.enrollments = ChannelTicketRegistry()
        self.channel_port = ChannelPortGuard()
        self.device_metrics = {}
        self.device_modules = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_accounts = {}
        self.device_interfaces = {}
        self.device_address = {}
        self.device_scope = {}
        self.device_last_error = {}
        self.client_scope = {}
        self.client_reached: dict = {}
        self.device_shares = DeviceShareRegistry()
        self.published_services = StubPublishedServices()
        self.desired_states = SeatPasswords()
        self.served_models = StubServedModels()
        self.agent_sessions = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.package_path = tmp_path / "neutrino-agent-0.5.0-amd64.deb"
        self.package_path.write_bytes(b"agent package bytes " * 3000)
        self.agent_packages = StubPackages(self.package_path)
        self.agent_modules = StubModules(self.package_path)
        self.state_requests = 0
        self.desired = ("h1", {"modules": {}, "desktop": {"seat_password": ""}})
        self.pushed: list = []
        self.urls = ["https://192.168.100.1:8443"]
        self.overlays: list = []
        self.settings: dict = {}

    def host_scopes(self):
        return []

    def overlay_networks(self):
        return {}

    def interface_networks(self):
        return []

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
    monkeypatch.setattr(channel_state, "channel_urls", lambda given: list(given.urls))
    monkeypatch.setattr(
        "neutrino_hub.web.channel_overlay.overlay_materials",
        lambda given: given.overlays,
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


def test_a_report_whose_sessions_moved_hands_every_client_its_state(api, monkeypatch):
    client, runtime = api
    pushed: list = []
    monkeypatch.setattr(
        channel_serve.channel_state,
        "push_states",
        lambda runtime, role: pushed.append(role),
    )
    device_id, token = bound_device()
    machine = {"hostname": "box", "platform": PLATFORM, "metrics": {}}
    held = {**machine, "sessions": [{"session_id": "s-1"}]}
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(machine=machine))
        socket.receive_json()
        socket.send_json(report(machine=machine))
        socket.send_json(report(machine=held))
        socket.send_json(report(machine=held))
        assert wait_until(
            lambda: runtime.agent_sessions.get(device_id).report_serial == 4
        )

        assert pushed == ["client"]
        # The first report, then the sessions moving, which the panel reads too.
        assert runtime.events.published.count(("device_report", device_id)) == 2
    finally:
        socket.__exit__(None, None, None)


def test_an_uninstall_the_machine_confirms_keeps_the_row_saying_absent(api):
    """The reported bug: the machine took the module off and said so, and
    the row the Modules page reads never agreed with it. What the person
    asked for stays on the row, the machine's word is what the row shows,
    and the state stops naming the module, so nothing installed there
    afterwards is taken off again."""
    client, runtime = api
    store = DesiredStateStore()
    runtime.desired_states = store
    device_id, token = bound_device()
    store.set_want(device_id, "samba", "absent")
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(modules={"samba": {"state": "uninstalling"}}))
        socket.receive_json()
        socket.send_json(report(modules={"samba": {"state": "absent"}}))
        assert wait_until(
            lambda: runtime.agent_sessions.get(device_id).report_serial == 2
        )

        assert runtime.device_modules[device_id]["samba"]["state"] == "absent"
        assert store.want_of(device_id, "samba") == "absent"
        assert store.compose(device_id, PLATFORM)[0]["modules"] == {}
        assert runtime.pushed == [device_id]
        assert ("device_report", device_id) in runtime.events.published
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


# --- the first report on a socket makes the hub's record match the machine ---


SAMBA_DETAILS = {
    "shares": [
        {"name": "media", "path": "/srv/media", "params": {"valid users": "alice"}}
    ],
    "users": [{"name": "alice", "is_present": True, "has_password": True}],
}
SAMBA_IMPORTED = {
    "shares": [
        {
            "name": "media",
            "path": "/srv/media",
            "comment": "",
            "is_read_only": False,
            "valid_users": ["alice"],
        }
    ],
    "users": ["alice"],
}
SAMBA_HELD = {"shares": [], "users": ["bob"]}


def samba(state: str, is_active: bool = True) -> dict:
    return {"state": state, "is_active": is_active, "details": SAMBA_DETAILS}


def adopting(api) -> tuple:
    """A device over the real per-device store, its socket past the welcome."""
    client, runtime = api
    runtime.desired_states = DesiredStateStore()
    device_id, token = bound_device()
    return client, runtime, device_id, token


def reported(runtime, device_id: str, serial: int) -> None:
    assert wait_until(
        lambda: runtime.agent_sessions.get(device_id).report_serial == serial
    )


@pytest.mark.parametrize(
    "is_active, want", [(True, "running"), (False, "stopped")], ids=["up", "down"]
)
def test_a_hand_installed_module_serving_something_is_adopted_as_it_stands(
    api, is_active, want
):
    """S2: a machine joins with shares already served; they become the hub's
    configuration at once and the module is wanted as its unit is."""
    client, runtime, device_id, token = adopting(api)
    store = runtime.desired_states
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(modules={"samba": samba("installed", is_active)}))
        socket.receive_json()
        reported(runtime, device_id, 1)

        assert store.want_of(device_id, "samba") == want
        assert store.modules(device_id)["samba"]["is_settled"] is False
        assert store.read(device_id, "samba") == SAMBA_IMPORTED
        assert runtime.pushed == [device_id]
        assert runtime.published_services.refreshes == 2
    finally:
        socket.__exit__(None, None, None)


def test_a_module_whose_configuration_the_hub_kept_is_wanted_as_it_reports(api):
    """S4: the hub still holds the module's file and no want; the want is
    the machine's word and the file is left as the hub has it."""
    client, runtime, device_id, token = adopting(api)
    store = runtime.desired_states
    store.write(device_id, "samba", SAMBA_HELD)
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(modules={"samba": samba("stopped")}))
        socket.receive_json()
        reported(runtime, device_id, 1)

        assert store.want_of(device_id, "samba") == "stopped"
        assert store.read(device_id, "samba") == SAMBA_HELD
        assert runtime.pushed == [device_id]
    finally:
        socket.__exit__(None, None, None)


def test_a_configured_module_the_hub_lost_is_imported_and_a_gitea_is_not(api):
    """S5: the machine carries the hub's mark and the hub holds nothing. The
    share is taken back from the machine; Gitea, whose configuration is the
    hub's own secrets, stays as it reports until Configure."""
    client, runtime, device_id, token = adopting(api)
    store = runtime.desired_states
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(
            report(
                modules={
                    "samba": samba("running"),
                    "gitea": {
                        "state": "running",
                        "is_active": True,
                        "details": {"url": "http://192.168.100.7:3000"},
                    },
                }
            )
        )
        socket.receive_json()
        reported(runtime, device_id, 1)

        assert store.want_of(device_id, "samba") == "running"
        assert store.read(device_id, "samba") == SAMBA_IMPORTED
        assert store.want_of(device_id, "gitea") == ""
        assert store.read(device_id, "gitea") == {}
        assert not store.has_gitea_secrets(device_id)
        assert runtime.pushed == [device_id]
    finally:
        socket.__exit__(None, None, None)


def test_a_gitea_whose_secrets_the_hub_holds_is_wanted_as_it_reports(api):
    client, runtime, device_id, token = adopting(api)
    store = runtime.desired_states
    store.gitea_secrets(device_id)
    store.write(device_id, "gitea", {"listen_port": 3000})
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(
            report(modules={"gitea": {"state": "running", "is_active": True}})
        )
        socket.receive_json()
        reported(runtime, device_id, 1)

        assert store.want_of(device_id, "gitea") == "running"
        assert runtime.pushed == [device_id]
    finally:
        socket.__exit__(None, None, None)


def test_a_module_the_hub_wants_is_left_as_the_hub_has_it(api):
    """S6: a reconnect with no leave. The hub's copy is the truth, whatever
    the machine reports."""
    client, runtime, device_id, token = adopting(api)
    store = runtime.desired_states
    store.set_want(device_id, "samba", "running")
    store.write(device_id, "samba", SAMBA_HELD)
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(modules={"samba": samba("installed")}))
        socket.receive_json()
        reported(runtime, device_id, 1)

        assert store.want_of(device_id, "samba") == "running"
        assert store.read(device_id, "samba") == SAMBA_HELD
        assert runtime.pushed == []
        assert runtime.published_services.refreshes == 1
    finally:
        socket.__exit__(None, None, None)


def test_a_module_in_transit_or_failed_is_left_alone(api):
    """S9: nothing is read off a module mid-step; the next socket's first
    report looks again."""
    client, runtime, device_id, token = adopting(api)
    store = runtime.desired_states
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(
            report(
                modules={
                    "samba": samba("installing"),
                    "podman": {
                        "state": "failed",
                        "code": "install_failed",
                        "details": {"containers": [{"name": "web", "image": "x"}]},
                    },
                }
            )
        )
        socket.receive_json()
        reported(runtime, device_id, 1)

        assert store.modules(device_id) == {}
        assert store.read(device_id, "samba") == {}
        assert store.read(device_id, "podman") == {}
        assert runtime.pushed == []
    finally:
        socket.__exit__(None, None, None)


def test_a_module_wanted_installed_alone_is_left_installed(api):
    """S12: Install was pressed and Configure never was; the want stands."""
    client, runtime, device_id, token = adopting(api)
    store = runtime.desired_states
    store.set_want(device_id, "samba", "installed")
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(modules={"samba": samba("installed")}))
        socket.receive_json()
        reported(runtime, device_id, 1)

        assert store.want_of(device_id, "samba") == "installed"
        assert store.read(device_id, "samba") == {}
        assert runtime.pushed == []
    finally:
        socket.__exit__(None, None, None)


def test_only_a_sockets_first_report_adopts(api):
    """S14: what is installed by hand while the socket is open is shown and
    not taken."""
    client, runtime, device_id, token = adopting(api)
    store = runtime.desired_states
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report(modules={"samba": {"state": "absent"}}))
        socket.receive_json()
        socket.send_json(report(modules={"samba": samba("installed")}))
        reported(runtime, device_id, 2)

        assert runtime.device_modules[device_id]["samba"]["state"] == "installed"
        assert store.modules(device_id) == {}
        assert store.read(device_id, "samba") == {}
        assert runtime.pushed == []
    finally:
        socket.__exit__(None, None, None)


# --- streams the agent opens ---


def test_a_package_stream_is_served_under_credit_with_its_digest_in_the_close(api):
    """G137: the close names the release file, which msiexec reinstalls from."""
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
            "params": {
                "sha256": hashlib.sha256(expected).hexdigest(),
                "name": "neutrino-agent-0.5.0-amd64.deb",
            },
        }
        assert runtime.agent_packages.asked == [("deb", "amd64")]
    finally:
        socket.__exit__(None, None, None)


def test_a_package_is_read_from_its_file_and_sent_in_64_kb_pieces(api, monkeypatch):
    client, runtime = api
    big = runtime.package_path
    expected = b"!<arch>" + os.urandom(300 * 1024)
    big.write_bytes(expected)
    reads: list = []
    real_open = Path.open

    def recording_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        if path == big:
            real_read = handle.read

            def read(size=-1):
                reads.append(size)
                return real_read(size)

            handle.read = read
        return handle

    monkeypatch.setattr(Path, "open", recording_open)
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report())
        socket.receive_json()

        socket.send_json({"type": "open", "stream": 1, "kind": "package"})
        socket.receive_json()
        socket.send_json({"type": "credit", "stream": 1, "bytes": len(expected)})
        pieces: list = []
        while sum(len(piece) for piece in pieces) < len(expected):
            pieces.append(socket.receive_bytes()[4:])
        close = socket.receive_json()

        assert b"".join(pieces) == expected
        assert close["params"]["sha256"] == hashlib.sha256(expected).hexdigest()
        assert reads and set(reads) == {CHANNEL_CHUNK_BYTES}
        assert max(len(piece) for piece in pieces) <= CHANNEL_CHUNK_BYTES
        assert len(pieces) >= len(expected) // CHANNEL_CHUNK_BYTES
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

        assert close["params"]["sha256"] == hashlib.sha256(expected).hexdigest()
        assert runtime.agent_modules.asked == [("samba", PLATFORM)]
    finally:
        socket.__exit__(None, None, None)


def test_a_module_download_and_its_sending_are_lines_of_the_modules_task(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report())
        socket.receive_json()
        socket.send_json(
            {"type": "open", "stream": 1, "kind": "log", "module": "samba"}
        )
        socket.receive_json()
        label = channel_serve.module_task_label(device_id, "samba")
        assert wait_until(lambda: runtime.tasks.running(label) is not None)
        expected = runtime.package_path.read_bytes()

        socket.send_json(
            {"type": "open", "stream": 3, "kind": "package", "module": "samba"}
        )
        socket.receive_json()
        socket.send_json({"type": "credit", "stream": 3, "bytes": len(expected)})
        received = b""
        while len(received) < len(expected):
            received += socket.receive_bytes()[4:]
        socket.receive_json()

        task = runtime.tasks.running(label)
        assert wait_until(lambda: len(task.buffer) == 2)
        assert task.buffer == [
            "hub: downloading samba, 1.0 / 1.0 MB\n",
            "hub: sending 0.1 MB to box\n",
        ]
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


def test_a_log_stream_is_the_task_the_panel_follows_to_the_modules_state(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report())
        socket.receive_json()

        socket.send_json(
            {"type": "open", "stream": 1, "kind": "log", "module": "samba"}
        )
        assert socket.receive_json()["type"] == "credit"
        socket.send_bytes((1).to_bytes(4, "big") + b"samba: installing\n")
        socket.send_bytes((1).to_bytes(4, "big") + b"Setting up samba\n")
        socket.send_json(
            {
                "type": "close",
                "stream": 1,
                "code": "",
                "params": {"state": "installed"},
            }
        )

        label = channel_serve.module_task_label(device_id, "samba")
        assert wait_until(
            lambda: any(
                stream.label == label and stream.is_finished
                for stream in runtime.tasks.streams()
            )
        )
        (task,) = [s for s in runtime.tasks.streams() if s.label == label]
        assert "".join(task.buffer) == (
            "samba: installing\nSetting up samba\n[installed]\n"
        )
        assert task.exit_code == 0
    finally:
        socket.__exit__(None, None, None)


def test_a_log_stream_closed_with_a_code_ends_the_task_with_it(api):
    client, runtime = api
    device_id, token = bound_device()
    socket = welcomed(client, device_id, token)
    try:
        socket.send_json(report())
        socket.receive_json()

        socket.send_json(
            {"type": "open", "stream": 3, "kind": "log", "module": "samba"}
        )
        socket.receive_json()
        socket.send_json(
            {
                "type": "close",
                "stream": 3,
                "code": "install_failed",
                "params": {"state": "failed", "detail": "apt refused"},
            }
        )

        label = channel_serve.module_task_label(device_id, "samba")
        assert wait_until(
            lambda: any(
                stream.label == label and stream.is_finished
                for stream in runtime.tasks.streams()
            )
        )
        (task,) = [s for s in runtime.tasks.streams() if s.label == label]
        assert "".join(task.buffer) == (
            '{"code": "install_failed", "params": {"detail": "apt refused"}}\n'
            "[failed]\n"
        )
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
            "device_id",
            "device_name",
        }
        # The TestClient's peer is "testclient": on no served network, so
        # the scope is the link it reached the hub on.
        (scope,) = runtime.published_services.scopes
        assert (scope.id, scope.hub_address) == ("link", "testserver")
        assert runtime.client_scope[client_id] == scope
        stored = ClientRegistry().get(client_id)
        assert (stored.hostname, stored.version) == ("laptop", "1.2.3")
        assert stored.platform == PLATFORM

        socket.send_json(client_report(state["hash"]))
        socket.send_json({"type": "open", "stream": 1, "kind": "package"})
        assert socket.receive_json()["code"] == "kind_unknown"
    finally:
        socket.__exit__(None, None, None)
    assert wait_until(lambda: not runtime.client_sessions.is_online(client_id))


def test_a_later_client_report_whose_hash_differs_is_answered_with_the_state(api):
    """A push a client missed heals on its next report: the hub compares
    every report's hash, not only the first's."""
    client, runtime = api
    client_id, token = bound_client()
    socket = welcomed(client, client_id, token, role="client")
    try:
        socket.send_json(client_report())
        first = socket.receive_json()
        assert first["urls"] == ["https://192.168.100.1:8443"]

        runtime.urls = ["https://192.168.100.1:8443", "https://100.64.0.1:8443"]
        socket.send_json(client_report(first["hash"]))

        again = socket.receive_json()
        assert again["type"] == "state"
        assert again["urls"] == runtime.urls
        assert again["hash"] != first["hash"]
        session = runtime.client_sessions.get(client_id)
        assert session.offered_hash == again["hash"]
        socket.send_json(client_report(again["hash"]))
        socket.send_json({"type": "open", "stream": 1, "kind": "package"})
        assert socket.receive_json()["code"] == "kind_unknown"
    finally:
        socket.__exit__(None, None, None)


def test_a_refresh_report_is_answered_with_the_whole_state_whatever_its_hash(api):
    client, runtime = api
    client_id, token = bound_client()
    socket = welcomed(client, client_id, token, role="client")
    try:
        socket.send_json(client_report())
        first = socket.receive_json()

        socket.send_json({**client_report(first["hash"]), "is_refresh": True})

        again = socket.receive_json()
        assert again == first
        socket.send_json(client_report(first["hash"]))
        socket.send_json({"type": "open", "stream": 1, "kind": "package"})
        assert socket.receive_json()["code"] == "kind_unknown"
    finally:
        socket.__exit__(None, None, None)


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


def test_a_client_opens_shell_and_command_streams_beside_its_service_ones(api):
    client, runtime = api
    client_id, token = bound_client()
    socket = welcomed(client, client_id, token, role="client")
    try:
        socket.send_json(
            {"type": "open", "stream": 1, "kind": "shell", "device_id": "gone"}
        )
        assert socket.receive_json()["type"] == "credit"
        assert socket.receive_json() == {
            "type": "close",
            "stream": 1,
            "code": "agent_offline",
            "params": {"device": "gone"},
        }
        socket.send_json(
            {
                "type": "open",
                "stream": 3,
                "kind": "command",
                "module": "agent",
                "verb": "resize",
                "shell": 1,
            }
        )
        assert socket.receive_json()["type"] == "credit"
        assert socket.receive_json()["code"] == "shell_unknown"
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
            "params": {"password": "seat-pass"},  # scan: allow
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
        lambda registry, held, *, served_models: {
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
            "api_key": "key-one",  # scan: allow
            "model": "claude-x",
        }
    finally:
        socket.__exit__(None, None, None)


def test_a_clients_connect_reaches_the_agent_and_bytes_cross_both_ways(api):
    client, runtime = api
    device_id, device_token = bound_device()
    runtime.published_services.entries = [{**ENTRY, "device_id": device_id}]
    client_id, client_token = bound_client()
    agent = welcomed(client, device_id, device_token)
    person = welcomed(client, client_id, client_token, role="client")
    try:
        person.send_json(
            {"type": "open", "stream": 1, "kind": "connect", "id": "web_gitea"}
        )
        assert person.receive_json()["type"] == "credit"
        opened = agent.receive_json()
        assert {key: opened[key] for key in ("type", "kind", "port")} == {
            "type": "open",
            "kind": "connect",
            "port": 3000,
        }
        assert agent.receive_json() == {
            "type": "credit",
            "stream": opened["stream"],
            "bytes": CHANNEL_STREAM_CREDIT_BYTES,
        }
        far = opened["stream"].to_bytes(4, "big")
        agent.send_json({"type": "credit", "stream": opened["stream"], "bytes": 64})
        person.send_json({"type": "credit", "stream": 1, "bytes": 64})

        person.send_bytes((1).to_bytes(4, "big") + b"GET /")
        assert agent.receive_bytes() == far + b"GET /"
        agent.send_bytes(far + b"200 OK")
        received = person.receive()
        while received.get("bytes") is None:
            assert '"credit"' in received["text"]
            received = person.receive()
        assert received["bytes"] == (1).to_bytes(4, "big") + b"200 OK"
        agent.send_json(
            {"type": "close", "stream": opened["stream"], "code": "", "params": {}}
        )
        frames = text_frames(frames_until(person, "close"))
        assert frames[-1] == {"type": "close", "stream": 1, "code": "", "params": {}}
    finally:
        person.__exit__(None, None, None)
        agent.__exit__(None, None, None)


def test_a_panel_service_stream_closes_with_a_sign_in_token_or_its_refusal(api):
    client, runtime = api
    runtime.panel_tokens = PanelTokenStore()
    client_id, token = bound_client()
    socket = welcomed(client, client_id, token, role="client")
    try:
        socket.send_json(
            {"type": "open", "stream": 1, "kind": "service", "is_panel": True}
        )
        socket.receive_json()
        refused = socket.receive_json()
        ClientRegistry().set_permission(client_id, ["panel"])
        socket.send_json(
            {"type": "open", "stream": 3, "kind": "service", "is_panel": True}
        )
        socket.receive_json()
        answered = socket.receive_json()
    finally:
        socket.__exit__(None, None, None)

    assert (refused["code"], refused["params"]) == (
        "permission_denied",
        {"kind": "panel"},
    )
    assert answered["code"] == ""
    assert runtime.panel_tokens.spend(answered["params"]["token"]) == (client_id, "")
