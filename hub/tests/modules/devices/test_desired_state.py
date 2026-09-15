"""One desired state per device under config/, composed under one hash.

What these pin: the directory a device id names, the module files and the
switches beside them, a hash that moves only with the state, the composed
shape the agent applies, the secrets a device's Gitea is handed once and
kept, the fence and address the hub folds in, and the sweep that removes a
directory no stored device names.
"""

import json

import pytest

from neutrino_hub.modules.devices import desired_state as desired_state_module
from neutrino_hub.modules.devices.desired_state import DesiredStateStore, state_hash

DEVICE = "device-one"
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        desired_state_module,
        "resolved_modules",
        lambda platform: {
            "samba": {
                "kind": "system_package",
                "entry": {
                    "packages": ["samba"],
                    "verify": "smbd -V",
                    "uninstall": {"packages": ["samba"], "is_data_kept": True},
                },
            },
            "gitea": {"kind": "binary", "entry": None},
        },
    )
    return tmp_path


def test_module_files_land_under_the_devices_directory(config):
    store = DesiredStateStore()

    store.write(DEVICE, "samba", {"shares": [], "users": ["ann"]})

    path = config / f"devices/{DEVICE}/samba.json"
    assert json.loads(path.read_text())["users"] == ["ann"]
    assert store.read(DEVICE, "samba") == {"shares": [], "users": ["ann"]}
    assert store.read(DEVICE, "gitea") == {}


def test_every_hosted_module_has_a_switch_off_by_default(config):
    store = DesiredStateStore()

    assert store.modules(DEVICE) == {
        "zfs": {"is_enabled": False},
        "samba": {"is_enabled": False},
        "gitea": {"is_enabled": False},
        "podman": {"is_enabled": False},
    }

    store.set_enabled(DEVICE, "samba", True)

    assert store.is_enabled(DEVICE, "samba") is True
    assert store.is_enabled(DEVICE, "gitea") is False
    stored = json.loads((config / f"devices/{DEVICE}/modules.json").read_text())
    assert stored["modules"]["samba"] == {"is_enabled": True}


def test_the_hash_is_stable_and_moves_with_the_state():
    assert state_hash({"a": 1, "b": [2]}) == state_hash({"b": [2], "a": 1})
    assert state_hash({"a": 1}) != state_hash({"a": 2})
    assert len(state_hash({})) == 64


def test_compose_is_the_modules_switched_on_with_their_recipes_and_the_desktop(
    config,
):
    """A module switched on is wanted running, with its configuration and
    the recipes resolved for the platform; one switched off is not
    mentioned, so the agent leaves it as it is."""
    store = DesiredStateStore()
    store.set_enabled(DEVICE, "samba", True)
    store.set_enabled(DEVICE, "gitea", True)
    store.write(
        DEVICE, "samba", {"shares": [{"name": "s", "path": "/srv"}], "users": []}
    )
    store.write(DEVICE, "gitea", {"listen_port": 3100, "root_url": ""})
    store.write(DEVICE, "podman", {"containers": []})

    desired, digest = store.compose(
        DEVICE, PLATFORM, address="192.168.100.7", allowed_subnets=["192.168.100.0/24"]
    )

    assert set(desired) == {"modules", "desktop"}
    assert set(desired["modules"]) == {"samba", "gitea"}
    samba = desired["modules"]["samba"]
    assert set(samba) == {"want", "config", "install", "uninstall"}
    assert samba["want"] == "running"
    assert samba["config"]["shares"] == [{"name": "s", "path": "/srv"}]
    assert samba["config"]["allowed_subnets"] == ["192.168.100.0/24"]
    assert samba["install"] == {
        "kind": "system_package",
        "packages": ["samba"],
        "verify": "smbd -V",
    }
    assert samba["uninstall"] == {"packages": ["samba"], "is_data_kept": True}
    gitea = desired["modules"]["gitea"]
    assert gitea["want"] == "running"
    assert gitea["config"]["listen_port"] == 3100
    assert gitea["config"]["address"] == "192.168.100.7"
    assert set(gitea["config"]["secrets"]) == {
        "SECRET_KEY",
        "INTERNAL_TOKEN",
        "JWT_SECRET",
        "LFS_JWT_SECRET",
    }
    assert (gitea["install"], gitea["uninstall"]) == ({}, {})
    assert desired["desktop"] == {"seat_password": ""}
    assert digest == state_hash(desired)


def test_compose_is_the_same_twice_and_moves_with_a_write(config):
    store = DesiredStateStore()

    first = store.compose(DEVICE, PLATFORM)
    again = store.compose(DEVICE, PLATFORM)
    store.set_enabled(DEVICE, "podman", True)
    changed = store.compose(DEVICE, PLATFORM)

    assert first[1] == again[1]
    assert changed[1] != first[1]


def test_gitea_secrets_are_generated_once_and_kept(config):
    store = DesiredStateStore()

    first = store.gitea_secrets(DEVICE)
    again = store.gitea_secrets(DEVICE)

    assert first == again
    assert all(len(value) >= 40 for value in first.values())
    path = config / f"devices/{DEVICE}/gitea_secrets.json"
    assert json.loads(path.read_text()) == first
    assert store.gitea_secrets("another-device") != first


def test_the_seat_password_is_empty_until_rdp_json_exists(config):
    """What ``rdp.json`` seals, and what a locked vault leaves of it, is
    ``test_rdp_passwords.py``'s case."""
    store = DesiredStateStore()

    assert store.seat_password(DEVICE) == ""


def test_forget_removes_the_devices_directory(config):
    store = DesiredStateStore()
    store.set_enabled(DEVICE, "samba", True)

    store.forget(DEVICE)

    assert not (config / f"devices/{DEVICE}").exists()
    assert store.modules(DEVICE)["samba"] == {"is_enabled": False}


def test_the_sweep_removes_a_directory_no_stored_id_names_and_keeps_the_rest(
    config,
):
    store = DesiredStateStore()
    store.set_enabled(DEVICE, "samba", True)
    store.set_enabled("aa-bb-cc-dd-ee-ff", "samba", True)
    (config / "devices" / "packages").mkdir()
    (config / "devices" / "devices.json").write_text("{}")

    removed = store.forget_orphans({DEVICE})

    assert removed == ["aa-bb-cc-dd-ee-ff"]
    assert (config / f"devices/{DEVICE}/modules.json").exists()
    assert (config / "devices" / "packages").is_dir()
    assert (config / "devices" / "devices.json").exists()
    assert not (config / "devices" / "aa-bb-cc-dd-ee-ff").exists()
    assert store.forget_orphans({DEVICE}) == []
