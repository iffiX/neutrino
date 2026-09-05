"""The SSH server: enabled and disabled, never installed or removed.

A platform capability, so the tokens are the capability half of the state
table and the machine's own words are each platform's: a systemd unit on
Linux, ``systemsetup`` on macOS, PowerShell on Windows. The Linux server is
a package recommendation, so a machine that skipped it gets the package
before the unit is started.
"""

import os
import subprocess

import pytest

import neutrino_agent.platforms.linux as linux_module
from neutrino_agent.modules import installers
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.modules.openssh import OpensshModuleReconciler
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform
from tests.conftest import discard

CAPABILITY_STATES = {"enabled", "disabled"}
PACKAGE_STATES = {"installed", "absent", "installing", "removing"}


class SwitchPlatform(AgentPlatform):
    """A machine whose SSH server is a switch, and which records its flips."""

    os_name = "linux"

    def __init__(self, *, is_running: bool):
        self.is_running = is_running
        self.calls: list = []

    def read_openssh_status(self, entry) -> bool:
        return self.is_running

    def enable_openssh(self, entry) -> None:
        self.calls.append("enable")
        self.is_running = True

    def disable_openssh(self, entry) -> None:
        self.calls.append("disable")
        self.is_running = False


def openssh_reconcile(platform, wish, *, entry=None):
    """One reconcile pass against a platform.

    Args:
        platform: The machine, behind the contract.
        wish: True to enable, False to disable, None to only report.
        entry: The manifest's platform entry; a Debian one by default.

    Returns:
        The typed status.
    """
    subject = OpensshModuleReconciler(platform=platform, log=discard)
    return subject.reconcile(
        name="openssh_server",
        manifest={"kind": "openssh"},
        entry={"service": "ssh"} if entry is None else entry,
        wanted=None if wish is None else {"is_enabled": wish},
    )


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


# --- the switch itself ---


def test_openssh_wanted_and_stopped_is_enabled():
    platform = SwitchPlatform(is_running=False)

    status = openssh_reconcile(platform, True)

    assert platform.calls == ["enable"]
    assert status == {"state": "enabled", "code": "", "params": {}, "is_active": False}


def test_openssh_unwanted_and_running_is_disabled():
    platform = SwitchPlatform(is_running=True)

    status = openssh_reconcile(platform, False)

    assert platform.calls == ["disable"]
    assert status == {"state": "disabled", "code": "", "params": {}, "is_active": False}


@pytest.mark.parametrize("is_running, state", [(True, "enabled"), (False, "disabled")])
def test_openssh_already_converged_is_reported_untouched(is_running, state):
    platform = SwitchPlatform(is_running=is_running)

    status = openssh_reconcile(platform, is_running)

    assert platform.calls == []
    assert status == {"state": state, "code": "", "params": {}, "is_active": False}


@pytest.mark.parametrize("is_running, state", [(True, "enabled"), (False, "disabled")])
def test_openssh_never_asked_is_reported_untouched(is_running, state):
    platform = SwitchPlatform(is_running=is_running)

    status = openssh_reconcile(platform, None)

    assert platform.calls == []
    assert status == {"state": state, "code": "", "params": {}, "is_active": False}


def test_openssh_states_are_the_capability_half_of_the_table():
    reported = set()

    for is_running in (True, False):
        for wish in (None, True, False):
            reported.add(
                openssh_reconcile(SwitchPlatform(is_running=is_running), wish)["state"]
            )

    assert reported == CAPABILITY_STATES
    assert not reported & PACKAGE_STATES


# --- what each platform actually runs ---


@pytest.mark.parametrize(
    "present, install_command",
    [
        ({"apt-get"}, ["apt-get", "install", "-y", "openssh-server"]),
        ({"dnf"}, ["dnf", "install", "-y", "openssh-server"]),
        (set(), ["yum", "install", "-y", "openssh-server"]),
    ],
)
def test_openssh_linux_enable_installs_the_server_first(
    monkeypatch, present, install_command
):
    linux_tools(monkeypatch, present=present)
    commands = recorded_commands(monkeypatch)
    monkeypatch.setattr(LinuxPlatform, "read_openssh_status", lambda self, entry: False)

    status = openssh_reconcile(LinuxPlatform(), True)

    assert commands == [install_command, ["systemctl", "enable", "--now", "ssh"]]
    assert status["state"] == "enabled"


def test_openssh_linux_enable_with_the_server_present_only_starts_the_unit(monkeypatch):
    linux_tools(monkeypatch, present={"sshd", "apt-get"})
    commands = recorded_commands(monkeypatch)
    monkeypatch.setattr(LinuxPlatform, "read_openssh_status", lambda self, entry: False)

    openssh_reconcile(LinuxPlatform(), True, entry={"service": "sshd"})

    assert commands == [["systemctl", "enable", "--now", "sshd"]]


def test_openssh_linux_disable_stops_the_named_unit(monkeypatch):
    linux_tools(monkeypatch, present={"sshd"})
    commands = recorded_commands(monkeypatch)
    monkeypatch.setattr(LinuxPlatform, "read_openssh_status", lambda self, entry: True)

    status = openssh_reconcile(LinuxPlatform(), False, entry={"service": "sshd"})

    assert commands == [["systemctl", "disable", "--now", "sshd"]]
    assert status["state"] == "disabled"


@pytest.mark.parametrize(
    "stdout, state", [("active\n", "enabled"), ("inactive\n", "disabled")]
)
def test_openssh_linux_status_is_systemd_own_word(monkeypatch, stdout, state):
    commands: list = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(linux_module.subprocess, "run", fake_run)

    status = openssh_reconcile(LinuxPlatform(), None)

    assert commands == [["systemctl", "is-active", "ssh"]]
    assert status["state"] == state


def test_openssh_linux_status_survives_a_systemctl_that_cannot_run(monkeypatch):
    def fake_run(command, **kwargs):
        raise OSError("no systemctl")

    monkeypatch.setattr(linux_module.subprocess, "run", fake_run)

    status = openssh_reconcile(LinuxPlatform(), None)

    assert status["state"] == "disabled"


@pytest.mark.parametrize(
    "wish, is_running, command",
    [
        (True, False, ["systemsetup", "-setremotelogin", "on"]),
        (False, True, ["systemsetup", "-f", "-setremotelogin", "off"]),
    ],
)
def test_openssh_darwin_switches_remote_login(monkeypatch, wish, is_running, command):
    commands = recorded_commands(monkeypatch)
    monkeypatch.setattr(
        DarwinPlatform, "read_openssh_status", lambda self, entry: is_running
    )

    status = openssh_reconcile(DarwinPlatform(), wish, entry={})

    assert commands == [command]
    assert status["state"] == ("enabled" if wish else "disabled")


@pytest.mark.parametrize(
    "wish, is_running, marker",
    [
        (True, False, "Add-WindowsCapability"),
        (False, True, "Set-Service -Name sshd -StartupType Disabled"),
    ],
)
def test_openssh_windows_switches_the_service(monkeypatch, wish, is_running, marker):
    commands = recorded_commands(monkeypatch)
    monkeypatch.setattr(
        WindowsPlatform, "read_openssh_status", lambda self, entry: is_running
    )

    status = openssh_reconcile(WindowsPlatform(), wish, entry={})

    assert len(commands) == 1
    assert commands[0][0] == "powershell"
    assert marker in commands[0][-1]
    assert status["state"] == ("enabled" if wish else "disabled")


def test_openssh_a_refusal_is_left_to_the_engine_to_type(monkeypatch):
    linux_tools(monkeypatch, present={"sshd"})
    monkeypatch.setattr(LinuxPlatform, "read_openssh_status", lambda self, entry: False)

    def refuse(command, **kwargs):
        raise InstallError("systemctl failed: Unit ssh.service is masked")

    monkeypatch.setattr(installers, "run_checked", refuse)

    with pytest.raises(InstallError) as caught:
        openssh_reconcile(LinuxPlatform(), True)

    assert "masked" in str(caught.value)
