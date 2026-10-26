"""The SSH server's hooks, and the shared runner driving them.

What these pin: the program is the one under the agent's ``bin`` on each
system, the platform's own directory first; the module needs no install;
the host key is made once with the program, root's alone under the
module's directory, and a failed making leaves nothing and refuses
``apply_failed``; each instance runs the program as its account on
``127.0.0.1`` at its port, with the copy of the host key and its one
authorized key in its run directory, the account's own, its shell the
row's, else the login shell, else ``/bin/sh``, and PowerShell on Windows;
on Linux the template unit reads the port and the shell from each
account's environment file, on macOS the job carries the account's
environment, and on Windows the task signs in with the password and logs
under the agent's log root; the shared runner takes each instance's port
from 22000 up; the details carry the host key and its fingerprint; and
through the shared runner two accounts run, a third refused, one disabled
losing its unit and its run directory.
"""

import functools
import os
import stat

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.instances import InstancesModuleRunner
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.modules.ssh_server.config import SshServerInstance
from neutrino_agent.modules.ssh_server.hooks import (
    SshServerHooks,
    binary_path,
    windows_powershell,
)
from neutrino_agent.platforms.base import AgentPlatform

from tests.modules.ssh_server.conftest import (
    PUBLIC_KEY,
    PUBLIC_KEY_FINGERPRINT,
    private_key_text,
)

BINARY = "/opt/neutrino/agent/bin/neutrino_ssh_server"
LAB = AccountEntry(1001, 1001, "/home/lab", "/bin/bash")
DEV = AccountEntry(1002, 1002, "/home/dev", "")


# Where each system's package puts the agent's Go programs.
BIN_DIRS = {
    "linux": "/opt/neutrino/agent/bin",
    "darwin": "/Library/Application Support/Neutrino/agent/app/bin",
    "windows": "C:\\Program Files\\Neutrino\\agent\\bin",
}


class Platform(AgentPlatform):
    def __init__(self, os_name="linux", log_path=""):
        self.os_name = os_name
        self._log_path = log_path

    def agent_bin_dir(self):
        return BIN_DIRS[self.os_name]

    def agent_log_path(self):
        return self._log_path


class BinPlatform(Platform):
    def agent_bin_dir(self):
        return "/custom/bin"


class Machine:
    """The commands the hooks and the layer run: the program makes a key, systemctl answers."""

    def __init__(self, *, is_failing=False):
        self.calls: list = []
        self.is_failing = is_failing

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[1:2] == ["--make-host-key"]:
            if self.is_failing:
                raise OSError("no such program")
            with open(command[2], "w", encoding="ascii") as stream:
                stream.write(private_key_text())
            return CommandResult(list(command), 0, PUBLIC_KEY + "\n", "")
        if command[:2] == ["systemctl", "is-active"]:
            return CommandResult(list(command), 0, "active\n", "")
        return CommandResult(list(command), 0, "", "")

    def made_keys(self):
        return [call for call in self.calls if call[1:2] == ["--make-host-key"]]


def lookup(account):
    accounts = {"lab": LAB, "dev": DEV}
    if account not in accounts:
        raise KeyError(account)
    return accounts[account]


def machine_at(tmp_path, os_name="linux", run=None):
    (tmp_path / "systemd").mkdir(exist_ok=True)
    return ServiceMachine(
        os_name=os_name,
        module_dir=str(tmp_path / "state" / "ssh_server"),
        record_dir=str(tmp_path / "config" / "ssh_server"),
        lookup_account=lookup,
        run=run if run is not None else Machine(),
        chown=lambda path, uid, gid: None,
        systemd_dir=str(tmp_path / "systemd"),
    )


def hooks_for(tmp_path, os_name="linux", *, run=None, log_path=""):
    hooks = SshServerHooks(
        platform=Platform(os_name, log_path), log=lambda line: None, binary=BINARY
    )
    hooks.bind(machine_at(tmp_path, os_name, run), None)
    return hooks


def instance(account="lab", **fields):
    return SshServerInstance(account=account, authorized_key=PUBLIC_KEY, **fields)


# --- the program ---


@pytest.mark.parametrize(
    "os_name, path",
    [
        ("linux", "/opt/neutrino/agent/bin/neutrino_ssh_server"),
        (
            "darwin",
            "/Library/Application Support/Neutrino/agent/app/bin/neutrino_ssh_server",
        ),
        ("windows", "C:\\Program Files\\Neutrino\\agent\\bin\\neutrino_ssh_server.exe"),
    ],
)
def test_the_program_is_the_one_under_the_agent_s_bin(os_name, path):
    assert binary_path(Platform(os_name)) == path


def test_the_program_is_under_the_platform_s_own_bin_directory():
    assert binary_path(BinPlatform("linux")) == "/custom/bin/neutrino_ssh_server"


def test_the_module_needs_no_install(tmp_path):
    assert hooks_for(tmp_path).verify() is True


# --- the host key ---


def test_the_host_key_is_made_once_and_kept_root_s_alone(tmp_path):
    run = Machine()
    hooks = hooks_for(tmp_path, run=run)

    assert hooks.prepare_module() == ["made the host key"]
    assert hooks.prepare_module() == []

    assert run.made_keys() == [
        [BINARY, "--make-host-key", hooks.host_key_path + ".new"]
    ]
    assert stat.S_IMODE(os.stat(hooks.host_key_path).st_mode) == 0o600
    assert not os.path.exists(hooks.host_key_path + ".new")
    for directory in (hooks.machine.module_dir, os.path.dirname(hooks.run_dir("x"))):
        assert stat.S_IMODE(os.stat(directory).st_mode) == 0o755


def test_a_host_key_that_cannot_be_made_refuses_and_leaves_nothing(tmp_path):
    hooks = hooks_for(tmp_path, run=Machine(is_failing=True))

    with pytest.raises(ModuleApplyError) as refusal:
        hooks.prepare_module()

    assert refusal.value.code == "apply_failed"
    assert "no such program" in refusal.value.params["detail"]
    assert not os.path.exists(hooks.host_key_path)
    assert not os.path.exists(hooks.host_key_path + ".new")


def test_the_details_carry_the_host_key_and_its_fingerprint(tmp_path):
    hooks = hooks_for(tmp_path)
    assert hooks.module_details() == {"host_key": "", "host_key_fingerprint": ""}

    hooks.prepare_module()

    assert hooks.module_details() == {
        "host_key": PUBLIC_KEY,
        "host_key_fingerprint": PUBLIC_KEY_FINGERPRINT,
    }


# --- the instance ---


def test_a_linux_instance_reads_its_port_and_shell_from_its_environment(tmp_path):
    hooks = hooks_for(tmp_path)
    hooks.prepare_module()
    run_dir = hooks.run_dir("lab")

    service = hooks.service(instance(), LAB, {"account": "lab", "port": 22000})

    assert service.command == (
        BINARY,
        "--listen",
        "127.0.0.1:${NEUTRINO_SSH_SERVER_PORT}",
        "--host-key",
        os.path.join(run_dir, "host_key"),
        "--authorized-key",
        os.path.join(run_dir, "authorized_key"),
        "--shell",
        "${NEUTRINO_SSH_SERVER_SHELL}",
    )
    assert service.environment == {
        "NEUTRINO_SSH_SERVER_PORT": "22000",
        "NEUTRINO_SSH_SERVER_SHELL": "/bin/bash",
    }
    assert service.files == (
        (os.path.join(run_dir, "host_key"), private_key_text()),
        (os.path.join(run_dir, "authorized_key"), PUBLIC_KEY + "\n"),
    )
    assert service.directories == (run_dir,)
    assert service.working_directory == "~"
    assert service.listen_port == 22000
    assert service.account == "lab"
    assert service.name == "ssh_server"


@pytest.mark.parametrize(
    "fields, entry, shell",
    [
        ({"shell_path": "/usr/bin/fish"}, LAB, "/usr/bin/fish"),
        ({}, LAB, "/bin/bash"),
        ({}, DEV, "/bin/sh"),
    ],
    ids=["the row's", "the login shell", "the fallback"],
)
def test_the_shell_is_the_row_s_else_the_login_shell(tmp_path, fields, entry, shell):
    service = hooks_for(tmp_path).service(
        instance(**fields), entry, {"account": "lab", "port": 22000}
    )

    assert service.environment["NEUTRINO_SSH_SERVER_SHELL"] == shell


def test_a_mac_instance_carries_the_account_s_environment(tmp_path):
    service = hooks_for(tmp_path, "darwin").service(
        instance(), AccountEntry(501, 20, "/Users/lab", "/bin/zsh"), {"port": 22001}
    )

    assert service.command[1:3] == ("--listen", "127.0.0.1:22001")
    assert service.command[-2:] == ("--shell", "/bin/zsh")
    assert service.environment == {
        "HOME": "/Users/lab",
        "USER": "lab",
        "LOGNAME": "lab",
        "SHELL": "/bin/zsh",
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    assert service.log_name == ""


def test_a_windows_instance_signs_in_with_its_password_and_logs_under_the_log_root(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("SystemRoot", raising=False)
    hooks = hooks_for(
        tmp_path,
        "windows",
        log_path="C:\\ProgramData\\Neutrino\\agent\\log\\agent.log",
    )

    service = hooks.service(
        instance(password="pw"),  # scan: allow
        AccountEntry(0, 0, "C:\\Users\\lab", ""),
        {"port": 22002},
    )

    assert service.command[1:3] == ("--listen", "127.0.0.1:22002")
    assert service.command[-2:] == ("--shell", windows_powershell())
    assert windows_powershell() == (
        "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    )
    assert service.password == "pw"  # scan: allow
    assert service.environment == {}
    assert service.working_directory == ""
    assert service.log_name == (
        "C:\\ProgramData\\Neutrino\\agent\\log\\ssh_server_lab.log"
    )


# --- the port ---


def test_the_record_is_the_account_and_the_port_the_runner_took(tmp_path):
    hooks = hooks_for(tmp_path)
    hooks.prepare_module()

    assert hooks.record(None, instance(), {"port": 22005}) == {
        "account": "lab",
        "port": 22005,
    }
    assert hooks.base_port == 22000


# --- through the shared runner ---


@pytest.fixture
def runner(tmp_path):
    machine = machine_at(tmp_path)
    hooks_class = functools.partial(SshServerHooks, binary=BINARY)
    return InstancesModuleRunner(
        hooks_class=hooks_class,
        platform=Platform(),
        log=lambda line: None,
        machine=machine,
        is_port_free=lambda port: True,
    )


def config(*accounts):
    return {
        "instances": [
            {"account": account, "authorized_key": PUBLIC_KEY, "shell_path": ""}
            for account in accounts
        ]
    }


def test_two_accounts_run_each_on_its_own_port(runner, tmp_path):
    runner.apply(config("lab", "dev"))

    unit = (tmp_path / "systemd" / "neutrino_ssh_server@.service").read_text()
    assert "User=%i" in unit
    assert (
        f"ExecStart={BINARY} --listen 127.0.0.1:${{NEUTRINO_SSH_SERVER_PORT}}" in unit
    )
    environment = tmp_path / "config" / "ssh_server" / "lab.env"
    assert "NEUTRINO_SSH_SERVER_PORT=22000" in environment.read_text()
    for account in ("lab", "dev"):
        run_dir = tmp_path / "state" / "ssh_server" / "run" / account
        assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
        for name in ("host_key", "authorized_key"):
            assert stat.S_IMODE((run_dir / name).stat().st_mode) == 0o600
    details = runner.details({})
    assert details["host_key"] == PUBLIC_KEY
    assert details["host_key_fingerprint"] == PUBLIC_KEY_FINGERPRINT
    assert [
        (row["account"], row["port"], row["is_running"]) for row in details["instances"]
    ] == [
        ("dev", 22001, True),
        ("lab", 22000, True),
    ]
    assert runner.is_active() is True


def test_an_account_the_machine_lacks_is_refused(runner):
    with pytest.raises(ModuleApplyError) as refusal:
        runner.apply(config("lab", "ghost"))

    assert (refusal.value.code, refusal.value.params) == (
        "account_unknown",
        {"account": "ghost"},
    )


def test_a_disabled_account_loses_its_unit_and_its_run_directory(runner, tmp_path):
    runner.apply(config("lab", "dev"))

    runner.apply(config("lab"))

    calls = runner.machine.run.calls
    assert ["systemctl", "disable", "--now", "neutrino_ssh_server@dev.service"] in calls
    assert not (tmp_path / "state" / "ssh_server" / "run" / "dev").exists()
    assert [row["account"] for row in runner.details({})["instances"]] == ["lab"]


def test_no_account_enabled_reads_stopped(runner):
    runner.apply(config())

    assert runner.is_active() is False
    assert runner.details({})["instances"] == []
