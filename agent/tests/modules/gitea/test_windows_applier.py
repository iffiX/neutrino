"""The git server on Windows, with ``sc.exe``, the registry and the file
system faked.

What these pin: Git for Windows found on the machine's ``Path`` as the
service reads it, and under ``%ProgramFiles%\\Git\\cmd`` when the ``Path``
names none; the layout's ``RUN_USER``, forward slashes and service name; the
service made with ``sc.exe`` as LocalSystem, started at boot and again after
a failure, its binary path quoted; a running server stopped before its
binary is replaced; an apply that starts, keeps or restarts it; the CLI run
by the agent itself; and an uninstall that deletes the service and keeps
the data.
"""

import ntpath
import os

import pytest

from neutrino_agent.modules.gitea.windows_applier import GiteaWindowsApplier
from neutrino_agent.modules.subprocess_run import CommandResult

STATE = "C:\\ProgramData\\Neutrino\\agent\\state"


class FakeSc:
    """``sc.exe`` and the binary, recorded, with one service's state."""

    def __init__(self):
        self.calls: list = []
        self.exists = False
        self.state = "STOPPED"

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        command = list(command)
        self.calls.append(command)
        if command[0] == "sc.exe":
            verb = command[1]
            if verb == "query":
                if not self.exists:
                    return CommandResult(command, 1060, "", "")
                return CommandResult(
                    command, 0, f"        STATE              : 4  {self.state}\n", ""
                )
            if verb == "create":
                self.exists = True
            if verb == "start":
                self.state = "RUNNING"
            if verb == "stop":
                self.state = "STOPPED"
            if verb == "delete":
                self.exists = False
            return CommandResult(command, 0, "", "")
        if command[1:] == ["--version"]:
            return CommandResult(command, 0, "Gitea version 1.27.3 built with go\n", "")
        return CommandResult(
            command, 0, "ID   Username   Email   IsActive\n1   ann   a@x   true\n", ""
        )

    def sc(self, verb) -> list:
        return [call for call in self.calls if call[:2] == ["sc.exe", verb]]


@pytest.fixture
def sc():
    return FakeSc()


def windows_files(files: set):
    return lambda path: path in files


def make(sc, tmp_path, *, machine_path="", files=None, state=STATE):
    return GiteaWindowsApplier(
        state_dir=state,
        run=sc,
        read_machine_path=lambda: machine_path,
        is_file=windows_files(files or set()),
        expand=lambda text: text.replace("%ProgramFiles%", "C:\\Program Files"),
        join=ntpath.join if state == STATE else os.path.join,
        user="NMXWIN$",
        sleep=lambda seconds: None,
    )


def test_git_is_found_on_the_machines_path_as_the_service_reads_it(sc, tmp_path):
    applier = make(
        sc,
        tmp_path,
        machine_path="C:\\Windows\\system32;%ProgramFiles%\\Git\\cmd;C:\\Tools",
        files={"C:\\Program Files\\Git\\cmd\\git.exe", "C:\\Tools\\git.exe"},
    )

    assert applier.find_git() == "C:\\Program Files\\Git\\cmd\\git.exe"


def test_git_is_looked_for_where_git_for_windows_installs_when_the_path_has_none(
    sc, tmp_path
):
    fallback = "C:\\Program Files\\Git\\cmd\\git.exe"
    assert make(sc, tmp_path, files={fallback}).find_git() == fallback
    assert make(sc, tmp_path).find_git() == ""


def test_the_layout_runs_as_localsystem_with_forward_slashes(sc, tmp_path):
    layout = make(sc, tmp_path).layout("C:\\Program Files\\Git\\cmd\\git.exe")

    assert layout.run_user == "NMXWIN$"
    assert layout.work_path == "C:/ProgramData/Neutrino/agent/state/gitea_data"
    assert layout.git_path == "C:/Program Files/Git/cmd/git.exe"
    assert layout.is_ssh_served is False
    assert layout.windows_service_name == "neutrino_gitea"


@pytest.fixture
def state(tmp_path):
    return str(tmp_path / "state")


def test_an_install_registers_the_service_as_gitea_s_page_describes(
    sc, tmp_path, state
):
    binary = tmp_path / "downloaded.exe"
    binary.write_bytes(b"MZ")
    applier = make(sc, tmp_path, state=state)

    applier.install(str(binary))

    exe = os.path.join(state, "gitea", "gitea.exe")
    conf = os.path.join(state, "gitea_data", "custom", "conf", "app.ini")
    assert sc.sc("create") == [
        [
            "sc.exe",
            "create",
            "neutrino_gitea",
            "binPath=",
            f'"{exe}" web --config "{conf}"',
            "start=",
            "auto",
            "DisplayName=",
            "Neutrino Gitea",
        ]
    ]
    assert sc.sc("failure")[0][3:] == [
        "reset=",
        "86400",
        "actions=",
        "restart/5000/restart/5000/restart/5000",
    ]
    assert (tmp_path / "state" / "gitea" / "gitea.exe").read_bytes() == b"MZ"


def test_a_reinstall_stops_the_running_server_and_keeps_the_service(
    sc, tmp_path, state
):
    binary = tmp_path / "downloaded.exe"
    binary.write_bytes(b"MZ")
    applier = make(sc, tmp_path, state=state)
    sc.exists, sc.state = True, "RUNNING"

    applier.install(str(binary))

    assert sc.sc("stop")
    assert sc.sc("create") == []
    assert sc.sc("config")[0][2:4] == ["neutrino_gitea", "binPath="]


def test_an_apply_starts_keeps_or_restarts_the_service(sc, tmp_path, state):
    applier = make(sc, tmp_path, state=state)
    sc.exists = True

    assert applier.apply("one\n", git_path="C:\\git.exe") == "started"
    assert applier.apply("one\n", git_path="C:\\git.exe") == "unchanged"
    assert applier.apply("two\n", git_path="C:\\git.exe") == "restarted"
    conf = tmp_path / "state" / "gitea_data" / "custom" / "conf" / "app.ini"
    assert conf.read_text() == "two\n"
    assert applier.is_active() is True


def test_the_cli_is_run_by_the_agent_itself(sc, tmp_path, state):
    conf = ntpath.join(state, "gitea_data", "custom", "conf", "app.ini")
    exe = ntpath.join(state, "gitea", "gitea.exe")
    applier = GiteaWindowsApplier(
        state_dir=state,
        run=sc,
        is_file=windows_files({exe, conf}),
        user="NMXWIN$",
        sleep=lambda seconds: None,
    )

    state_read = applier.survey()
    applier.change_password(username="ann", password="pw")

    assert state_read.version == "1.27.3"
    assert state_read.admin_usernames == ["ann"]
    assert sc.calls[-1][:4] == [exe, "admin", "user", "change-password"]
    assert sc.calls[-1][-2:] == ["--config", conf]


def test_an_uninstall_deletes_the_service_and_keeps_the_data(sc, tmp_path, state):
    binary = tmp_path / "downloaded.exe"
    binary.write_bytes(b"MZ")
    applier = make(sc, tmp_path, state=state)
    applier.install(str(binary))
    applier.apply("x\n", git_path="C:\\git.exe")
    repository = tmp_path / "state" / "gitea_data" / "data" / "gitea_repositories"
    repository.mkdir(parents=True)

    applier.uninstall()

    assert sc.sc("delete") == [["sc.exe", "delete", "neutrino_gitea"]]
    assert not (tmp_path / "state" / "gitea").exists()
    assert repository.is_dir()
