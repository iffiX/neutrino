"""The account block: a Windows account's password is sealed as a vault login.

What these pin: an add with a password on a Windows machine stores one
login holding ``password``, the row references it, and the view says it
holds one.
"""

import json

import pytest

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.web.routers.agent import module_account
from tests.conftest import FakeDeviceRegistry, unlock_vault
from tests.web.module_api_box import DEVICE, module_box

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
