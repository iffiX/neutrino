"""The Ayakaleaf block: the forwarder's port, the AI model, and what its presses give the module.

What these pin: the view reads the forwarder's port and the module's state,
version and details as the machine reported them, the stored model and the
names the gateway serves; ``set`` stores the model, pushes the state and
keeps the secrets, and refuses a machine with no session; the module's
install gives it its file with the four secrets and its gateway key, and
its uninstall voids the key and keeps the file.
"""

import json

import pytest

from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.web.routers.agent import module as device_modules
from neutrino_hub.web.routers.agent import module_ayakaleaf
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, OFFLINE, module_box

BASE = "/api/agent/module/ayakaleaf"
MODULE_PATH = "/api/agent/module"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
SECRETS = (
    "secret_sealed",
    "password_sealed",
    "session_secret_sealed",
    "invite_secret_sealed",
)


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    monkeypatch.setattr(
        module_ayakaleaf, "gateway_models", lambda served: ["model-a", "model-b"]
    )
    client, runtime = module_box(
        monkeypatch, tmp_path, [device_modules.router, module_ayakaleaf.router]
    )
    runtime.device_platform[DEVICE] = LINUX
    with client:
        yield client, runtime, tmp_path


def stored(tmp_path, device=DEVICE) -> dict:
    path = tmp_path / "devices" / device / "ayakaleaf.json"
    return json.loads(path.read_text()) if path.exists() else {}


def test_the_view_reads_the_port_the_model_and_the_module_as_reported(api):
    client, runtime, _ = api
    runtime.report(
        DEVICE, "ayakaleaf", state="installing", version="6.3.2", port=8900, guests=[]
    )

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert (view["port"], view["state"], view["version"]) == (
        8900,
        "installing",
        "6.3.2",
    )
    assert (view["model"], view["models"], view["is_gateway_serving"]) == (
        "",
        ["model-a", "model-b"],
        True,
    )
    assert view["details"] == {"version": "6.3.2", "port": 8900, "guests": []}


def test_set_stores_the_model_pushes_the_state_and_keeps_the_secrets(api):
    client, runtime, tmp_path = api
    client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "ayakaleaf"}
    )
    before = stored(tmp_path)
    pushes = len(runtime.agent_sessions.pushes)

    view = client.post(f"{BASE}/set", json={"device_id": DEVICE, "model": " model-b "})

    assert view.status_code == 200
    assert view.json()["model"] == "model-b"
    assert stored(tmp_path) == {**before, "model": "model-b"}
    assert len(runtime.agent_sessions.pushes) == pushes + 1

    client.post(f"{BASE}/set", json={"device_id": DEVICE, "model": ""})

    assert stored(tmp_path)["model"] == ""


def test_set_refuses_a_machine_with_no_session(api):
    client, _, tmp_path = api

    answer = client.post(f"{BASE}/set", json={"device_id": OFFLINE, "model": "m"})

    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "agent_offline"
    assert stored(tmp_path, OFFLINE) == {}


def test_the_install_gives_the_module_its_four_secrets_and_its_gateway_key(api):
    client, _, tmp_path = api

    answer = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "ayakaleaf"}
    )

    assert answer.status_code == 200
    held = stored(tmp_path)
    assert {*SECRETS, "gateway_key"} <= set(held)
    assert held["gateway_key"]["name"] == "device/box/ayakaleaf"


def test_the_uninstall_voids_the_gateway_key_and_keeps_the_file(api):
    client, _, tmp_path = api
    client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "ayakaleaf"}
    )
    secrets = {key: stored(tmp_path)[key] for key in SECRETS}

    client.post(
        f"{MODULE_PATH}/uninstall", json={"device_id": DEVICE, "module": "ayakaleaf"}
    )

    assert "gateway_key" not in stored(tmp_path)
    assert {key: stored(tmp_path)[key] for key in SECRETS} == secrets


def test_the_installed_version_is_the_one_the_details_name(api):
    client, runtime, _ = api
    runtime.report(DEVICE, "ayakaleaf", state="running", version="6.3.1", port=8900)

    view = client.get(
        f"{MODULE_PATH}/version", params={"device_id": DEVICE, "module": "ayakaleaf"}
    ).json()

    assert view["installed"] == "6.3.1"
    assert view["is_data_forward_only"] is True
    assert view["is_locked"] is False
