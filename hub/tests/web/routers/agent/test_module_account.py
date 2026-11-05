"""The account block: a Windows account's password is sealed as a vault login.

What these pin: an add with a password on a Windows machine stores one
login holding ``password``, the row references it, and the view says it
holds one; removing an account a module with a gateway key per account
enables hands the gateway its keys again. A password test sends the typed
password, or the stored login's with none typed, to the agent's one verb,
answers the agent's refusal and writes nothing. A share path is read by the
file share's ``folder`` verb first, and the home of an account the file
share enables when its share path is emptied; a folder the machine reads as
missing or a link is refused with the account as the share's name, nothing
written and nothing pushed.
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
    client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw"}
    )
    runtime.desired_states.set_enabled_accounts(DEVICE, "siyuan", ["lab"])

    answer = client.post(f"{BASE}/remove", json={"device_id": DEVICE, "account": "lab"})

    assert answer.status_code == 200, answer.text
    assert runtime.desired_states.read(DEVICE, "siyuan")["accounts"] == []
    assert applied == [True]


# --- the password test ---


def password_test(client, **fields):
    return client.post(
        f"{BASE}/password/test",
        json={"device_id": DEVICE, "account": "lab", **fields},
    )


def test_a_typed_password_goes_to_the_agents_verb_and_nothing_is_written(api):
    client, runtime, tmp_path = api

    answer = password_test(client, password="pw-1")

    assert answer.status_code == 200, answer.text
    assert runtime.agent_sessions.commands == [
        (
            DEVICE,
            "agent",
            "account_password_test",
            {"account": "lab", "password": "pw-1"},
        )
    ]
    assert not (tmp_path / "devices" / DEVICE / "accounts.json").exists()
    assert SecretVault().list_records() == []


def test_a_password_the_agent_refuses_is_answered_with_its_code(api):
    client, runtime, tmp_path = api
    runtime.agent_sessions.outcome = {
        "exit_code": 1,
        "code": "credential_invalid",
        "params": {"account": "lab"},
        "output": "",
    }

    answer = password_test(client, password="wrong")

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "credential_invalid",
        "params": {"account": "lab"},
    }
    assert "wrong" not in answer.text
    assert not (tmp_path / "devices" / DEVICE / "accounts.json").exists()
    assert SecretVault().list_records() == []


def test_a_logon_refused_otherwise_is_answered_with_windows_sentence(api):
    client, runtime, _tmp_path = api
    runtime.agent_sessions.outcome = {
        "exit_code": 1,
        "code": "account_logon_refused",
        "params": {"account": "lab", "detail": "locked out"},
        "output": "",
    }

    answer = password_test(client, password="pw-1")

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "account_logon_refused",
        "params": {"account": "lab", "detail": "locked out"},
    }


def test_no_password_typed_tests_the_login_the_account_has(api):
    client, runtime, _tmp_path = api
    client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw-9"}
    )

    answer = password_test(client)

    assert answer.status_code == 200, answer.text
    assert runtime.agent_sessions.commands[-1][3] == {
        "account": "lab",
        "password": "pw-9",
    }


def test_no_password_and_no_login_is_refused_before_the_agent_is_asked(api):
    client, runtime, _tmp_path = api

    answer = password_test(client)

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "credential_missing"
    assert runtime.agent_sessions.commands == []


def test_an_account_the_machine_does_not_report_is_refused(api):
    client, runtime, _tmp_path = api

    answer = password_test(client, account="ghost", password="pw-1")

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "account_unknown",
        "params": {"account": "ghost"},
    }
    assert runtime.agent_sessions.commands == []


def test_a_machine_that_is_not_windows_tests_no_password(api):
    client, runtime, _tmp_path = api
    runtime.device_platform[DEVICE] = {"os": "darwin"}

    answer = password_test(client, password="pw-1")

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "unsupported_platform"
    assert runtime.agent_sessions.commands == []


def test_a_machine_with_no_socket_answers_agent_offline(api):
    client, runtime, _tmp_path = api
    runtime.device_platform[OFFLINE] = WINDOWS
    runtime.device_accounts[OFFLINE] = ["lab"]

    answer = password_test(client, device_id=OFFLINE, password="pw-1")

    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "agent_offline"


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
    assert runtime.agent_sessions.commands == [
        ("device-one", "samba", "folder", {"path": "D:\\gone"})
    ]
    assert not (tmp_path / "devices" / DEVICE / "accounts.json").exists()
    assert runtime.agent_sessions.pushes == []


def test_an_add_with_no_share_path_asks_the_machine_nothing(api):
    client, runtime, _tmp_path = api

    answer = client.post(
        f"{BASE}/add", json={"device_id": DEVICE, "account": "lab", "password": "pw"}
    )

    assert answer.status_code == 200, answer.text
    assert runtime.agent_sessions.commands == []


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
