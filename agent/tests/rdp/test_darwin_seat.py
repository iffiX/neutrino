"""The macOS seat: the console user, netstat, and the permissions dialog.

Commands are faked at ``subprocess.run`` and accounts at ``pwd``. What is
pinned is who is at the screen, read from the system configuration's
console user, the console's owner only when that cannot be asked; that a
seated Mac says nothing a peer would wait on; and that a share start asks
for the dialog and the Screen Recording pane inside the account's own
session, as the account, through the agent's own step-down and never
``chroot`` or ``sudo``, without waiting for either, and logs a failure.
"""

import subprocess
import threading
from types import SimpleNamespace

import pytest

from neutrino_agent.rdp import darwin_seat as seat_module
from neutrino_agent.rdp.darwin_seat import DarwinSeat


def printing(monkeypatch, stdout, *, returncode=0, calls=None):
    def run(command, **kwargs):
        if calls is not None:
            calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout=stdout)

    monkeypatch.setattr(seat_module.subprocess, "run", run)


# What scutil printed on the rented Mac, signed in by auto-login while
# /dev/console stayed root's.
CONSOLE_USER = """<dictionary> {
  GID : 20
  Name : chuzu
  SessionInfo : <array> {
    0 : <dictionary> {
      kCGSSessionOnConsoleKey : TRUE
      kCGSSessionUserIDKey : 502
      kCGSSessionUserNameKey : chuzu
    }
  }
  UID : 502
}
"""


def test_the_system_configurations_console_user_is_the_seat(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((list(command), kwargs.get("input")))
        return subprocess.CompletedProcess(command, 0, stdout=CONSOLE_USER)

    monkeypatch.setattr(seat_module.subprocess, "run", run)

    assert DarwinSeat().graphical_accounts() == ["chuzu"]
    assert seat_module.console_user() == ("chuzu", 502)
    assert calls[0] == (["/usr/sbin/scutil"], "show State:/Users/ConsoleUser\n")
    assert all(command[0] != "stat" for command, _ in calls)


@pytest.mark.parametrize(
    "printed",
    [
        "<dictionary> {\n  Name : loginwindow\n  UID : 0\n}\n",
        "<dictionary> {\n  Name : root\n  UID : 0\n}\n",
        "  No such key\n",
        "",
    ],
)
def test_the_login_window_root_and_no_key_are_nobody_seated(monkeypatch, printed):
    printing(monkeypatch, printed)

    assert DarwinSeat().graphical_accounts() == []
    assert seat_module.console_user() == ()


def test_the_consoles_owner_stands_in_only_when_scutil_cannot_be_asked(
    monkeypatch,
):
    calls = []

    def run(command, **kwargs):
        calls.append(list(command))
        if command[0] == "/usr/sbin/scutil":
            raise FileNotFoundError(command[0])
        return subprocess.CompletedProcess(command, 0, stdout="pat 501\n")

    monkeypatch.setattr(seat_module.subprocess, "run", run)

    assert DarwinSeat().graphical_accounts() == ["pat"]
    assert calls[-1] == ["stat", "-f", "%Su %u", "/dev/console"]


def test_a_console_that_cannot_be_asked_cannot_say(monkeypatch):
    printing(monkeypatch, "", returncode=1)

    assert DarwinSeat().graphical_accounts() is None


def test_the_peers_are_the_established_rows_on_the_direct_port(monkeypatch):
    calls = []
    printing(
        monkeypatch,
        "tcp4  0  0  192.0.2.10.21118  192.0.2.20.50123  ESTABLISHED\n"
        "tcp4  0  0  *.21118  *.*  LISTEN\n",
        calls=calls,
    )

    assert DarwinSeat().connected_count(21118) == 1
    assert calls == [["netstat", "-an", "-p", "tcp"]]


def test_a_seated_mac_says_nothing_a_peer_would_wait_on(monkeypatch):
    """The privacy database is closed to root, so no grant is read."""

    def refuse(command, **kwargs):
        raise AssertionError("the seat must not run anything to answer")

    monkeypatch.setattr(seat_module.subprocess, "run", refuse)

    assert DarwinSeat().screen_attention("/Users/pat") == ""


class SessionCommands:
    """subprocess.run for the session's commands, each held until released."""

    def __init__(self):
        self.commands = []
        self.kwargs = []
        self.released = threading.Event()
        self.lock = threading.Lock()
        self.both_asked = threading.Event()

    def __call__(self, command, **kwargs):
        with self.lock:
            self.commands.append(list(command))
            self.kwargs.append(kwargs)
            if len(self.commands) == 2:
                self.both_asked.set()
        self.released.wait(timeout=5)
        return subprocess.CompletedProcess(command, 0)


def an_account(monkeypatch):
    """The account database knows one account, pat."""
    entry = SimpleNamespace(pw_uid=501, pw_gid=20, pw_dir="/Users/pat")

    def getpwnam(name):
        if name != "pat":
            raise KeyError(name)
        return entry

    monkeypatch.setattr(seat_module, "pwd", SimpleNamespace(getpwnam=getpwnam))


def session_prefix():
    return [
        "/bin/launchctl",
        "asuser",
        "501",
        "/Library/Application Support/Neutrino/agent/app/nagent",
        "step-down",
        "--uid",
        "501",
        "--gid",
        "20",
        "--",
    ]


def test_a_share_start_asks_for_the_dialog_and_the_pane_in_the_session(monkeypatch):
    an_account(monkeypatch)
    run = SessionCommands()
    monkeypatch.setattr(seat_module.subprocess, "run", run)

    DarwinSeat().ask_for_permissions("pat")
    assert run.both_asked.wait(timeout=5)
    run.released.set()

    dialog = [c for c in run.commands if "/usr/bin/osascript" in c][0]
    pane = [c for c in run.commands if "/usr/bin/open" in c][0]
    assert dialog[: len(session_prefix())] == session_prefix()
    assert pane[: len(session_prefix())] == session_prefix()
    script = dialog[-1]
    assert "Screen Recording" in script and "Accessibility" in script
    assert "System Settings" in script
    assert "giving up after" in script
    assert pane[-1] == (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_ScreenCapture"
    )
    for command in run.commands:
        assert not any("chroot" in word or "sudo" in word for word in command)
    for kwargs in run.kwargs:
        assert kwargs["timeout"] > 0
        assert kwargs["env"]["HOME"] == "/Users/pat"
        assert kwargs["env"]["USER"] == "pat"


def test_the_dialog_is_never_waited_for(monkeypatch):
    """Nobody may be at the screen to answer; the share goes on regardless."""
    an_account(monkeypatch)
    run = SessionCommands()
    monkeypatch.setattr(seat_module.subprocess, "run", run)

    DarwinSeat().ask_for_permissions("pat")

    # Returned while both commands are still held.
    assert run.both_asked.wait(timeout=5)
    assert not run.released.is_set()
    run.released.set()


def test_a_command_that_fails_to_start_or_exits_badly_is_logged(monkeypatch):
    an_account(monkeypatch)
    lines = []

    def run(command, **kwargs):
        if "/usr/bin/open" in command:
            raise OSError("exec format error")
        return subprocess.CompletedProcess(command, 137, stdout="", stderr="Killed: 9")

    monkeypatch.setattr(seat_module.subprocess, "run", run)
    started = []
    real_thread = threading.Thread

    def thread(**kwargs):
        made = real_thread(**kwargs)
        started.append(made)
        return made

    monkeypatch.setattr(seat_module.threading, "Thread", thread)

    DarwinSeat(log=lines.append).ask_for_permissions("pat")
    for made in started:
        made.join(timeout=5)

    assert any("exited 137: Killed: 9" in line for line in lines)
    assert any("could not start: exec format error" in line for line in lines)


def test_a_command_that_fails_or_runs_out_of_time_is_swallowed(monkeypatch):
    an_account(monkeypatch)
    finished = []

    def run(command, **kwargs):
        finished.append(command)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(seat_module.subprocess, "run", run)
    started = []
    real_thread = threading.Thread

    def thread(**kwargs):
        made = real_thread(**kwargs)
        started.append(made)
        return made

    monkeypatch.setattr(seat_module.threading, "Thread", thread)

    DarwinSeat().ask_for_permissions("pat")
    for made in started:
        made.join(timeout=5)

    assert len(finished) == 2
    assert all(made.daemon for made in started)


def test_an_account_the_mac_does_not_have_is_asked_nothing(monkeypatch):
    an_account(monkeypatch)

    def refuse(command, **kwargs):
        raise AssertionError("nothing must run for an unknown account")

    monkeypatch.setattr(seat_module.subprocess, "run", refuse)

    DarwinSeat().ask_for_permissions("nobody-here")
    DarwinSeat().ask_for_permissions("")


def test_a_mac_screen_is_always_a_desktop():
    assert DarwinSeat().has_desktop_session() is True
