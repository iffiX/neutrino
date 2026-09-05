"""Installing, removing and verifying a package module.

Execution only. The runner is handed a module the hub already resolved and
bytes the hub already fetched; what is pinned here is that it does what it
was told, judges the result by the machine's own state, and keeps nothing
about how it went — no latch, no failure memory, no policy of any kind.
"""

import os
import subprocess

import pytest

from neutrino_agent.modules.installers import InstallError
from neutrino_agent.modules.package import PackageModuleRunner
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError

DEB_MODULE = {
    "title": "ToDesk",
    "kind": "package",
    "entry": {"package_kind": "deb", "uninstall": "apt-get remove -y todesk"},
    "verify": "",
    "package": "todesk",
}

COMMAND_MODULE = {
    "title": "AnyDesk",
    "kind": "package",
    "entry": {"package_kind": "dmg", "uninstall": "rm -rf /Applications/AnyDesk.app"},
    "verify": "test -d /Applications/AnyDesk.app",
    "package": "anydesk",
}


class RecordingPlatform(AgentPlatform):
    """Records installs and uninstalls instead of running them."""

    os_name = "linux"

    def __init__(self, *, install_error=None, uninstall_error=None):
        self.installs: list = []
        self.uninstalls: list = []
        self._install_error = install_error
        self._uninstall_error = uninstall_error

    def install_package(self, path, *, package_kind, entry):
        self.installs.append((os.path.basename(path), package_kind, entry))
        if self._install_error is not None:
            raise self._install_error

    def uninstall_package(self, command):
        self.uninstalls.append(command)
        if self._uninstall_error is not None:
            raise self._uninstall_error


@pytest.fixture
def runner():
    """A runner over a platform that records rather than installs."""
    platform = RecordingPlatform()
    return PackageModuleRunner(platform=platform, log=lambda message: None), platform


def test_install_hands_the_bytes_to_the_platform(runner, tmp_path):
    package = tmp_path / "package.deb"
    package.write_bytes(b"!<arch>")
    module, platform = runner

    module.install(DEB_MODULE, str(package))

    assert platform.installs == [
        ("package.deb", "deb", DEB_MODULE["entry"]),
    ]


def test_install_that_refuses_is_left_to_the_engine_to_type(tmp_path):
    platform = RecordingPlatform(install_error=InstallError("dpkg failed: held"))
    module = PackageModuleRunner(platform=platform, log=lambda message: None)

    with pytest.raises(InstallError):
        module.install(DEB_MODULE, str(tmp_path / "package.deb"))


def test_install_on_a_platform_that_installs_nothing_is_not_swallowed(tmp_path):
    module = PackageModuleRunner(platform=AgentPlatform(), log=lambda message: None)

    with pytest.raises(PlatformUnsupportedError):
        module.install(DEB_MODULE, str(tmp_path / "package.deb"))


def test_a_deb_uninstall_purges_the_resolved_package_name(runner):
    module, platform = runner

    module.uninstall(DEB_MODULE)

    # apt-get remove leaves the `rc` state, whose remnant reads as installed.
    assert platform.uninstalls == ["apt-get purge -y todesk"]


def test_a_non_deb_uninstall_keeps_the_catalog_command(runner):
    module, platform = runner

    module.uninstall(COMMAND_MODULE)

    assert platform.uninstalls == ["rm -rf /Applications/AnyDesk.app"]


def test_an_uninstall_with_no_command_named_asks_the_platform_nothing(runner):
    module, platform = runner

    module.uninstall({"entry": {"package_kind": "dmg"}, "package": "x", "verify": ""})

    assert platform.uninstalls == []


def test_an_uninstall_that_refuses_is_left_to_the_engine_to_type():
    platform = RecordingPlatform(uninstall_error=InstallError("uninstall failed: busy"))
    module = PackageModuleRunner(platform=platform, log=lambda message: None)

    with pytest.raises(InstallError):
        module.uninstall(DEB_MODULE)


@pytest.mark.parametrize(
    "status, is_installed",
    [
        ("install ok installed", True),
        ("deinstall ok config-files", False),
        ("unknown ok not-installed", False),
    ],
)
def test_deb_verify_reads_dpkgs_own_status_word(
    runner, monkeypatch, status, is_installed
):
    module, _ = runner
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout=status, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert module.verify(DEB_MODULE) is is_installed
    assert seen["command"] == ["dpkg-query", "-W", "-f=${Status}", "todesk"]


def test_deb_verify_an_unknown_package_is_absent(runner, monkeypatch):
    module, _ = runner
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", ""),
    )

    assert module.verify(DEB_MODULE) is False


@pytest.mark.parametrize(
    "error", [OSError("no dpkg"), subprocess.TimeoutExpired("x", 1)]
)
def test_deb_verify_a_query_that_cannot_run_is_absent(runner, monkeypatch, error):
    module, _ = runner

    def raise_error(command, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", raise_error)

    assert module.verify(DEB_MODULE) is False


def test_command_verify_runs_the_catalogs_own_command(runner, monkeypatch):
    module, _ = runner
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert module.verify(COMMAND_MODULE) is True
    assert seen["command"] == "test -d /Applications/AnyDesk.app"


def test_command_verify_non_zero_exit_is_absent(runner, monkeypatch):
    module, _ = runner
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, b"", b""),
    )

    assert module.verify(COMMAND_MODULE) is False


def test_verify_with_no_command_for_this_platform_is_absent(runner):
    module, _ = runner

    assert module.verify({"entry": {"package_kind": "dmg"}, "verify": ""}) is False


def test_the_runner_keeps_no_memory_of_anything(runner, tmp_path):
    module, _ = runner
    package = tmp_path / "package.deb"
    package.write_bytes(b"!<arch>")

    module.install(DEB_MODULE, str(package))
    module.uninstall(DEB_MODULE)

    # No latch, no failure map, no set of names: policy is the hub's, and a
    # runner that remembered would be a second opinion about retrying.
    assert [name for name in vars(module) if not name.startswith("_")] == []
    assert set(vars(module)) == {"_platform", "_log", "_publish"}
