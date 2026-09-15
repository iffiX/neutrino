"""The box the Devices page and a device's Modules page stand on.

One stored, managed device under a registry that can adopt a scan row, a
runtime holding the desired states and the tasks, and a module manifest of
one hub-installed module.
"""

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.registry import (
    DeviceClientInfo,
    ManagedDevice,
    normalized_mac,
)
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.task_stream import TaskStreamRegistry
from tests.conftest import FakeChannelSessions, StubPublishedServices

DEVICE = "device-one"
FINGERPRINT = "ab" * 32
MANIFESTS = {
    "fakedesk": {
        "title": "FakeDesk",
        "installer": "hub",
        "platforms": {"debian": {}},
    }
}


class BoxRegistry:
    """The one stored device, and any scan row adopted under a fresh id."""

    device: ManagedDevice
    adopted: ManagedDevice

    def get(self, device_id: str):
        if device_id == BoxRegistry.device.id:
            return BoxRegistry.device
        if device_id.startswith("scan:") and normalized_mac(device_id[5:]):
            return ManagedDevice(id=device_id, link_mac=device_id[5:])
        return None

    def adopt(self, device_id: str) -> ManagedDevice:
        if device_id.startswith("scan:"):
            BoxRegistry.adopted = ManagedDevice(id="adopted-id", link_mac=device_id[5:])
            return BoxRegistry.adopted
        return BoxRegistry.device

    def annotate(self, device_id: str, payload: dict) -> ManagedDevice:
        device = self.adopt(device_id)
        if "name" in payload:
            device.name = payload["name"]
        return device


class BoxRuntime:
    def __init__(self):
        self.events = PanelEventBus()
        self.tasks = TaskStreamRegistry()
        self.device_modules = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_metrics = {}
        self.device_address = {}
        self.device_last_error = {}
        self.pending = {}
        self.enrollments = {}
        self.device_shares = DeviceShareRegistry()
        self.agent_sessions = FakeChannelSessions()
        self.desired_states = DesiredStateStore()
        self.published_services = StubPublishedServices()

    def push_desired_state(self, key: str) -> None:
        self.agent_sessions.push_state_from_thread(
            key, {"hash": f"hash-{key}", "modules": {}}
        )

    def forget_device(self, device_id: str) -> None:
        for held in (
            self.device_modules,
            self.device_platform,
            self.device_metrics,
            self.device_address,
            self.device_last_error,
            self.pending,
        ):
            held.pop(device_id, None)


def beating(seconds_ago: float) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return stamp.isoformat()


def stored_device() -> ManagedDevice:
    """The managed device every box starts with."""
    BoxRegistry.device = ManagedDevice(
        id=DEVICE,
        name="testbox",
        client=DeviceClientInfo(token_sha256="t" * 64),
    )
    return BoxRegistry.device


def device_box(monkeypatch, router_module):
    """One router over the box, its registry and manifests patched in.

    Args:
        monkeypatch: The test's monkeypatch.
        router_module: The router module under test; its ``DeviceRegistry``
            and ``load_module_manifests`` are replaced.

    Returns:
        ``(client, runtime)``.
    """
    stored_device()
    monkeypatch.setattr(router_module, "DeviceRegistry", BoxRegistry)
    monkeypatch.setattr(router_module, "load_module_manifests", lambda: MANIFESTS)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = BoxRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), runtime
