"""The panel's event socket, driven end to end through the test client.

The panel holds one of these open and refetches what it draws when a frame
arrives, so what is pinned here is the socket's gate, the frame it opens
with, that it closes once its session ends, and that the things a page
watches — a machine's channel, a report
saying something new, a report saying nothing new, a machine's vitals, and a
write under ``config/`` — reach it exactly as often as they should, carrying
what they carry. The agent arrives as the transport brings it: a
``session_open`` event and its frames, through the control handler.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_AGENT, PROTOCOL
from neutrino_hub.modules.channel.port_guard import ChannelPortGuard
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
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
from neutrino_hub.web.channel_serve import ChannelControlHandler
from neutrino_hub.web.dependencies import session_cookie
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.web_share_access import WebShareGuestSessions
from tests.conftest import StubDesiredStates, StubPublishedServices

SESSION_TOKEN = "panel-session"
# This panel answers on the default port, so its cookie is named for it.
SESSION_COOKIE = session_cookie(SimpleNamespace(settings={}))
POLICY_VIOLATION_CODE = 1008


class StubSessions:
    """The panel's session store: one token is signed in until it ends."""

    def __init__(self):
        self.is_ended = False

    def is_valid(self, token) -> bool:
        return token == SESSION_TOKEN and not self.is_ended


class FakeChannel:
    """The local channel as the handler writes to it: every frame kept."""

    def __init__(self):
        self.frames: list = []

    async def send_frame(self, session, frame, *, is_last=False):
        self.frames.append((session, frame, is_last))

    async def send_command(self, command, **fields):
        return {}


class FakeRuntime:
    """The runtime the socket and the handler reach, wired to the bus as the panel's is."""

    def __init__(self):
        self.settings: dict = {}
        self.events = PanelEventBus()
        self.channel = FakeChannel()
        self.channel_port = ChannelPortGuard()
        self.sessions = StubSessions()
        self.device_metrics = {}
        self.device_modules = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_accounts = {}
        self.device_interfaces = {}
        self.device_address = {}
        self.device_scope = {}
        self.device_last_error = {}
        self.device_shares = DeviceShareRegistry()
        self.published_services = StubPublishedServices()
        self.desired_states = StubDesiredStates()
        self.agent_sessions = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        self.web_share_guests = WebShareGuestSessions()
        self.agent_update_sessions = {}
        self.agent_sessions.on_presence_change = self._publish_devices
        self.desired = ("", {"modules": {}, "desktop": {}})

    def host_scopes(self):
        return []

    def desired_state_for(self, device):
        return self.desired

    def settle_legacy_channel(self):
        return None

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
    monkeypatch.setattr("neutrino_hub.web.channel_serve.HUB_VERSION", "1.2.3")
    app = FastAPI()
    app.include_router(ws.router)
    runtime = FakeRuntime()
    app.state.runtime = runtime
    set_config_write_hook(runtime._publish_config_write)
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, SESSION_TOKEN)
        yield client, runtime
    set_config_write_hook(None)


@pytest.fixture
def device():
    """One bound device's id."""
    stored = DeviceRegistry().create("testbox")
    DeviceRegistry().issue_token(stored.id)
    return stored.id


def hello(device_id: str) -> dict:
    return {
        "type": "hello",
        "protocol": PROTOCOL,
        "role": "agent",
        "id": device_id,
        "name": "box",
        "software": "neutrino_agent/1.2.3",
    }


class Agent:
    """One agent's session, driven through the control handler as the
    transport drives it: a ``session_open`` event, then its frames."""

    def __init__(self, runtime, device_id: str):
        self.handler = ChannelControlHandler(runtime)
        self.session_id = "s-1"
        self.device_id = device_id

    def open(self) -> None:
        asyncio.run(self._open())

    def send(self, frame: dict) -> None:
        asyncio.run(self.handler.take_frame(self.session_id, frame))

    def close(self) -> None:
        asyncio.run(
            self.handler.take_event("session_end", {"session": self.session_id})
        )

    async def _open(self):
        await self.handler.take_event(
            "session_open",
            {
                "session": self.session_id,
                "binding_id": self.device_id,
                "role": CHANNEL_ROLE_AGENT,
                "address": "192.168.100.7",
                "listener": "main",
                "local_address": "192.168.100.1",
            },
        )
        await self.handler.take_frame(self.session_id, hello(self.device_id))


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


def closed(*opened) -> None:
    """Shut every socket and session a case opened, newest first."""
    for held in reversed(opened):
        if isinstance(held, Agent):
            held.close()
        else:
            held.__exit__(None, None, None)


def agent_of(runtime, panel, device) -> Agent:
    """One agent's session, with the presence event it caused read off."""
    agent = Agent(runtime, device)
    agent.open()
    assert panel.receive_json()["type"] == WEB_EVENT_DEVICES
    return agent


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
    client, runtime = box
    panel = opened(client)

    agent = Agent(runtime, device)
    agent.open()
    frame = panel.receive_json()
    closed(agent, panel)

    assert frame["type"] == WEB_EVENT_DEVICES
    assert frame["key"] == ""
    assert runtime.channel.frames[0][1]["type"] == "welcome"


def test_a_report_with_a_new_module_state_says_so_for_that_device(box, device):
    client, runtime = box
    panel = opened(client)
    agent = agent_of(runtime, panel, device)

    agent.send(report())
    frame = panel.receive_json()
    closed(agent, panel)

    assert frame["type"] == WEB_EVENT_DEVICE_REPORT
    assert frame["key"] == device


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
    client, runtime = box
    panel = opened(client)
    agent = agent_of(runtime, panel, device)

    agent.send(vitals(cpu_percent=91.0, gpus=[]))
    frames = frames_until(panel, WEB_EVENT_METRICS)
    closed(agent, panel)

    metrics = frames[-1]
    assert metrics["key"] == device
    assert metrics["data"] == {"cpu_percent": 91.0, "gpus": []}


def test_a_report_saying_nothing_new_asks_for_no_refetch(box, device):
    client, runtime = box
    panel = opened(client)
    agent = agent_of(runtime, panel, device)
    agent.send(report())
    assert frames_until(panel, WEB_EVENT_METRICS)[0]["type"] == (
        WEB_EVENT_DEVICE_REPORT
    )

    agent.send(vitals(cpu_percent=91.0))
    metrics = frames_until(panel, WEB_EVENT_METRICS)
    write_config("router/network.json", {"interfaces": []})
    config = frames_until(panel, WEB_EVENT_CONFIG)
    closed(agent, panel)

    assert [frame["type"] for frame in metrics + config] == [
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


def test_a_session_that_ends_closes_its_open_socket(box, monkeypatch):
    client, runtime = box
    monkeypatch.setattr(ws, "WEB_SOCKET_SESSION_CHECK_INTERVAL_S", 0.01)
    panel = opened(client)

    runtime.sessions.is_ended = True

    with pytest.raises(WebSocketDisconnect) as ended:
        while True:
            panel.receive_json()
    assert ended.value.code == POLICY_VIOLATION_CODE
    assert ended.value.reason == "session ended"
    closed(panel)
