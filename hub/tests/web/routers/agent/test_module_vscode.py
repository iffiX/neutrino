"""The VS Code block: the instances, their logins, and their tokens.

What these pin: the view reads the instances, each with its login and what
the machine reports of it, and the accounts; a set is checked on the agent
with the accounts and ports alone, stores each instance beside its login and
a token sealed once per account and kept across sets, and pushes; two
instances sharing an account or a port, a login the vault does not hold, and
a Windows instance with no login are each refused by code before the agent
is asked; the state the agent is sent holds each instance's opened token,
the password of its login on Windows only, and never a seal or a login's id.
"""

import json

import pytest

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.web.routers.agent import module_vscode
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, module_box

BASE = "/api/agent/module/vscode"
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(monkeypatch, tmp_path, module_vscode.router)
    with client:
        yield client, runtime


def stored(tmp_path) -> list:
    path = tmp_path / "devices" / DEVICE / "vscode.json"
    return json.loads(path.read_text())["instances"]


def login(name: str) -> str:
    return (
        SecretVault()
        .add(
            kind="login", name=name, secret={"username": name, "password": f"pw-{name}"}
        )
        .id
    )


def test_the_view_reads_the_instances_what_the_machine_says_and_the_accounts(api):
    client, runtime = api
    DesiredStateStore().write(
        DEVICE,
        "vscode",
        {
            "instances": [
                {"account": "alice", "port": 8000, "login_id": "l1"},
                {"account": "bob", "port": 8001},
            ]
        },
    )
    runtime.report(
        DEVICE,
        "vscode",
        state="running",
        instances=[
            {"account": "alice", "is_running": True, "code": ""},
            {"account": "bob", "is_running": False, "code": "credential_invalid"},
        ],
    )
    runtime.device_accounts[DEVICE] = ["alice", "bob"]

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert view["instances"] == [
        {
            "account": "alice",
            "port": 8000,
            "login_id": "l1",
            "is_running": True,
            "code": "",
        },
        {
            "account": "bob",
            "port": 8001,
            "login_id": "",
            "is_running": False,
            "code": "credential_invalid",
        },
    ]
    assert view["accounts"] == ["alice", "bob"]


def test_a_set_is_checked_stored_with_a_token_per_account_kept_and_pushed(
    api, tmp_path
):
    client, runtime = api
    body = {"device_id": DEVICE, "instances": [{"account": "alice", "port": 8000}]}

    first = client.post(f"{BASE}/set", json=body)
    seal = stored(tmp_path)[0]["token_sealed"]
    body["instances"].append({"account": "bob", "port": 8001})
    second = client.post(f"{BASE}/set", json=body)
    store = DesiredStateStore()

    assert first.status_code == 200 and second.status_code == 200
    assert runtime.agent_sessions.validations[0] == (
        DEVICE,
        "vscode",
        {"instances": [{"account": "alice", "port": 8000}]},
    )
    assert stored(tmp_path)[0]["token_sealed"] == seal
    assert stored(tmp_path)[1]["token_sealed"] != seal
    assert store.vscode_token(DEVICE, "alice") != store.vscode_token(DEVICE, "bob")
    assert len(store.vscode_token(DEVICE, "alice")) >= 32
    assert len(runtime.agent_sessions.pushes) == 2


@pytest.mark.parametrize(
    "instances, code",
    [
        (
            [{"account": "alice", "port": 8000}, {"account": "Alice", "port": 8001}],
            "account_duplicate",
        ),
        (
            [{"account": "alice", "port": 8000}, {"account": "bob", "port": 8000}],
            "port_duplicate",
        ),
    ],
)
def test_two_instances_sharing_an_account_or_a_port_are_refused(api, instances, code):
    client, runtime = api

    answer = client.post(
        f"{BASE}/set", json={"device_id": DEVICE, "instances": instances}
    )

    assert (answer.status_code, answer.json()["detail"]["code"]) == (400, code)
    assert runtime.agent_sessions.validations == []


def test_a_windows_instance_needs_a_stored_login(api):
    client, runtime = api
    runtime.device_platform[DEVICE] = WINDOWS
    instance = {"account": "hanha", "port": 8000}

    missing = client.post(
        f"{BASE}/set", json={"device_id": DEVICE, "instances": [instance]}
    )
    unknown = client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "instances": [{**instance, "login_id": "nope"}]},
    )
    taken = client.post(
        f"{BASE}/set",
        json={
            "device_id": DEVICE,
            "instances": [{**instance, "login_id": login("hanha")}],
        },
    )

    assert missing.json()["detail"] == {
        "code": "credential_missing",
        "params": {"account": "hanha"},
    }
    assert unknown.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "login_id"},
    }
    assert taken.status_code == 200


@pytest.mark.parametrize("platform, has_password", [(WINDOWS, True), (LINUX, False)])
def test_the_agent_is_sent_each_opened_token_and_on_windows_the_password(
    api, platform, has_password
):
    client, runtime = api
    runtime.device_platform[DEVICE] = WINDOWS
    client.post(
        f"{BASE}/set",
        json={
            "device_id": DEVICE,
            "instances": [
                {"account": "hanha", "port": 8000, "login_id": login("hanha")}
            ],
        },
    )
    store = DesiredStateStore()
    store.set_want(DEVICE, "vscode", "running")

    desired, _ = store.compose(DEVICE, platform, address="192.168.1.20")

    module = desired["modules"]["vscode"]
    expected = {
        "account": "hanha",
        "port": 8000,
        "token": store.vscode_token(DEVICE, "hanha"),
    }
    if has_password:
        expected["password"] = "pw-hanha"
    assert module["config"] == {"address": "192.168.1.20", "instances": [expected]}
    assert module["install"]["kind"] == "vscode"
    assert module["install"]["package_kind"] == ("zip" if has_password else "tar")
