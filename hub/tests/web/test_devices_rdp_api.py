"""The drawer's one RustDesk action: resetting a machine's seat password.

Nobody types the password and nobody is shown it, so the route neither
takes one nor answers with one. It generates a fresh one, seals it, and
hands the machine the state that carries it — which is why a machine with
no channel is refused before anything is written.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices import desired_state as desired_state_module
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.web.constants import WEB_EVENT_DEVICE_REPORT
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router
from tests.conftest import FakeAgentSessions, unlock_vault

MAC = "aa:bb:cc:dd:ee:ff"
PATH = f"/api/devices/{MAC}/rdp/seat_password"


class FakeRegistry:
    device: ManagedDevice

    def get(self, mac_address: str) -> ManagedDevice:
        return FakeRegistry.device


class FakeRuntime:
    """The runtime as this one route reaches for it."""

    def __init__(self, online=()):
        self.events = PanelEventBus()
        self.agent_sessions = FakeAgentSessions(online)
        self.desired_states = DesiredStateStore()

    def push_desired_state(self, key: str) -> None:
        desired, state_hash = self.desired_states.compose(key, {})
        self.agent_sessions.push_state_from_thread(key, state_hash, desired)


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "resolved_modules", lambda platform: {})
    unlock_vault(monkeypatch, tmp_path)
    FakeRegistry.device = ManagedDevice(
        mac_address=MAC,
        name="xenode",
        client=DeviceClientInfo(token_sha256="t" * 64),
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", FakeRegistry)
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime(online=[MAC])
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_a_reset_generates_a_password_and_pushes_the_state_carrying_it(api):
    client, runtime = api
    runtime.desired_states.ensure_seat_password(MAC)
    before = runtime.desired_states.seat_password(MAC)

    answer = client.post(PATH)

    assert answer.status_code == 200
    assert answer.json() == {}
    after = runtime.desired_states.seat_password(MAC)
    assert after != before
    key, _, desired = runtime.agent_sessions.pushes[-1]
    assert key == MAC
    assert desired["rdp"] == {"seat_password": after}


def test_a_reset_tells_the_panel_the_device_moved(api):
    client, runtime = api
    events = []
    runtime.events.publish = lambda event_type, key="", data=None: events.append(
        (event_type, key)
    )

    client.post(PATH)

    assert (WEB_EVENT_DEVICE_REPORT, MAC) in events


def test_a_machine_with_no_channel_is_refused_and_keeps_its_password(api):
    client, runtime = api
    runtime.desired_states.ensure_seat_password(MAC)
    before = runtime.desired_states.seat_password(MAC)
    runtime.agent_sessions.online.clear()

    answer = client.post(PATH)

    assert answer.status_code == 409
    assert answer.json()["detail"] == {"code": "agent_offline", "params": {}}
    assert runtime.desired_states.seat_password(MAC) == before
    assert runtime.agent_sessions.pushes == []
