"""A machine's available accounts and its default account, in ``accounts.json``.

What these pin: ``default_account`` is the first key of the file, read and
written, empty while the machine has none and while it names no available
account; an add can make the account the default in the same write; a
replace or a removal keeps it; and whether the file holds the key at all,
empty included, is read apart from its value.
"""

import json

import pytest

from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.desired_state import DesiredStateStore

DEVICE = "device-one"


@pytest.fixture
def accounts(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    return DeviceAccountStore(DesiredStateStore()), tmp_path


def held(tmp_path) -> dict:
    return json.loads((tmp_path / "devices" / DEVICE / "accounts.json").read_text())


def test_a_machine_with_no_file_has_no_default(accounts):
    store, _ = accounts

    assert store.default_account(DEVICE) == ""
    assert store.has_default_key(DEVICE) is False


def test_an_add_makes_the_default_first_in_the_file_and_later_adds_keep_it(accounts):
    store, tmp_path = accounts

    store.add(DEVICE, DeviceAccount(account="lab"), is_default=True)
    store.add(DEVICE, DeviceAccount(account="ann"))
    store.replace(DEVICE, DeviceAccount(account="ann", shell_path="/bin/zsh"))
    store.remove(DEVICE, "ann")

    assert store.default_account(DEVICE) == "lab"
    assert list(held(tmp_path)) == ["default_account", "accounts"]
    assert held(tmp_path)["default_account"] == "lab"


def test_an_empty_default_is_a_key_the_file_holds(accounts):
    store, tmp_path = accounts
    store.add(DEVICE, DeviceAccount(account="lab"))

    assert store.has_default_key(DEVICE) is False
    store.set_default_account(DEVICE, "")

    assert store.has_default_key(DEVICE) is True
    assert store.default_account(DEVICE) == ""
    assert held(tmp_path)["default_account"] == ""


def test_a_default_that_names_no_available_account_reads_empty(accounts):
    store, tmp_path = accounts
    store.add(DEVICE, DeviceAccount(account="lab"))
    (tmp_path / "devices" / DEVICE / "accounts.json").write_text(
        json.dumps({"default_account": "ghost", "accounts": [{"account": "lab"}]})
    )

    assert store.default_account(DEVICE) == ""
    with pytest.raises(KeyError):
        store.set_default_account(DEVICE, "ghost")
