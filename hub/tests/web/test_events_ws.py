"""The panel's event socket, driven end to end through the test client.

The panel holds one of these open and refetches what it draws when a frame
arrives, so what is pinned here is the socket's gate, the frame it opens
with, and that the things a page watches — a machine's channel, a report
saying something new, a report saying nothing new, a machine's vitals, and a
write under ``config/`` — reach it exactly as often as they should, carrying
what they carry.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_AGENT, PROTOCOL
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.utils.json_file import set_config_write_hook, write_config
from neutrino_hub.web import identity, ws
from neutrino_hub.web.constants import (
    WEB_EVENT_CONFIG,
    WEB_EVENT_DEVICE_REPORT,
    WEB_EVENT_DEVICES,
    WEB_EVENT_HELLO,
    WEB_EVENT_METRICS,
)
from neutrino_hub.web.dependencies import session_cookie
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.routers import channel as channel_router
from tests.conftest import StubDesiredStates, StubPublishedServices

SESSION_TOKEN = "panel-session"
# This panel answers on the default port, so its cookie is named for it.
SESSION_COOKIE = session_cookie(SimpleNamespace(settings={}))
POLICY_VIOLATION_CODE = 1008


class StubSessions:
    """The panel's session store: one token is signed in."""

    def is_valid(self, token) -> bool:
        return token == SESSION_TOKEN


class _EmptyNetwork:
    lan_interfaces: list = []


class FakeRuntime:
    """The runtime both sockets reach, wired to the bus as the panel's is."""

    def __init__(self):
        self.settings: dict = {}
        self.events = PanelEventBus()
        self.sessions = StubSessions()
        self.device_metrics = {}
        self.device_modules = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_accounts = {}
        self.device_interfaces = {}
        self.device_address = {}
        self.device_hub_host = {}
        self.device_last_error = {}
        self.device_shares = DeviceShareRegistry()
        self.published_services = StubPublishedServices()
        self.desired_states = StubDesiredStates()
        self.agent_sessions = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        self.agent_sessions.on_presence_change = self._publish_devices
        self.agent_module_orders = AgentModuleController(
            cache=None, locks=DeviceInstallLocks()
        )
        self.desired = ("", {"modules": {}, "desktop": {}})

    def network(self):
        return _EmptyNetwork()

    def desired_state_for(self, device):
        return self.desired

    def push_desired_state(self, key):
        return None

    def _publish_devices(self) -> None:
        self.events.publish(WEB_EVENT_DEVICES)

    def _publish_config_write(self, relative_path: str) -> None:
        self.events.publish(WEB_EVENT_CONFIG, relative_path)


@pytest.fixture
def box(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    identity.ensure_hub_identity()
    monkeypatch.setattr(channel_router, "HUB_VERSION", "1.2.3")
    app = FastAPI()
    app.include_router(ws.router)
    app.include_router(channel_router.router)
    runtime = FakeRuntime()
    app.state.runtime = runtime
    set_config_write_hook(runtime._publish_config_write)
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, SESSION_TOKEN)
        yield client, runtime
    set_config_write_hook(None)


@pytest.fixture
def device():
    """One bound device: its id and the token its hello carries."""
    stored = DeviceRegistry().create("testbox")
    return stored.id, DeviceRegistry().issue_token(stored.id)


def hello(device_id: str, token: str) -> dict:
    return {
        "type": "hello",
        "protocol": PROTOCOL,
        "role": "agent",
        "id": device_id,
        "name": "box",
        "software": "neutrino_agent/1.2.3",
        "token": token,
    }


def report(**sections) -> dict:
    body = {
        "type": "report",
        "state_hash": "",
        "machine": {
            "hostname": "box",
            "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
            "accounts": ["alice"],
            "metrics": {"cpu_percent": 4.0},
        },
        "modules": {"rustdesk": {"state": "installed", "code": "", "params": {}}},
        "desktop": {"is_shared": False},
        "error": None,
    }
    body.update(sections)
    return body


def opened(client):
    """A panel event socket past its hello frame."""
    socket = client.websocket_connect("/ws/hub/event")
    socket.__enter__()
    assert socket.receive_json()["type"] == WEB_EVENT_HELLO
    return socket


def closed(*sockets) -> None:
    """Shut every socket a case opened, newest first."""
    for socket in reversed(sockets):
        socket.__exit__(None, None, None)


def agent_of(client, panel, device):
    """One agent's channel, with the presence event it caused read off."""
    socket = client.websocket_connect("/api/channel/socket")
    socket.__enter__()
    socket.send_json(hello(*device))
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
    client.cookies.delete(SESSION_COOKIE)

    with pytest.raises(WebSocketDisconnect) as refusal:
        with client.websocket_connect("/ws/hub/event"):
            pass

    assert refusal.value.code == POLICY_VIOLATION_CODE


def test_the_socket_opens_with_a_hello_frame(box):
    client, _ = box

    with client.websocket_connect("/ws/hub/event") as socket:
        frame = socket.receive_json()

    assert frame["type"] == WEB_EVENT_HELLO
    assert frame["key"] == ""
    assert frame["at"]


def test_a_channel_opening_says_the_device_list_moved(box, device):
    client, _ = box
    panel = opened(client)

    agent = client.websocket_connect("/api/channel/socket")
    agent.__enter__()
    agent.send_json(hello(*device))
    agent.receive_json()
    frame = panel.receive_json()
    closed(agent, panel)

    assert frame["type"] == WEB_EVENT_DEVICES
    assert frame["key"] == ""


def test_a_report_with_a_new_module_state_says_so_for_that_device(box, device):
    client, _ = box
    panel = opened(client)
    agent = agent_of(client, panel, device)

    agent.send_json(report())
    frame = panel.receive_json()
    closed(agent, panel)

    assert frame["type"] == WEB_EVENT_DEVICE_REPORT
    assert frame["key"] == device[0]


def vitals(**metrics) -> dict:
    """A report's machine section carrying these metrics."""
    return report(
        machine={
            "hostname": "box",
            "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
            "accounts": ["alice"],
            "metrics": metrics,
        }
    )


def test_every_report_carries_the_machines_vitals(box, device):
    client, _ = box
    panel = opened(client)
    agent = agent_of(client, panel, device)

    agent.send_json(vitals(cpu_percent=91.0, gpus=[]))
    frames = frames_until(panel, WEB_EVENT_METRICS)
    closed(agent, panel)

    metrics = frames[-1]
    assert metrics["key"] == device[0]
    assert metrics["data"] == {"cpu_percent": 91.0, "gpus": []}


def test_a_report_saying_nothing_new_asks_for_no_refetch(box, device):
    client, _ = box
    panel = opened(client)
    agent = agent_of(client, panel, device)
    agent.send_json(report())
    assert frames_until(panel, WEB_EVENT_METRICS)[0]["type"] == (
        WEB_EVENT_DEVICE_REPORT
    )

    agent.send_json(vitals(cpu_percent=91.0))
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

    write_config("devices/device-one/samba.json", {"is_enabled": True})
    frame = panel.receive_json()
    closed(panel)

    assert frame["type"] == WEB_EVENT_CONFIG
    assert frame["key"] == "devices/device-one/samba.json"
