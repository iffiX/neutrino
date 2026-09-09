"""One desired state per device under config/, composed under one hash.

What these pin: the directory a device key becomes, the module files and
the switches beside them, a hash that moves only with the state, the
composed shape the agent applies, the secrets a device's Gitea is handed
once and kept, and the fence and address the hub folds in.
"""

import json

import pytest

from neutrino_hub.modules.devices import desired_state as desired_state_module
from neutrino_hub.modules.devices.desired_state import (
    DesiredStateStore,
    device_dir,
    state_hash,
)

MAC = "AA:BB:cc:dd:ee:ff"
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        desired_state_module,
        "resolved_modules",
        lambda platform: {"samba": {"kind": "system_package", "platform": platform}},
    )
    return tmp_path


def test_a_device_key_becomes_a_directory_name():
    assert device_dir(MAC) == "aa-bb-cc-dd-ee-ff"
    assert device_dir("id:abc123") == "id-abc123"


def test_module_files_land_under_the_devices_directory(config):
    store = DesiredStateStore()

    store.write(MAC, "samba", {"shares": [], "users": ["ann"]})

    path = config / "devices/aa-bb-cc-dd-ee-ff/samba.json"
    assert json.loads(path.read_text())["users"] == ["ann"]
    assert store.read(MAC, "samba") == {"shares": [], "users": ["ann"]}
    assert store.read(MAC, "gitea") == {}


def test_every_hosted_module_has_a_switch_off_by_default(config):
    store = DesiredStateStore()

    assert store.modules(MAC) == {
        "zfs": {"is_enabled": False},
        "samba": {"is_enabled": False},
        "gitea": {"is_enabled": False},
        "podman": {"is_enabled": False},
    }

    store.set_enabled(MAC, "samba", True)

    assert store.is_enabled(MAC, "samba") is True
    assert store.is_enabled(MAC, "gitea") is False
    stored = json.loads((config / "devices/aa-bb-cc-dd-ee-ff/modules.json").read_text())
    assert stored["modules"]["samba"] == {"is_enabled": True}


def test_the_hash_is_stable_and_moves_with_the_state():
    assert state_hash({"a": 1, "b": [2]}) == state_hash({"b": [2], "a": 1})
    assert state_hash({"a": 1}) != state_hash({"a": 2})
    assert len(state_hash({})) == 64


def test_compose_carries_every_module_the_rdp_seat_and_the_catalog(config):
    store = DesiredStateStore()
    store.set_enabled(MAC, "samba", True)
    store.write(MAC, "samba", {"shares": [{"name": "s", "path": "/srv"}], "users": []})
    store.write(MAC, "gitea", {"listen_port": 3100, "root_url": ""})

    desired, digest = store.compose(
        MAC, PLATFORM, address="192.168.100.7", allowed_subnets=["192.168.100.0/24"]
    )

    assert set(desired) == {"modules", "rdp", "catalog"}
    assert set(desired["modules"]) == {"zfs", "samba", "gitea", "podman"}
    samba = desired["modules"]["samba"]
    assert samba["is_enabled"] is True
    assert samba["config"]["shares"] == [{"name": "s", "path": "/srv"}]
    assert samba["config"]["allowed_subnets"] == ["192.168.100.0/24"]
    gitea = desired["modules"]["gitea"]
    assert gitea["is_enabled"] is False
    assert gitea["config"]["listen_port"] == 3100
    assert gitea["config"]["address"] == "192.168.100.7"
    assert set(gitea["config"]["secrets"]) == {
        "SECRET_KEY",
        "INTERNAL_TOKEN",
        "JWT_SECRET",
        "LFS_JWT_SECRET",
    }
    assert desired["rdp"] == {"seat_password": ""}
    assert desired["catalog"]["modules"]["samba"]["platform"] == PLATFORM
    assert digest == state_hash(desired)


def test_compose_is_the_same_twice_and_moves_with_a_write(config):
    store = DesiredStateStore()

    first = store.compose(MAC, PLATFORM)
    again = store.compose(MAC, PLATFORM)
    store.set_enabled(MAC, "podman", True)
    changed = store.compose(MAC, PLATFORM)

    assert first[1] == again[1]
    assert changed[1] != first[1]


def test_gitea_secrets_are_generated_once_and_kept(config):
    store = DesiredStateStore()

    first = store.gitea_secrets(MAC)
    again = store.gitea_secrets(MAC)

    assert first == again
    assert all(len(value) >= 40 for value in first.values())
    path = config / "devices/aa-bb-cc-dd-ee-ff/gitea_secrets.json"
    assert json.loads(path.read_text()) == first
    assert store.gitea_secrets("11:22:33:44:55:66") != first


def test_the_seat_password_is_empty_until_rdp_json_exists(config):
    store = DesiredStateStore()
    assert store.seat_password(MAC) == ""

    (config / "devices/aa-bb-cc-dd-ee-ff").mkdir(parents=True)
    (config / "devices/aa-bb-cc-dd-ee-ff/rdp.json").write_text(
        json.dumps({"seat_password_sealed": "sealed"})
    )

    assert store.seat_password(MAC) == "sealed"


def test_forget_removes_the_devices_directory(config):
    store = DesiredStateStore()
    store.set_enabled(MAC, "samba", True)

    store.forget(MAC)

    assert not (config / "devices/aa-bb-cc-dd-ee-ff").exists()
    assert store.modules(MAC)["samba"] == {"is_enabled": False}
