"""The five roots, one table per system, and the development root over them."""

from pathlib import Path

import pytest

from neutrino_hub.utils import constants

LINUX_ROOTS = {
    "static": "/opt/neutrino/hub",
    "config": "/etc/neutrino/hub",
    "state": "/var/lib/neutrino/hub",
    "log": "/var/log/neutrino/hub",
    "runtime": "/run/neutrino/hub",
}


@pytest.fixture
def no_dev_root(monkeypatch):
    monkeypatch.delenv(constants.UTILS_DEV_ROOT_ENV, raising=False)


@pytest.mark.parametrize(("question", "path"), sorted(LINUX_ROOTS.items()))
def test_linux_keeps_its_paths(monkeypatch, no_dev_root, question, path):
    monkeypatch.setattr(constants, "hub_os", lambda: "linux")

    assert str(constants._rooted(question)) == path


def test_linux_config_root_is_still_etc_neutrino(monkeypatch, no_dev_root):
    monkeypatch.setattr(constants, "hub_os", lambda: "linux")

    assert constants._rooted("config").parent == Path("/etc/neutrino")


@pytest.mark.parametrize(
    ("question", "path"),
    [
        ("static", "/Library/Application Support/Neutrino/hub/app"),
        ("config", "/Library/Application Support/Neutrino/hub/config"),
        ("state", "/Library/Application Support/Neutrino/hub/state"),
        ("log", "/Library/Logs/Neutrino/hub"),
        ("runtime", "/var/run/neutrino/hub"),
    ],
)
def test_macos_answers_from_its_own_table(monkeypatch, no_dev_root, question, path):
    monkeypatch.setattr(constants, "hub_os", lambda: "darwin")

    assert str(constants._rooted(question)) == path


@pytest.mark.parametrize(
    ("question", "path"),
    [
        ("static", "C:\\Program Files\\Neutrino\\hub"),
        ("config", "C:\\ProgramData\\Neutrino\\hub\\config"),
        ("state", "C:\\ProgramData\\Neutrino\\hub\\state"),
        ("log", "C:\\ProgramData\\Neutrino\\hub\\log"),
        ("runtime", "C:\\ProgramData\\Neutrino\\hub\\run"),
    ],
)
def test_windows_answers_from_its_own_table(monkeypatch, no_dev_root, question, path):
    monkeypatch.setattr(constants, "hub_os", lambda: "windows")

    assert str(constants._rooted(question)) == path


def test_a_development_root_holds_linux_paths_as_before(monkeypatch, tmp_path):
    monkeypatch.setattr(constants, "hub_os", lambda: "linux")
    monkeypatch.setenv(constants.UTILS_DEV_ROOT_ENV, str(tmp_path))

    assert constants._rooted("config") == tmp_path / "etc/neutrino/hub"
    assert constants._rooted("state") == tmp_path / "var/lib/neutrino/hub"


@pytest.mark.parametrize(
    ("system", "relative"),
    [
        ("darwin", "Library/Logs/Neutrino/hub"),
        ("windows", "ProgramData/Neutrino/hub/log"),
    ],
)
def test_a_development_root_holds_every_system(monkeypatch, tmp_path, system, relative):
    monkeypatch.setattr(constants, "hub_os", lambda: system)
    monkeypatch.setenv(constants.UTILS_DEV_ROOT_ENV, str(tmp_path))

    assert constants._rooted("log") == tmp_path / relative


def test_a_carried_program_ends_in_exe_on_windows_alone(monkeypatch):
    monkeypatch.setattr(constants, "hub_os", lambda: "windows")
    assert constants.carried_program("xray").name == "xray.exe"
    monkeypatch.setattr(constants, "hub_os", lambda: "darwin")
    assert constants.carried_program("xray").name == "xray"
    monkeypatch.setattr(constants, "hub_os", lambda: "linux")
    assert constants.carried_program("xray") == constants.UTILS_PROGRAM_DIR / "xray"


# --- where the configuration is ---


@pytest.fixture
def config_places(monkeypatch, tmp_path, no_dev_root):
    """A system directory and a checkout directory of this test's own."""
    system = tmp_path / "system_config"
    checkout = tmp_path / "checkout_config"
    monkeypatch.delenv(constants.UTILS_CONFIG_ENV, raising=False)
    monkeypatch.setattr(constants, "UTILS_SYSTEM_CONFIG_DIR", system)
    monkeypatch.setattr(constants, "UTILS_CHECKOUT_CONFIG_DIR", checkout)
    return system, checkout


@pytest.mark.parametrize("is_present", [True, False])
def test_a_built_package_keeps_its_configuration_in_the_system_directory(
    monkeypatch, config_places, is_present
):
    """On Windows nothing makes the directory before the service first
    imports the hub, and the checkout's directory there is under Program
    Files, which every account reads."""
    system, _ = config_places
    if is_present:
        system.mkdir()
    monkeypatch.setattr(constants, "is_stamped_package", lambda: True)

    assert constants.resolve_config_dir() == system


def test_a_checkout_uses_the_system_directory_only_when_it_exists(
    monkeypatch, config_places
):
    system, checkout = config_places
    monkeypatch.setattr(constants, "is_stamped_package", lambda: False)

    assert constants.resolve_config_dir() == checkout
    system.mkdir()
    assert constants.resolve_config_dir() == system


@pytest.mark.parametrize("is_stamped", [True, False])
def test_the_environment_override_wins_over_everything(
    monkeypatch, config_places, tmp_path, is_stamped
):
    monkeypatch.setattr(constants, "is_stamped_package", lambda: is_stamped)
    monkeypatch.setenv(constants.UTILS_CONFIG_ENV, str(tmp_path / "elsewhere"))

    assert constants.resolve_config_dir() == tmp_path / "elsewhere"


def test_a_development_root_uses_the_system_directory_absent_or_not(
    monkeypatch, config_places, tmp_path
):
    system, _ = config_places
    monkeypatch.setattr(constants, "is_stamped_package", lambda: False)
    monkeypatch.setenv(constants.UTILS_DEV_ROOT_ENV, str(tmp_path))

    assert constants.resolve_config_dir() == system


def test_a_checkout_has_no_build_stamp():
    assert constants.is_stamped_package() is False


def test_a_build_stamp_makes_a_stamped_package(monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "neutrino_hub._version", types.ModuleType("v"))

    assert constants.is_stamped_package() is True
