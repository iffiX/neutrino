"""The box every device-hosted module's API test stands on."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import device_modules
from tests.conftest import FakeDeviceRegistry, FakeModuleRuntime, managed_device

DEVICE = "aa:bb:cc:dd:ee:ff"
OFFLINE = "aa:bb:cc:dd:ee:00"
HOST = "192.168.100.7"


def module_box(monkeypatch, tmp_path, router):
    """One online device and one offline, under a temporary config dir."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    runtime = FakeModuleRuntime(
        devices=[managed_device(DEVICE, "box"), managed_device(OFFLINE, "attic")],
        online=[DEVICE],
    )
    runtime.client_address = {DEVICE: HOST, OFFLINE: "192.168.100.9"}
    FakeDeviceRegistry.runtime = runtime
    monkeypatch.setattr(device_modules, "DeviceRegistry", FakeDeviceRegistry)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), runtime
