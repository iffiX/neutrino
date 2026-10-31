"""The account block: a Windows account's password is sealed as a vault login.

What these pin: an add with a password on a Windows machine stores one
login holding ``password``, the row references it, and the view says it
holds one; removing an account a module with a gateway key per account
enables hands the gateway its keys again. A password test sends the typed
password, or the stored login's with none typed, to the agent's one verb,
answers the agent's refusal and writes nothing.
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
