"""What the Modules block on a device is told, and what it can act on.

The bug these came from: a device showed AnyDesk and ToDesk running in the
remote-desktop block and "not installed, waiting for the agent" in the module
list above it. Two halves of one drawer disagreeing, because one asks the
machine over SSH and the other reads a flag that records only that an install
was once asked for. `is_installed` is never cleared — not when the install
fails, not when the agent is stopped, not when somebody removes it by hand —
so it cannot be what the list is drawn from.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router

MAC = "aa:bb:cc:dd:ee:ff"


class FakeRegistry:
    device: ManagedDevice

    def get(self, mac_address: str) -> ManagedDevice:
        return FakeRegistry.device

    def annotate(self, mac_address: str, payload: dict) -> ManagedDevice:
        if "name" in payload:
            FakeRegistry.device.name = payload["name"]
        return FakeRegistry.device


class FakeRuntime:
    def __init__(self):
        self.client_features = {}
        self.client_platform = {}
        self.client_metrics = {}
        self.pending = {}

    def forget_client_state(self, mac_address: str) -> None:
        key = mac_address.lower()
        for held in (
            self.client_features,
            self.client_platform,
            self.client_metrics,
            self.pending,
        ):
            held.pop(key, None)


def beating(seconds_ago: float) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return stamp.isoformat()


@pytest.fixture
def api(monkeypatch):
    FakeRegistry.device = ManagedDevice(
        mac_address=MAC,
        name="testbox",
        client=DeviceClientInfo(is_installed=True, token="t"),
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", FakeRegistry)
    monkeypatch.setattr(
        devices_router,
        "load_catalog",
        lambda: {"anydesk": {"title": "AnyDesk", "platforms": {"debian": {}}}},
    )
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_an_agent_that_has_never_beaten_is_not_online(api):
    client, _ = api

    answer = client.get(f"/api/devices/{MAC}/features").json()

    assert answer["is_agent_installed"]
    assert not answer["is_agent_online"]


def test_an_agent_that_beat_just_now_is_online(api):
    client, _ = api
    FakeRegistry.device.client.last_seen = beating(2)

    answer = client.get(f"/api/devices/{MAC}/features").json()

    assert answer["is_agent_online"]


def test_an_agent_that_stopped_beating_is_not_online(api):
    """Which is the reported bug: the install flag stays true for ever, so
    this device drew every module as absent while its remote desktop was
    plainly running."""
    client, _ = api
    FakeRegistry.device.client.last_seen = beating(3600)

    answer = client.get(f"/api/devices/{MAC}/features").json()

    assert answer["is_agent_installed"]
    assert not answer["is_agent_online"]


def test_what_the_agent_reported_is_found_whatever_case_the_MAC_is_asked_in(api):
    """Everything else keys by the lowercased address; looking the runtime up
    by the raw path segment finds nothing, and every module then reads as
    waiting for an agent that is in fact answering."""
    client, runtime = api
    FakeRegistry.device.client.last_seen = beating(2)
    runtime.client_features[MAC] = {
        "anydesk": {"state": "installed", "is_active": True}
    }

    answer = client.get(f"/api/devices/{MAC.upper()}/features").json()

    assert answer["features"][0]["state"] == "installed"
    assert answer["features"][0]["is_active"]


def test_forgetting_a_device_drops_what_was_queued_for_it(api, monkeypatch):
    """A command queued for a device that is forgotten would be delivered to
    whatever machine turns up on that MAC next: enrol a rebuilt box and its
    first heartbeat drains a shutdown nobody asked it for."""
    client, runtime = api
    monkeypatch.setattr(FakeRegistry, "forget", lambda self, mac: None, raising=False)
    runtime.pending[MAC] = ["shutdown"]
    runtime.client_features[MAC] = {"anydesk": {"state": "installed"}}

    assert client.delete(f"/api/devices/{MAC}").status_code == 200

    assert runtime.pending == {}
    assert runtime.client_features == {}


@pytest.mark.parametrize(
    "address", ["hello", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "", "12345"]
)
def test_a_device_has_to_be_addressed_by_a_MAC(api, address):
    """Every part of a device is keyed by its address — the registry, the host
    key store, the command queue, the magic packet — so a record stored under
    something else is one none of them can act on."""
    client, _ = api

    response = client.put(f"/api/devices/{address}", json={"name": "nonsense"})

    assert response.status_code in (400, 404, 405)


def test_an_unknown_remote_desktop_product_is_refused_at_once(api):
    """`set_password_stream` is an async generator, so calling it runs none of
    its body: the refusal it documents used to surface minutes later as a
    failed task rather than as this answer."""
    client, _ = api
    FakeRegistry.device.ssh = {"host": "10.0.0.5", "username": "me"}

    response = client.post(
        f"/api/devices/{MAC}/remote_desktop/anydsk/password",
        json={"password": "hunter2hunter2"},  # scan: allow
    )

    assert response.status_code == 400


def test_renaming_a_device_keeps_its_monitor_alive(api):
    """The page redraws the tile from this answer. Built with no metrics, it
    reads as a machine that went offline the moment somebody renamed it."""
    client, runtime = api
    FakeRegistry.device.client.last_seen = beating(2)
    runtime.client_metrics[MAC] = {"cpu_percent": 12.5, "memory_percent": 40.0}

    answer = client.put(f"/api/devices/{MAC}", json={"name": "renamed"}).json()

    assert answer["name"] == "renamed"
    assert answer["client"]["cpu_percent"] == 12.5
