"""The system-package runner: packages by name, steps before them."""

import pytest

from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared import system_package as system_package_module
from neutrino_agent.exceptions import InstallError
from neutrino_agent.modules.shared.system_package import SystemPackageModuleRunner
from neutrino_agent.platforms.base import AgentPlatform


class RecordingPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self):
        self.installed: list = []
        self.removed: list = []

    def install_system_packages(self, names):
        self.installed.append(list(names))
        return ""

    def remove_system_packages(self, names):
        self.removed.append(list(names))
        return ""


@pytest.fixture
def steps(monkeypatch):
    ran: list = []

    def run_shell(command, *, timeout_s=installers.INSTALL_TIMEOUT_S):
        ran.append(command)
        if "fail" in command:
            raise InstallError("step failed: no")
        return "stepped\n"

    monkeypatch.setattr(system_package_module.installers, "run_shell", run_shell)
    return ran


def test_pre_install_steps_run_before_the_packages(steps):
    platform = RecordingPlatform()
    logged: list = []
    runner = SystemPackageModuleRunner(platform=platform, log=logged.append)

    runner.install(
        {
            "runner": "zfs",
            "method": "system",
            "params": {
                "pre_install": ["enable contrib", "apt-get update"],
                "packages": ["zfsutils-linux"],
            },
        }
    )

    assert steps == ["enable contrib", "apt-get update"]
    assert platform.installed == [["zfsutils-linux"]]
    assert "stepped" in logged


def test_a_failing_step_stops_the_install_before_any_package(steps):
    platform = RecordingPlatform()
    runner = SystemPackageModuleRunner(platform=platform, log=lambda m: None)

    with pytest.raises(InstallError):
        runner.install({"params": {"pre_install": ["fail"], "packages": ["x"]}})

    assert platform.installed == []


def test_an_entry_without_steps_installs_its_packages_only(steps):
    platform = RecordingPlatform()
    runner = SystemPackageModuleRunner(platform=platform, log=lambda m: None)

    runner.install({"params": {"packages": ["samba"]}})

    assert steps == []
    assert platform.installed == [["samba"]]


def test_the_runners_own_check_looks_for_its_binary(monkeypatch):
    """The runner's own check, which answers for a module the state does
    not name: its binary on the path, and no for a runner with none."""
    found: list = []
    monkeypatch.setattr(
        system_package_module.shutil,
        "which",
        lambda name: found.append(name) or ("/usr/sbin/" + name),
    )

    class NamedRunner(SystemPackageModuleRunner):
        binary = "smbd"

    assert NamedRunner(platform=RecordingPlatform()).verify({}) is True
    assert SystemPackageModuleRunner(platform=RecordingPlatform()).verify({}) is False
    assert found == ["smbd"]


def test_an_uninstall_removes_the_packages_its_uninstall_names():
    platform = RecordingPlatform()
    runner = SystemPackageModuleRunner(platform=platform, log=lambda m: None)

    runner.uninstall(
        {
            "params": {
                "packages": ["podman"],
                "uninstall": {"packages": ["podman", "podman-plugins"]},
            }
        }
    )

    assert platform.removed == [["podman", "podman-plugins"]]
