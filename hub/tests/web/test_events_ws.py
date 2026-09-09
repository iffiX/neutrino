"""The panel's event socket, driven end to end through the test client.

The panel holds one of these open and refetches what it draws when a frame
arrives, so what is pinned here is the socket's gate, the frame it opens
with, and that the things a page watches — a machine's channel, a report
saying something new, a report saying nothing new, a machine's vitals, and a
write under ``config/`` — reach it exactly as often as they should, carrying
what they carry.
"""

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.agent_sessions import AgentSessionRegistry
from neutrino_hub.modules.devices.constants import AGENT_WIRE_GENERATION
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.utils.json_file import set_config_write_hook, write_config
from neutrino_hub.web import ws
from neutrino_hub.web.constants import (
    WEB_EVENT_CONFIG,
    WEB_EVENT_DEVICE_REPORT,
    WEB_EVENT_DEVICES,
    WEB_EVENT_HELLO,
    WEB_EVENT_METRICS,
    WEB_SESSION_COOKIE,
)
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.routers import agent as agent_router
from neutrino_hub.web.routers import agent_ws
from tests.conftest import StubDesiredStates

MAC = "aa:bb:cc:dd:ee:ff"
AGENT_TOKEN = "device-token"
SESSION_TOKEN = "panel-session"
POLICY_VIOLATION_CODE = 1008


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


class StubSessions:
    """The panel's session store: one token is signed in."""

    def is_valid(self, token) -> bool:
        return token == SESSION_TOKEN


class StubPublishedServices:
    def expire(self):
        return None


class _EmptyNetwork:
    lan_interfaces: list = []


class FakeRuntime:
    """The runtime both sockets reach, wired to the bus as the panel's is."""

    def __init__(self):
        self.events = PanelEventBus()
        self.sessions = StubSessions()
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
        self.agent_sessions.on_presence_change = self._publish_devices
        self.agent_module_orders = AgentModuleController(
            cache=None, locks=DeviceInstallLocks()
        )
        self.desired = ("", {})

    def network(self):
        return _EmptyNetwork()

    def desired_state_for(self, device):
        return self.desired

    def _publish_devices(self) -> None:
        self.events.publish(WEB_EVENT_DEVICES)

    def _publish_config_write(self, relative_path: str) -> None:
        self.events.publish(WEB_EVENT_CONFIG, relative_path)


@pytest.fixture
def box(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    FakeRegistry.reset(
        ManagedDevice(
            mac_address=MAC,
            name="testbox",
            client=DeviceClientInfo(
                token_sha256=hashlib.sha256(AGENT_TOKEN.encode()).hexdigest()
            ),
        )
    )
    monkeypatch.setattr(agent_ws, "DeviceRegistry", FakeRegistry)
    monkeypatch.setattr(agent_ws, "HUB_VERSION", "1.2.3")
    monkeypatch.setattr(agent_router, "HUB_VERSION", "1.2.3")
    app = FastAPI()
    app.include_router(ws.router)
    app.include_router(agent_ws.router)
    runtime = FakeRuntime()
    app.state.runtime = runtime
    set_config_write_hook(runtime._publish_config_write)
    with TestClient(app) as client:
        client.cookies.set(WEB_SESSION_COOKIE, SESSION_TOKEN)
        yield client, runtime
    set_config_write_hook(None)


def hello(**fields) -> dict:
    body = {
        "type": "hello",
        "token": AGENT_TOKEN,
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
        "accounts": ["alice"],
        "modules": {"rustdesk": {"state": "installed", "code": "", "params": {}}},
        "state_hash": "",
        "state_error": None,
        "rdp": {"is_shared": False},
        "last_error": None,
    }
    body.update(fields)
    return body


def opened(client):
    """A panel event socket past its hello frame."""
    socket = client.websocket_connect("/ws/events")
    socket.__enter__()
    assert socket.receive_json()["type"] == WEB_EVENT_HELLO
    return socket


def closed(*sockets) -> None:
    """Shut every socket a case opened, newest first."""
    for socket in reversed(sockets):
        socket.__exit__(None, None, None)


def agent_of(client, panel):
    """One agent's channel, with the presence event it caused read off."""
    socket = client.websocket_connect("/api/agent/ws")
    socket.__enter__()
    socket.send_json(hello())
    socket.receive_json()
    assert panel.receive_json()["type"] == WEB_EVENT_DEVICES
    return socket


def frames_until(panel, event_type: str) -> list:
    """Every frame up to and including the next one of this type."""
    frames = []
    while True:
        frame = panel.receive_json()
        frames.append(frame)
        if frame["type"] == event_type:
            return frames


def test_an_unauthenticated_socket_is_closed_on_the_policy_code(box):
    client, _ = box
    client.cookies.delete(WEB_SESSION_COOKIE)

    with pytest.raises(WebSocketDisconnect) as refusal:
        with client.websocket_connect("/ws/events"):
            pass

    assert refusal.value.code == POLICY_VIOLATION_CODE


def test_the_socket_opens_with_a_hello_frame(box):
    client, _ = box

    with client.websocket_connect("/ws/events") as socket:
        frame = socket.receive_json()

    assert frame["type"] == WEB_EVENT_HELLO
    assert frame["key"] == ""
    assert frame["at"]


def test_a_channel_opening_says_the_device_list_moved(box):
    client, _ = box
    panel = opened(client)

    agent = client.websocket_connect("/api/agent/ws")
    agent.__enter__()
    agent.send_json(hello())
    agent.receive_json()
    frame = panel.receive_json()
    closed(agent, panel)

    assert frame["type"] == WEB_EVENT_DEVICES
    assert frame["key"] == ""


def test_a_report_with_a_new_module_state_says_so_for_that_device(box):
    client, _ = box
    panel = opened(client)
    agent = agent_of(client, panel)

    agent.send_json(report())
    frame = panel.receive_json()
    closed(agent, panel)

    assert frame["type"] == WEB_EVENT_DEVICE_REPORT
    assert frame["key"] == MAC


def test_every_report_carries_the_machines_vitals(box):
    client, _ = box
    panel = opened(client)
    agent = agent_of(client, panel)

    agent.send_json(report(metrics={"cpu_percent": 91.0, "gpus": []}))
    frames = frames_until(panel, WEB_EVENT_METRICS)
    closed(agent, panel)

    metrics = frames[-1]
    assert metrics["key"] == MAC
    assert metrics["data"] == {"cpu_percent": 91.0, "gpus": []}


def test_a_report_saying_nothing_new_asks_for_no_refetch(box):
    client, _ = box
    panel = opened(client)
    agent = agent_of(client, panel)
    agent.send_json(report())
    assert frames_until(panel, WEB_EVENT_METRICS)[0]["type"] == (
        WEB_EVENT_DEVICE_REPORT
    )

    agent.send_json(report(metrics={"cpu_percent": 91.0}))
    write_config("router/network.json", {"interfaces": []})
    frames = frames_until(panel, WEB_EVENT_CONFIG)
    closed(agent, panel)

    assert [frame["type"] for frame in frames] == [
        WEB_EVENT_METRICS,
        WEB_EVENT_CONFIG,
    ]


def test_a_config_write_names_the_file_it_wrote(box):
    client, _ = box
    panel = opened(client)

    write_config(f"devices/{MAC}/samba.json", {"is_enabled": True})
    frame = panel.receive_json()
    closed(panel)

    assert frame["type"] == WEB_EVENT_CONFIG
    assert frame["key"] == f"devices/{MAC}/samba.json"
