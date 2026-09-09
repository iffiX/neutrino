"""The agent channel's socket, driven end to end through the test client.

The test plays the agent: it connects, says hello, reads the welcome,
reports, answers the streams the hub opens. What these pin is the wire
both sides must match — the hello gate and its close codes, the welcome,
what a report lands in the runtime, the empty state answer, an order and a
command opened from a hub thread and closed with the machine's word, and
that a socket ending takes the device offline, stamped and unshared.
"""

import hashlib
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.agent_sessions import (
    AgentOfflineError,
    AgentSessionRegistry,
    StreamRefusedError,
)
from neutrino_hub.modules.devices.constants import AGENT_WIRE_GENERATION
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.routers import agent as agent_router
from neutrino_hub.web.routers import agent_ws
from tests.conftest import StubDesiredStates

MAC = "aa:bb:cc:dd:ee:ff"
TOKEN = "device-token"


class FakeRegistry:
    """A registry of one device, in memory; the router builds one per socket."""

    device: ManagedDevice

    @classmethod
    def reset(cls, device: ManagedDevice) -> None:
        cls.device = device

    def find_by_client_token(self, token):
        stored = FakeRegistry.device.client.token_sha256
        presented = hashlib.sha256(token.encode()).hexdigest()
        return FakeRegistry.device if stored and stored == presented else None


class StubPublishedServices:
    def __init__(self):
        self.expiries = 0

    def expire(self):
        self.expiries += 1


class _EmptyNetwork:
    lan_interfaces: list = []


class FakeRuntime:
    """Only the parts of the runtime the socket touches."""

    def __init__(self):
        self.events = PanelEventBus()
        self.client_metrics = {}
        self.client_modules = {}
        self.client_platform = {}
        self.client_hostname = {}
        self.client_accounts = {}
        self.client_address = {}
        self.client_device_host = {}
        self.client_last_error = {}
        self.device_shares = DeviceShareRegistry()
        self.published_services = StubPublishedServices()
        self.desired_states = StubDesiredStates()
        self.agent_sessions = AgentSessionRegistry()
        self.agent_module_orders = AgentModuleController(
            cache=None, locks=DeviceInstallLocks()
        )
        self.state_requests = 0
        self.desired = ("", {})

    def network(self):
        return _EmptyNetwork()

    def desired_state_for(self, device):
        self.state_requests += 1
        return self.desired


@pytest.fixture
def api(monkeypatch):
    FakeRegistry.reset(
        ManagedDevice(
            mac_address=MAC,
            name="testbox",
            client=DeviceClientInfo(
                token_sha256=hashlib.sha256(TOKEN.encode()).hexdigest()
            ),
        )
    )
    monkeypatch.setattr(agent_ws, "DeviceRegistry", FakeRegistry)
    monkeypatch.setattr(agent_ws, "HUB_VERSION", "1.2.3")
    monkeypatch.setattr(agent_router, "HUB_VERSION", "1.2.3")
    monkeypatch.setattr(agent_ws, "AGENT_WS_HELLO_TIMEOUT_S", 0.3)
    app = FastAPI()
    app.include_router(agent_ws.router)
    runtime = FakeRuntime()
    app.state.runtime = runtime
    with TestClient(app) as client:
        yield client, runtime


def hello(**fields) -> dict:
    body = {
        "type": "hello",
        "token": TOKEN,
        "client_version": "1.2.3",
        "wire": AGENT_WIRE_GENERATION,
        "hostname": "box",
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
        "addresses": [{"mac": MAC, "address": "192.168.100.7"}],
        "accounts": ["alice"],
        "state_hash": "",
    }
    body.update(fields)
    return body


def report(**fields) -> dict:
    body = {
        "type": "report",
        "metrics": {"cpu_percent": 4.0},
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
        "addresses": [{"mac": MAC, "address": "192.168.100.7"}],
        "accounts": ["alice", "bob"],
        "modules": {"rustdesk": {"state": "installed", "code": "", "params": {}}},
        "state_hash": "",
        "state_error": None,
        "rdp": {"is_shared": False},
        "last_error": None,
    }
    body.update(fields)
    return body


def closed_with(socket) -> tuple:
    """The close code and reason the hub ended the socket with."""
    message = socket.receive()
    assert message["type"] == "websocket.close"
    return message["code"], message.get("reason", "")


def welcomed(client, **fields):
    """A socket past its hello, with the welcome read."""
    socket = client.websocket_connect("/api/agent/ws")
    socket.__enter__()
    socket.send_json(hello(**fields))
    welcome = socket.receive_json()
    return socket, welcome


def wait_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- the hello gate ---


def test_a_late_hello_closes_the_socket(api):
    client, _ = api

    with client.websocket_connect("/api/agent/ws") as socket:
        assert closed_with(socket) == (4400, "bad_hello")


def test_a_first_frame_that_is_no_hello_closes_the_socket(api):
    client, _ = api

    with client.websocket_connect("/api/agent/ws") as socket:
        socket.send_json({"type": "report"})
        assert closed_with(socket) == (4400, "bad_hello")


def test_an_unknown_token_closes_with_its_own_code(api):
    client, runtime = api

    with client.websocket_connect("/api/agent/ws") as socket:
        socket.send_json(hello(token="nonsense"))  # scan: allow
        assert closed_with(socket) == (4401, "unknown_token")
    assert not runtime.agent_sessions.is_online(MAC)


def test_another_wire_generation_is_refused_with_the_code_word(api):
    client, runtime = api

    with client.websocket_connect("/api/agent/ws") as socket:
        socket.send_json(hello(wire=1))
        assert closed_with(socket) == (4409, "agent_wire_stale")
    assert not runtime.agent_sessions.is_online(MAC)
    # A refusal is not a sighting: the device has no version and no stamp.
    assert runtime.agent_sessions.version_of(MAC) == ""
    assert runtime.agent_sessions.last_seen_at(MAC) is None


def test_a_newer_agent_is_refused_with_the_code_word(api):
    client, _ = api

    with client.websocket_connect("/api/agent/ws") as socket:
        socket.send_json(hello(client_version="1.3.0"))
        assert closed_with(socket) == (4409, "agent_newer_than_hub")


# --- hello and welcome ---


def test_a_good_hello_is_welcomed_and_puts_the_device_online(api):
    client, runtime = api

    socket, welcome = welcomed(client)
    try:
        assert welcome == {
            "type": "welcome",
            "hub_version": "1.2.3",
            "device_id": MAC,
            "state_hash": "",
        }
        assert runtime.agent_sessions.is_online(MAC)
        session = runtime.agent_sessions.get(MAC)
        assert (session.hostname, session.version) == ("box", "1.2.3")
        assert runtime.client_hostname[MAC] == "box"
        assert runtime.client_platform[MAC]["arch"] == "amd64"
        assert runtime.client_accounts[MAC] == ["alice"]
        # The address on the identity MAC, over the socket's own peer.
        assert runtime.client_address[MAC] == "192.168.100.7"
        assert runtime.client_device_host[MAC]
        # The hello's version is held in memory; an online device has no
        # last-seen stamp.
        assert runtime.agent_sessions.version_of(MAC) == "1.2.3"
        assert runtime.agent_sessions.last_seen_at(MAC) is None
    finally:
        socket.__exit__(None, None, None)


def test_the_socket_ending_takes_the_device_offline_and_stamps_it(api):
    client, runtime = api
    socket, _ = welcomed(client)
    socket.send_json(report(rdp={"is_shared": True, "share_id": "s1"}))
    assert wait_until(lambda: runtime.device_shares.live())

    socket.__exit__(None, None, None)

    assert wait_until(lambda: not runtime.agent_sessions.is_online(MAC))
    # The detach stamps the device under the same lock that took it
    # offline, so the stamp is there the moment the device reads offline.
    assert runtime.agent_sessions.last_seen_at(MAC)
    assert runtime.agent_sessions.version_of(MAC) == "1.2.3"
    assert wait_until(lambda: runtime.device_shares.live() == [])


# --- the install a returned agent came from ---

REINSTALL_RESULT = {
    "package": "neutrino-agent_1.2.3_amd64.deb",
    "kind": "deb",
    "started_at": "2026-09-10T10:00:00Z",
    "finished_at": "2026-09-10T10:00:12Z",
    "exit_code": 0,
    "output": "Setting up neutrino-agent\n",
}


def test_a_hello_carrying_a_reinstall_record_lands_before_any_report(api):
    client, runtime = api

    socket, _ = welcomed(client, last_reinstall=REINSTALL_RESULT)
    try:
        session = runtime.agent_sessions.get(MAC)
        assert session.report["last_reinstall"] == REINSTALL_RESULT
        assert session.reported_at == ""
    finally:
        socket.__exit__(None, None, None)


def test_a_report_carries_the_reinstall_record_on(api):
    client, runtime = api
    socket, _ = welcomed(client)
    try:
        socket.send_json(report(last_reinstall=REINSTALL_RESULT))

        assert wait_until(
            lambda: runtime.agent_sessions.get(MAC).report.get("last_reinstall")
        )
        assert (
            runtime.agent_sessions.get(MAC).report["last_reinstall"] == REINSTALL_RESULT
        )
    finally:
        socket.__exit__(None, None, None)


def test_a_report_without_a_reinstall_record_leaves_none_standing(api):
    client, runtime = api
    socket, _ = welcomed(client, last_reinstall=REINSTALL_RESULT)
    try:
        socket.send_json(report())

        assert wait_until(lambda: runtime.agent_sessions.get(MAC).reported_at)
        assert "last_reinstall" not in runtime.agent_sessions.get(MAC).report
    finally:
        socket.__exit__(None, None, None)


# --- reports ---


def test_a_report_lands_in_the_runtime_and_declares_the_share(api):
    client, runtime = api
    socket, _ = welcomed(client)
    try:
        socket.send_json(
            report(
                rdp={"is_shared": True, "share_id": "s1", "port": 21118},
                last_error={"code": "hub_unreachable", "params": {}},
            )
        )

        assert wait_until(lambda: MAC in runtime.client_metrics)
        assert runtime.client_metrics[MAC] == {"cpu_percent": 4.0}
        assert runtime.client_modules[MAC]["rustdesk"]["state"] == "installed"
        assert runtime.client_accounts[MAC] == ["alice", "bob"]
        assert runtime.client_last_error[MAC] == {
            "code": "hub_unreachable",
            "params": {},
        }
        (share,) = runtime.device_shares.live()
        assert (share.share_id, share.host, share.port) == (
            "s1",
            "192.168.100.7",
            21118,
        )
        assert runtime.agent_sessions.get(MAC).report["metrics"] == {"cpu_percent": 4.0}
        # A report is not an ending: the device is still online, unstamped.
        assert runtime.agent_sessions.last_seen_at(MAC) is None
    finally:
        socket.__exit__(None, None, None)


def test_a_state_request_is_answered_with_an_empty_state(api):
    client, runtime = api
    socket, _ = welcomed(client)
    try:
        socket.send_json({"type": "state_request"})

        assert socket.receive_json() == {"type": "state", "hash": "", "desired": {}}
        assert runtime.state_requests == 2
    finally:
        socket.__exit__(None, None, None)


def test_a_frame_that_is_no_object_is_ignored(api):
    client, runtime = api
    socket, _ = welcomed(client)
    try:
        socket.send_text("not json")
        socket.send_text("[1, 2]")
        socket.send_json({"type": "state_request"})

        assert socket.receive_json()["type"] == "state"
        assert runtime.agent_sessions.is_online(MAC)
    finally:
        socket.__exit__(None, None, None)


# --- streams ---


def test_an_order_opened_from_a_thread_runs_to_the_machines_close(api):
    client, runtime = api
    socket, _ = welcomed(client)
    lines: list = []
    outcome: dict = {}

    def hub_side():
        outcome["info"] = runtime.agent_sessions.run_order_from_thread(
            MAC,
            {"id": "o1", "module": "rustdesk", "action": "install"},
            on_line=lines.append,
            timeout=5.0,
        )

    thread = threading.Thread(target=hub_side)
    try:
        thread.start()
        opened = socket.receive_json()
        assert opened["type"] == "open"
        assert opened["kind"] == "order"
        assert opened["args"] == {"id": "o1", "module": "rustdesk", "action": "install"}
        assert opened["credit"] > 0
        stream = opened["stream"]
        socket.send_json({"type": "opened", "stream": stream})
        socket.send_json(
            {"type": "event", "stream": stream, "line": "rustdesk: install"}
        )
        socket.send_json({"type": "event", "stream": stream, "line": "Setting up"})
        socket.send_json(
            {
                "type": "close",
                "stream": stream,
                "state": "done",
                "code": "",
                "params": {},
                "output": "rustdesk: install\nSetting up",
            }
        )
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert lines == ["rustdesk: install", "Setting up"]
        assert outcome["info"]["state"] == "done"
        assert outcome["info"]["output"] == "rustdesk: install\nSetting up"
    finally:
        socket.__exit__(None, None, None)


def test_a_command_rides_the_same_way_and_closes_with_its_exit(api):
    client, runtime = api
    socket, _ = welcomed(client)
    outcome: dict = {}

    def hub_side():
        outcome["info"] = runtime.agent_sessions.run_command_from_thread(
            MAC, "reboot", timeout=5.0
        )

    thread = threading.Thread(target=hub_side)
    try:
        thread.start()
        opened = socket.receive_json()
        assert opened["kind"] == "command"
        assert opened["args"] == {"action": "reboot", "args": {}}
        stream = opened["stream"]
        socket.send_json({"type": "opened", "stream": stream})
        socket.send_json(
            {
                "type": "close",
                "stream": stream,
                "exit_code": 0,
                "code": "",
                "params": {},
                "output": "rebooting\n",
            }
        )
        thread.join(timeout=5)

        assert outcome["info"] == {
            "exit_code": 0,
            "code": "",
            "params": {},
            "output": "rebooting\n",
        }
    finally:
        socket.__exit__(None, None, None)


def test_a_refused_stream_carries_the_agents_code(api):
    client, runtime = api
    socket, _ = welcomed(client)
    outcome: dict = {}

    def hub_side():
        try:
            runtime.agent_sessions.open_stream_from_thread(
                MAC, "shell", {}, timeout=5.0
            )
        except StreamRefusedError as refused:
            outcome["code"] = refused.code
            outcome["params"] = refused.params

    thread = threading.Thread(target=hub_side)
    try:
        thread.start()
        opened = socket.receive_json()
        socket.send_json(
            {
                "type": "refused",
                "stream": opened["stream"],
                "code": "stream_unknown",
                "params": {"kind": "shell"},
            }
        )
        thread.join(timeout=5)

        assert outcome == {
            "code": "stream_unknown",
            "params": {"kind": "shell"},
        }
    finally:
        socket.__exit__(None, None, None)


def test_a_binary_frame_reaches_its_stream_and_credit_comes_back(api):
    client, runtime = api
    socket, _ = welcomed(client)
    outcome: dict = {}

    def hub_side():
        stream = runtime.agent_sessions.open_stream_from_thread(
            MAC, "file_download", {}, timeout=5.0
        )
        outcome["item"] = stream.recv_from_thread(timeout=5.0)

    thread = threading.Thread(target=hub_side)
    try:
        thread.start()
        opened = socket.receive_json()
        stream = opened["stream"]
        socket.send_json({"type": "opened", "stream": stream})
        socket.send_bytes(stream.encode() + b"file bytes")
        thread.join(timeout=5)

        assert outcome["item"] == ("data", b"file bytes")
        assert socket.receive_json() == {
            "type": "credit",
            "stream": stream,
            "bytes": len(b"file bytes"),
        }
    finally:
        socket.__exit__(None, None, None)


def test_a_device_with_no_socket_is_offline_to_a_thread(api):
    _, runtime = api

    with pytest.raises(AgentOfflineError):
        runtime.agent_sessions.run_command_from_thread(MAC, "reboot")


def test_a_second_socket_from_the_same_device_replaces_the_first(api):
    client, runtime = api
    first, _ = welcomed(client)
    try:
        second, _ = welcomed(client)
        try:
            assert closed_with(first) == (4410, "replaced")
            assert runtime.agent_sessions.is_online(MAC)
        finally:
            second.__exit__(None, None, None)
    finally:
        first.__exit__(None, None, None)
    assert wait_until(lambda: not runtime.agent_sessions.is_online(MAC))


def test_the_welcome_state_hash_is_what_the_provider_says(api):
    client, runtime = api
    runtime.desired = ("h9", {"modules": {}})

    socket, welcome = welcomed(client, state_hash="h9")
    try:
        assert welcome["state_hash"] == "h9"
        socket.send_json({"type": "state_request"})
        assert socket.receive_json() == {
            "type": "state",
            "hash": "h9",
            "desired": {"modules": {}},
        }
    finally:
        socket.__exit__(None, None, None)


def test_a_hello_holding_another_state_is_handed_the_state_at_once(api):
    client, runtime = api
    runtime.desired = ("h9", {"modules": {"samba": {"is_enabled": True}}})

    socket, welcome = welcomed(client, state_hash="stale")
    try:
        assert welcome["state_hash"] == "h9"
        assert socket.receive_json() == {
            "type": "state",
            "hash": "h9",
            "desired": {"modules": {"samba": {"is_enabled": True}}},
        }
        # Composed once for the hello, not again for the push.
        assert runtime.state_requests == 1
    finally:
        socket.__exit__(None, None, None)


def test_a_hello_holding_the_same_state_is_handed_nothing(api):
    client, runtime = api
    runtime.desired = ("h9", {"modules": {}})

    socket, _ = welcomed(client, state_hash="h9")
    try:
        socket.send_json({"type": "state_request"})
        # The first frame after the welcome is the answer, not a push.
        assert socket.receive_json()["type"] == "state"
        assert runtime.state_requests == 2
    finally:
        socket.__exit__(None, None, None)
