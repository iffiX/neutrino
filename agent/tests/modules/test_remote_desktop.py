"""The user-tier remote desktops, read and set up through faked commands.

What these pin: which product is asked as root and which as the seated
account on its own display, a stopped daemon started on the way, the id
read out of the table TeamViewer draws, the password on stdin for AnyDesk
and never in any output, and the typed refusal when nobody is seated.
"""

import subprocess

import pytest

from neutrino_agent.modules import remote_desktop
from neutrino_agent.modules.remote_desktop import RemoteDesktopReader, teamviewer_id
from neutrino_agent.modules.subprocess_run import CommandResult

# What `teamviewer info` prints on 15.61.3, escapes and all.
TEAMVIEWER_INFO = (
    "\x1b[1m TeamViewer                          \x1b[0m 15.61.3  (DEB) \n"
    "\n"
    "\x1b[1m TeamViewer ID:                      \x1b[0m  1146575818\n"
    " 1146575818 \n"
)
TEAMVIEWER_INFO_UNPRIVILEGED = (
    "grep: /opt/teamviewer/config/global.conf: Permission denied\n"
    "\x1b[1m TeamViewer ID:                      \x1b[0m  \n"
)
PASSWORD = "unattended-secret"  # scan: allow


class FakeRuns:
    """Answers each root command from a table and records every call."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list = []
        self.active: set = set()

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[:2] == ["systemctl", "is-active"]:
            word = "active" if command[2] in self.active else "inactive"
            return CommandResult(command, 0 if word == "active" else 3, word, "")
        if command[:3] == ["systemctl", "enable", "--now"]:
            self.active.add(command[3])
            return CommandResult(command, 0, "", "")
        code, stdout = self.answers.get(command[0], (127, ""))
        return CommandResult(command, code, stdout, "")


class FakePlatform:
    """Records what is run as which account, answering from a table."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list = []

    def run_as_account(self, account, argv, *, stdin="", timeout_s=120):
        self.calls.append((account, list(argv), stdin))
        binary = next(arg for arg in argv[1:] if "=" not in arg)
        code, stdout = self.answers.get(binary, (127, ""))
        return subprocess.CompletedProcess(argv, code, stdout, "")


@pytest.fixture
def machine(monkeypatch):
    runs = FakeRuns({"teamviewer": (0, TEAMVIEWER_INFO)})
    platform = FakePlatform({"anydesk": (0, "123456789\n")})
    monkeypatch.setattr(remote_desktop, "run", runs)
    monkeypatch.setattr(remote_desktop.shutil, "which", lambda name: None)
    monkeypatch.setattr(remote_desktop.os.path, "exists", lambda path: False)
    monkeypatch.setattr(remote_desktop, "graphical_accounts", lambda: ["alice"])
    monkeypatch.setattr(
        remote_desktop,
        "session_environment",
        lambda account: {"DISPLAY": ":0", "XAUTHORITY": f"/home/{account}/.Xauth"},
    )
    return runs, platform, RemoteDesktopReader(platform=platform)


def test_the_teamviewer_id_is_read_out_of_the_table_it_is_drawn_in():
    assert teamviewer_id(TEAMVIEWER_INFO) == "1146575818"
    assert teamviewer_id(TEAMVIEWER_INFO_UNPRIVILEGED) == ""
    assert teamviewer_id("") == ""


def test_a_product_that_is_not_there_reads_absent(machine):
    runs, _, reader = machine

    status = reader.status("teamviewer")

    assert status == {
        "product": "teamviewer",
        "is_installed": False,
        "is_running": False,
        "session_id": None,
        "can_set_password": True,
    }
    assert ["dpkg", "-s", "teamviewer"] in runs.calls
    assert ["rpm", "-q", "teamviewer"] in runs.calls


def test_teamviewer_is_read_as_root_and_its_daemon_started(machine):
    runs, platform, reader = machine
    runs.answers["dpkg"] = (0, "Status: install ok installed")

    status = reader.status("teamviewer")

    assert status["is_installed"] and status["is_running"]
    assert status["session_id"] == "1146575818"
    assert ["systemctl", "enable", "--now", "teamviewerd"] in runs.calls
    assert ["teamviewer", "info"] in runs.calls
    assert platform.calls == []


def test_anydesk_is_read_as_the_seated_account_on_its_display(machine):
    runs, platform, reader = machine
    runs.answers["dpkg"] = (0, "installed")
    runs.active.add("anydesk")

    status = reader.status("anydesk")

    assert status["session_id"] == "123456789"
    account, argv, stdin = platform.calls[0]
    assert account == "alice"
    assert argv[0] == "env"
    assert "DISPLAY=:0" in argv and "XAUTHORITY=/home/alice/.Xauth" in argv
    assert argv[-2:] == ["anydesk", "--get-id"]
    assert not any(call[0] == "anydesk" for call in runs.calls)


def test_anydesk_with_nobody_seated_has_no_id(machine, monkeypatch):
    runs, platform, reader = machine
    runs.answers["dpkg"] = (0, "installed")
    monkeypatch.setattr(remote_desktop, "graphical_accounts", lambda: [])

    assert reader.status("anydesk")["session_id"] is None
    assert platform.calls == []


def test_the_anydesk_password_rides_stdin_as_the_seated_account(machine):
    _, platform, reader = machine

    outcome = reader.set_password("anydesk", PASSWORD)

    assert outcome["exit_code"] == 0 and outcome["code"] == ""
    account, argv, stdin = platform.calls[0]
    assert account == "alice"
    assert argv[-2:] == ["anydesk", "--set-password"]
    assert stdin == f"{PASSWORD}\n"
    assert PASSWORD not in " ".join(argv)
    assert PASSWORD not in outcome["output"]
    assert "123456789" in outcome["output"]


def test_the_teamviewer_password_is_its_own_verb_as_root(machine):
    runs, platform, reader = machine
    runs.answers["teamviewer"] = (0, f"changed to {PASSWORD}\n")

    outcome = reader.set_password("teamviewer", PASSWORD)

    assert ["teamviewer", "passwd", PASSWORD] in runs.calls
    assert outcome["exit_code"] == 0
    assert PASSWORD not in outcome["output"]
    assert platform.calls == []


def test_setting_anydesks_password_with_nobody_seated_is_refused(machine, monkeypatch):
    _, platform, reader = machine
    monkeypatch.setattr(remote_desktop, "graphical_accounts", lambda: [])

    outcome = reader.set_password("anydesk", PASSWORD)

    assert outcome["code"] == "rdp_nobody_seated"
    assert platform.calls == []


def test_a_failing_verb_answers_command_failed_scrubbed(machine):
    runs, _, reader = machine
    runs.answers["teamviewer"] = (1, f"refused {PASSWORD}")

    outcome = reader.set_password("teamviewer", PASSWORD)

    assert outcome["exit_code"] == 1
    assert outcome["code"] == "command_failed"
    assert PASSWORD not in outcome["params"]["detail"]


def test_a_product_outside_the_two_is_a_value_error(machine):
    _, _, reader = machine

    with pytest.raises(ValueError):
        reader.status("vnc")
