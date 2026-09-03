"""What one device carries into the panel's two sections.

The Devices page splits on ``client.is_managed`` and draws a managed tile
with what its agent says the machine is. That platform is held in memory from
heartbeats and never stored, so what these pin is that the list carries it
when an agent has reported one, carries nulls when none has, and does not
lose it on the single-device path a save comes back through.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router

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
        self.client_platform = {}

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
        client=DeviceClientInfo(
            token_sha256="t" * 64,
            last_seen="2026-01-01T00:00:00+00:00",
            version="0.3.0",
        ),
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
