"""The install action: its credentials, its pre-flight, and the reinstall.

An install carries how to reach the machine: exactly one of a stored key,
a stored login, or a password typed now, saved as a login only when asked;
the sudo password is fed to the install and written nowhere. What these
pin is that shape, that the device's ssh block records the references and
never a secret, the pre-flight split (a non-Linux answer is a coded 409
before any task, a failed probe starts the task whose log is the surface),
and that a reinstall is a command on a live agent and a 409 without one.
"""

import json
from types import SimpleNamespace

import asyncssh
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.agent_package import AgentPackageCache
from neutrino_hub.modules.devices.constants import SSH_UNREACHABLE_STATUS
from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router
from neutrino_hub.web.task_stream import TaskStreamRegistry
from tests.conftest import FakeAgentSessions, unlock_vault

MAC = "aa:bb:cc:dd:ee:ff"
LOGIN_PASSWORD = "a-password"  # scan: allow
TYPED_PASSWORD = "typed-now"  # scan: allow
SUDO_PASSWORD = "a-sudo-password"  # scan: allow


class FakeRuntime:
    instance = None

    def __init__(self, packages_dir):
        self.events = PanelEventBus()
        self.settings = {}
        self.tasks = TaskStreamRegistry()
        self.client_metrics = {}
        self.client_address = {}
        self.client_platform = {}
        self.enrollments = {}
        self.agent_sessions = FakeAgentSessions()
        self.agent_packages = AgentPackageCache(
            root=packages_dir / "agent_cache",
            manifest_path=packages_dir / "agent_packages.json",
            pinned_dir=packages_dir / "devices" / "packages",
        )

    def network(self):
        return SimpleNamespace(lan_interfaces=[], primary_lan_address="192.168.100.1")


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime(tmp_path)
    FakeRuntime.instance = runtime
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, tmp_path


def stored_login() -> str:
    return (
        SecretVault()
        .add(kind="login", name="a password", secret={"password": LOGIN_PASSWORD})
        .id
    )


def stored_key() -> str:
    key = asyncssh.generate_private_key("ssh-ed25519")
    return (
        KeyRegistry()
        .add(name="a key", private_key=key.export_private_key().decode())
        .id
    )


def probe_answers(monkeypatch, code: int, output: str):
    async def run_once(self, command, *, timeout_s=20, input_text=None):
        return code, output

    monkeypatch.setattr(devices_router.DeviceSshOperator, "run_once", run_once)


def capture_install(monkeypatch) -> dict:
    """Record what the install is started with, running nothing."""
    captured: dict = {}

    def install_client(self, *, packages, enrollment_link, sudo_password=None):
        captured["credentials"] = self._credentials
        captured["sudo_password"] = sudo_password

        async def lines():
            yield "[installed]\n"

        return lines()

    monkeypatch.setattr(
        devices_router.DeviceSshOperator, "install_client", install_client
    )
    return captured


def hub_carries_a_package(tmp_path, monkeypatch):
    packages = tmp_path / "devices" / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    (packages / "neutrino-agent_0.1.0_amd64.deb").write_bytes(b"deb")
    monkeypatch.setattr(
        devices_router, "_agent_urls", lambda runtime: ["https://192.168.100.1:8443"]
    )
    monkeypatch.setattr(devices_router, "certificate_fingerprint", lambda: "ab" * 32)


def install(client, **fields):
    body = {
        "action": "install_client",
        "host": "192.168.100.2",
        "port": 22,
        "username": "iffi",
        **fields,
    }
    return client.post(f"/api/devices/{MAC}/action", json=body)


def stored_ssh(tmp_path) -> dict:
    stored = json.loads((tmp_path / "devices" / "devices.json").read_text())
    return stored["devices"][MAC]["ssh"]


def ready(monkeypatch, tmp_path):
    hub_carries_a_package(tmp_path, monkeypatch)
    probe_answers(monkeypatch, 0, "Linux")
    return capture_install(monkeypatch)


# --- the credential sources ---


def test_a_stored_key_is_the_credential_and_the_block_records_it(api, monkeypatch):
    client, tmp_path = api
    captured = ready(monkeypatch, tmp_path)
    key_id = stored_key()

    started = install(client, key_id=key_id, sudo_password=SUDO_PASSWORD)

    assert started.status_code == 200
    assert started.json()["task_id"]
    assert stored_ssh(tmp_path) == {
        "host": "192.168.100.2",
        "port": 22,
        "username": "iffi",
        "auth": "key",
        "key_id": key_id,
        "login_id": None,
        "sudo_login_id": None,
    }
    assert captured["credentials"].private_key
    assert captured["credentials"].password is None
    assert captured["sudo_password"] == SUDO_PASSWORD


def test_the_sudo_login_is_opened_from_the_vault_and_referenced(api, monkeypatch):
    client, tmp_path = api
    captured = ready(monkeypatch, tmp_path)
    key_id = stored_key()
    sudo_id = stored_login()

    started = install(client, key_id=key_id, sudo_login_id=sudo_id)

    assert started.status_code == 200
    assert captured["sudo_password"] == LOGIN_PASSWORD
    assert stored_ssh(tmp_path)["sudo_login_id"] == sudo_id
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.name != "vault.json":
            assert LOGIN_PASSWORD.encode() not in path.read_bytes()


def test_a_stale_sudo_login_is_refused(api, monkeypatch):
    client, tmp_path = api
    ready(monkeypatch, tmp_path)

    refused = install(client, key_id=stored_key(), sudo_login_id="deadbeef")

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "unknown_credential",
        "field": "sudo_login_id",
    }


def test_a_stored_login_is_opened_from_the_vault(api, monkeypatch):
    client, tmp_path = api
    captured = ready(monkeypatch, tmp_path)
    login_id = stored_login()

    started = install(client, login_id=login_id)

    assert started.status_code == 200
    assert stored_ssh(tmp_path)["auth"] == "password"
    assert stored_ssh(tmp_path)["login_id"] == login_id
    assert captured["credentials"].password == LOGIN_PASSWORD
    assert captured["sudo_password"] is None


def test_a_typed_password_is_used_and_stored_nowhere_unless_asked(api, monkeypatch):
    client, tmp_path = api
    captured = ready(monkeypatch, tmp_path)

    started = install(client, password=TYPED_PASSWORD, sudo_password=SUDO_PASSWORD)

    assert started.status_code == 200
    assert captured["credentials"].password == TYPED_PASSWORD
    block = stored_ssh(tmp_path)
    assert block["login_id"] is None and block["auth"] == "password"
    assert SecretVault().list_records(kind="login") == []
    for path in tmp_path.rglob("*"):
        if path.is_file():
            text = path.read_bytes()
            assert TYPED_PASSWORD.encode() not in text
            assert SUDO_PASSWORD.encode() not in text


def test_a_typed_password_saved_becomes_a_login_the_block_names(api, monkeypatch):
    client, tmp_path = api
    captured = ready(monkeypatch, tmp_path)

    started = install(
        client,
        password=TYPED_PASSWORD,
        is_password_saved=True,
        sudo_password=SUDO_PASSWORD,
    )

    assert started.status_code == 200
    (record,) = SecretVault().list_records(kind="login")
    assert record.name == "iffi@192.168.100.2"
    assert SecretVault().open(record.id) == {
        "username": "iffi",
        "password": TYPED_PASSWORD,
    }
    assert stored_ssh(tmp_path)["login_id"] == record.id
    assert captured["credentials"].password == TYPED_PASSWORD
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SUDO_PASSWORD.encode() not in path.read_bytes()


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"key_id": "k", "login_id": "l"},
        {"key_id": "k", "password": "p"},
        {"password": "p", "host": ""},
        {"password": "p", "username": ""},
    ],
)
def test_anything_but_one_credential_source_is_refused(api, monkeypatch, fields):
    client, tmp_path = api
    ready(monkeypatch, tmp_path)

    refused = install(client, **fields)

    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "install_credentials_invalid"
    assert not (tmp_path / "devices" / "devices.json").exists()


def test_a_stale_credential_id_is_refused_by_field(api, monkeypatch):
    client, tmp_path = api
    ready(monkeypatch, tmp_path)

    refused = install(client, login_id="absent")

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "unknown_credential",
        "field": "login_id",
    }


# --- the pre-flight ---


def test_a_non_linux_device_is_refused_before_any_task(api, monkeypatch):
    client, tmp_path = api
    hub_carries_a_package(tmp_path, monkeypatch)
    probe_answers(monkeypatch, 0, "Darwin")

    refused = install(client, login_id=stored_login())

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "unsupported_remote_install",
        "os": "Darwin",
    }


def test_an_unanswered_probe_starts_the_task(api, monkeypatch):
    client, tmp_path = api
    hub_carries_a_package(tmp_path, monkeypatch)
    probe_answers(monkeypatch, SSH_UNREACHABLE_STATUS, "Connection refused")
    capture_install(monkeypatch)

    started = install(client, login_id=stored_login())

    assert started.status_code == 200
    assert started.json()["task_id"]


def test_a_hub_with_no_agent_package_refuses_with_a_code(api, monkeypatch):
    client, _ = api
    probe_answers(monkeypatch, 0, "Linux")

    refused = install(client, login_id=stored_login())

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "agent_package_missing"}


def test_the_install_ticket_binds_to_the_device(api, monkeypatch):
    """The SSH install walks the same enrollment path a pasted link does."""
    client, tmp_path = api
    ready(monkeypatch, tmp_path)

    started = install(client, login_id=stored_login())

    assert started.status_code == 200
    tickets = list(FakeRuntime.instance.enrollments.values())
    assert tickets and tickets[-1]["mac_address"] == MAC


# --- the reinstall ---


def test_a_reinstall_with_no_channel_is_409(api):
    client, _ = api

    refused = client.post(
        f"/api/devices/{MAC}/action", json={"action": "reinstall_agent"}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "agent_offline"}


def test_a_reinstall_on_a_live_agent_runs_the_command_as_a_task(api):
    client, _ = api
    sessions = FakeRuntime.instance.agent_sessions
    sessions.online.add(MAC)
    sessions.scripts["command"] = lambda args: (
        [],
        {"exit_code": 0, "code": "", "params": {}, "output": "reinstall launched\n"},
    )

    started = client.post(
        f"/api/devices/{MAC}/action", json={"action": "reinstall_agent"}
    )

    assert started.status_code == 200
    (stream,) = sessions.streams
    assert stream.kind == "command"
    assert stream.args == {"action": "reinstall", "args": {}}


def test_an_unknown_action_is_refused_typed(api):
    client, _ = api

    refused = client.post(f"/api/devices/{MAC}/action", json={"action": "dance"})

    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "unknown_action"


# --- reinstall follows the agent out and back ---


class Presence:
    """A sessions stand-in whose presence flips on a script."""

    def __init__(self, script):
        self.script = list(script)
        self.outcome = {
            "exit_code": 0,
            "code": "",
            "params": {},
            "output": "reinstall launched\n",
        }

    def is_online(self, key):
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]

    def version_of(self, key):
        return "9.9.9"

    async def open_stream(self, key, kind, args):
        return _ClosedStream(self.outcome)


class _ClosedStream:
    def __init__(self, info):
        self.close_info = info

    async def recv(self):
        return None


def test_reinstall_follows_the_agent_out_and_back(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from neutrino_hub.web.routers import devices as devices_router

    monkeypatch.setattr(devices_router, "WEB_REINSTALL_POLL_S", 0.0)
    runtime = SimpleNamespace(agent_sessions=Presence([True, True, False, False, True]))

    async def drain():
        return [line async for line in devices_router._reinstall_stream(runtime, MAC)]

    lines = asyncio.run(drain())

    assert lines[0] == "reinstall launched\n"
    assert "waiting for the agent to leave\n" in lines
    assert "waiting for the agent to come back\n" in lines
    assert lines[-1] == "agent 9.9.9 is back\n"


def test_reinstall_says_when_the_agent_never_leaves(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from neutrino_hub.web.routers import devices as devices_router

    monkeypatch.setattr(devices_router, "WEB_REINSTALL_POLL_S", 0.0)
    monkeypatch.setattr(devices_router, "WEB_REINSTALL_LEAVE_TIMEOUT_S", 0.01)
    runtime = SimpleNamespace(agent_sessions=Presence([True]))

    async def drain():
        return [line async for line in devices_router._reinstall_stream(runtime, MAC)]

    lines = asyncio.run(drain())

    assert lines[-1] == "the agent kept its socket; the package may not have changed\n"
