"""One desired state per device under config/, composed under one hash.

What these pin: the directory a device id names, the module files and the
wants beside them, a module the file does not name being mentioned nowhere,
a module the machine settled keeping its want and leaving the state,
a hash that moves only with the state, the composed shape the agent
applies, the secrets a device's Gitea is handed once and kept, the fence
and address the hub folds in, the sweep that removes a directory no
stored device names, and the Containers Run settings: sent to Windows and
macOS alone, with the login's password on Windows and never the login's
id, and a Linux entry byte for byte as before.
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
            "cloudcli": {
                "kind": "cloudcli",
                "entry": {
                    "components": [
                        {
                            "name": "node",
                            "url": "https://nodejs.org/dist/node.tar.gz",
                            "cn_url": "https://mirror.example/node.tar.gz",
                            "sha256": "b" * 64,
                            "package_kind": "tar",
                            "directory": "node",
                        }
                    ],
                    "verify": "node --version",
                    "uninstall": {"packages": [], "is_data_kept": True},
                },
                "components": [
                    {
                        "name": "node",
                        "package_kind": "tar",
                        "directory": "node",
                        "sha256": "b" * 64,
                    }
                ],
            },
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


def test_a_recipe_carries_each_component_without_where_it_comes_from(config):
    """The agent opens ``package {module, component}`` for each and is told
    the kind, the directory and the digest; the urls stay the hub's."""
    store = DesiredStateStore()
    store.set_want(DEVICE, "cloudcli", "running")
    store.write(DEVICE, "cloudcli", {"instances": []})

    desired, _ = store.compose(DEVICE, PLATFORM)

    assert desired["modules"]["cloudcli"]["install"] == {
        "kind": "cloudcli",
        "verify": "node --version",
        "components": [
            {
                "name": "node",
                "package_kind": "tar",
                "directory": "node",
                "sha256": "b" * 64,
            }
        ],
    }
    assert "url" not in json.dumps(desired["modules"]["cloudcli"]["install"])


@pytest.fixture
def shipped(monkeypatch, tmp_path):
    """A config directory, with the shipped manifests resolved as they are."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


# Containers' Linux recipe as the hub sent it before its manifest named
# branches of its own, in the canonical form the state hash is taken over.
PODMAN_LINUX_RECIPE = (
    '{"install":{"kind":"system_package","packages":["podman","podman-docker"],'
    '"verify":"podman --version"},"uninstall":{"is_data_kept":true,'
    '"packages":["podman","podman-docker"],"post_uninstall":[]}}'
)


@pytest.mark.parametrize(
    "platform",
    [
        {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"},
        {"os": "linux", "family": "rhel", "arch": "arm64", "version": "2.34"},
        {"os": "linux", "family": "arch", "arch": "amd64", "version": "2.40"},
    ],
)
def test_the_linux_containers_recipe_is_byte_for_byte_as_before(shipped, platform):
    store = DesiredStateStore()
    store.set_want(DEVICE, "podman", "running")

    desired, _ = store.compose(DEVICE, platform)

    podman = desired["modules"]["podman"]
    recipe = {"install": podman["install"], "uninstall": podman["uninstall"]}
    assert json.dumps(recipe, sort_keys=True, separators=(",", ":")) == (
        PODMAN_LINUX_RECIPE
    )


@pytest.mark.parametrize(
    ("platform", "floor", "verify", "components"),
    [
        (
            {"os": "windows", "family": "", "arch": "amd64", "version": "26100"},
            "19041",
            '"C:\\Program Files\\Podman\\podman.exe" --version',
            [("wsl", "msi"), ("installer", "msi"), ("image", "tar_zst")],
        ),
        (
            {"os": "darwin", "family": "", "arch": "arm64", "version": "15.3"},
            "13",
            "/opt/podman/bin/podman --version",
            [("installer", "pkg"), ("image", "raw_zst")],
        ),
    ],
)
def test_an_off_linux_containers_recipe_has_the_branchs_kind_and_no_identity(
    shipped, platform, floor, verify, components
):
    """The recipe's kind is the branch's own, and the branch's installer,
    version, source, license and source pointer stay on the hub."""
    store = DesiredStateStore()
    store.set_want(DEVICE, "podman", "running")
    store.set_want(DEVICE, "samba", "running")

    desired, _ = store.compose(DEVICE, platform)

    install = desired["modules"]["podman"]["install"]
    assert set(install) == {"kind", "min_version", "verify", "components"}
    assert (install["kind"], install["min_version"], install["verify"]) == (
        "podman_machine",
        floor,
        verify,
    )
    assert [
        (component["name"], component["package_kind"])
        for component in install["components"]
    ] == components
    assert all(
        set(component) == {"name", "package_kind", "directory", "sha256"}
        for component in install["components"]
    )
    assert desired["modules"]["podman"]["uninstall"] == {
        "packages": [],
        "post_uninstall": [],
        "is_data_kept": True,
    }
    assert desired["modules"]["samba"]["install"] == {"kind": "system_package"}


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

AI_GATEWAY = {"gateway_url": "http://127.0.0.1:8317", "gateway_key": "dev-key"}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}


def ai_tools_box(monkeypatch, *, models=("gw-model", "other")):
    """Three modules naming accounts, the gateway reachable with a key."""
    from neutrino_hub.modules.devices import desired_state

    monkeypatch.setattr(
        desired_state, "device_gateway", lambda key, is_hub_machine=False: AI_GATEWAY
    )
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
    store.set_want(DEVICE, "codeg", "running")
    store.write(
        DEVICE,
        "codeg",
        {"instances": [{"account": "bob", "port": 3101, "login_id": "login-third"}]},
    )
    return store, list(models)


def test_the_ai_tools_accounts_are_every_instance_of_a_module_not_withdrawn(
    config,
    monkeypatch,
):
    store, _ = ai_tools_box(monkeypatch)

    assert store.ai_tool_accounts(DEVICE) == [
        ("alice", "login-alice", ["cloudcli"]),
        ("bob", "login-bob", ["vscode", "cloudcli", "codeg"]),
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
        "is_forwarded": True,
        "base_url": "http://127.0.0.1:8317",
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


def test_the_hubs_own_machine_is_composed_with_the_gateways_own_address(
    config, monkeypatch
):
    """A managed machine is sent its agent's forward to open; the hub's own
    machine, the gateway's own port and no forward."""
    from neutrino_hub.modules.devices import desired_state

    store, models = ai_tools_box(monkeypatch)
    store.set_ai_tools(DEVICE, is_enabled=True)
    asked: list = []

    def gateway(key, is_hub_machine=False):
        asked.append(is_hub_machine)
        port = 9417 if is_hub_machine else 8317
        return {"gateway_url": f"http://127.0.0.1:{port}", "gateway_key": "k"}

    monkeypatch.setattr(desired_state, "device_gateway", gateway)

    managed, _ = store.compose(DEVICE, PLATFORM, ai_models=models)
    own, _ = store.compose(DEVICE, PLATFORM, is_hub_machine=True, ai_models=models)

    assert asked == [False, True]
    assert managed["ai_tools"]["base_url"] == "http://127.0.0.1:8317"
    assert managed["ai_tools"]["is_forwarded"] is True
    assert own["ai_tools"]["base_url"] == "http://127.0.0.1:9417"
    assert own["ai_tools"]["is_forwarded"] is False


def test_a_composed_state_is_the_channels_agent_state(config, monkeypatch):
    """Every field the composer writes is one the pinned model names."""
    from neutrino_hub.web.models import ChannelAgentState

    store, models = ai_tools_box(monkeypatch)
    store.set_ai_tools(DEVICE, is_enabled=True)
    on, digest = store.compose(DEVICE, WINDOWS, ai_models=models)
    off, _ = store.compose(DEVICE, PLATFORM, ai_models=[])

    for desired in (on, off):
        held = ChannelAgentState.model_validate({"hash": digest, **desired})
        assert held.ai_tools.model_dump(exclude_unset=True) == desired["ai_tools"]


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
        lambda key, is_hub_machine=False: {"gateway_url": "", "gateway_key": ""},
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


# --- the compositions the description table drives, pinned to the code before it ---

# The platform tuples the fixtures were captured under.
PINNED_PLATFORMS = {
    "linux": {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"},
    "windows": {"os": "windows", "family": "", "arch": "amd64", "version": "26100"},
    "darwin": {"os": "darwin", "family": "", "arch": "arm64", "version": "15.3.1"},
}
# Each module's file as it was handed to the composition: seals stand in as
# ``{"v": ...}`` and open to ``<v>:<aad>``, a login's password to ``pw-<id>``.
PINNED_STORED = {
    "vscode": {
        "terms_accepted_at": "2026-10-05T08:00:00+00:00",
        "instances": [
            {
                "account": "alice",
                "port": 8000,
                "login_id": "l-a",
                "token_sealed": {"v": "tok-a"},
            },
            {
                "account": "bob",
                "port": 8001,
                "login_id": "",
                "token_sealed": {"v": "tok-b"},
            },
            {"account": "carol", "port": 8002},
            "junk",
        ],
    },
    "cloudcli": {
        "instances": [
            {
                "account": "alice",
                "port": 3001,
                "login_id": "l-a",
                "web_password_sealed": {"v": "pw-a"},
                "token_secret_sealed": {"v": "sec-a"},
            },
            {
                "account": "bob",
                "port": 3002,
                "login_id": "l-b",
                "token_secret_sealed": {},
            },
            {"account": "carol", "port": 3003},
            7,
        ]
    },
    "code_server": {
        "instances": [
            {"account": "alice", "port": 8443, "secret_sealed": {"v": "sec-a"}},
            {"account": "bob", "port": 8444, "login_id": "l-b"},
            None,
        ]
    },
}
# What ``vscode_agent_config``, ``code_server_agent_config`` and
# ``cloudcli_agent_config`` answered for those files before the table drove
# one composition, keyed ``<module>/<platform>[/<edition>]``.
PINNED_CONFIGS = {
    "cloudcli/darwin/cn": {
        "instances": [
            {
                "account": "alice",
                "port": 3001,
                "token_secret": "sec-a:device_cloudcli:token_secret",  # scan: allow
                "web_password": "pw-a:device_cloudcli:web_password",  # scan: allow
            },
            {"account": "bob", "port": 3002, "token_secret": "", "web_password": ""},
            {"account": "carol", "port": 3003, "token_secret": "", "web_password": ""},
        ],
        "npm_environment": {
            "npm_config_better_sqlite3_binary_host": "https://registry.npmmirror.com/-/binary/better-sqlite3"
        },
        "npm_registry": "https://registry.npmmirror.com",
    },
    "cloudcli/darwin/intl": {
        "instances": [
            {
                "account": "alice",
                "port": 3001,
                "token_secret": "sec-a:device_cloudcli:token_secret",
                "web_password": "pw-a:device_cloudcli:web_password",
            },
            {"account": "bob", "port": 3002, "token_secret": "", "web_password": ""},
            {"account": "carol", "port": 3003, "token_secret": "", "web_password": ""},
        ],
        "npm_environment": {},
        "npm_registry": "https://registry.npmjs.org",
    },
    "cloudcli/linux/cn": {
        "instances": [
            {
                "account": "alice",
                "port": 3001,
                "token_secret": "sec-a:device_cloudcli:token_secret",
                "web_password": "pw-a:device_cloudcli:web_password",
            },
            {"account": "bob", "port": 3002, "token_secret": "", "web_password": ""},
            {"account": "carol", "port": 3003, "token_secret": "", "web_password": ""},
        ],
        "npm_environment": {
            "npm_config_better_sqlite3_binary_host": "https://registry.npmmirror.com/-/binary/better-sqlite3"
        },
        "npm_registry": "https://registry.npmmirror.com",
    },
    "cloudcli/linux/intl": {
        "instances": [
            {
                "account": "alice",
                "port": 3001,
                "token_secret": "sec-a:device_cloudcli:token_secret",
                "web_password": "pw-a:device_cloudcli:web_password",
            },
            {"account": "bob", "port": 3002, "token_secret": "", "web_password": ""},
            {"account": "carol", "port": 3003, "token_secret": "", "web_password": ""},
        ],
        "npm_environment": {},
        "npm_registry": "https://registry.npmjs.org",
    },
    "cloudcli/windows/cn": {
        "instances": [
            {
                "account": "alice",
                "password": "pw-l-a",
                "port": 3001,
                "token_secret": "sec-a:device_cloudcli:token_secret",
                "web_password": "pw-a:device_cloudcli:web_password",
            },
            {
                "account": "bob",
                "password": "pw-l-b",
                "port": 3002,
                "token_secret": "",
                "web_password": "",
            },
            {"account": "carol", "port": 3003, "token_secret": "", "web_password": ""},
        ],
        "npm_environment": {
            "npm_config_better_sqlite3_binary_host": "https://registry.npmmirror.com/-/binary/better-sqlite3"
        },
        "npm_registry": "https://registry.npmmirror.com",
    },
    "cloudcli/windows/intl": {
        "instances": [
            {
                "account": "alice",
                "password": "pw-l-a",
                "port": 3001,
                "token_secret": "sec-a:device_cloudcli:token_secret",
                "web_password": "pw-a:device_cloudcli:web_password",
            },
            {
                "account": "bob",
                "password": "pw-l-b",
                "port": 3002,
                "token_secret": "",
                "web_password": "",
            },
            {"account": "carol", "port": 3003, "token_secret": "", "web_password": ""},
        ],
        "npm_environment": {},
        "npm_registry": "https://registry.npmjs.org",
    },
    "code_server/darwin": {
        "instances": [
            {
                "account": "alice",
                "port": 8443,
                "secret": "sec-a:device_code_server:secret",  # scan: allow
            },
            {"account": "bob", "port": 8444, "secret": ""},
        ]
    },
    "code_server/linux": {
        "instances": [
            {
                "account": "alice",
                "port": 8443,
                "secret": "sec-a:device_code_server:secret",
            },
            {"account": "bob", "port": 8444, "secret": ""},
        ]
    },
    "code_server/windows": {
        "instances": [
            {
                "account": "alice",
                "port": 8443,
                "secret": "sec-a:device_code_server:secret",
            },
            {"account": "bob", "port": 8444, "secret": ""},
        ]
    },
    "vscode/darwin": {
        "address": "",
        "instances": [
            {"account": "alice", "port": 8000, "token": "tok-a:device_vscode:token"},
            {"account": "bob", "port": 8001, "token": "tok-b:device_vscode:token"},
            {"account": "carol", "port": 8002, "token": ""},
        ],
    },
    "vscode/linux": {
        "address": "",
        "instances": [
            {"account": "alice", "port": 8000, "token": "tok-a:device_vscode:token"},
            {"account": "bob", "port": 8001, "token": "tok-b:device_vscode:token"},
            {"account": "carol", "port": 8002, "token": ""},
        ],
    },
    "vscode/windows": {
        "address": "",
        "instances": [
            {
                "account": "alice",
                "password": "pw-l-a",
                "port": 8000,
                "token": "tok-a:device_vscode:token",
            },
            {"account": "bob", "port": 8001, "token": "tok-b:device_vscode:token"},
            {"account": "carol", "port": 8002, "token": ""},
        ],
    },
}


def _opened_for_pin(sealed, aad: bytes) -> str:
    if not isinstance(sealed, dict) or not sealed:
        return ""
    return f"{sealed['v']}:{aad.decode()}"


def _password_for_pin(login_id: str) -> str:
    return f"pw-{login_id}"


@pytest.mark.parametrize("pinned", sorted(PINNED_CONFIGS))
def test_the_one_composition_answers_byte_for_byte_what_the_three_did(
    pinned, monkeypatch
):
    from neutrino_hub.modules.devices.desired_state import instances_agent_config
    from neutrino_hub.modules.devices.module_table import module_row

    monkeypatch.setattr(desired_state_module, "_unsealed_text", _opened_for_pin)
    monkeypatch.setattr(desired_state_module, "_login_password", _password_for_pin)
    module, platform_name, *edition = pinned.split("/")
    kwargs = {"edition": edition[0]} if edition else {}

    composed = instances_agent_config(
        module_row(module),
        PINNED_STORED[module],
        PINNED_PLATFORMS[platform_name],
        **kwargs,
    )

    # The state hash is over the canonical JSON, which is what is compared.
    assert json.dumps(composed, sort_keys=True) == json.dumps(
        PINNED_CONFIGS[pinned], sort_keys=True
    )


# --- Containers: the Run settings ---

PODMAN_STORED = {
    "containers": [
        {
            "name": "web",
            "image": "docker.io/library/nginx:1.27",
            "ports": ["8080:80", "5353:53/udp"],
            "volumes": ["/srv/web:/usr/share/nginx/html", "data:/data"],
            "environment": ["NGINX_PORT=80"],
            "command": "",
            "is_autostart": True,
        }
    ],
    "mirrors": ["mirror.example"],
}
PODMAN_RUN_SETTINGS = {
    "account": "lab",
    "login_id": "l-lab",
    "cpus": 4,
    "memory_gib": 8,
    "disk_gib": 120,
}
PODMAN_SENT_MACHINE = {"account": "lab", "cpus": 4, "memory_gib": 8, "disk_gib": 120}
# The hash of the Linux ``podman`` entry for ``PODMAN_STORED`` under the
# catalog's own recipe, captured before the Run settings existed.
PODMAN_LINUX_ENTRY_HASH = (
    "be399912fdb9cc26d9bd724feef0aab35f7a58e0fdc325c63f8dcea3deec6318"  # scan: allow
)


@pytest.fixture
def podman_config(monkeypatch, tmp_path):
    """The config dir under tmp_path, the catalog's own recipes, pinned logins."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "_login_password", _password_for_pin)
    return tmp_path


def test_a_linux_podman_entry_is_byte_for_byte_as_before_and_names_no_machine(
    podman_config,
):
    store = DesiredStateStore()
    store.set_want(DEVICE, "podman", "running")
    store.write(DEVICE, "podman", PODMAN_STORED)
    before, before_hash = store.compose(DEVICE, PINNED_PLATFORMS["linux"])
    store.write(DEVICE, "podman", {**PODMAN_STORED, "machine": PODMAN_RUN_SETTINGS})
    after, after_hash = store.compose(DEVICE, PINNED_PLATFORMS["linux"])

    assert state_hash(before["modules"]["podman"]) == PODMAN_LINUX_ENTRY_HASH
    assert after == before
    assert after_hash == before_hash


@pytest.mark.parametrize(
    "platform, machine",
    [
        ("windows", {**PODMAN_SENT_MACHINE, "password": "pw-l-lab"}),
        ("darwin", PODMAN_SENT_MACHINE),
        ("linux", None),
        ("unreported", None),
    ],
)
def test_the_run_settings_reach_windows_and_macos_alone_with_a_password_on_windows(
    podman_config, platform, machine
):
    from neutrino_hub.modules.devices.desired_state import podman_agent_config

    composed = podman_agent_config(
        {**PODMAN_STORED, "machine": PODMAN_RUN_SETTINGS},
        PINNED_PLATFORMS.get(platform, {}),
    )

    assert composed.get("machine") == machine
    assert {key: value for key, value in composed.items() if key != "machine"} == (
        PODMAN_STORED
    )


def test_a_windows_machine_with_no_login_is_sent_no_password(podman_config):
    from neutrino_hub.modules.devices.desired_state import podman_agent_config

    composed = podman_agent_config(
        {"machine": {**PODMAN_RUN_SETTINGS, "login_id": ""}},
        PINNED_PLATFORMS["windows"],
    )

    assert composed == {"machine": PODMAN_SENT_MACHINE}


def test_the_podman_section_checked_on_an_apply_is_the_one_a_windows_state_carries(
    podman_config,
):
    store = DesiredStateStore()
    store.set_want(DEVICE, "podman", "running")
    store.write(DEVICE, "podman", {**PODMAN_STORED, "machine": PODMAN_RUN_SETTINGS})
    windows = PINNED_PLATFORMS["windows"]

    desired, digest = store.compose(DEVICE, windows)
    checked = store.agent_config(
        DEVICE, "podman", store.read(DEVICE, "podman"), windows
    )
    store.write(
        DEVICE,
        "podman",
        {**PODMAN_STORED, "machine": {**PODMAN_RUN_SETTINGS, "cpus": 2}},
    )
    _, moved = store.compose(DEVICE, windows)

    assert checked == desired["modules"]["podman"]["config"]
    assert checked["machine"] == {**PODMAN_SENT_MACHINE, "password": "pw-l-lab"}
    assert moved != digest
