"""The Hermes WebUI block: the forwarder's port, and what its presses give the module.

What these pin: the view reads the forwarder's port and the module's state,
version and details as the machine reported them; the module's install
gives it its file, the token secret and the password, and its gateway key,
and its uninstall voids the key and keeps the file.
"""

import json

import pytest

from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.web.routers.agent import module as device_modules
from neutrino_hub.web.routers.agent import module_hermes_webui
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, OFFLINE, module_box

BASE = "/api/agent/module/hermes_webui"
MODULE_PATH = "/api/agent/module"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    client, runtime = module_box(
        monkeypatch, tmp_path, [device_modules.router, module_hermes_webui.router]
    )
    runtime.device_platform[DEVICE] = LINUX
    with client:
        yield client, runtime, tmp_path


def stored(tmp_path, device=DEVICE) -> dict:
    path = tmp_path / "devices" / device / "hermes_webui.json"
    return json.loads(path.read_text()) if path.exists() else {}


def test_the_view_reads_the_port_and_the_module_as_reported(api):
    client, runtime, _ = api
    runtime.report(
        DEVICE, "hermes_webui", state="installing", version="0.52.492", port=8787
    )

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert (view["port"], view["state"], view["version"]) == (
        8787,
        "installing",
        "0.52.492",
    )
    assert view["details"] == {"version": "0.52.492", "port": 8787}


def test_the_install_gives_the_module_its_file_and_its_gateway_key(api):
    client, runtime, tmp_path = api
    runtime.agent_sessions.online.add(DEVICE)

    answer = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "hermes_webui"}
    )

    assert answer.status_code == 200
    held = stored(tmp_path)
    assert "port" not in held
    assert {"secret_sealed", "password_sealed", "gateway_key"} <= set(held)
    assert held["gateway_key"]["name"] == "device/box/hermes_webui"


def test_the_uninstall_voids_the_gateway_key_and_keeps_the_file(api):
    client, runtime, tmp_path = api
    runtime.agent_sessions.online.add(DEVICE)
    client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "hermes_webui"}
    )
    secrets = {
        key: stored(tmp_path)[key] for key in ("secret_sealed", "password_sealed")
    }

    client.post(
        f"{MODULE_PATH}/uninstall",
        json={"device_id": DEVICE, "module": "hermes_webui"},
    )

    assert "gateway_key" not in stored(tmp_path)
    assert {
        key: stored(tmp_path)[key] for key in ("secret_sealed", "password_sealed")
    } == secrets
