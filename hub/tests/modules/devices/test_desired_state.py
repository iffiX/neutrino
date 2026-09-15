"""One desired state per device under config/, composed under one hash.

What these pin: the directory a device id names, the module files and the
wants beside them, a module the file does not name being mentioned nowhere,
a module the machine settled keeping its want and leaving the state,
a hash that moves only with the state, the composed shape the agent
applies, the secrets a device's Gitea is handed once and kept, the fence
and address the hub folds in, and the sweep that removes a directory no
stored device names.
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


def test_a_module_is_named_only_once_a_want_is_written_for_it(config):
    store = DesiredStateStore()

    assert store.modules(DEVICE) == {}
    assert store.want_of(DEVICE, "samba") == ""

    store.set_want(DEVICE, "samba", "running")
    store.set_want(DEVICE, "podman", "installed")

    assert store.modules(DEVICE) == {
        "samba": {"want": "running", "is_settled": False},
        "podman": {"want": "installed", "is_settled": False},
    }
    assert store.want_of(DEVICE, "samba") == "running"
    assert store.want_of(DEVICE, "gitea") == ""
    stored = json.loads((config / f"devices/{DEVICE}/modules.json").read_text())
    assert stored["modules"]["samba"] == {"want": "running", "is_settled": False}


def test_a_want_outside_the_four_is_refused_and_one_on_disk_is_skipped(config):
    store = DesiredStateStore()

    with pytest.raises(ValueError):
        store.set_want(DEVICE, "samba", "installing")

    path = config / f"devices/{DEVICE}/modules.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"modules": {"samba": {"want": "nonsense"}}}))
    assert store.modules(DEVICE) == {}


def test_settling_a_module_keeps_its_want_and_leaves_it_out_of_the_state(config):
    """What an uninstall the machine confirmed leaves behind: the row still
    says what was asked, and the state names the module no more, so nothing
    installed on that machine afterwards is taken off again."""
    store = DesiredStateStore()
    store.set_want(DEVICE, "samba", "absent")
    store.set_want(DEVICE, "gitea", "running")

    assert store.settle_want(DEVICE, "samba") is True
    assert store.settle_want(DEVICE, "samba") is False
    assert store.settle_want(DEVICE, "podman") is False

    assert store.want_of(DEVICE, "samba") == "absent"
    assert store.modules(DEVICE) == {
        "samba": {"want": "absent", "is_settled": True},
        "gitea": {"want": "running", "is_settled": False},
    }
    desired, _ = store.compose(DEVICE, PLATFORM)
    assert set(desired["modules"]) == {"gitea"}


def test_a_press_asks_again_for_a_module_the_machine_had_settled(config):
    store = DesiredStateStore()
    store.set_want(DEVICE, "samba", "absent")
    store.settle_want(DEVICE, "samba")

    store.set_want(DEVICE, "samba", "installed")

    assert store.modules(DEVICE) == {
        "samba": {"want": "installed", "is_settled": False}
    }
    desired, _ = store.compose(DEVICE, PLATFORM)
    assert desired["modules"]["samba"]["want"] == "installed"


def test_the_hash_is_stable_and_moves_with_the_state():
    assert state_hash({"a": 1, "b": [2]}) == state_hash({"b": [2], "a": 1})
    assert state_hash({"a": 1}) != state_hash({"a": 2})
    assert len(state_hash({})) == 64


def test_compose_is_every_named_module_with_its_want_and_recipes_and_the_desktop(
    config,
):
    """A named module is sent with its want, its configuration and the
    recipes resolved for the platform; one the file does not name is not
    mentioned, so the agent leaves it as it is."""
    store = DesiredStateStore()
    store.set_want(DEVICE, "samba", "running")
    store.set_want(DEVICE, "gitea", "absent")
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
    assert gitea["want"] == "absent"
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
    store.set_want(DEVICE, "podman", "installed")
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
    store.set_want(DEVICE, "samba", "running")

    store.forget(DEVICE)

    assert not (config / f"devices/{DEVICE}").exists()
    assert store.modules(DEVICE) == {}


def test_the_sweep_removes_a_directory_no_stored_id_names_and_keeps_the_rest(
    config,
):
    store = DesiredStateStore()
    store.set_want(DEVICE, "samba", "running")
    store.set_want("aa-bb-cc-dd-ee-ff", "samba", "running")
    (config / "devices" / "packages").mkdir()
    (config / "devices" / "devices.json").write_text("{}")

    removed = store.forget_orphans({DEVICE})

    assert removed == ["aa-bb-cc-dd-ee-ff"]
    assert (config / f"devices/{DEVICE}/modules.json").exists()
    assert (config / "devices" / "packages").is_dir()
    assert (config / "devices" / "devices.json").exists()
    assert not (config / "devices" / "aa-bb-cc-dd-ee-ff").exists()
    assert store.forget_orphans({DEVICE}) == []
