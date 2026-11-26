"""ComfyUI on the hub: its file, its PyTorch build, its recipe and the configuration the state sends.

What these pin: Install writes the token secret once and ``torch_build``
from the machine's last report, NVIDIA's card first, then AMD's on Linux,
then an Intel card named Arc, else ``cpu``, a build the machine's entry has
no lock of passed over, none on a Mac, and the build kept across later
reports that miss a card; the state's ``config`` carries the secret opened,
the cookie and local names, the settings with ``30m`` while none is
stored, the default as ``account``, its login on Windows alone, empty with
no default, and ``tools`` the three program modules whose ``want`` is
neither empty nor ``absent``; the recipe names the lock of the machine's
platform and build with ``source_sets`` ``pytorch`` and ``pypi``, and the
state carries both sets; the app is told apart among the machine's apps;
and the models folder and the service's account by system.
"""

import hashlib

import pytest

from neutrino_hub.modules.credentials.vault import SecretVault, unseal_bytes
from neutrino_hub.modules.devices import comfyui
from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.desired_state import DesiredStateStore, machine_apps
from neutrino_hub.modules.devices.manifests import (
    entry_params,
    load_module_manifests,
)
from tests.conftest import unlock_vault

DEVICE = "dev-1"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
LINUX_ARM = {"os": "linux", "family": "debian", "arch": "arm64", "version": "2.36"}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}
MAC = {"os": "darwin", "family": "", "arch": "arm64", "version": "15.1"}
COOKIE_NAME = (
    "neutrino_" + hashlib.sha256(f"comfyui_{DEVICE}_web".encode()).hexdigest()[:12]
)
NVIDIA = {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 4090"}
AMD = {"vendor": "amd", "name": "AMD Radeon RX 7900 XTX"}
ARC = {"vendor": "intel", "name": "Intel(R) Arc(TM) A770 Graphics"}
IRIS = {"vendor": "intel", "name": "Intel(R) Iris(R) Xe Graphics"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    unlock_vault(monkeypatch, tmp_path)
    return DesiredStateStore()


def venv_digest(platform: dict, build: str = "") -> str:
    manifest = load_module_manifests()["comfyui"]
    key = f"{platform['os']}-{platform['arch']}"
    venv = entry_params(manifest["platforms"][key])["artifacts"][-1]
    return venv["builds"][build] if build else venv["digest"]


@pytest.mark.parametrize(
    "platform, builds",
    [
        (LINUX, ["nvidia", "amd", "intel", "cpu"]),
        (LINUX_ARM, ["nvidia", "cpu"]),
        (WINDOWS, ["nvidia", "intel", "cpu"]),
        (MAC, []),
        ({}, []),
    ],
)
def test_each_entry_offers_the_builds_it_has_a_lock_of_in_the_page_s_order(
    platform, builds
):
    assert comfyui.entry_builds(platform) == builds


@pytest.mark.parametrize(
    "platform, gpus, build",
    [
        (LINUX, [AMD, NVIDIA], "nvidia"),
        (LINUX, [ARC, AMD], "amd"),
        (LINUX, [IRIS, ARC], "intel"),
        (LINUX, [IRIS], "cpu"),
        (LINUX, [], "cpu"),
        (LINUX_ARM, [AMD, ARC], "cpu"),
        (WINDOWS, [AMD], "cpu"),
        (WINDOWS, [AMD, ARC], "intel"),
        (WINDOWS, [NVIDIA], "nvidia"),
        (MAC, [{"vendor": "apple", "name": "Apple M3"}], ""),
    ],
)
def test_install_picks_the_build_of_the_first_card_whose_build_has_a_lock(
    store, platform, gpus, build
):
    written = comfyui.ensure_config(store, DEVICE, platform, gpus)

    assert written.get("torch_build", "") == build
    assert ("torch_build" in store.read(DEVICE, "comfyui")) is bool(build)


def test_install_writes_the_secret_once_and_keeps_the_build_across_reports(store):
    first = comfyui.ensure_config(store, DEVICE, LINUX, [NVIDIA])
    again = comfyui.ensure_config(store, DEVICE, LINUX, [])

    assert first == again == store.read(DEVICE, "comfyui")
    assert set(first) == {"secret_sealed", "torch_build"}
    assert first["torch_build"] == "nvidia"
    secret = unseal_bytes(first["secret_sealed"], b"device_comfyui:secret").decode()
    assert len(secret) >= 40
    store.write(DEVICE, "comfyui", {**first, "torch_build": "amd"})
    assert comfyui.ensure_config(store, DEVICE, WINDOWS, [])["torch_build"] == "cpu"


def test_a_locked_vault_still_writes_the_build_and_leaves_the_secret(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path / "state"
    )
    store = DesiredStateStore()

    assert comfyui.ensure_config(store, DEVICE, LINUX, [AMD]) == {"torch_build": "amd"}


def test_the_settings_default_to_cpu_and_30m_while_none_are_stored():
    builds = comfyui.entry_builds(LINUX)

    assert comfyui.settings({}, builds) == {"torch_build": "cpu", "idle_unload": "30m"}
    assert comfyui.settings({"torch_build": "intel", "idle_unload": "4h"}, builds) == {
        "torch_build": "intel",
        "idle_unload": "4h",
    }
    assert comfyui.settings({"torch_build": "amd", "idle_unload": "2h"}, ["cpu"]) == {
        "torch_build": "cpu",
        "idle_unload": "30m",
    }
    assert comfyui.settings({"idle_unload": "-1"}, []) == {
        "torch_build": "",
        "idle_unload": "-1",
    }


def with_default(store, *, is_windows_login: bool = False) -> None:
    login_id = ""
    if is_windows_login:
        login_id = (
            SecretVault()
            .add(kind="login", name="ann", secret={"username": "ann", "password": "pw"})
            .id
        )
    accounts = DeviceAccountStore(store)
    accounts.add(
        DEVICE, DeviceAccount(account="ann", login_id=login_id), is_default=True
    )
    accounts.add(DEVICE, DeviceAccount(account="bob"))


def test_the_state_carries_the_secret_the_names_the_settings_and_the_default(store):
    with_default(store, is_windows_login=True)
    stored = comfyui.ensure_config(store, DEVICE, LINUX, [NVIDIA])
    store.write(DEVICE, "comfyui", {**stored, "idle_unload": "1h"})
    for name, want in (
        ("claude_code", "running"),
        ("codex", "absent"),
        ("opencode", "running"),
    ):
        store.set_want(DEVICE, name, want)

    config = store.agent_config(
        DEVICE,
        "comfyui",
        store.read(DEVICE, "comfyui"),
        LINUX,
        machine_slug="argon",
    )

    assert config == {
        "secret": unseal_bytes(
            stored["secret_sealed"], b"device_comfyui:secret"
        ).decode(),
        "cookie_name": COOKIE_NAME,
        "local_name": "comfyui.argon.localhost",
        "torch_build": "nvidia",
        "idle_unload": "1h",
        "account": "ann",
        "password": "",
        "tools": ["claude_code", "opencode"],
    }


def test_a_windows_machine_is_sent_the_default_s_login(store):
    with_default(store, is_windows_login=True)
    comfyui.ensure_config(store, DEVICE, WINDOWS, [])

    config = store.agent_config(
        DEVICE, "comfyui", store.read(DEVICE, "comfyui"), WINDOWS
    )

    assert (config["account"], config["password"]) == ("ann", "pw")
    assert config["torch_build"] == "cpu"


def test_a_machine_with_no_default_names_no_account_and_no_tool(store):
    comfyui.ensure_config(store, DEVICE, MAC, [])
    store.set_want(DEVICE, "codex", "running")

    config = store.agent_config(DEVICE, "comfyui", store.read(DEVICE, "comfyui"), MAC)

    assert (config["account"], config["password"], config["tools"]) == ("", "", [])
    assert config["torch_build"] == ""


@pytest.mark.parametrize(
    "platform, build, sets",
    [
        (LINUX, "amd", ["pytorch", "pypi"]),
        (LINUX_ARM, "nvidia", ["pytorch", "pypi"]),
        (WINDOWS, "intel", ["pytorch", "pypi"]),
        (MAC, "", ["pypi"]),
    ],
)
def test_the_recipe_names_the_lock_of_the_machine_s_platform_and_build(
    store, platform, build, sets
):
    if build:
        store.write(DEVICE, "comfyui", {"torch_build": build})
    store.set_want(DEVICE, "comfyui", "installed")

    composed, _ = store.compose(DEVICE, platform)

    recipe = composed["modules"]["comfyui"]["install"]
    venv = recipe["params"]["artifacts"][-1]
    assert recipe["runner"] == "comfyui"
    assert venv == {
        "name": "venv",
        "kind": "uv_lock",
        "digest": venv_digest(platform, build),
        "source_sets": sets,
    }
    assert set(composed["source_sets"]) >= set(sets)
    assert "pytorch" in composed["source_sets"] or not build


def test_a_new_build_names_another_lock_and_another_hash(store):
    store.write(DEVICE, "comfyui", {"torch_build": "cpu"})
    store.set_want(DEVICE, "comfyui", "running")
    _, cpu = store.compose(DEVICE, LINUX)

    store.write(DEVICE, "comfyui", {"torch_build": "nvidia"})
    composed, nvidia = store.compose(DEVICE, LINUX)

    assert cpu != nvidia
    assert composed["modules"]["comfyui"]["install"]["params"]["artifacts"][-1][
        "digest"
    ] == venv_digest(LINUX, "nvidia")


def test_the_app_is_told_apart_among_the_machine_s_apps(store):
    assert machine_apps(store, DEVICE)[f"comfyui_{DEVICE}"] == "ComfyUI"


@pytest.mark.parametrize(
    "platform, folder, account",
    [
        (
            LINUX,
            "/var/lib/neutrino/agent/comfyui_data/data/models/",
            "neutrino_comfyui",
        ),
        (
            MAC,
            "/Library/Application Support/Neutrino/agent/state/comfyui_data/data/models/",
            "neutrino_comfyui",
        ),
        (
            WINDOWS,
            "%ProgramData%\\Neutrino\\agent\\state\\comfyui_data\\data\\models\\",
            "LOCAL SERVICE",
        ),
        ({}, "/var/lib/neutrino/agent/comfyui_data/data/models/", "neutrino_comfyui"),
    ],
)
def test_the_models_folder_and_the_service_s_account_follow_the_system(
    platform, folder, account
):
    assert comfyui.models_dir(platform) == folder
    assert comfyui.service_user(platform) == account
