"""The 0.5 device files move into the account layer once.

What these pin: a program's ``instances`` become the module's ``accounts``
with their sealed fields and without ``port`` and ``login_id``; every account
they named is an available account, a Windows login going with it; the
Terminal module's one account becomes its enabled list and its shell the
account's; the file share drops ``users`` and keeps its shares; the Podman
machine drops ``login_id``; Hermes WebUI drops ``port``; the machine's AI
tools setting turns into each account's switch and the file is gone; a
directory already of the new shape is left alone; and the move names the
machines it touched.
"""

import json

import pytest

from neutrino_hub.modules.devices.accounts import DeviceAccountStore
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.legacy_files import move_legacy_device_files

DEVICE = "device-one"
OTHER = "device-two"
SEALED = {"nonce": "n", "ciphertext": "c"}


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    return tmp_path


def legacy_box(store: DesiredStateStore) -> None:
    store.write(DEVICE, "terminal", {"account": "ann", "shell_path": "/bin/zsh"})
    store.write(
        DEVICE,
        "codeg",
        {
            "instances": [
                {"account": "ann", "port": 3101, "secret_sealed": SEALED},
                {
                    "account": "bob",
                    "port": 3102,
                    "login_id": "l-bob",
                    "secret_sealed": SEALED,
                },
            ]
        },
    )
    store.write(
        DEVICE,
        "vscode",
        {
            "terms_accepted_at": "2026-01-01T00:00:00+00:00",
            "instances": [{"account": "ann", "port": 8001, "token_sealed": SEALED}],
        },
    )
    store.write(
        DEVICE,
        "samba",
        {"shares": [{"name": "media", "path": "/tank/media"}], "users": ["ann"]},
    )
    store.write(
        DEVICE,
        "podman",
        {
            "containers": [],
            "mirrors": [],
            "machine": {"account": "lab", "login_id": "l-lab", "cpus": 2},
        },
    )
    store.write(DEVICE, "hermes_webui", {"port": 8787, "secret_sealed": SEALED})
    store.write(
        DEVICE,
        "ai_tools",
        {"is_enabled": True, "tool_configs": {"claude": {"opus": "claude-opus-4"}}},
    )


def test_the_instances_become_the_modules_accounts_and_the_available_accounts(config):
    store = DesiredStateStore()
    legacy_box(store)

    moved = move_legacy_device_files(store, [DEVICE, OTHER])

    assert moved == [DEVICE]
    assert store.read(DEVICE, "codeg") == {
        "accounts": [
            {"account": "ann", "secret_sealed": SEALED},
            {"account": "bob", "secret_sealed": SEALED},
        ]
    }
    assert store.read(DEVICE, "vscode") == {
        "terms_accepted_at": "2026-01-01T00:00:00+00:00",
        "accounts": [{"account": "ann", "token_sealed": SEALED}],
    }
    assert store.enabled_accounts(DEVICE, "codeg") == ["ann", "bob"]
    rows = {row.account: row for row in DeviceAccountStore(store).accounts(DEVICE)}
    assert set(rows) == {"ann", "bob", "lab"}
    assert rows["ann"].shell_path == "/bin/zsh"
    assert rows["bob"].login_id == "l-bob"
    assert rows["lab"].login_id == "l-lab"


def test_the_terminal_the_share_the_machine_and_hermes_take_the_new_shape(config):
    store = DesiredStateStore()
    legacy_box(store)

    move_legacy_device_files(store, [DEVICE])

    assert store.read(DEVICE, "terminal") == {"accounts": [{"account": "ann"}]}
    assert store.read(DEVICE, "samba") == {
        "shares": [{"name": "media", "path": "/tank/media"}]
    }
    assert store.read(DEVICE, "podman")["machine"] == {"account": "lab", "cpus": 2}
    assert store.read(DEVICE, "hermes_webui") == {"secret_sealed": SEALED}


def test_the_machines_ai_tools_setting_becomes_each_accounts_switch(config):
    store = DesiredStateStore()
    legacy_box(store)

    move_legacy_device_files(store, [DEVICE])

    assert not (config / "devices" / DEVICE / "ai_tools.json").exists()
    rows = {row.account: row for row in DeviceAccountStore(store).accounts(DEVICE)}
    assert all(row.is_ai_tools_enabled for row in rows.values())
    assert rows["ann"].tool_configs["claude"]["opus"] == "claude-opus-4"
    assert store.is_ai_tools_enabled(DEVICE) is True


def test_a_directory_of_the_new_shape_is_left_alone(config):
    store = DesiredStateStore()
    store.write(DEVICE, "terminal", {"accounts": [{"account": "ann"}]})
    store.write(
        DEVICE, "codeg", {"accounts": [{"account": "ann", "secret_sealed": SEALED}]}
    )
    store.write(DEVICE, "samba", {"accounts": [], "shares": []})
    before = {
        name: json.loads((config / "devices" / DEVICE / f"{name}.json").read_text())
        for name in ("terminal", "codeg", "samba")
    }

    assert move_legacy_device_files(store, [DEVICE]) == []
    assert move_legacy_device_files(store, [DEVICE]) == []
    assert {
        name: json.loads((config / "devices" / DEVICE / f"{name}.json").read_text())
        for name in ("terminal", "codeg", "samba")
    } == before
    assert DeviceAccountStore(store).accounts(DEVICE) == []


def test_an_account_the_machine_already_lists_keeps_its_row(config):
    store = DesiredStateStore()
    legacy_box(store)
    from neutrino_hub.modules.devices.accounts import DeviceAccount

    DeviceAccountStore(store).add(
        DEVICE, DeviceAccount(account="ann", share_path="/srv/ann", login_id="kept")
    )

    move_legacy_device_files(store, [DEVICE])

    row = DeviceAccountStore(store).get(DEVICE, "ann")
    assert (row.share_path, row.login_id, row.shell_path) == ("/srv/ann", "kept", "")
