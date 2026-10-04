"""The macOS seat: the console's owner, netstat, and the permissions dialog.

Commands are faked at ``subprocess.run`` and accounts at ``pwd``. What is
pinned is who is at the screen, that a seated Mac says nothing a peer would
wait on, and that a share start asks for the dialog and the Screen Recording
pane inside the account's own session, as the account, without waiting for
either.
"""

import subprocess
import threading
from types import SimpleNamespace

from neutrino_agent.rdp import darwin_seat as seat_module
from neutrino_agent.rdp.darwin_seat import DarwinSeat


def printing(monkeypatch, stdout, *, returncode=0, calls=None):
    def run(command, **kwargs):
        if calls is not None:
            calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout=stdout)

    monkeypatch.setattr(seat_module.subprocess, "run", run)


def test_the_consoles_owner_is_the_seat(monkeypatch):
    calls = []
    printing(monkeypatch, "pat\n", calls=calls)

    assert DarwinSeat().graphical_accounts() == ["pat"]
    assert calls == [["stat", "-f", "%Su", "/dev/console"]]


def test_the_login_window_is_nobody_seated(monkeypatch):
    printing(monkeypatch, "root\n")

    assert DarwinSeat().graphical_accounts() == []


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
        "/usr/sbin/chroot",
        "-u",
        "pat",
        "-g",
        "20",
        "-G",
        "20",
        "/",
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
