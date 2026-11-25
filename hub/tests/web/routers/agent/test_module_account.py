"""The account block: every account added is tested, and the first one becomes the default.

What these pin: an add first has the agent's ``account_test`` test the
account, with the password on Windows and none elsewhere, and a refusal
writes nothing; a Windows password is then sealed as a vault login the row
references; a new Windows password on ``set`` is tested the same way. The
first account added to a machine with no default account becomes the
default, enabled first in Terminal, the SSH server and every installed
module of the account layer, the agent checking each changed section and a
refusal writing nothing; a later one does not. ``remove`` refuses the
default with ``account_is_default``; removing an account a module with a
gateway key per account enables hands the gateway its keys again; a switch
changed settles SiYuan's keys and the container modules'. A share path is
read by the file share's ``folder`` verb first, and the home of an account
the file share enables when its share path is emptied; a folder the machine
reads as missing or a link is refused with the account as the share's name,
nothing written and nothing pushed.
"""

import json

import pytest

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.web.routers.agent import module_account
from tests.conftest import FakeDeviceRegistry, unlock_vault
from tests.web.module_api_box import DEVICE, OFFLINE, module_box

BASE = "/api/agent/module/account"
WINDOWS = {"os": "windows", "family": "windows", "arch": "amd64", "version": "10"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(monkeypatch, tmp_path, module_account.router)
    monkeypatch.setattr(module_account, "DeviceRegistry", FakeDeviceRegistry)
    runtime.device_platform[DEVICE] = WINDOWS
    runtime.device_accounts = {DEVICE: ["lab"]}
    with client:
        yield client, runtime, tmp_path


def stored_accounts(tmp_path) -> list:
    path = tmp_path / "devices" / DEVICE / "accounts.json"
    return json.loads(path.read_text())["accounts"]


def test_a_windows_password_is_sealed_as_a_login_the_row_references(api):
    client, _runtime, tmp_path = api
    answer = client.post(
        f"{BASE}/add",
        json={"device_id": DEVICE, "account": "lab", "password": "pw-1"},
    )
    assert answer.status_code == 200, answer.text
    row = answer.json()["accounts"][0]
    (stored,) = stored_accounts(tmp_path)
    assert (row["account"], row["has_login"]) == ("lab", True)
    assert stored["login_id"] != ""
    assert SecretVault().open(stored["login_id"]) == {"password": "pw-1"}


def test_a_windows_account_without_a_password_is_refused(api):
    client, _runtime, _tmp_path = api
    answer = client.post(f"{BASE}/add", json={"device_id": DEVICE, "account": "lab"})
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "credential_missing"


def test_removing_an_account_siyuan_enables_hands_the_gateway_its_keys_again(
    api, monkeypatch
):
    client, runtime, _tmp_path = api
    applied: list = []
    monkeypatch.setattr(module_account, "apply_keys", lambda: applied.append(True))
    runtime.device_accounts = {DEVICE: ["lab", "ann"]}
    client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw"}
    )
    client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "ann", "password": "pw"}
    )
    runtime.desired_states.set_enabled_accounts(DEVICE, "siyuan", ["lab", "ann"])

    answer = client.post(f"{BASE}/remove", json={"device_id": DEVICE, "account": "ann"})

    assert answer.status_code == 200, answer.text
    assert runtime.desired_states.enabled_accounts(DEVICE, "siyuan") == ["lab"]
    assert applied == [True]


# --- the test before the write ---


def test_an_add_has_the_agent_test_the_account_with_its_password_first(api):
    client, runtime, tmp_path = api

    answer = client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw-1"}
    )

    assert answer.status_code == 200, answer.text
    assert runtime.agent_sessions.commands[0] == (
        DEVICE,
        "agent",
        "account_test",
        {"account": "lab", "password": "pw-1"},
    )


def test_off_windows_the_test_carries_no_password(api):
    client, runtime, _tmp_path = api
    runtime.device_platform[DEVICE] = {"os": "linux", "family": "debian"}

    answer = client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "x"}
    )

    assert answer.status_code == 200, answer.text
    assert runtime.agent_sessions.commands[0][2:] == (
        "account_test",
        {"account": "lab", "password": ""},
    )
    assert stored_accounts(_tmp_path)[0]["login_id"] == ""


@pytest.mark.parametrize(
    "code, params",
    [
        ("credential_invalid", {"account": "lab"}),
        ("account_logon_refused", {"account": "lab", "detail": "locked out"}),
        ("account_no_login", {"account": "lab"}),
    ],
)
def test_a_refused_test_is_answered_with_its_code_and_writes_nothing(api, code, params):
    client, runtime, tmp_path = api
    runtime.agent_sessions.outcomes["account_test"] = {
        "exit_code": 1,
        "code": code,
        "params": params,
    }

    answer = client.post(
        f"{BASE}/add",
        json={"device_id": DEVICE, "account": "lab", "password": "wrong"},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {"code": code, "params": params}
    assert "wrong" not in answer.text
    assert not (tmp_path / "devices" / DEVICE / "accounts.json").exists()
    assert SecretVault().list_records() == []
    assert runtime.agent_sessions.pushes == []


def test_a_new_windows_password_is_tested_and_an_empty_one_is_not(api):
    client, runtime, tmp_path = api
    client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw-1"}
    )
    login = stored_accounts(tmp_path)[0]["login_id"]
    runtime.agent_sessions.commands.clear()

    kept = client.post(f"{BASE}/set", json={"device_id": DEVICE, "account": "lab"})
    runtime.agent_sessions.outcomes["account_test"] = {
        "exit_code": 1,
        "code": "credential_invalid",
        "params": {"account": "lab"},
    }
    refused = client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "account": "lab", "password": "wrong"},
    )

    assert kept.status_code == 200, kept.text
    assert refused.status_code == 400
    assert [command[2] for command in runtime.agent_sessions.commands] == [
        "account_test"
    ]
    assert stored_accounts(tmp_path)[0]["login_id"] == login
    assert [record.id for record in SecretVault().list_records()] == [login]


def test_a_machine_with_no_socket_answers_agent_offline(api):
    client, runtime, _tmp_path = api
    runtime.device_platform[OFFLINE] = WINDOWS
    runtime.device_accounts[OFFLINE] = ["lab"]

    answer = client.post(
        f"{BASE}/add",
        json={"device_id": OFFLINE, "account": "lab", "password": "pw-1"},
    )

    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "agent_offline"


def test_the_password_test_route_is_gone(api):
    client, _runtime, _tmp_path = api

    answer = client.post(
        f"{BASE}/password/test", json={"device_id": DEVICE, "account": "lab"}
    )

    assert answer.status_code in (404, 405)


# --- the default account ---


def test_the_first_account_becomes_the_default_in_terminal_ssh_and_installed_modules(
    api,
):
    client, runtime, tmp_path = api
    runtime.device_accounts = {DEVICE: ["lab", "ann"]}
    store = runtime.desired_states
    store.set_want(DEVICE, "code_server", "running")
    store.set_want(DEVICE, "vscode", "absent")

    first = client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw"}
    )
    second = client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "ann", "password": "pw"}
    )

    assert first.status_code == 200, first.text
    assert second.json()["default_account"] == "lab"
    held = json.loads((tmp_path / "devices" / DEVICE / "accounts.json").read_text())
    assert list(held)[0] == "default_account"
    assert held["default_account"] == "lab"
    assert store.enabled_accounts(DEVICE, "terminal") == ["lab"]
    assert store.enabled_accounts(DEVICE, "ssh_server") == ["lab"]
    assert store.enabled_accounts(DEVICE, "code_server") == ["lab"]
    assert store.account_secret(DEVICE, "code_server", "lab", "secret_sealed")
    assert store.enabled_accounts(DEVICE, "vscode") == []
    checked = {module for _key, module, _config in runtime.agent_sessions.validations}
    assert checked == {"terminal", "ssh_server", "code_server"}
    assert store.enabled_accounts(DEVICE, "terminal") == ["lab"]


def test_a_section_the_agent_refuses_writes_nothing_of_the_first_account(api):
    client, runtime, tmp_path = api
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "account_no_profile",
        "params": {"account": "lab"},
    }

    answer = client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw"}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "account_no_profile"
    held = runtime.desired_states.read(DEVICE, "accounts")
    assert held == {}
    assert runtime.desired_states.read(DEVICE, "terminal") == {}
    assert runtime.desired_states.read(DEVICE, "ssh_server") == {}
    assert SecretVault().list_records() == []
    assert runtime.agent_sessions.pushes == []


def test_the_default_account_is_never_removed(api):
    client, runtime, _tmp_path = api
    client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw"}
    )

    answer = client.post(f"{BASE}/remove", json={"device_id": DEVICE, "account": "lab"})

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "account_is_default",
        "params": {"account": "lab"},
    }
    assert runtime.desired_states.default_account(DEVICE) == "lab"


def test_a_switch_change_settles_siyuan_and_the_container_modules_keys(
    api, monkeypatch
):
    client, runtime, _tmp_path = api
    settled: list = []
    monkeypatch.setattr(
        module_account,
        "settle_instance_keys",
        lambda store, key, module, name: settled.append(("instances", module)),
    )
    monkeypatch.setattr(
        module_account,
        "settle_module_keys",
        lambda store, key, name: settled.append(("modules", key)),
    )
    monkeypatch.setattr(module_account, "gateway_models", lambda served: ["m1"])
    monkeypatch.setattr(module_account, "ensure_device_key", lambda key, name: "k")
    monkeypatch.setattr(module_account, "revoke_device_key", lambda key: None)
    client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw"}
    )
    runtime.desired_states.set_enabled_accounts(DEVICE, "siyuan", ["lab"])
    settled.clear()

    same = client.post(f"{BASE}/set", json={"device_id": DEVICE, "account": "lab"})
    after_same = list(settled)
    switched = client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "account": "lab", "is_ai_tools_enabled": True},
    )

    assert same.status_code == 200, same.text
    assert switched.status_code == 200, switched.text
    assert after_same == []
    assert settled == [("instances", "siyuan"), ("modules", DEVICE)]


# --- the share path ---


def test_a_share_path_at_no_real_folder_is_refused_and_nothing_written(api):
    client, runtime, tmp_path = api
    runtime.agent_sessions.outcomes["folder"] = {
        "exit_code": 1,
        "code": "share_path_missing",
        "params": {"path": "D:\\gone"},
    }

    answer = client.post(
        f"{BASE}/add",
        json={
            "device_id": DEVICE,
            "account": "lab",
            "password": "pw",
            "share_path": "D:\\gone",
        },
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "share_path_missing",
        "params": {"name": "lab", "path": "D:\\gone"},
    }
    assert runtime.agent_sessions.commands[-1] == (
        "device-one",
        "samba",
        "folder",
        {"path": "D:\\gone"},
    )
    assert not (tmp_path / "devices" / DEVICE / "accounts.json").exists()
    assert runtime.agent_sessions.pushes == []


def test_an_add_with_no_share_path_asks_the_machine_no_folder(api):
    client, runtime, _tmp_path = api

    answer = client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw"}
    )

    assert answer.status_code == 200, answer.text
    assert [command[2] for command in runtime.agent_sessions.commands] == [
        "account_test"
    ]


def test_an_emptied_share_path_of_a_file_share_account_reads_its_home(api):
    client, runtime, _tmp_path = api
    client.post(
        f"{BASE}/add",
        json={
            "device_id": DEVICE,
            "account": "lab",
            "password": "pw",
            "share_path": "D:\\share",
        },
    )
    runtime.desired_states.set_enabled_accounts(DEVICE, "samba", ["lab"])
    runtime.device_account_details[DEVICE] = {"lab": {"home": "C:\\Users\\lab"}}
    runtime.agent_sessions.outcomes["folder"] = {
        "exit_code": 1,
        "code": "share_path_link",
        "params": {"path": "C:\\Users\\lab"},
    }

    answer = client.post(
        f"{BASE}/set", json={"device_id": DEVICE, "account": "lab", "share_path": ""}
    )

    assert answer.json()["detail"] == {
        "code": "share_path_link",
        "params": {"name": "lab", "path": "C:\\Users\\lab"},
    }
    assert stored_accounts(_tmp_path)[0]["share_path"] == "D:\\share"
