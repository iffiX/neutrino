"""The SSH server: one verb pair, mechanics each platform's own.

Install puts the server in place and serving; uninstall genuinely removes
the package on Linux and the capability on Windows, and on macOS — whose
sealed system volume nothing may leave — switches Remote Login off with no
binary moved. The row reads installed while the server is serving.
"""

import os
import subprocess

import pytest

import neutrino_agent.platforms.linux as linux_module
from neutrino_agent.modules import installers
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.modules.openssh import OpensshModuleRunner
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform
from tests.conftest import discard

DEBIAN_ENTRY = {"packages": ["openssh-server"], "service": "ssh"}


class SwitchPlatform(AgentPlatform):
    """A machine whose SSH server is observable, recording each step."""

    os_name = "linux"

    def __init__(self, *, is_running: bool):
        self.is_running = is_running
        self.calls: list = []

    def read_openssh_status(self, entry) -> bool:
        return self.is_running

    def install_openssh(self, entry) -> None:
        self.calls.append("install")
        self.is_running = True

    def uninstall_openssh(self, entry) -> None:
        self.calls.append("uninstall")
        self.is_running = False


def runner_for(platform) -> OpensshModuleRunner:
    return OpensshModuleRunner(platform=platform, log=discard)


def recorded_commands(monkeypatch) -> list:
    """The commands a platform runs, recorded instead of run."""
    commands: list = []

    def run_checked(command, **kwargs):
        commands.append(list(command))
        return ""

    monkeypatch.setattr(installers, "run_checked", run_checked)
    return commands


def linux_tools(monkeypatch, *, present) -> None:
    """A Linux machine carrying exactly the named tools.

    Args:
        monkeypatch: The pytest patcher.
        present: Tool names this machine has; ``sshd`` stands for the server
            package being installed already.
    """
    monkeypatch.setattr(
        linux_module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in present else None,
    )
    real_exists = os.path.exists
    monkeypatch.setattr(
        linux_module.os.path,
        "exists",
        lambda path: (
            "sshd" in present if path == "/usr/sbin/sshd" else real_exists(path)
        ),
    )


# --- the runner: verify, install, uninstall ---


def test_openssh_verify_is_whether_the_server_serves():
    runner = runner_for(SwitchPlatform(is_running=True))
    assert runner.verify({"entry": DEBIAN_ENTRY}) is True

    runner = runner_for(SwitchPlatform(is_running=False))
    assert runner.verify({"entry": DEBIAN_ENTRY}) is False


def test_openssh_install_and_uninstall_ride_the_platform():
    platform = SwitchPlatform(is_running=False)
    runner = runner_for(platform)

    runner.install({"entry": DEBIAN_ENTRY})
    assert platform.calls == ["install"] and runner.verify({"entry": DEBIAN_ENTRY})

    runner.uninstall({"entry": DEBIAN_ENTRY})
    assert platform.calls == ["install", "uninstall"]
    assert not runner.verify({"entry": DEBIAN_ENTRY})


# --- what each platform actually runs ---


@pytest.mark.parametrize(
    "present, install_command",
    [
        ({"apt-get"}, ["apt-get", "install", "-y", "openssh-server"]),
        ({"dnf"}, ["dnf", "install", "-y", "openssh-server"]),
        (set(), ["yum", "install", "-y", "openssh-server"]),
    ],
)
def test_openssh_linux_install_puts_the_package_then_starts_the_unit(
    monkeypatch, present, install_command
):
    linux_tools(monkeypatch, present=present)
    commands = recorded_commands(monkeypatch)

    LinuxPlatform().install_openssh(DEBIAN_ENTRY)

    assert commands == [install_command, ["systemctl", "enable", "--now", "ssh"]]


def test_openssh_linux_install_with_the_server_present_only_starts_the_unit(
    monkeypatch,
):
    linux_tools(monkeypatch, present={"sshd", "apt-get"})
    commands = recorded_commands(monkeypatch)

    LinuxPlatform().install_openssh({"packages": ["openssh-server"], "service": "sshd"})

    assert commands == [["systemctl", "enable", "--now", "sshd"]]


def test_openssh_linux_uninstall_stops_the_unit_and_removes_the_package(monkeypatch):
    linux_tools(monkeypatch, present={"sshd", "apt-get"})
    commands = recorded_commands(monkeypatch)

    LinuxPlatform().uninstall_openssh(DEBIAN_ENTRY)

    assert commands == [
        ["systemctl", "disable", "--now", "ssh"],
        ["apt-get", "purge", "-y", "openssh-server"],
    ]


@pytest.mark.parametrize(
    "stdout, is_serving", [("active\n", True), ("inactive\n", False)]
)
def test_openssh_linux_status_is_systemd_own_word(monkeypatch, stdout, is_serving):
    commands: list = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(linux_module.subprocess, "run", fake_run)

    assert LinuxPlatform().read_openssh_status({"service": "ssh"}) is is_serving
    assert commands == [["systemctl", "is-active", "ssh"]]


def test_openssh_linux_status_survives_a_systemctl_that_cannot_run(monkeypatch):
    def fake_run(command, **kwargs):
        raise OSError("no systemctl")

    monkeypatch.setattr(linux_module.subprocess, "run", fake_run)

    assert LinuxPlatform().read_openssh_status({"service": "ssh"}) is False


def test_openssh_darwin_switches_remote_login_and_moves_no_binary(monkeypatch):
    commands = recorded_commands(monkeypatch)
    entry = {"service": "remote_login"}

    DarwinPlatform().install_openssh(entry)
    DarwinPlatform().uninstall_openssh(entry)

    assert commands == [
        ["systemsetup", "-setremotelogin", "on"],
        ["systemsetup", "-f", "-setremotelogin", "off"],
    ]


def test_openssh_windows_adds_and_removes_the_capability(monkeypatch):
    commands = recorded_commands(monkeypatch)
    entry = {"capability": "OpenSSH.Server~~~~0.0.1.0"}

    WindowsPlatform().install_openssh(entry)
    WindowsPlatform().uninstall_openssh(entry)

    assert [command[0] for command in commands] == ["powershell", "powershell"]
    assert "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0" in (
        commands[0][-1]
    )
    assert "Start-Service sshd" in commands[0][-1]
    assert "Remove-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0" in (
        commands[1][-1]
    )


def test_openssh_a_refusal_is_left_to_the_engine_to_type(monkeypatch):
    linux_tools(monkeypatch, present={"sshd"})

    def refuse(command, **kwargs):
        raise InstallError("systemctl failed: Unit ssh.service is masked")

    monkeypatch.setattr(installers, "run_checked", refuse)

    with pytest.raises(InstallError) as caught:
        runner_for(LinuxPlatform()).install({"entry": DEBIAN_ENTRY})

    assert "masked" in str(caught.value)
