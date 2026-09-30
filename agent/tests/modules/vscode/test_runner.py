"""The VS Code runner: the CLI from the hub's bytes, a server per account.

What these pin: the CLI is there when its file is; an install unpacks the
archive into the applier's directory under the system's name for it; an
apply validates for this system and hands the applier the configuration,
a failure arriving as ``apply_failed``; the row is active only while there
is a server and every one runs; the details list each server's url and
state; and each system gets its own applier.
"""

import io
import tarfile

import pytest

from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.vscode.darwin_applier import VscodeDarwinApplier
from neutrino_agent.modules.vscode.linux_applier import VscodeLinuxApplier
from neutrino_agent.modules.vscode.runner import (
    VscodeModuleRunner,
    vscode_applier_for,
)
from neutrino_agent.modules.vscode.windows_applier import VscodeWindowsApplier
from neutrino_agent.platforms.base import AgentPlatform

CONFIG = {
    "address": "192.168.1.5",
    "instances": [{"account": "ann", "port": 8000, "token": "t"}],
}


class FakeApplier:
    def __init__(self, directory):
        self.cli_dir = str(directory)
        self.cli_path = str(directory / "code")
        self.calls: list = []
        self.error = None
        self.running = True

    def apply(self, config):
        self.calls.append(("apply", config.instances[0].account))
        if self.error is not None:
            raise self.error
        return []

    def stop(self):
        self.calls.append(("stop",))

    def remove(self):
        self.calls.append(("remove",))

    def states(self, config):
        instances = config.instances if config is not None else []
        return [
            {
                "account": item.account,
                "port": item.port,
                "url": config.url_of(item),
                "is_running": self.running,
                "code": "",
            }
            for item in instances
        ]

    def units(self):
        return ["neutrino_vscode@ann.service"]


class Platform(AgentPlatform):
    def __init__(self, os_name, root=""):
        self.os_name = os_name
        self._root = root

    def hub_package_root(self):
        return self._root


@pytest.fixture
def runner(tmp_path):
    applier = FakeApplier(tmp_path / "vscode")
    held = VscodeModuleRunner(
        platform=Platform("linux"), log=lambda message: None, applier=applier
    )
    held.applier = applier
    return held


def test_the_cli_is_there_when_its_file_is(runner, tmp_path):
    assert runner.verify({}) is False

    archive = tmp_path / "cli.tar.gz"
    with tarfile.open(archive, "w:gz") as packed:
        info = tarfile.TarInfo("code")
        info.size = 2
        packed.addfile(info, io.BytesIO(b"hi"))
    runner.install({"entry": {"package_kind": "tar"}}, str(archive))

    assert runner.verify({}) is True
    runner.uninstall({})
    assert runner.verify({}) is False


def test_an_apply_reaches_the_applier_and_the_details_list_each_server(runner):
    runner.apply(CONFIG)

    assert runner.applier.calls == [("apply", "ann")]
    assert runner.is_active() is True
    assert runner.details({}) == {
        "instances": [
            {
                "account": "ann",
                "port": 8000,
                "url": "http://192.168.1.5:8000/",
                "is_running": True,
                "code": "",
            }
        ]
    }


def test_the_row_is_active_only_while_every_server_runs(runner):
    assert runner.is_active() is False

    runner.apply(CONFIG)
    runner.applier.running = False
    runner._forget_states()

    assert runner.is_active() is False


def test_a_failure_of_the_system_is_apply_failed(runner):
    runner.applier.error = OSError("systemctl refused")

    with pytest.raises(ModuleApplyError) as refused:
        runner.apply(CONFIG)

    assert refused.value.code == "apply_failed"
    assert "systemctl refused" in refused.value.params["detail"]


def test_a_configuration_is_checked_for_this_system(tmp_path):
    runner = VscodeModuleRunner(
        platform=Platform("windows", "C:\\ProgramData\\Neutrino"),
        applier=FakeApplier(tmp_path),
    )

    with pytest.raises(ModuleApplyError) as refused:
        runner.validate(CONFIG)

    assert refused.value.code == "credential_missing"


def test_stop_remove_and_the_journal_reach_the_applier(runner):
    runner.stop()
    runner.remove_configuration()

    assert runner.applier.calls == [("stop",), ("remove",)]
    assert runner.journal_units() == ["neutrino_vscode@ann.service"]


def test_each_system_gets_its_own_applier():
    assert isinstance(vscode_applier_for(Platform("linux")), VscodeLinuxApplier)
    darwin = vscode_applier_for(Platform("darwin", "/Library/Application Support/N"))
    assert isinstance(darwin, VscodeDarwinApplier)
    assert darwin.cli_dir == "/Library/Application Support/N/vscode"
    windows = vscode_applier_for(Platform("windows", "C:\\ProgramData\\Neutrino"))
    assert isinstance(windows, VscodeWindowsApplier)
    assert windows.cli_path == "C:\\ProgramData\\Neutrino\\vscode\\code.exe"
    with pytest.raises(PlatformUnsupportedError):
        vscode_applier_for(Platform("freebsd"))
