"""One command over an ``exec`` stream, served through a fake channel.

What these pin: without ``is_tty`` the command runs on pipes with no shell
between, stdout and stderr arrive apart, each frame headed with its ``fd``,
and the exit code closes the stream; the hub's bytes reach stdin in order
with credit offered back, ``eof`` closes stdin, and a frame after it is
dropped with its credit still offered back; a signal death closes with 128
plus the signal's number; a stream the hub closes first ends the process
and what it started; an ``argv`` that is empty, not a list of strings, or
whose program is not found refuses the open ``shell_program_unusable``
before anything starts. With ``is_tty`` the ``argv`` runs on a
pseudo-terminal of the open's size, every frame headed with stdout's
``fd``, and ``eof`` is ignored. The Terminal module's account: the command
starts as the platform steps down to it, in its home with its environment,
on both paths, and an account the machine does not have is refused; the
module's shell program is never read.
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
from neutrino_agent.modules.terminal.config import TerminalConfig
from neutrino_agent.streams import STREAM_KINDS
from neutrino_agent.streams.exec import ExecStream, open_exec_stream
from neutrino_agent.streams.shell import ShellStream
from tests.streams.fake_channel import FakeChannel

ME = getpass.getuser()


class StepDownPlatform:
    """Steps down by running a stand-in command, and records what it was asked."""

    def __init__(self, tmp_path, command):
        self.asked: list = []
        self._tmp_path = tmp_path
        self._command = command

    def account_process(self, account, argv):
        self.asked.append((account, list(argv)))
        return list(self._command), {
            "cwd": str(self._tmp_path),
            "env": {
                "HOME": str(self._tmp_path),
                "USER": account,
                "PATH": "/bin:/usr/bin",
            },
        }


def opened(channel, argv, *, settings=None, platform=None, **args):
    stream = open_exec_stream(
        channel,
        {"argv": argv, "is_tty": False, "cols": 80, "rows": 24, **args},
        terminal=(lambda: settings) if settings is not None else None,
        platform=platform,
    )
    stream.open()
    return stream


def run(channel, argv, **kwargs) -> dict:
    return opened(channel, argv, **kwargs).run()


def by_fd(channel: FakeChannel) -> dict:
    outputs = {}
    for sent in channel.sent:
        outputs[sent[0]] = outputs.get(sent[0], b"") + sent[1:]
    return outputs


def test_the_kind_table_serves_exec():
    assert STREAM_KINDS["exec"] is open_exec_stream


def test_stdout_and_stderr_arrive_apart_and_the_exit_code_closes():
    channel = FakeChannel()

    closed = run(channel, ["/bin/sh", "-c", "echo out; echo err >&2; exit 3"])

    assert by_fd(channel) == {1: b"out\n", 2: b"err\n"}
    assert closed == {"code": "", "params": {"exit_code": 3}}
    assert channel.credits[0] > 0
    assert channel.closed is None


def test_the_argv_runs_with_no_shell_between_and_is_found_on_the_path():
    channel = FakeChannel()

    closed = run(channel, ["echo", "$HOME", "a;b"])

    assert by_fd(channel) == {1: b"$HOME a;b\n"}
    assert closed["params"]["exit_code"] == 0


def test_stdin_takes_the_hubs_bytes_and_eof_closes_it():
    channel = FakeChannel()
    channel.feed(("data", b"one\n"))
    channel.feed(("data", b"two\n"))
    channel.feed(("eof",))
    channel.feed(("data", b"late\n"))

    closed = run(channel, ["/bin/sh", "-c", "cat; sleep 0.3"])

    assert by_fd(channel) == {1: b"one\ntwo\n"}
    assert closed == {"code": "", "params": {"exit_code": 0}}
    assert channel.credits[1:] == [4, 4, 5]


def test_a_signal_death_closes_with_128_plus_the_signal():
    channel = FakeChannel()

    closed = run(channel, ["/bin/sh", "-c", "kill -TERM $$"])

    assert closed == {"code": "", "params": {"exit_code": 128 + signal.SIGTERM}}


def test_a_close_from_the_hub_ends_the_process_and_what_it_started():
    channel = FakeChannel()
    stream = opened(channel, ["/bin/sh", "-c", "sleep 30 & echo $!; wait"])
    outcome: dict = {}
    thread = threading.Thread(target=lambda: outcome.update(stream.run()))
    thread.start()
    deadline = time.monotonic() + 3
    while not channel.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    child = int(by_fd(channel)[1])

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
def test_an_argv_that_cannot_run_is_refused_before_anything_starts(argv, path):
    stream = open_exec_stream(FakeChannel(), {"argv": argv, "is_tty": False})

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
        opened(FakeChannel(), [str(plain)])

    assert refused.value.params == {"path": str(plain)}


def test_with_is_tty_the_argv_runs_on_a_terminal_of_the_opens_size():
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
    )
    stream.open()

    closed = stream.run()

    assert type(stream) is ShellStream
    assert all(sent[:1] == b"\x01" for sent in channel.sent)
    output = b"".join(sent[1:] for sent in channel.sent)
    assert b"30 100" in output
    assert b"tty_ok" in output
    assert closed == {"code": "", "params": {"exit_code": 5}}


def test_with_is_tty_a_missing_program_is_refused():
    stream = open_exec_stream(
        FakeChannel(), {"argv": ["/no/such/program"], "is_tty": True}
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.params == {"path": "/no/such/program"}


def test_the_command_runs_as_the_module_account_through_the_step_down(tmp_path):
    platform = StepDownPlatform(
        tmp_path, ["/bin/sh", "-c", 'echo "as:$USER:$HOME"; pwd']
    )
    channel = FakeChannel()
    settings = TerminalConfig(account=ME, shell_path="/no/such/shell")

    closed = run(channel, ["id", "-u"], settings=settings, platform=platform)

    assert platform.asked == [(ME, ["id", "-u"])]
    assert by_fd(channel) == {1: f"as:{ME}:{tmp_path}\n{tmp_path}\n".encode()}
    assert closed["params"]["exit_code"] == 0


def test_with_is_tty_the_terminal_is_handed_to_the_module_account(tmp_path):
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
        terminal=lambda: TerminalConfig(account=ME),
        platform=platform,
    )

    stream.open()
    stream.run()

    output = b"".join(sent[1:] for sent in channel.sent).decode()
    assert platform.asked == [(ME, ["true"])]
    assert f"as:{ME}" in output
    assert f"uid:{pwd.getpwnam(ME).pw_uid}" in output
    assert stream._session.account == ME


@pytest.mark.parametrize("is_tty", [False, True])
def test_an_account_the_machine_does_not_have_is_refused(tmp_path, is_tty):
    platform = StepDownPlatform(tmp_path, ["/bin/true"])
    stream = open_exec_stream(
        FakeChannel(),
        {"argv": ["true"], "is_tty": is_tty},
        terminal=lambda: TerminalConfig(account="nobody-here-xyz"),
        platform=platform,
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (
        "account_unknown",
        {"account": "nobody-here-xyz"},
    )
    assert platform.asked == []


def test_without_an_account_the_module_shell_program_is_not_read():
    channel = FakeChannel()

    closed = run(
        channel,
        ["/bin/sh", "-c", "echo ran"],
        settings=TerminalConfig(shell_path="/no/such/shell"),
    )

    assert by_fd(channel) == {1: b"ran\n"}
    assert closed["params"]["exit_code"] == 0
    assert isinstance(opened(FakeChannel(), ["true"]), ExecStream)


class WindowsStartDir:
    def shell_start_dir(self):
        return "C:\\Users\\alice"


def test_on_windows_is_tty_takes_the_console_and_the_pipes_start_in_the_shells_directory(
    monkeypatch,
):
    from neutrino_agent.streams import exec as exec_module
    from neutrino_agent.streams.windows_shell import WindowsShellStream

    monkeypatch.setattr(exec_module, "sys", types.SimpleNamespace(platform="win32"))
    tty = open_exec_stream(
        FakeChannel(), {"argv": ["true"], "is_tty": True, "cols": 80, "rows": 24}
    )
    piped = open_exec_stream(
        FakeChannel(),
        {"argv": ["true"], "is_tty": False},
        terminal=lambda: TerminalConfig(account=ME),
        platform=WindowsStartDir(),
    )
    piped.open()

    assert type(tty) is WindowsShellStream
    assert tty._argv == ["true"]
    assert piped._command == ["true"]
    assert piped._process_arguments == {"cwd": "C:\\Users\\alice"}
