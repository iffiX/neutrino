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
# The section while the setting is off: the pinned cc-switch version beside it.
AI_TOOLS_OFF = {"is_enabled": False, "cc_switch_version": "5.10.4"}


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
    assert set(desired["modules"]) == {"gitea", "terminal", "remote_desktop"}


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

    assert set(desired) == {"modules", "desktop", "urls", "ai_tools"}
    assert desired["ai_tools"] == AI_TOOLS_OFF
    assert set(desired["modules"]) == {"samba", "gitea", "terminal", "remote_desktop"}
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


def test_compose_names_the_hubs_addresses_under_the_hash(config):
    """The agent keeps the set it is handed and reconnects by it, so a set
    that moved is a state that moved."""
    store = DesiredStateStore()
    urls = ["https://192.168.100.1:8443", "https://100.64.0.1:8443"]

    desired, digest = store.compose(DEVICE, PLATFORM, urls=urls)
    moved = store.compose(DEVICE, PLATFORM, urls=urls[:1])

    assert desired["urls"] == urls
    assert set(desired) == {"modules", "desktop", "urls", "ai_tools"}
    assert desired["ai_tools"] == AI_TOOLS_OFF
    assert digest == state_hash(desired)
    assert moved[0]["urls"] == urls[:1]
    assert moved[1] != digest


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


# --- the machine's AI tools ---

AI_GATEWAY = {"gateway_url": "http://192.168.100.1:8317", "gateway_key": "dev-key"}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}


def ai_tools_box(monkeypatch, *, models=("gw-model", "other")):
    """Three modules naming accounts, the gateway reachable with a key."""
    from neutrino_hub.modules.devices import desired_state

    monkeypatch.setattr(desired_state, "device_gateway", lambda key, hub: AI_GATEWAY)
    monkeypatch.setattr(
        desired_state, "_login_password", lambda login_id: f"pw-{login_id}"
    )
    store = DesiredStateStore()
    store.set_want(DEVICE, "vscode", "running")
    store.set_want(DEVICE, "cloudcli", "running")
    store.set_want(DEVICE, "code_server", "absent")
    store.write(
        DEVICE,
        "vscode",
        {"instances": [{"account": "bob", "port": 8001, "login_id": "login-bob"}]},
    )
    store.write(
        DEVICE,
        "cloudcli",
        {
            "instances": [
                {"account": "alice", "port": 3001, "login_id": "login-alice"},
                {"account": "bob", "port": 3002, "login_id": "login-other"},
            ]
        },
    )
    store.write(DEVICE, "code_server", {"instances": [{"account": "carol", "port": 9}]})
    return store, list(models)


def test_the_ai_tools_accounts_are_every_instance_of_a_module_not_withdrawn(
    config,
    monkeypatch,
):
    store, _ = ai_tools_box(monkeypatch)

    assert store.ai_tool_accounts(DEVICE) == [
        ("alice", "login-alice", ["cloudcli"]),
        ("bob", "login-bob", ["vscode", "cloudcli"]),
    ]


def test_a_setting_that_is_on_sends_the_gateway_the_key_and_the_accounts(
    config, monkeypatch
):
    store, models = ai_tools_box(monkeypatch)
    store.set_ai_tools(
        DEVICE,
        is_enabled=True,
        tool_configs={
            "claude": {"opus": "big", "nonsense": "x"},
            "codex": {"model_reasoning_effort": "extreme"},
            "lisp": {"model": "y"},
        },
    )

    desired, _ = store.compose(DEVICE, PLATFORM, ai_models=models)

    assert desired["ai_tools"] == {
        "is_enabled": True,
        "base_url": "http://192.168.100.1:8317",
        "api_key": "dev-key",
        "tool_configs": {
            "claude": {
                "default": "gw-model",
                "opus": "big",
                "sonnet": "gw-model",
                "haiku": "gw-model",
            },
            "codex": {"model": "", "model_reasoning_effort": ""},
            "gemini": {"model": ""},
        },
        "accounts": [{"account": "alice"}, {"account": "bob"}],
        "cc_switch_version": "5.10.4",
    }


def test_a_windows_machine_is_sent_each_accounts_login_password(config, monkeypatch):
    store, models = ai_tools_box(monkeypatch)
    store.set_ai_tools(DEVICE, is_enabled=True)

    desired, _ = store.compose(DEVICE, WINDOWS, ai_models=models)

    assert desired["ai_tools"]["accounts"] == [
        {"account": "alice", "password": "pw-login-alice"},
        {"account": "bob", "password": "pw-login-bob"},
    ]


def test_the_setting_is_sent_off_while_it_is_off_or_the_gateway_serves_nothing(
    config,
    monkeypatch,
):
    from neutrino_hub.modules.devices import desired_state

    store, models = ai_tools_box(monkeypatch)
    off, _ = store.compose(DEVICE, PLATFORM, ai_models=models)
    store.set_ai_tools(DEVICE, is_enabled=True)
    serving, served_hash = store.compose(DEVICE, PLATFORM, ai_models=models)
    stopped, stopped_hash = store.compose(DEVICE, PLATFORM, ai_models=[])
    monkeypatch.setattr(
        desired_state,
        "device_gateway",
        lambda key, hub: {"gateway_url": "", "gateway_key": ""},
    )
    keyless, _ = store.compose(DEVICE, PLATFORM, ai_models=models)

    assert off["ai_tools"] == AI_TOOLS_OFF
    assert serving["ai_tools"]["is_enabled"] is True
    assert stopped["ai_tools"] == AI_TOOLS_OFF
    assert keyless["ai_tools"] == AI_TOOLS_OFF
    assert served_hash != stopped_hash
    assert store.ai_tools(DEVICE)["is_enabled"] is True


# --- the retry marks ---


@pytest.mark.parametrize("name", ["samba", "gitea", "terminal"])
def test_the_section_checked_on_an_apply_is_the_one_the_state_carries(config, name):
    """One step composes a module's section for the push and for the check."""
    store = DesiredStateStore()
    store.set_want(DEVICE, name, "running")
    store.write(DEVICE, name, {"listen_port": 3000} if name == "gitea" else {})
    subnets = ["192.168.10.0/24"]

    desired, _ = store.compose(
        DEVICE, PLATFORM, address="192.168.10.7", allowed_subnets=subnets
    )
    checked = store.agent_config(
        DEVICE,
        name,
        store.read(DEVICE, name),
        PLATFORM,
        address="192.168.10.7",
        allowed_subnets=subnets,
    )

    assert checked == desired["modules"][name]["config"]


def test_a_retry_mark_rides_its_module_entry_and_moves_the_hash(config):
    store = DesiredStateStore()
    store.set_want(DEVICE, "samba", "running")
    store.write(DEVICE, "samba", {"shares": [], "users": []})

    plain, plain_hash = store.compose(DEVICE, PLATFORM)
    marked, marked_hash = store.compose(
        DEVICE, PLATFORM, retry_marks={"samba": "a1b2", "gitea": "c3d4"}
    )
    again, again_hash = store.compose(DEVICE, PLATFORM, retry_marks={"samba": "e5f6"})

    assert "retry_mark" not in plain["modules"]["samba"]
    assert marked["modules"]["samba"]["retry_mark"] == "a1b2"
    assert marked["modules"]["samba"]["config"] == plain["modules"]["samba"]["config"]
    assert "gitea" not in marked["modules"]
    assert len({plain_hash, marked_hash, again_hash}) == 3


def test_the_ai_tools_mark_rides_the_section_on_and_off(config, monkeypatch):
    """Off, the mark is what retries a switch back that could not run."""
    store, models = ai_tools_box(monkeypatch)
    marks = {"ai_tools": "a1b2"}

    plain, plain_hash = store.compose(DEVICE, PLATFORM, ai_models=models)
    off, off_hash = store.compose(DEVICE, PLATFORM, ai_models=models, retry_marks=marks)
    store.set_ai_tools(DEVICE, is_enabled=True)
    on, _ = store.compose(DEVICE, PLATFORM, ai_models=models, retry_marks=marks)

    assert plain["ai_tools"] == AI_TOOLS_OFF
    assert off["ai_tools"] == {**AI_TOOLS_OFF, "retry_mark": "a1b2"}
    assert off_hash != plain_hash
    assert on["ai_tools"]["retry_mark"] == "a1b2"


def test_the_retry_marks_keep_one_per_module_and_go_with_the_device(tmp_path):
    from neutrino_hub.modules.devices.retry_marks import DeviceRetryMarks

    marks = DeviceRetryMarks(path=tmp_path / "marks.json")
    first = marks.mark(DEVICE, "code_server")
    second = marks.mark(DEVICE, "code_server")
    marks.mark("other", "samba")

    assert first != second
    assert DeviceRetryMarks(path=tmp_path / "marks.json").marks(DEVICE) == {
        "code_server": second
    }
    marks.forget(DEVICE)
    assert marks.marks(DEVICE) == {}
    assert set(marks.marks("other")) == {"samba"}
