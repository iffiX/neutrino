"""The five roots, one table per system, and the development root over them."""

from pathlib import Path

import pytest

from neutrino_hub.utils import constants

LINUX_ROOTS = {
    "static": "/opt/neutrino",
    "config": "/etc/neutrino/hub",
    "state": "/var/lib/neutrino",
    "log": "/var/log/neutrino",
    "runtime": "/run/neutrino",
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
        ("runtime", "/var/run/neutrino_hub"),
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
    assert constants._rooted("state") == tmp_path / "var/lib/neutrino"


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
