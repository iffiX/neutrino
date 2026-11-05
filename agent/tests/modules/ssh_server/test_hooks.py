"""The SSH server's hooks, and the shared runner driving them.

What these pin: the program is the one under the agent's ``bin`` on each
system, the platform's own directory first; the module needs no install;
each instance's host key is made once with the program in its run
directory, and a failed making leaves nothing and refuses
``apply_failed``; the one host key of an earlier version is deleted; each
run directory and every file in it is root's, of the account's group,
0750 and 0640, and one an earlier version gave the account is taken back;
a link at a file, at its ``.new``, at the made key or at the run directory
turns no write, mode or owner onto another file; each instance runs the
program as its account on ``127.0.0.1`` at its port, with its host key and
its one authorized key in its run directory, its shell the row's, else the
login shell, else ``/bin/sh``, and PowerShell on Windows; on Linux the
template unit reads the port and the shell from each account's
environment file, on macOS the job carries the account's environment, and
on Windows the task signs in with the password and logs under the agent's
log root; the shared runner takes each instance's port from 22000 up;
each instance's details carry its host key and its fingerprint; and
through the shared runner two accounts run, each with its own host key, a
third refused, one disabled losing its unit and its run directory.
"""

import functools
import os
import stat

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared import account_service
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

from tests.conftest import chowned_path, fd_owners
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


# The state root of each system, which holds every command line program's
# launcher folder.
VAR_DIRS = {
    "linux": "/var/lib/neutrino/agent",
    "darwin": "/Library/Application Support/Neutrino/agent/state",
    "windows": "C:\\ProgramData\\Neutrino\\agent\\state",
}


class Platform(AgentPlatform):
    def __init__(self, os_name="linux", log_path=""):
        self.os_name = os_name
        self._log_path = log_path

    def agent_bin_dir(self):
        return BIN_DIRS[self.os_name]

    def agent_var_dir(self):
        return VAR_DIRS[self.os_name]

    def agent_log_path(self):
        return self._log_path

    def has_account(self, account):
        return account in ("lab", "dev")


class BinPlatform(Platform):
    def agent_bin_dir(self):
        return "/custom/bin"


class Machine:
    """The commands the hooks and the layer run: the program makes a key, systemctl answers, and each list ``setfacl --set`` writes is read back by ``getfacl``."""

    def __init__(self, *, is_failing=False):
        self.calls: list = []
        self.is_failing = is_failing
        self.lists: dict = {}

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[0] == "setfacl":
            self.lists[command[-1]] = command[2]
            return CommandResult(list(command), 0, "", "")
        if command[0] == "getfacl":
            path = command[-1]
            held = self.lists.get(path) or self.lists.get(path + ".new", "")
            return CommandResult(list(command), 0, held.replace(",", "\n"), "")
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

    def entries(self, account_uid: int) -> list:
        """Each path ``setfacl`` gave the uid's read entry, staged names folded in."""
        return sorted(
            {
                path[: -len(".new")] if path.endswith(".new") else path
                for path, entries in self.lists.items()
                if f"user:{account_uid}:" in entries
            }
        )

    def changes(self, first: int = 0) -> list:
        """The commands from ``first`` on, every ``getfacl`` left out."""
        return [call for call in self.calls[first:] if call[0] != "getfacl"]


def lookup(account):
    accounts = {"lab": LAB, "dev": DEV}
    if account not in accounts:
        raise KeyError(account)
    return accounts[account]


@pytest.fixture(autouse=True)
def owned(monkeypatch):
    """Owners given on a descriptor, read back by ``os.fstat`` as root would see them."""
    return fd_owners(monkeypatch, {})


class Owners:
    """Every change of owner, by the path of the open file or of the path given."""

    def __init__(self):
        self.given: list = []

    def __call__(self, target, uid, gid):
        self.given.append((chowned_path(target), uid, gid))
        if isinstance(target, int):
            os.fchown(target, uid, gid)


def machine_at(tmp_path, os_name="linux", run=None, chown=None):
    (tmp_path / "systemd").mkdir(exist_ok=True)
    return ServiceMachine(
        os_name=os_name,
        module_dir=str(tmp_path / "state" / "ssh_server"),
        record_dir=str(tmp_path / "config" / "ssh_server"),
        lookup_account=lookup,
        run=run if run is not None else Machine(),
        chown=chown if chown is not None else Owners(),
        systemd_dir=str(tmp_path / "systemd"),
    )


def hooks_for(tmp_path, os_name="linux", *, run=None, log_path="", chown=None):
    hooks = SshServerHooks(
        platform=Platform(os_name, log_path), log=lambda line: None, binary=BINARY
    )
    hooks.bind(machine_at(tmp_path, os_name, run, chown), None)
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


def host_key_of(hooks, account="lab"):
    return os.path.join(hooks.run_dir(account), "instance_host_key")


def test_each_instance_s_host_key_is_made_once_in_its_run_directory(tmp_path):
    run = Machine()
    owners = Owners()
    hooks = hooks_for(tmp_path, run=run, chown=owners)
    hooks.prepare_module()
    path = host_key_of(hooks)

    assert hooks.prepare(None, instance(), LAB) == [
        "made the host key of lab",
        "wrote the path folders of lab",
    ]
    assert hooks.prepare(None, instance(), LAB) == []

    assert run.made_keys() == [[BINARY, "--make-host-key", path + ".made"]]
    with open(path, encoding="ascii") as stream:
        assert stream.read() == private_key_text()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert (path, 0, 0) in owners.given
    assert path in run.entries(1001)
    assert not os.path.exists(path + ".made")
    assert not os.path.exists(path + ".new")
    for directory in (hooks.machine.module_dir, os.path.dirname(hooks.run_dir("x"))):
        assert stat.S_IMODE(os.stat(directory).st_mode) == 0o755


def test_a_host_key_that_cannot_be_made_refuses_and_leaves_nothing(tmp_path):
    hooks = hooks_for(tmp_path, run=Machine(is_failing=True))

    with pytest.raises(ModuleApplyError) as refusal:
        hooks.prepare(None, instance(), LAB)

    assert refusal.value.code == "apply_failed"
    assert "no such program" in refusal.value.params["detail"]
    assert not os.path.exists(host_key_of(hooks))
    assert not os.path.exists(host_key_of(hooks) + ".made")


def test_the_one_host_key_of_an_earlier_version_is_deleted(tmp_path):
    hooks = hooks_for(tmp_path)
    machine_key = tmp_path / "state" / "ssh_server" / "host_key"
    machine_key.parent.mkdir(parents=True)
    machine_key.write_text(private_key_text())

    assert hooks.prepare_module() == ["removed the machine's host key"]
    assert hooks.prepare_module() == []
    assert not machine_key.exists()


def test_each_instance_s_details_carry_its_host_key_and_its_fingerprint(tmp_path):
    hooks = hooks_for(tmp_path)
    assert hooks.details_extra({"account": "lab"}) == {
        "host_key": "",
        "host_key_fingerprint": "",
    }

    hooks.prepare(None, instance(), LAB)

    assert hooks.details_extra({"account": "lab"}) == {
        "host_key": PUBLIC_KEY,
        "host_key_fingerprint": PUBLIC_KEY_FINGERPRINT,
    }
    assert hooks.module_details() == {}


# --- the run directory ---


def test_the_run_directory_is_root_s_alone_and_the_account_reads_it_by_its_entry(
    tmp_path,
):
    owners = Owners()
    run = Machine()
    hooks = hooks_for(tmp_path, chown=owners, run=run)
    run_dir = hooks.run_dir("lab")

    hooks.prepare(None, instance(), LAB)

    assert stat.S_IMODE(os.stat(run_dir).st_mode) == 0o700
    assert (run_dir, 0, 0) in owners.given
    assert run.lists[run_dir] == (
        "user::rwx,user:1001:r-x,group::---,mask::r-x,other::---"
    )
    for name in ("instance_host_key", "path_folders"):
        path = os.path.join(run_dir, name)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert (path, 0, 0) in owners.given
    assert run.entries(1001) == sorted(
        [run_dir]
        + [
            os.path.join(run_dir, name)
            for name in ("instance_host_key", "path_folders")
        ]
    )
    assert [given for given in owners.given if given[2] != 0] == []


def test_a_run_directory_an_earlier_version_gave_the_account_is_taken_back(
    tmp_path,
):
    owners = Owners()
    run = Machine()
    hooks = hooks_for(tmp_path, chown=owners, run=run)
    run_dir = hooks.run_dir("lab")
    os.makedirs(run_dir, mode=0o700)
    os.chmod(run_dir, 0o700)
    copy = os.path.join(run_dir, "host_key")
    with open(copy, "w", encoding="ascii") as stream:
        stream.write("the machine's host key")

    planted = os.path.join(run_dir, "authorized_key.new")
    os.symlink("/etc/passwd", planted)

    hooks.prepare(None, instance(), LAB)

    assert stat.S_IMODE(os.stat(run_dir).st_mode) == 0o700
    assert owners.given[0] == (run_dir, 0, 0)
    assert not os.path.exists(copy)
    assert not os.path.lexists(planted)
    assert len(run.made_keys()) == 1


@pytest.mark.parametrize(
    "planted",
    [
        "instance_host_key.made",
        "instance_host_key.new",
        "path_folders",
        "path_folders.new",
        "authorized_key",
        "authorized_key.new",
    ],
)
def test_a_link_in_the_run_directory_turns_no_write_mode_or_owner_onto_another_file(
    tmp_path, planted
):
    owners = Owners()
    hooks = hooks_for(tmp_path, chown=owners)
    run_dir = hooks.run_dir("lab")
    os.makedirs(run_dir)
    held = tmp_path / "held"
    held.write_text("kept\n")
    os.chmod(held, 0o600)
    os.symlink(held, os.path.join(run_dir, planted))
    service = None

    hooks.prepare(None, instance(programs=("codex",)), LAB)
    service = hooks.service(instance(), LAB, {"account": "lab", "port": 22000})
    for path, text in service.read_files:
        account_service.write_read_file(path, text, "lab", hooks.machine)

    assert held.read_text() == "kept\n"
    assert stat.S_IMODE(held.stat().st_mode) == 0o600
    assert str(held) not in [path for path, _uid, _gid in owners.given]
    for name in ("instance_host_key", "path_folders", "authorized_key"):
        assert not os.path.islink(os.path.join(run_dir, name))


def test_a_link_at_the_run_directory_is_never_followed(tmp_path):
    owners = Owners()
    hooks = hooks_for(tmp_path, chown=owners)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.chmod(elsewhere, 0o700)
    os.makedirs(os.path.dirname(hooks.run_dir("lab")))
    os.symlink(elsewhere, hooks.run_dir("lab"))

    with pytest.raises(OSError):
        hooks.prepare(None, instance(), LAB)

    assert os.listdir(elsewhere) == []
    assert stat.S_IMODE(elsewhere.stat().st_mode) == 0o700
    assert owners.given == []


# --- the instance ---


def test_a_linux_instance_reads_its_port_and_shell_from_its_environment(tmp_path):
    hooks = hooks_for(tmp_path)
    hooks.prepare(None, instance(), LAB)
    run_dir = hooks.run_dir("lab")

    service = hooks.service(
        instance(programs=("codex", "claude_code")),
        LAB,
        {"account": "lab", "port": 22000},
    )

    assert service.command == (
        BINARY,
        "--listen",
        "127.0.0.1:${NEUTRINO_SSH_SERVER_PORT}",
        "--host-key",
        os.path.join(run_dir, "instance_host_key"),
        "--authorized-key",
        os.path.join(run_dir, "authorized_key"),
        "--shell",
        "${NEUTRINO_SSH_SERVER_SHELL}",
        "--path-folders",
        os.path.join(run_dir, "path_folders"),
    )
    assert service.environment == {
        "NEUTRINO_SSH_SERVER_PORT": "22000",
        "NEUTRINO_SSH_SERVER_SHELL": "/bin/bash",
    }
    assert service.read_files == (
        (os.path.join(run_dir, "instance_host_key"), private_key_text()),
        (os.path.join(run_dir, "authorized_key"), PUBLIC_KEY + "\n"),
    )
    assert service.files == ()
    assert service.directories == ()
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
        instance(programs=("claude_code",)),
        AccountEntry(501, 20, "/Users/lab", "/bin/zsh"),
        {"port": 22001},
    )

    assert service.command[1:3] == ("--listen", "127.0.0.1:22001")
    assert service.command[-4:-2] == ("--shell", "/bin/zsh")
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
        instance(password="pw", programs=("codex",)),  # scan: allow
        AccountEntry(0, 0, "C:\\Users\\lab", ""),
        {"port": 22002},
    )

    assert service.command[1:3] == ("--listen", "127.0.0.1:22002")
    assert service.command[-4:] == (
        "--shell",
        windows_powershell(),
        "--path-folders",
        hooks.run_dir("lab") + "\\path_folders",
    )
    assert windows_powershell() == (
        "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    )
    assert service.password == "pw"  # scan: allow
    assert service.environment == {}
    assert service.working_directory == ""
    assert service.log_name == (
        "C:\\ProgramData\\Neutrino\\agent\\log\\ssh_server_lab.log"
    )


@pytest.mark.parametrize("os_name", ["linux", "darwin", "windows"])
def test_the_service_does_not_change_with_the_account_s_programs(tmp_path, os_name):
    hooks = hooks_for(tmp_path, os_name)
    entry = AccountEntry(1001, 1001, "/home/lab", "/bin/bash")

    services = [
        hooks.service(
            instance(password="pw", programs=programs),  # scan: allow
            entry,
            {"account": "lab", "port": 22000},
        )
        for programs in ((), ("codex",), ("codex", "claude_code"))
    ]

    assert services[0] == services[1] == services[2]


# --- the PATH of a session ---


def path_folders_of(hooks, account="lab"):
    return os.path.join(hooks.run_dir(account), "path_folders")


def test_the_path_folders_file_names_each_launcher_folder_and_changes_only_with_them(
    tmp_path,
):
    hooks = hooks_for(tmp_path)
    hooks.prepare(None, instance(), LAB)
    path = path_folders_of(hooks)

    notes = hooks.prepare(None, instance(programs=("codex", "claude_code")), LAB)

    assert notes == ["wrote the path folders of lab"]
    with open(path, encoding="utf-8") as stream:
        assert stream.read() == (
            "/var/lib/neutrino/agent/claude_code/bin\n"
            "/var/lib/neutrino/agent/codex/bin\n"
        )
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    written = os.stat(path)

    assert hooks.prepare(None, instance(programs=("claude_code", "codex")), LAB) == []
    assert (os.stat(path).st_ino, os.stat(path).st_mtime_ns) == (
        written.st_ino,
        written.st_mtime_ns,
    )

    assert hooks.prepare(None, instance(), LAB) == ["wrote the path folders of lab"]
    with open(path, encoding="utf-8") as stream:
        assert stream.read() == ""
    assert sorted(os.listdir(hooks.run_dir("lab"))) == [
        "instance_host_key",
        "path_folders",
    ]


def test_a_new_account_s_path_folders_file_is_written_before_its_run_directory_exists(
    tmp_path,
):
    hooks = hooks_for(tmp_path)

    hooks.prepare(None, instance(account="dev", programs=("codex",)), DEV)

    with open(path_folders_of(hooks, "dev"), encoding="utf-8") as stream:
        assert stream.read() == "/var/lib/neutrino/agent/codex/bin\n"


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


def config(*accounts, programs=()):
    return {
        "instances": [
            {
                "account": account,
                "authorized_key": PUBLIC_KEY,
                "shell_path": "",
                "programs": list(programs),
            }
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
    for account, uid, other in (("lab", 1001, 1002), ("dev", 1002, 1001)):
        run_dir = tmp_path / "state" / "ssh_server" / "run" / account
        assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
        named = [str(run_dir)]
        for name in ("instance_host_key", "authorized_key", "path_folders"):
            assert stat.S_IMODE((run_dir / name).stat().st_mode) == 0o600
            named.append(str(run_dir / name))
        entries = runner.machine.run.entries
        assert [path for path in entries(uid) if path.startswith(str(run_dir))] == (
            sorted(named)
        )
        assert [path for path in entries(other) if path.startswith(str(run_dir))] == []
    assert len(runner.machine.run.made_keys()) == 2
    details = runner.details({})
    assert "host_key" not in details
    assert [
        (
            row["account"],
            row["port"],
            row["is_running"],
            row["host_key"],
            row["host_key_fingerprint"],
        )
        for row in details["instances"]
    ] == [
        ("dev", 22001, True, PUBLIC_KEY, PUBLIC_KEY_FINGERPRINT),
        ("lab", 22000, True, PUBLIC_KEY, PUBLIC_KEY_FINGERPRINT),
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


def test_a_change_of_programs_rewrites_the_file_alone_and_restarts_no_instance(
    runner, tmp_path
):
    runner.apply(config("lab", programs=["codex"]))
    unit = tmp_path / "systemd" / "neutrino_ssh_server@.service"
    environment = tmp_path / "config" / "ssh_server" / "lab.env"
    held = (unit.read_text(), environment.read_text())
    path = tmp_path / "state" / "ssh_server" / "run" / "lab" / "path_folders"
    assert path.read_text() == "/var/lib/neutrino/agent/codex/bin\n"
    calls = runner.machine.run.calls
    first = len(calls)

    runner.apply(config("lab", programs=["codex", "claude_code"]))
    runner.apply(config("lab"))

    assert path.read_text() == ""
    assert (unit.read_text(), environment.read_text()) == held
    assert [
        call for call in runner.machine.run.changes(first) if call[0] != "setfacl"
    ] == [["systemctl", "enable", "--now", "neutrino_ssh_server@lab.service"]] * 2


def test_no_account_enabled_reads_stopped(runner):
    runner.apply(config())

    assert runner.is_active() is False
    assert runner.details({})["instances"] == []
