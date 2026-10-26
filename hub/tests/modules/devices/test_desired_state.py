"""One desired state per device under config/, composed under one hash.

What these pin: the directory a device id names, the module files and the
wants and versions beside them, a module the file does not name being
mentioned nowhere, a module the machine settled keeping its want and
leaving the state, a hash that moves only with the state, the composed
shape the agent applies, and the account layer: the available accounts,
each module's enabled accounts with secrets generated once and kept across
a disable, the file share's shares, users and passwords, the SSH server's
public keys, the local names and cookie names of the programs behind a
forwarder, a Windows machine's login passwords, the removal of an account
from every module, and the Containers Run settings naming an account.
"""

import json

import pytest

from neutrino_hub.modules.credentials.vault import unseal_bytes
from neutrino_hub.modules.devices import desired_state as desired_state_module
from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.desired_state import (
    DesiredStateStore,
    smb_user,
    state_hash,
)
from neutrino_hub.modules.devices.ssh_account_keys import public_key_of
from neutrino_hub.modules.services.apps import entry_id, local_port
from tests.conftest import unlock_vault

DEVICE = "device-one"
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64"}
AGENT_RECIPE = {"method": "agent", "params": {}}


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        desired_state_module,
        "resolved_modules",
        lambda platform: {
            "samba": {"recipe": {"method": "system", "params": {}}},
            "gitea": {"recipe": {}},
            "vscode": {"recipe": {"method": "hub", "params": {"version": "1.0"}}},
            "terminal": {"recipe": {"runner": "terminal", **AGENT_RECIPE}},
            "remote_desktop": {"recipe": {"runner": "remote_desktop", **AGENT_RECIPE}},
            "ssh_server": {"recipe": {"runner": "ssh_server", **AGENT_RECIPE}},
        },
    )
    return tmp_path


@pytest.fixture
def unlocked(config, monkeypatch):
    unlock_vault(monkeypatch, config)
    return config


def with_accounts(
    store: DesiredStateStore, *names: str, **fields
) -> DeviceAccountStore:
    accounts = DeviceAccountStore(store)
    for name in names:
        accounts.add(DEVICE, DeviceAccount(account=name, **fields))
    return accounts


def test_module_files_land_under_the_devices_directory(config):
    store = DesiredStateStore()

    store.write(DEVICE, "gitea", {"listen_port": 3000})

    path = config / f"devices/{DEVICE}/gitea.json"
    assert json.loads(path.read_text())["listen_port"] == 3000
    assert store.read(DEVICE, "gitea") == {"listen_port": 3000}
    assert store.read(DEVICE, "samba") == {}


def test_a_module_is_named_once_a_want_is_written_and_keeps_its_version(config):
    store = DesiredStateStore()

    assert store.modules(DEVICE) == {}
    store.set_want(DEVICE, "samba", "running")
    store.set_version(DEVICE, "vscode", "1.2.3")
    store.set_want(DEVICE, "vscode", "installed")

    assert store.modules(DEVICE) == {
        "samba": {"want": "running", "is_settled": False, "version": ""},
        "vscode": {"want": "installed", "is_settled": False, "version": "1.2.3"},
    }
    assert store.version_of(DEVICE, "vscode") == "1.2.3"
    assert store.named_versions() == {"vscode": {"1.2.3"}}
    with pytest.raises(ValueError):
        store.set_want(DEVICE, "samba", "installing")


def test_settling_a_module_keeps_its_want_and_leaves_it_out_of_the_state(config):
    store = DesiredStateStore()
    store.set_want(DEVICE, "samba", "absent")
    store.set_want(DEVICE, "gitea", "running")

    assert store.settle_want(DEVICE, "samba") is True
    assert store.settle_want(DEVICE, "samba") is False

    desired, _ = store.compose(DEVICE, PLATFORM)
    assert set(desired["modules"]) == {
        "gitea",
        "terminal",
        "remote_desktop",
        "ssh_server",
    }
    assert store.named_modules() == {"gitea"}


def test_the_three_carried_modules_are_always_composed_with_the_agent_recipe(config):
    store = DesiredStateStore()

    desired, _ = store.compose(DEVICE, PLATFORM)

    assert desired["modules"]["terminal"] == {
        "want": "running",
        "config": {"accounts": []},
        "install": {"runner": "terminal", **AGENT_RECIPE},
    }
    assert desired["modules"]["ssh_server"]["want"] == "stopped"
    assert desired["modules"]["ssh_server"]["config"] == {"instances": []}
    assert desired["modules"]["remote_desktop"]["config"] == {"is_enabled": False}
    assert set(desired) == {"modules", "desktop", "urls", "ai_tools", "source_sets"}


def test_the_hash_moves_with_the_state_and_nothing_else(config):
    store = DesiredStateStore()
    first, hash_one = store.compose(DEVICE, PLATFORM)
    _, hash_again = store.compose(DEVICE, PLATFORM)
    store.set_want(DEVICE, "gitea", "running")
    _, hash_two = store.compose(DEVICE, PLATFORM)

    assert hash_one == hash_again == state_hash(first)
    assert hash_two != hash_one


def test_the_available_accounts_are_kept_in_the_order_they_were_added(unlocked):
    store = DesiredStateStore()
    accounts = with_accounts(store, "bob", "ann", shell_path="/bin/zsh")

    assert [row.account for row in store.available_accounts(DEVICE)] == ["bob", "ann"]
    assert accounts.get(DEVICE, "ann").shell_path == "/bin/zsh"
    with pytest.raises(ValueError):
        accounts.add(DEVICE, DeviceAccount(account="ann"))
    accounts.replace(
        DEVICE, DeviceAccount(account="ann", is_ai_tools_enabled=True, tool_configs={})
    )
    assert [row.account for row in store.ai_tool_accounts(DEVICE)] == ["ann"]
    assert accounts.remove(DEVICE, "bob").account == "bob"
    assert accounts.remove(DEVICE, "bob") is None


def test_enabling_an_account_seals_its_secret_once_and_a_disable_keeps_it(unlocked):
    store = DesiredStateStore()
    with_accounts(store, "ann")

    first = store.set_enabled_accounts(DEVICE, "samba", ["ann"])
    secret = store.account_secret(DEVICE, "samba", "ann", "password_sealed")
    store.set_enabled_accounts(DEVICE, "samba", [])
    disabled = store.read(DEVICE, "samba")
    store.set_enabled_accounts(DEVICE, "samba", ["ann"])

    assert [row["account"] for row in first["accounts"]] == ["ann"]
    assert len(secret) >= 24
    assert disabled["accounts"] == []
    assert [row["account"] for row in disabled["disabled"]] == ["ann"]
    assert store.account_secret(DEVICE, "samba", "ann", "password_sealed") == secret
    assert store.enabled_accounts(DEVICE, "samba") == ["ann"]


def test_an_enabled_account_that_is_no_longer_available_is_composed_nowhere(unlocked):
    store = DesiredStateStore()
    accounts = with_accounts(store, "ann", "bob")
    store.set_enabled_accounts(DEVICE, "terminal", ["ann", "bob"])

    accounts.remove(DEVICE, "bob")

    assert store.enabled_accounts(DEVICE, "terminal") == ["ann"]
    desired, _ = store.compose(DEVICE, PLATFORM)
    assert [
        row["account"] for row in desired["modules"]["terminal"]["config"]["accounts"]
    ] == ["ann"]


def test_the_file_share_is_one_share_one_user_and_one_password_per_account(unlocked):
    store = DesiredStateStore()
    with_accounts(store, "ann", share_path="")
    DeviceAccountStore(store).add(
        DEVICE, DeviceAccount(account="bob", share_path="/srv/b")
    )
    store.set_enabled_accounts(DEVICE, "samba", ["ann", "bob"])
    store.set_want(DEVICE, "samba", "running")

    desired, _ = store.compose(
        DEVICE,
        PLATFORM,
        allowed_subnets=["192.168.1.0/24"],
        account_details={"ann": {"home": "/home/ann", "shell": "/bin/bash"}},
    )

    config = desired["modules"]["samba"]["config"]
    assert config["shares"] == [
        {
            "name": "ann",
            "path": "/home/ann",
            "comment": "",
            "is_read_only": False,
            "valid_users": ["neutrino-ann"],
            "force_user": "ann",
        },
        {
            "name": "bob",
            "path": "/srv/b",
            "comment": "",
            "is_read_only": False,
            "valid_users": ["neutrino-bob"],
            "force_user": "bob",
        },
    ]
    assert config["users"] == ["neutrino-ann", "neutrino-bob"]
    assert set(config["passwords"]) == {"neutrino-ann", "neutrino-bob"}
    assert config["passwords"]["neutrino-ann"] == store.account_secret(
        DEVICE, "samba", "ann", "password_sealed"
    )
    assert config["allowed_subnets"] == ["192.168.1.0/24"]


def test_a_windows_share_user_is_neutrino_and_the_account_cut_to_twenty(unlocked):
    store = DesiredStateStore()
    with_accounts(store, "averyveryverylongaccountname", share_path="C:\\Share")
    store.set_enabled_accounts(DEVICE, "samba", ["averyveryverylongaccountname"])
    store.set_want(DEVICE, "samba", "running")

    desired, _ = store.compose(DEVICE, WINDOWS)

    assert smb_user("averyveryverylongaccountname", WINDOWS) == "neutrino-averyveryve"
    assert desired["modules"]["samba"]["config"]["users"] == ["neutrino-averyveryve"]
    assert smb_user("averyveryverylongaccountname", PLATFORM) == (
        "neutrino-averyveryverylongaccountname"
    )


def test_an_enabled_account_with_no_share_path_and_no_reported_home_is_left_out(
    unlocked,
):
    store = DesiredStateStore()
    with_accounts(store, "ann", share_path="")
    DeviceAccountStore(store).add(DEVICE, DeviceAccount(account="bob", share_path=""))
    store.set_enabled_accounts(DEVICE, "samba", ["ann", "bob"])
    store.set_want(DEVICE, "samba", "running")

    desired, _ = store.compose(
        DEVICE,
        WINDOWS,
        account_details={
            "ann": {"home": "", "shell": ""},
            "bob": {"home": "C:\\Users\\bob", "shell": ""},
        },
    )

    config = desired["modules"]["samba"]["config"]
    assert [share["name"] for share in config["shares"]] == ["bob"]
    assert config["shares"][0]["path"] == "C:\\Users\\bob"
    assert config["users"] == ["neutrino-bob"]
    assert list(config["passwords"]) == ["neutrino-bob"]
    assert smb_user("ann", PLATFORM) == "neutrino-ann"


def test_a_dataset_share_the_file_names_rides_beside_the_accounts_shares(unlocked):
    store = DesiredStateStore()
    with_accounts(store, "ann", share_path="/home/ann")
    store.set_enabled_accounts(DEVICE, "samba", ["ann"])
    stored = store.read(DEVICE, "samba")
    stored["shares"] = [
        {
            "name": "media",
            "path": "/tank/media",
            "valid_users": ["neutrino-ann", "neutrino-gone"],
        }
    ]
    store.write(DEVICE, "samba", stored)
    store.set_want(DEVICE, "samba", "running")

    desired, _ = store.compose(DEVICE, PLATFORM)

    assert desired["modules"]["samba"]["config"]["shares"][1] == {
        "name": "media",
        "path": "/tank/media",
        "comment": "",
        "is_read_only": False,
        "valid_users": ["neutrino-ann"],
    }


def test_the_ssh_server_sends_each_accounts_public_key_and_shell(unlocked):
    store = DesiredStateStore()
    with_accounts(store, "ann", shell_path="/bin/fish")
    store.set_enabled_accounts(DEVICE, "ssh_server", ["ann"])

    desired, _ = store.compose(DEVICE, PLATFORM)
    private = store.account_secret(DEVICE, "ssh_server", "ann", "private_key_sealed")

    assert desired["modules"]["ssh_server"]["want"] == "running"
    assert desired["modules"]["ssh_server"]["config"] == {
        "instances": [
            {
                "account": "ann",
                "authorized_key": public_key_of(private, comment="neutrino"),
                "shell_path": "/bin/fish",
            }
        ]
    }
    assert private.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")


def test_a_program_behind_a_forwarder_carries_its_local_name_and_cookie(unlocked):
    store = DesiredStateStore()
    with_accounts(store, "ann")
    store.set_enabled_accounts(DEVICE, "codeg", ["ann"])
    store.set_want(DEVICE, "codeg", "running")

    desired, _ = store.compose(DEVICE, PLATFORM, machine_slug="argon")

    (instance,) = desired["modules"]["codeg"]["config"]["instances"]
    assert instance["local_name"] == "codeg-ann.argon.localhost"
    assert instance["cookie_name"].startswith("neutrino_")
    assert len(instance["cookie_name"]) == len("neutrino_") + 12
    assert instance["secret"] == store.account_secret(
        DEVICE, "codeg", "ann", "secret_sealed"
    )
    assert "port" not in instance


def test_gitea_is_handed_the_local_port_of_its_ssh_entry(unlocked):
    store = DesiredStateStore()
    store.set_want(DEVICE, "gitea", "running")

    desired, _ = store.compose(DEVICE, PLATFORM, address="192.168.100.7")

    assert desired["modules"]["gitea"]["config"]["ssh_port"] == local_port(
        entry_id(f"gitea_{DEVICE}", "ssh")
    )
    assert 24000 <= desired["modules"]["gitea"]["config"]["ssh_port"] < 32000


def test_a_windows_machine_is_sent_each_accounts_login_password(unlocked):
    store = DesiredStateStore()
    from neutrino_hub.modules.credentials.vault import SecretVault

    login = SecretVault().add(
        kind="login", name="ann", secret={"username": "ann", "password": "pw-ann"}
    )
    DeviceAccountStore(store).add(
        DEVICE, DeviceAccount(account="ann", login_id=login.id)
    )
    store.set_enabled_accounts(DEVICE, "terminal", ["ann"])
    store.set_enabled_accounts(DEVICE, "ssh_server", ["ann"])

    windows, _ = store.compose(DEVICE, WINDOWS)
    linux, _ = store.compose(DEVICE, PLATFORM)

    assert (
        windows["modules"]["terminal"]["config"]["accounts"][0]["password"] == "pw-ann"
    )
    assert windows["modules"]["ssh_server"]["config"]["instances"][0]["password"] == (
        "pw-ann"
    )
    assert "password" not in linux["modules"]["terminal"]["config"]["accounts"][0]
    assert "pw-ann" not in json.dumps(store.read(DEVICE, "accounts"))


def test_forgetting_an_account_takes_it_out_of_every_module_and_names_them(unlocked):
    store = DesiredStateStore()
    with_accounts(store, "ann", "bob")
    store.set_enabled_accounts(DEVICE, "samba", ["ann", "bob"])
    store.set_enabled_accounts(DEVICE, "vscode", ["ann"])
    store.set_enabled_accounts(DEVICE, "codeg", ["bob"])

    modules = store.forget_account(DEVICE, "ann")

    assert sorted(modules) == ["samba", "vscode"]
    assert store.enabled_accounts(DEVICE, "samba") == ["bob"]
    assert store.enabled_accounts(DEVICE, "vscode") == []
    assert store.account_secret(DEVICE, "vscode", "ann", "token_sealed") == ""
    assert "ann" not in json.dumps(store.read(DEVICE, "vscode"))


def test_the_containers_run_settings_name_an_account_and_its_login_on_windows(
    unlocked,
):
    store = DesiredStateStore()
    from neutrino_hub.modules.credentials.vault import SecretVault

    login = SecretVault().add(
        kind="login", name="lab", secret={"username": "lab", "password": "pw-lab"}
    )
    DeviceAccountStore(store).add(
        DEVICE, DeviceAccount(account="lab", login_id=login.id)
    )
    stored = {
        "containers": [],
        "machine": {"account": "lab", "cpus": 4, "memory_gib": 8, "disk_gib": 120},
    }

    windows = desired_state_module.podman_agent_config(
        stored, WINDOWS, store.available_accounts(DEVICE)
    )
    darwin = desired_state_module.podman_agent_config(
        stored, {"os": "darwin", "arch": "arm64"}, store.available_accounts(DEVICE)
    )
    linux = desired_state_module.podman_agent_config(
        stored, PLATFORM, store.available_accounts(DEVICE)
    )

    assert windows["machine"] == {
        "account": "lab",
        "cpus": 4,
        "memory_gib": 8,
        "disk_gib": 120,
        "password": "pw-lab",
    }
    assert darwin["machine"] == {
        "account": "lab",
        "cpus": 4,
        "memory_gib": 8,
        "disk_gib": 120,
    }
    assert "machine" not in linux


def test_the_seat_password_is_generated_once_and_reset_on_demand(unlocked):
    store = DesiredStateStore()

    assert store.ensure_seat_password(DEVICE) is True
    first = store.seat_password(DEVICE)
    assert store.ensure_seat_password(DEVICE) is False
    store.reset_seat_password(DEVICE)

    assert first and store.seat_password(DEVICE) != first
    sealed = store.read(DEVICE, "rdp")
    assert "seat_password" not in json.dumps(sealed) or first not in json.dumps(sealed)


def test_forgetting_a_device_and_the_orphans_removes_their_directories(config):
    store = DesiredStateStore()
    store.set_want(DEVICE, "gitea", "running")
    store.set_want("device-two", "gitea", "running")

    store.forget(DEVICE)
    orphans = store.forget_orphans({"device-two"})

    assert not (config / "devices" / DEVICE).exists()
    assert orphans == []
    assert (config / "devices" / "device-two").is_dir()
    assert store.forget_orphans(set()) == ["device-two"]
    assert not (config / "devices" / "device-two").exists()
