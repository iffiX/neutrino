"""The default account of a machine 0.6.1 kept, set once at the panel's start.

What these pin: an ``accounts.json`` with no ``default_account`` key takes
its first available account, the one added earliest, as the default; one
with no account takes the key empty; a file that holds the key, empty
included, is left alone; a machine with no file is not touched. The
default moves first in every module file that enables it, and is added to
Terminal, the SSH server and each module of the account layer whose
``want`` is neither empty nor ``absent``, nothing new installed; its AI
switch off voids the container modules' keys, and SiYuan's keys follow
each account's own switch.
"""

import json

import pytest

from neutrino_hub.modules.clients import ai_keys
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.legacy_defaults import set_legacy_defaults
from tests.conftest import unlock_vault

DEVICE = "device-one"
EMPTY = "device-two"
SET = "device-three"
NO_FILE = "device-four"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    unlock_vault(monkeypatch, tmp_path)
    applied: list = []
    monkeypatch.setattr(ai_keys, "_apply", lambda **kwargs: applied.append(kwargs))
    return DesiredStateStore()


def a_0_6_1_machine(store: DesiredStateStore) -> None:
    """Two accounts, lab added first with its switch off, and the modules it
    and ann had enabled in 0.6.1."""
    store.write(
        DEVICE,
        "accounts",
        {
            "accounts": [
                {"account": "lab"},
                {"account": "ann", "is_ai_tools_enabled": True},
            ]
        },
    )
    store.set_want(DEVICE, "code_server", "running")
    store.set_want(DEVICE, "vscode", "absent")
    store.set_want(DEVICE, "hermes_webui", "running")
    store.set_enabled_accounts(DEVICE, "code_server", ["ann"])
    store.set_enabled_accounts(DEVICE, "terminal", ["ann", "lab"])
    store.set_enabled_accounts(DEVICE, "codeg", ["ann", "lab"])
    store.write(DEVICE, "hermes_webui", {"gateway_key": {"id": "k"}})


def test_the_first_account_becomes_the_default_and_joins_the_installed_modules(
    store, tmp_path
):
    a_0_6_1_machine(store)

    changed = set_legacy_defaults(store, {DEVICE: "argon", NO_FILE: "attic"})

    assert changed == [DEVICE]
    held = json.loads((tmp_path / "devices" / DEVICE / "accounts.json").read_text())
    assert list(held)[0] == "default_account"
    assert store.default_account(DEVICE) == "lab"
    assert store.enabled_accounts(DEVICE, "terminal") == ["lab", "ann"]
    assert store.enabled_accounts(DEVICE, "ssh_server") == ["lab"]
    assert store.enabled_accounts(DEVICE, "code_server") == ["lab", "ann"]
    assert store.account_secret(DEVICE, "code_server", "lab", "secret_sealed")
    assert store.enabled_accounts(DEVICE, "codeg") == ["lab", "ann"]
    assert store.enabled_accounts(DEVICE, "vscode") == []
    assert store.want_of(DEVICE, "vscode") == "absent"
    assert store.want_of(DEVICE, "ssh_server") == ""
    assert not (tmp_path / "devices" / NO_FILE).exists()


def test_the_containers_follow_the_new_defaults_switch(store):
    a_0_6_1_machine(store)

    set_legacy_defaults(store, {DEVICE: "argon"})

    assert store.is_gateway_used(DEVICE) is False
    assert "gateway_key" not in store.read(DEVICE, "hermes_webui")


def test_a_machine_with_no_account_takes_the_key_empty(store):
    store.write(EMPTY, "accounts", {"accounts": []})

    changed = set_legacy_defaults(store, {EMPTY: "attic"})

    assert changed == [EMPTY]
    assert store.read(EMPTY, "accounts") == {"default_account": "", "accounts": []}
    assert store.is_gateway_used(EMPTY) is True


@pytest.mark.parametrize("default", ["", "ann"])
def test_a_file_that_holds_the_key_is_left_alone(store, default):
    held = {
        "default_account": default,
        "accounts": [{"account": "lab"}, {"account": "ann"}],
    }
    store.write(SET, "accounts", held)

    changed = set_legacy_defaults(store, {SET: "box"})

    assert changed == []
    assert store.read(SET, "accounts") == held
    assert store.read(SET, "terminal") == {}
