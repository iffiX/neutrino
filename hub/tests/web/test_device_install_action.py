"""The install action's pre-flight.

A device that answers ``uname -s`` with something other than Linux cannot run
the agent, and starting a task that fails minutes later says so in the wrong
place. What these pin is the split: an answered non-Linux probe is a coded 409
before any task exists, and a probe that failed — device off, wrong
credentials — starts the task, whose log is the surface for that failure.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.constants import SSH_UNREACHABLE_STATUS
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router
from neutrino_hub.web.task_stream import TaskStreamRegistry

MAC = "aa:bb:cc:dd:ee:ff"
LOGIN_PASSWORD = "a-password"  # scan: allow


class FakeRuntime:
    instance = None

    def __init__(self):
        self.settings = {}
        self.tasks = TaskStreamRegistry()
        self.client_metrics = {}
        self.client_platform = {}
        self.enrollments = {}

    def network(self):
        return SimpleNamespace(lan_interfaces=[], primary_lan_address="192.168.100.1")


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(devices_router, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(devices_router, "UTILS_DATA_DIR", tmp_path / "no_data")
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime()
    FakeRuntime.instance = runtime
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client


def device_with_ssh(client):
    password_id = (
        SecretVault()
        .add(kind="password", name="a password", secret={"password": LOGIN_PASSWORD})
        .id
    )
    saved = client.put(
        f"/api/devices/{MAC}",
        json={
            "name": "a device",
            "ssh": {
                "host": "192.168.100.2",
                "port": 22,
                "username": "iffi",
                "auth": "password",
                "password_id": password_id,
            },
        },
    )
    assert saved.status_code == 200


def probe_answers(monkeypatch, code: int, output: str):
    async def run_once(self, command, *, timeout_s=20, input_text=None):
        return code, output

    monkeypatch.setattr(devices_router.DeviceSshOperator, "run_once", run_once)


def hub_carries_a_package(tmp_path, monkeypatch):
    packages = tmp_path / "devices" / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    (packages / "neutrino-agent_0.1.0_all.deb").write_bytes(b"deb")
    monkeypatch.setattr(
        devices_router, "_panel_urls", lambda runtime: ["http://192.168.100.1:8080"]
    )


def test_a_non_linux_device_is_refused_before_any_task(api, monkeypatch, tmp_path):
    device_with_ssh(api)
    hub_carries_a_package(tmp_path, monkeypatch)
    probe_answers(monkeypatch, 0, "Darwin")

    refused = api.post(f"/api/devices/{MAC}/action", json={"action": "install_client"})

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "unsupported_remote_install",
        "os": "Darwin",
    }


def test_an_unanswered_probe_starts_the_task(api, monkeypatch, tmp_path):
    device_with_ssh(api)
    hub_carries_a_package(tmp_path, monkeypatch)
    probe_answers(monkeypatch, SSH_UNREACHABLE_STATUS, "Connection refused")

    started = api.post(f"/api/devices/{MAC}/action", json={"action": "install_client"})

    assert started.status_code == 200
    assert started.json()["task_id"]


def test_a_hub_with_no_agent_package_refuses_with_a_code(api, monkeypatch):
    device_with_ssh(api)
    probe_answers(monkeypatch, 0, "Linux")

    refused = api.post(f"/api/devices/{MAC}/action", json={"action": "install_client"})

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "agent_package_missing"}


def test_the_install_ticket_binds_to_the_device(api, monkeypatch, tmp_path):
    """The SSH install walks the same enrollment path a pasted link does."""
    device_with_ssh(api)
    hub_carries_a_package(tmp_path, monkeypatch)
    probe_answers(monkeypatch, 0, "Linux")

    started = api.post(f"/api/devices/{MAC}/action", json={"action": "install_client"})

    assert started.status_code == 200
    tickets = list(FakeRuntime.instance.enrollments.values())
    assert tickets and tickets[-1]["mac_address"] == MAC
