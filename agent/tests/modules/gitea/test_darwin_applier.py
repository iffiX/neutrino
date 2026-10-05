"""The git server on macOS, with every system tool faked.

What these pin: git found by the tools' own paths and never ``/usr/bin/git``;
the hidden account made with ``sysadminctl`` and read back, its refusal
carrying the tool's line when the record is not usable; the data directory
and ``app.ini`` the account's own; the LaunchDaemon run as the account with
the git's directory first on its ``PATH``; an apply that starts, keeps or
restarts the job; a stop that waits until launchd lets go; the CLI run as
the account; and an uninstall that keeps the data and the account.
"""

import plistlib

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.gitea.darwin_applier import GiteaDarwinApplier
from neutrino_agent.modules.subprocess_run import CommandResult

ACCOUNT_RECORD = (
    "NFSHomeDirectory: /x/gitea_data\nPrimaryGroupID: 20\n"
    "UniqueID: 502\nUserShell: /usr/bin/false\n"
)


class FakeTools:
    """Every command recorded, answered by a test-held table of states."""

    def __init__(self):
        self.calls: list = []
        self.has_account = False
        self.is_refusing_account = False
        self.is_loaded = False
        self.is_running = False
        self.version = "Gitea version 1.27.3 built with GNU Make 4.4.1, go1.25.3\n"

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        command = list(command)
        self.calls.append(command)
        if command[:2] == ["sysadminctl", "-addUser"]:
            if self.is_refusing_account:
                return CommandResult(
                    command,
                    0,
                    "",
                    "2026-10-05 10:00:00.000 sysadminctl[1:2] User with full name "
                    "'Neutrino Gitea' already exists.\n",
                )
            self.has_account = True
            return CommandResult(command, 0, "", "")
        if command[:3] == ["dscl", ".", "-read"]:
            if self.has_account:
                return CommandResult(command, 0, ACCOUNT_RECORD, "")
            return CommandResult(command, 56, "", "eDSRecordNotFound")
        if command[:2] == ["launchctl", "print"]:
            if not self.is_loaded:
                return CommandResult(command, 113, "", "")
            state = "running" if self.is_running else "spawn scheduled"
            return CommandResult(command, 0, f"\tstate = {state}\n", "")
        if command[:2] == ["launchctl", "bootstrap"]:
            self.is_loaded = self.is_running = True
        if command[:2] == ["launchctl", "bootout"]:
            self.is_loaded = self.is_running = False
        if command[1:] == ["--version"]:
            return CommandResult(command, 0, self.version, "")
        return CommandResult(command, 0, "", "")

    def ran(self, *words) -> list:
        return [call for call in self.calls if call[: len(words)] == list(words)]


@pytest.fixture
def tools():
    return FakeTools()


@pytest.fixture
def applier(tools, tmp_path):
    held = GiteaDarwinApplier(
        state_dir=str(tmp_path / "state"),
        run=tools,
        run_as=lambda entry, command, environment, cwd: tools.cli(
            entry, command, environment, cwd
        ),
        lookup_account=lambda account: (502, 20),
        chown=lambda path, uid, gid: tools.calls.append(["chown", path, uid, gid]),
        is_executable=lambda path: path in tools.gits,
        launchd_dir=str(tmp_path / "LaunchDaemons"),
        output_path=str(tmp_path / "Logs" / "gitea.log"),
        sleep=lambda seconds: None,
    )
    (tmp_path / "LaunchDaemons").mkdir()
    tools.gits = {"/opt/homebrew/bin/git"}
    tools.cli_calls = []

    def cli(entry, command, environment, cwd):
        tools.cli_calls.append((entry, command, environment, cwd))
        return CommandResult(
            command, 0, "ID   Username   Email   IsActive\n1   ann   a@x   true\n", ""
        )

    tools.cli = cli
    return held


@pytest.fixture
def binary(tmp_path):
    path = tmp_path / "downloaded"
    path.write_bytes(b"\xcf\xfa\xed\xfe")
    return str(path)


def test_git_is_found_by_the_tools_own_paths_and_never_the_stub(applier, tools):
    tools.gits = {
        "/usr/bin/git",
        "/opt/homebrew/bin/git",
        "/Library/Developer/CommandLineTools/usr/bin/git",
    }
    assert applier.find_git() == "/Library/Developer/CommandLineTools/usr/bin/git"

    tools.gits = {"/usr/bin/git"}
    assert applier.find_git() == ""


def test_the_layout_names_the_account_the_data_and_no_ssh(applier, tmp_path):
    layout = applier.layout("/opt/homebrew/bin/git")

    assert layout.run_user == "neutrino_gitea"
    assert layout.work_path == str(tmp_path / "state" / "gitea_data")
    assert layout.git_path == "/opt/homebrew/bin/git"
    assert layout.is_ssh_served is False


def test_an_install_makes_the_hidden_account_and_puts_the_binary_in_place(
    applier, tools, binary, tmp_path
):
    applier.install(binary)

    (made,) = tools.ran("sysadminctl", "-addUser")
    assert made[2:][:7] == [
        "neutrino_gitea",
        "-fullName",
        "Neutrino Gitea",
        "-shell",
        "/usr/bin/false",
        "-home",
        str(tmp_path / "state" / "gitea_data"),
    ]
    assert tools.ran("dscl", ".", "-create") == [
        ["dscl", ".", "-create", "/Users/neutrino_gitea", "IsHidden", "1"]
    ]
    gitea = tmp_path / "state" / "gitea" / "gitea"
    assert gitea.read_bytes() == b"\xcf\xfa\xed\xfe"
    assert gitea.stat().st_mode & 0o777 == 0o755
    data = tmp_path / "state" / "gitea_data"
    assert data.stat().st_mode & 0o777 == 0o700
    for part in ("custom/conf", "data", "log"):
        assert (data / part).is_dir()
    assert ["chown", str(data), 502, 20] in tools.calls


def test_an_account_made_already_is_not_made_again(applier, tools, binary):
    tools.has_account = True

    applier.install(binary)

    assert tools.ran("sysadminctl") == []


def test_a_refusal_sysadminctl_exits_0_on_is_refused_with_its_line(
    applier, tools, binary
):
    tools.is_refusing_account = True

    with pytest.raises(ModuleApplyError) as refused:
        applier.install(binary)

    assert refused.value.code == "user_create_failed"
    assert refused.value.params == {
        "user": "neutrino_gitea",
        "detail": "User with full name 'Neutrino Gitea' already exists.",
    }


def test_an_apply_writes_app_ini_and_the_job_and_starts_it(applier, tools, tmp_path):
    tools.has_account = True

    note = applier.apply(
        "[server]\nHTTP_PORT = 3000\n", git_path="/opt/homebrew/bin/git"
    )

    assert note == "started"
    conf = tmp_path / "state" / "gitea_data" / "custom" / "conf" / "app.ini"
    assert conf.read_text() == "[server]\nHTTP_PORT = 3000\n"
    assert conf.stat().st_mode & 0o777 == 0o600
    assert ["chown", str(conf), 502, 20] in tools.calls
    plist_path = tmp_path / "LaunchDaemons" / "com.neutrino.gitea.plist"
    job = plistlib.loads(plist_path.read_bytes())
    assert job["UserName"] == "neutrino_gitea"
    assert job["ProgramArguments"] == [
        str(tmp_path / "state" / "gitea" / "gitea"),
        "web",
        "--config",
        str(conf),
    ]
    assert job["EnvironmentVariables"]["PATH"].startswith("/opt/homebrew/bin:")
    assert job["EnvironmentVariables"]["USER"] == "neutrino_gitea"
    assert job["KeepAlive"] is True
    assert tools.ran("launchctl", "bootstrap") == [
        ["launchctl", "bootstrap", "system", str(plist_path)]
    ]
    assert applier.read_listen_port() == 3000
    assert applier.is_active() is True


def test_a_second_apply_keeps_a_running_job_and_a_changed_app_ini_restarts_it(
    applier, tools
):
    tools.has_account = True
    applier.apply("one\n", git_path="/opt/homebrew/bin/git")
    tools.calls.clear()

    assert applier.apply("one\n", git_path="/opt/homebrew/bin/git") == "unchanged"
    assert applier.apply("two\n", git_path="/opt/homebrew/bin/git") == "restarted"
    assert tools.ran("launchctl", "kickstart") == [
        ["launchctl", "kickstart", "-k", "system/com.neutrino.gitea"]
    ]


def test_a_stop_unloads_the_job_and_keeps_its_plist(applier, tools, tmp_path):
    tools.has_account = True
    applier.apply("one\n", git_path="/opt/homebrew/bin/git")

    applier.stop()

    assert applier.is_active() is False
    assert (tmp_path / "LaunchDaemons" / "com.neutrino.gitea.plist").exists()


def test_the_cli_runs_as_the_servers_account(applier, tools, binary):
    tools.has_account = True
    applier.install(binary)
    applier.apply("x\n", git_path="/opt/homebrew/bin/git")

    state = applier.survey()
    applier.create_admin(username="ann", password="pw", email="a@x")

    assert state.version == "1.27.3"
    assert state.admin_usernames == ["ann"]
    entry, command, environment, cwd = tools.cli_calls[-1]
    assert entry == (502, 20)
    assert command[1:4] == ["admin", "user", "create"]
    assert command[-2] == "--config"
    assert environment["USER"] == "neutrino_gitea"
    assert environment["HOME"] == cwd == applier.data_dir


def test_an_uninstall_keeps_the_data_and_the_account(applier, tools, binary, tmp_path):
    tools.has_account = True
    applier.install(binary)
    applier.apply("x\n", git_path="/opt/homebrew/bin/git")
    repository = tmp_path / "state" / "gitea_data" / "data" / "gitea_repositories"
    repository.mkdir()

    applier.uninstall()

    assert not (tmp_path / "state" / "gitea").exists()
    assert not (tmp_path / "LaunchDaemons" / "com.neutrino.gitea.plist").exists()
    assert not (
        tmp_path / "state" / "gitea_data" / "custom" / "conf" / "app.ini"
    ).exists()
    assert repository.is_dir()
    assert tools.ran("dscl", ".", "-delete") == []
    assert tools.ran("sysadminctl", "-deleteUser") == []
    assert applier.is_active() is False
