"""The ComfyUI block: the forwarder's port, the settings, and what an install gives the module.

What these pin: the view reads the forwarder's port, the module's state,
version and details as the machine reported them, the builds the machine's
entry has a lock of on each platform, the stored build, ``cpu`` while none
is stored and empty on a Mac, ``idle_unload`` ``30m`` while none is stored,
the machine's GPUs and the models folder of its system; the install writes
the token secret and the build of the machine's last report, and a later
install keeps them; ``set`` stores the settings after the agent checked
them and pushes the state, and refuses ``body_invalid`` for a build the
machine's entry has no lock of, a build on a Mac and an ``idle_unload``
outside the five, and ``agent_offline`` for a machine whose agent is away.
"""

import json

import pytest
from fastapi.exceptions import RequestValidationError

from neutrino_hub.web import app as web_app
from neutrino_hub.web.routers.agent import module as device_modules
from neutrino_hub.web.routers.agent import module_comfyui
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, OFFLINE, module_box

BASE = "/api/agent/module/comfyui"
MODULE_PATH = "/api/agent/module"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
LINUX_ARM = {"os": "linux", "family": "debian", "arch": "arm64", "version": "2.36"}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}
MAC = {"os": "darwin", "family": "", "arch": "arm64", "version": "15.1"}
NVIDIA = {
    "vendor": "nvidia",
    "name": "NVIDIA GeForce RTX 4090",
    "memory_total_mb": 24564,
}


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(
        monkeypatch, tmp_path, [device_modules.router, module_comfyui.router]
    )
    client.app.add_exception_handler(RequestValidationError, web_app._body_invalid)
    runtime.device_platform[DEVICE] = LINUX
    with client:
        yield client, runtime, tmp_path


def stored(tmp_path, device=DEVICE) -> dict:
    path = tmp_path / "devices" / device / "comfyui.json"
    return json.loads(path.read_text()) if path.exists() else {}


def view(client, device=DEVICE) -> dict:
    return client.get(BASE, params={"device_id": device}).json()


def test_the_view_reads_the_port_the_settings_and_the_machine_as_reported(api):
    client, runtime, _ = api
    runtime.report(
        DEVICE, "comfyui", state="running", version="0.46.0", is_running=True, port=8188
    )
    runtime.device_metrics[DEVICE] = {"gpus": [NVIDIA]}

    held = view(client)

    assert (held["port"], held["state"], held["version"]) == (8188, "running", "0.46.0")
    assert held["details"] == {"version": "0.46.0", "is_running": True, "port": 8188}
    assert (held["torch_build"], held["idle_unload"]) == ("cpu", "30m")
    assert held["torch_builds"] == ["nvidia", "amd", "intel", "cpu"]
    assert held["resources"]["gpus"][0]["name"] == "NVIDIA GeForce RTX 4090"
    assert held["models_dir"] == "/var/lib/neutrino/agent/comfyui_data/data/models/"


@pytest.mark.parametrize(
    "platform, builds, build",
    [
        (LINUX_ARM, ["nvidia", "cpu"], "cpu"),
        (WINDOWS, ["nvidia", "intel", "cpu"], "cpu"),
        (MAC, [], ""),
    ],
)
def test_the_view_offers_the_builds_of_each_platform(api, platform, builds, build):
    client, runtime, _ = api
    runtime.device_platform[DEVICE] = platform

    held = view(client)

    assert (held["torch_builds"], held["torch_build"]) == (builds, build)


def test_the_install_writes_the_secret_and_the_build_of_the_last_report(api):
    client, runtime, tmp_path = api
    runtime.device_metrics[DEVICE] = {"gpus": [NVIDIA]}

    answer = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "comfyui"}
    )

    assert answer.status_code == 200
    held = stored(tmp_path)
    assert set(held) == {"secret_sealed", "torch_build"}
    assert held["torch_build"] == "nvidia"
    runtime.device_metrics[DEVICE] = {"gpus": []}
    client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "comfyui"}
    )
    assert stored(tmp_path) == held
    assert view(client)["torch_build"] == "nvidia"


def test_set_stores_the_settings_after_the_agent_checked_them_and_pushes(api):
    client, runtime, tmp_path = api
    client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "comfyui"}
    )
    secret = stored(tmp_path)["secret_sealed"]
    pushes = len(runtime.agent_sessions.pushes)

    answer = client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "torch_build": "amd", "idle_unload": "-1"},
    )

    assert answer.status_code == 200
    assert (answer.json()["torch_build"], answer.json()["idle_unload"]) == ("amd", "-1")
    assert stored(tmp_path) == {
        "secret_sealed": secret,
        "torch_build": "amd",
        "idle_unload": "-1",
    }
    checked = runtime.agent_sessions.validations[-1][2]
    assert (checked["torch_build"], checked["idle_unload"]) == ("amd", "-1")
    assert len(runtime.agent_sessions.pushes) > pushes


def test_set_on_a_mac_stores_the_idle_unload_time_alone(api):
    client, runtime, tmp_path = api
    runtime.device_platform[DEVICE] = MAC

    answer = client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "torch_build": "", "idle_unload": "5m"},
    )

    assert answer.status_code == 200
    assert stored(tmp_path) == {"idle_unload": "5m"}


@pytest.mark.parametrize(
    "platform, body, fields",
    [
        (LINUX_ARM, {"torch_build": "amd", "idle_unload": "30m"}, "torch_build"),
        (WINDOWS, {"torch_build": "amd", "idle_unload": "30m"}, "torch_build"),
        (LINUX, {"torch_build": "", "idle_unload": "30m"}, "torch_build"),
        (MAC, {"torch_build": "cpu", "idle_unload": "30m"}, "torch_build"),
        (LINUX, {"torch_build": "rocm", "idle_unload": "30m"}, "torch_build"),
        (LINUX, {"torch_build": "cpu", "idle_unload": "2h"}, "idle_unload"),
        (LINUX, {"torch_build": "cpu", "idle_unload": 30}, "idle_unload"),
        (LINUX, {"torch_build": "cpu"}, "idle_unload"),
    ],
)
def test_set_refuses_a_build_with_no_lock_and_a_time_outside_the_five(
    api, platform, body, fields
):
    client, runtime, tmp_path = api
    runtime.device_platform[DEVICE] = platform

    answer = client.post(f"{BASE}/set", json={"device_id": DEVICE, **body})

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "body_invalid"
    assert fields in answer.json()["detail"]["params"]["fields"]
    assert stored(tmp_path) == {}
    assert not runtime.agent_sessions.validations


def test_set_refuses_a_machine_whose_agent_is_away(api):
    client, runtime, tmp_path = api
    runtime.device_platform[OFFLINE] = LINUX

    answer = client.post(
        f"{BASE}/set",
        json={"device_id": OFFLINE, "torch_build": "cpu", "idle_unload": "30m"},
    )

    assert answer.json()["detail"]["code"] == "agent_offline"
    assert stored(tmp_path, OFFLINE) == {}
