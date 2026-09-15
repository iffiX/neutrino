"""The box the Devices page and a device's Modules page stand on.

One stored, managed device under a registry that can adopt a scan row, a
runtime holding the module order controller, and a module manifest of one
hub-installed module.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.agent_module_cache import AgentModuleArtifact
from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import (
    DeviceClientInfo,
    ManagedDevice,
    normalized_mac,
)
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.events import PanelEventBus
from tests.conftest import FakeChannelSessions, holding_dispatch

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


class StubModuleCache:
    """A cache that answers at once and never reaches a vendor."""

    def artifact(self, *, name, manifest, platform):
        return AgentModuleArtifact(
            key=f"{name}-key", path=Path("/nonexistent"), digest="d", package_kind="deb"
        )


class BoxRuntime:
    def __init__(self):
        self.events = PanelEventBus()
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
        self.agent_modules = StubModuleCache()
        self.device_install_locks = DeviceInstallLocks()
        # A dispatch that holds each order open briefly and never answers:
        # the row shows the step, and no worker sits on a lock for long.
        self.agent_module_orders = AgentModuleController(
            cache=self.agent_modules,
            locks=self.device_install_locks,
            dispatch=holding_dispatch,
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
        self.agent_module_orders.forget(device_id)


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
