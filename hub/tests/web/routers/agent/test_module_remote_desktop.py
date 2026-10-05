"""The Remote desktop block: the one switch that shares a machine's desktop.

What these pin: the view reads the switch, the module's state as the
machine reported it and the machine's system; a set writes the switch and
pushes, and turning it on gives the device its seat password once; an
offline machine is refused before anything is written; the state sends the
module to every device, ``want`` running while on and stopped while off.
"""

import json

import pytest

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.web.routers.agent import module_remote_desktop
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, OFFLINE, module_box

BASE = "/api/agent/module/remote_desktop"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(monkeypatch, tmp_path, module_remote_desktop.router)
    runtime.device_platform[DEVICE] = LINUX
    with client:
        yield client, runtime, tmp_path


def stored(tmp_path) -> dict:
    path = tmp_path / "devices" / DEVICE / "remote_desktop.json"
    return json.loads(path.read_text())


def test_the_view_reads_the_switch_and_the_machines_word(api):
    client, runtime, _ = api
    runtime.report(DEVICE, "remote_desktop", state="failed")

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert (view["is_enabled"], view["state"], view["platform_os"]) == (
        False,
        "failed",
        "linux",
    )


def test_on_writes_the_switch_pushes_and_gives_a_seat_password_once(api):
    client, runtime, tmp_path = api
    store = DesiredStateStore()

    on = client.post(f"{BASE}/set", json={"device_id": DEVICE, "is_enabled": True})
    password = store.seat_password(DEVICE)
    client.post(f"{BASE}/set", json={"device_id": DEVICE, "is_enabled": True})

    assert on.json()["is_enabled"] is True
    assert stored(tmp_path) == {"is_enabled": True}
    assert password != ""
    assert store.seat_password(DEVICE) == password
    assert len(runtime.agent_sessions.pushes) == 2


def test_off_writes_the_switch_and_keeps_the_password(api):
    client, _runtime, tmp_path = api
    client.post(f"{BASE}/set", json={"device_id": DEVICE, "is_enabled": True})
    password = DesiredStateStore().seat_password(DEVICE)

    off = client.post(f"{BASE}/set", json={"device_id": DEVICE, "is_enabled": False})

    assert off.json()["is_enabled"] is False
    assert stored(tmp_path) == {"is_enabled": False}
    assert DesiredStateStore().seat_password(DEVICE) == password


def test_an_offline_machine_is_refused_before_anything_is_written(api):
    client, _runtime, tmp_path = api

    answer = client.post(f"{BASE}/set", json={"device_id": OFFLINE, "is_enabled": True})

    assert (answer.status_code, answer.json()["detail"]["code"]) == (
        409,
        "agent_offline",
    )
    assert not (tmp_path / "devices" / OFFLINE / "remote_desktop.json").exists()


def test_the_switch_is_the_modules_want_in_the_state(api):
    _, _, _ = api
    store = DesiredStateStore()

    off, _ = store.compose(DEVICE, LINUX)
    store.set_remote_desktop(DEVICE, True)
    on, _ = store.compose(DEVICE, LINUX)

    assert off["modules"]["remote_desktop"] == {
        "want": "stopped",
        "config": {"is_enabled": False},
    }
    assert on["modules"]["remote_desktop"] == {
        "want": "running",
        "config": {"is_enabled": True},
    }
