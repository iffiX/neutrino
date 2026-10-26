"""One command over an ``exec`` stream, served through a fake channel.

What these pin: without ``is_tty`` the command runs on pipes with no shell
between, stdout arrives as ``data`` records and stderr as ``stderr``
records, and the exit code closes the stream; the hub's bytes reach stdin
in order, ``eof`` closes stdin, and a record after it is dropped; a signal
death closes with 128 plus the signal's number; a stream the hub closes
first ends the process and what it started; an ``argv`` that is empty, not
a list of strings, or whose program is not found refuses the open
``shell_program_unusable`` before anything starts. With ``is_tty`` the
``argv`` runs on a pseudo-terminal of the open's size, every record
``data``, and ``eof`` is ignored. The account: the command starts as the
enabled account the open names, the first one when it names none, as the
platform steps down to it, in its home with its environment, on both paths;
no enabled account, an account the module does not enable and one the
machine does not have are refused; the account's shell is never read. On
Windows the command runs under the account's logon, refused
``credential_missing`` with no login.
"""

import getpass
import os
import pwd
import signal
import threading
import time
import types

import pytest

from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.modules.terminal.config import TerminalAccount, TerminalConfig
from neutrino_agent.streams import STREAM_KINDS
from neutrino_agent.streams.exec import ExecStream, open_exec_stream
from neutrino_agent.streams.shell import ShellStream
from tests.streams.fake_channel import FakeChannel

ME = getpass.getuser()


def enabled(*accounts) -> TerminalConfig:
    """The Terminal module's settings with these accounts enabled."""
    return TerminalConfig(
        accounts=[
            each if isinstance(each, TerminalAccount) else TerminalAccount(each)
            for each in accounts
        ]
    )


class StepDownPlatform:
    """Steps down by running a stand-in command, and records what it was asked.

    With no command it runs the asked ``argv`` itself, as the test's own
    account, with a plain environment.
    """

    def __init__(self, tmp_path, command=None):
        self.asked: list = []
        self._tmp_path = tmp_path
        self._command = command

    def account_process(self, account, argv):
        self.asked.append((account, list(argv)))
        return list(self._command or argv), {
            "cwd": str(self._tmp_path),
            "env": {
                "HOME": str(self._tmp_path),
                "USER": account,
                "PATH": "/bin:/usr/bin",
            },
        }


def opened(channel, argv, tmp_path, *, settings=None, platform=None, **args):
    stream = open_exec_stream(
        channel,
        {"argv": argv, "is_tty": False, "cols": 80, "rows": 24, **args},
        terminal=lambda: settings if settings is not None else enabled(ME),
        platform=platform if platform is not None else StepDownPlatform(tmp_path),
    )
    stream.open()
    return stream


def run(channel, argv, tmp_path, **kwargs) -> dict:
    return opened(channel, argv, tmp_path, **kwargs).run()


def test_the_kind_table_serves_exec():
    assert STREAM_KINDS["exec"] is open_exec_stream


def test_stdout_and_stderr_arrive_apart_and_the_exit_code_closes(tmp_path):
    channel = FakeChannel()

    closed = run(channel, ["/bin/sh", "-c", "echo out; echo err >&2; exit 3"], tmp_path)

    assert channel.output() == b"out\n"
    assert channel.errors() == b"err\n"
    assert closed == {"code": "", "params": {"exit_code": 3}}
    assert channel.closed is None


def test_the_argv_runs_with_no_shell_between_and_is_found_on_the_path(tmp_path):
    channel = FakeChannel()

    closed = run(channel, ["echo", "$HOME", "a;b"], tmp_path)

    assert channel.output() == b"$HOME a;b\n"
    assert closed["params"]["exit_code"] == 0


def test_stdin_takes_the_hubs_bytes_and_eof_closes_it(tmp_path):
    channel = FakeChannel()
    channel.feed(("data", b"one\n"))
    channel.feed(("data", b"two\n"))
    channel.feed(("eof",))
    channel.feed(("data", b"late\n"))

    closed = run(channel, ["/bin/sh", "-c", "cat; sleep 0.3"], tmp_path)

    assert channel.output() == b"one\ntwo\n"
    assert closed == {"code": "", "params": {"exit_code": 0}}


def test_a_signal_death_closes_with_128_plus_the_signal(tmp_path):
    channel = FakeChannel()

    closed = run(channel, ["/bin/sh", "-c", "kill -TERM $$"], tmp_path)

    assert closed == {"code": "", "params": {"exit_code": 128 + signal.SIGTERM}}


def test_a_close_from_the_hub_ends_the_process_and_what_it_started(tmp_path):
    channel = FakeChannel()
    stream = opened(channel, ["/bin/sh", "-c", "sleep 30 & echo $!; wait"], tmp_path)
    outcome: dict = {}
    thread = threading.Thread(target=lambda: outcome.update(stream.run()))
    thread.start()
    deadline = time.monotonic() + 3
    while not channel.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    child = int(channel.output())

    channel.close_from_hub()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert outcome == {"code": "", "params": {}}
    assert stream._process.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


@pytest.mark.parametrize(
    "argv, path",
    [
        ([], ""),
        (None, ""),
        ("ls -l", ""),
        (["ls", 3], ""),
        ([""], ""),
        (["no-such-program-xyz"], "no-such-program-xyz"),
        (["/no/such/program"], "/no/such/program"),
    ],
)
def test_an_argv_that_cannot_run_is_refused_before_anything_starts(
    tmp_path, argv, path
):
    stream = open_exec_stream(
        FakeChannel(),
        {"argv": argv, "is_tty": False},
        terminal=lambda: enabled(ME),
        platform=StepDownPlatform(tmp_path),
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "shell_program_unusable",
        {"path": path},
    )
    assert stream._process is None


def test_a_file_with_no_execute_bit_is_refused(tmp_path):
    plain = tmp_path / "plain"
    plain.write_text("#!/bin/sh\n")

    with pytest.raises(StreamRefused) as refused:
        opened(FakeChannel(), [str(plain)], tmp_path)

    assert refused.value.params == {"path": str(plain)}


def test_with_is_tty_the_argv_runs_on_a_terminal_of_the_opens_size(tmp_path):
    channel = FakeChannel()
    channel.feed(("eof",))
    stream = open_exec_stream(
        channel,
        {
            "argv": ["/bin/sh", "-c", "stty size; test -t 0 && echo tty_ok; exit 5"],
            "is_tty": True,
            "cols": 100,
            "rows": 30,
        },
        terminal=lambda: enabled(ME),
        platform=StepDownPlatform(tmp_path),
    )
    stream.open()

    closed = stream.run()

    assert type(stream) is ShellStream
    assert channel.sent_stderr == []
    assert b"30 100" in channel.output()
    assert b"tty_ok" in channel.output()
    assert closed == {"code": "", "params": {"exit_code": 5}}


def test_with_is_tty_a_missing_program_is_refused(tmp_path):
    stream = open_exec_stream(
        FakeChannel(),
        {"argv": ["/no/such/program"], "is_tty": True},
        terminal=lambda: enabled(ME),
        platform=StepDownPlatform(tmp_path),
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.params == {"path": "/no/such/program"}


def test_the_command_runs_as_the_enabled_account_through_the_step_down(tmp_path):
    platform = StepDownPlatform(
        tmp_path, ["/bin/sh", "-c", 'echo "as:$USER:$HOME"; pwd']
    )
    channel = FakeChannel()
    settings = enabled(TerminalAccount(ME, shell_path="/no/such/shell"))

    closed = run(channel, ["id", "-u"], tmp_path, settings=settings, platform=platform)

    assert platform.asked == [(ME, ["id", "-u"])]
    assert channel.output() == f"as:{ME}:{tmp_path}\n{tmp_path}\n".encode()
    assert closed["params"]["exit_code"] == 0


def test_the_command_runs_as_the_account_the_open_names(tmp_path):
    platform = StepDownPlatform(tmp_path, ["/bin/true"])

    opened(
        FakeChannel(),
        ["true"],
        tmp_path,
        settings=enabled("root", ME),
        platform=platform,
        account=ME,
    )

    assert platform.asked == [(ME, ["true"])]


def test_with_is_tty_the_terminal_is_handed_to_the_enabled_account(tmp_path):
    platform = StepDownPlatform(
        tmp_path,
        [
            "/bin/sh",
            "-c",
            'echo "as:$USER"; ls -ln "$(tty)" | awk \'{print "uid:" $3}\'',
        ],
    )
    channel = FakeChannel()
    stream = open_exec_stream(
        channel,
        {"argv": ["true"], "is_tty": True, "cols": 80, "rows": 24},
        terminal=lambda: enabled(ME),
        platform=platform,
    )

    stream.open()
    stream.run()

    output = channel.output().decode()
    assert platform.asked == [(ME, ["true"])]
    assert f"as:{ME}" in output
    assert f"uid:{pwd.getpwnam(ME).pw_uid}" in output
    assert stream._session.account == ME


@pytest.mark.parametrize("is_tty", [False, True])
@pytest.mark.parametrize(
    "settings, account, code, params",
    [
        (enabled(), "", "terminal_account_missing", {}),
        (enabled(ME), "root", "account_not_enabled", {"account": "root"}),
        (
            enabled("nobody-here-xyz"),
            "",
            "account_unknown",
            {"account": "nobody-here-xyz"},
        ),
    ],
)
def test_an_account_that_cannot_run_the_command_is_refused(
    tmp_path, is_tty, settings, account, code, params
):
    platform = StepDownPlatform(tmp_path, ["/bin/true"])
    stream = open_exec_stream(
        FakeChannel(),
        {"argv": ["true"], "is_tty": is_tty, "account": account},
        terminal=lambda: settings,
        platform=platform,
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (code, params)
    assert platform.asked == []


class WindowsHome:
    def account_home(self, account):
        return f"C:\\Users\\{account}"

    def shell_start_dir(self):
        return "C:\\"


class FakeLogon:
    opened: list = []

    def __init__(self, account, password):
        self.account = account
        self.password = password
        self.is_closed = False

    def open(self):
        FakeLogon.opened.append((self.account, self.password))

    def close(self):
        self.is_closed = True


def test_on_windows_is_tty_takes_the_console_and_the_pipes_run_under_the_logon(
    monkeypatch,
):
    from neutrino_agent.streams import exec as exec_module
    from neutrino_agent.streams import windows_shell
    from neutrino_agent.streams.windows_shell import WindowsShellStream

    monkeypatch.setattr(exec_module, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(windows_shell, "account_sid", lambda account: "S-1-5-21-1")
    FakeLogon.opened = []
    settings = enabled(TerminalAccount("alice", password="pw"))
    tty = open_exec_stream(
        FakeChannel(),
        {"argv": ["true"], "is_tty": True, "cols": 80, "rows": 24},
        terminal=lambda: settings,
    )
    piped = ExecStream(
        FakeChannel(),
        ["true"],
        terminal=lambda: settings,
        platform=WindowsHome(),
        logon_class=FakeLogon,
    )
    piped.open()

    assert type(tty) is WindowsShellStream
    assert tty._argv == ["true"]
    assert piped._command == ["true"]
    assert piped._process_arguments == {"cwd": "C:\\Users\\alice"}
    assert FakeLogon.opened == [("alice", "pw")]


def test_on_windows_an_account_with_no_login_is_refused(monkeypatch):
    from neutrino_agent.streams import exec as exec_module
    from neutrino_agent.streams import windows_shell

    monkeypatch.setattr(exec_module, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(windows_shell, "account_sid", lambda account: "S-1-5-21-1")
    FakeLogon.opened = []
    stream = ExecStream(
        FakeChannel(),
        ["true"],
        terminal=lambda: enabled("alice"),
        platform=WindowsHome(),
        logon_class=FakeLogon,
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "credential_missing",
        {"account": "alice"},
    )
    assert FakeLogon.opened == []
