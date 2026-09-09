"""What one device carries into the panel's two sections.

The Devices page splits on ``client.is_managed`` and draws a managed tile
with what its agent says the machine is. The platform, the agent version
and the last-seen stamp are held in memory and never stored, so what these
pin is that the list carries them when an agent has been seen, carries
nulls when none has, and does not lose them on the single-device path a
save comes back through.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router
from tests.conftest import FakeAgentSessions

MAC = "aa:bb:cc:dd:ee:ff"


class FakeRegistry:
    """The one device the list is built from."""

    device: ManagedDevice

    def merged(self, discovered: list) -> list:
        return [FakeRegistry.device]

    def get(self, mac_address: str) -> ManagedDevice:
        return FakeRegistry.device

    def annotate(self, mac_address: str, payload: dict) -> ManagedDevice:
        if "name" in payload:
            FakeRegistry.device.name = payload["name"]
        return FakeRegistry.device


class FakeScanner:
    """A sweep that finds nothing, so the stored device is all there is."""

    def __init__(self, *, lan_interfaces):
        self.lan_interfaces = lan_interfaces

    def scan(self, *, is_active: bool) -> list:
        return []


class FakeRuntime:
    def __init__(self):
        self.client_metrics = {}
        self.client_address = {}
        self.client_platform = {}
        self.client_hostname = {}
        self.client_last_error = {}
        self.agent_sessions = FakeAgentSessions()

    def network(self):
        return _EmptyNetwork()


class _EmptyNetwork:
    lan_device_names: list = []
    lan_interfaces: list = []
    device_facing_device_names: list = []
    device_facing_interfaces: list = []


@pytest.fixture
def api(monkeypatch):
    FakeRegistry.device = ManagedDevice(
        mac_address=MAC,
        name="xenode",
        ipv4_address="192.168.100.2",
        client=DeviceClientInfo(token_sha256="t" * 64),
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", FakeRegistry)
    monkeypatch.setattr(devices_router, "LanScanner", FakeScanner)
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_a_managed_device_carries_the_platform_its_agent_reported(api):
    client, runtime = api
    runtime.client_platform[MAC] = {
        "os": "linux",
        "family": "debian",
        "arch": "amd64",
    }

    device = client.get("/api/devices").json()["devices"][0]

    assert device["client"]["platform_os"] == "linux"
    assert device["client"]["platform_arch"] == "amd64"


def test_a_platform_nobody_has_reported_reads_as_unknown(api):
    """The panel holds it in memory only, so it is absent until the agent beats
    again after a restart. Null, never a guess."""
    client, _ = api

    device = client.get("/api/devices").json()["devices"][0]

    assert device["client"]["platform_os"] is None
    assert device["client"]["platform_arch"] is None


def test_a_device_with_no_agent_has_no_client_block(api):
    client, runtime = api
    FakeRegistry.device.client = DeviceClientInfo()
    runtime.client_platform[MAC] = {"os": "windows", "arch": "amd64"}

    device = client.get("/api/devices").json()["devices"][0]

    assert device["client"] is None


def test_the_platform_is_found_whatever_case_the_MAC_is_stored_in(api):
    client, runtime = api
    FakeRegistry.device.mac_address = MAC.upper()
    runtime.client_platform[MAC] = {"os": "linux", "arch": "arm64"}

    device = client.get("/api/devices").json()["devices"][0]

    assert device["client"]["platform_os"] == "linux"


def test_renaming_a_device_keeps_its_platform(api):
    """The page redraws the tile from this answer. Built without the platform,
    a managed tile loses its chip until the next poll."""
    client, runtime = api
    runtime.client_platform[MAC] = {"os": "linux", "arch": "amd64"}

    answer = client.put(f"/api/devices/{MAC}", json={"name": "renamed"}).json()

    assert answer["name"] == "renamed"
    assert answer["client"]["platform_os"] == "linux"


def test_the_version_and_the_stamp_come_from_the_session_registry(api):
    client, runtime = api
    runtime.agent_sessions.versions[MAC] = "0.3.0"
    runtime.agent_sessions.ended_at[MAC] = "2026-01-01T00:00:00+00:00"

    (device,) = client.get("/api/devices").json()["devices"]

    assert device["client"]["version"] == "0.3.0"
    assert device["client"]["last_seen"] == "2026-01-01T00:00:00+00:00"
    assert device["client"]["is_online"] is False


def test_a_device_not_seen_since_the_panel_started_has_no_version_or_stamp(api):
    """Presence lives in memory alone. A managed device the hub has not
    heard from is still managed, with nothing to say about when it was
    last here."""
    client, _ = api

    (device,) = client.get("/api/devices").json()["devices"]

    assert device["client"]["is_managed"] is True
    assert device["client"]["version"] is None
    assert device["client"]["last_seen"] is None
    assert device["client"]["is_version_mismatched"] is False


def test_a_device_is_at_the_address_its_channel_comes_from(api):
    """SSH is for installing and power, never for locating: an agent joined
    by a link has no stored host and is no less reachable."""
    client, runtime = api
    runtime.client_address[MAC] = "192.168.100.7"

    (device,) = client.get("/api/devices").json()["devices"]

    assert device["ipv4_address"] == "192.168.100.7"
