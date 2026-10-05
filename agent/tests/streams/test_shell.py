"""A shell on a real pseudo-terminal, served through a fake channel.

What these pin: the shell's output arrives as bytes, its exit status is
the close's params, the first size and a resize both reach the terminal,
the hub's bytes reach the shell's input with credit offered back as each
piece is written, a close from the hub ends a shell that would run on, the
``shell`` kind's entry picks the machine's shell or a container's by the
open's ``module``, a container shell is refused typed when podman does
not list the container, and a shell opened with a session id and made
persistent keeps running when its stream closes and is attached again with
its output. The Terminal module: a shell for a named account starts as the
platform steps down to it, with its login shell or the module's program as
a login shell, in its home with its environment, on a terminal handed to
it, and is listed under that account; the module's program alone runs as
the agent; an account the machine does not have and a program that cannot
be run refuse the open with no fallback; a session already open keeps what
it runs when the settings change; a container's shell reads none of them.
"""

import getpass
import os
import pwd
import threading
import time

import pytest

from neutrino_agent.streams import shell as shell_module
from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.modules.terminal.config import TerminalConfig
from neutrino_agent.streams.shell import (
    ContainerShellStream,
    ShellStream,
    open_shell_stream,
)
from neutrino_agent.streams.shell_session import ShellSessionRegistry
from tests.streams.fake_channel import FakeChannel


def run_shell(channel, command, **args) -> dict:
    stream = ShellStream(channel, {"cols": 80, "rows": 24, **args}, command=command)
    stream.open()
    return stream.run()


def wait_for_output(channel: FakeChannel, wanted: bytes, timeout_s: float = 3.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if wanted in channel.output():
            return
        time.sleep(0.01)
    raise AssertionError(f"{wanted!r} never arrived: {channel.output()!r}")


def test_output_arrives_as_bytes_and_the_exit_status_closes():
    channel = FakeChannel()

    closed = run_shell(channel, ["/bin/sh", "-c", "echo hi; exit 3"])

    assert b"hi" in channel.output()
    assert closed == {"code": "", "params": {"exit_code": 3}}
    assert channel.credits[0] > 0
    assert channel.closed is None


def test_the_shell_owns_its_terminal():
    """``/dev/tty`` opens only for a process with a controlling terminal,
    which is what carries ``SIGWINCH`` to the shell on a resize."""
    channel = FakeChannel()

    run_shell(channel, ["/bin/sh", "-c", "exec 3<>/dev/tty && echo ctty_ok"])

    assert b"ctty_ok" in channel.output()


def test_the_first_size_is_the_terminals():
    channel = FakeChannel()

    run_shell(channel, ["/bin/sh", "-c", "stty size"], cols=100, rows=30)

    assert b"30 100" in channel.output()


def test_a_resize_reaches_the_terminal():
    channel = FakeChannel()
    channel.feed(("resize", 132, 50))

    run_shell(channel, ["/bin/sh", "-c", "sleep 0.3; stty size"])

    assert b"50 132" in channel.output()


def test_the_hubs_bytes_reach_the_shells_input_and_credit_comes_back():
    channel = FakeChannel()
    channel.feed(("data", b"echo typed\n"))
    channel.feed(("data", b"exit 4\n"))

    closed = run_shell(channel, ["/bin/sh"])

    assert b"typed" in channel.output()
    assert closed["params"]["exit_code"] == 4
    assert channel.credits[1:] == [len(b"echo typed\n"), len(b"exit 4\n")]


def test_a_close_from_the_hub_ends_a_shell_that_would_run_on():
    channel = FakeChannel()
    outcome: dict = {}

    def serve():
        outcome.update(run_shell(channel, ["/bin/sh", "-c", "sleep 30"]))

    thread = threading.Thread(target=serve)
    thread.start()
    time.sleep(0.2)
    channel.close_from_hub()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert outcome["code"] == ""
    assert outcome["params"]["exit_code"] != 0


def test_a_command_that_cannot_start_closes_typed():
    channel = FakeChannel()

    closed = run_shell(channel, ["/nonexistent/shell"])

    assert closed["code"] == "shell_failed"
    assert "detail" in closed["params"]


def test_login_shell_is_usable_and_absolute():
    shell = shell_module.login_shell()

    assert shell.startswith("/")
    assert "nologin" not in shell


def test_a_container_podman_does_not_list_is_refused(monkeypatch):
    monkeypatch.setattr(shell_module, "listed_containers", lambda: ["web"])
    stream = ContainerShellStream(FakeChannel(), {"container": "kuma"})

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.code == "container_unknown"
    assert refused.value.params == {"name": "kuma"}


def test_a_listed_container_is_opened_with_podman_exec(monkeypatch):
    monkeypatch.setattr(shell_module, "listed_containers", lambda: ["kuma"])
    stream = ContainerShellStream(FakeChannel(), {"container": "kuma"})

    stream.open()

    assert stream._command[:4] == [shell_module.PODMAN_BINARY, "exec", "-it", "kuma"]
    assert stream._command[4:6] == ["sh", "-c"]


def test_the_entry_picks_the_shell_by_the_opens_module():
    plain = open_shell_stream(FakeChannel(), {"cols": 80, "rows": 24})
    inside = open_shell_stream(
        FakeChannel(), {"module": "podman", "container": "kuma", "cols": 1, "rows": 1}
    )

    assert type(plain) is ShellStream
    assert type(inside) is ContainerShellStream
    assert inside._name == "kuma"
    with pytest.raises(StreamRefused) as refused:
        open_shell_stream(FakeChannel(), {"module": "samba"})
    assert refused.value.code == "verb_unknown"
    assert refused.value.params == {"module": "samba"}


def serve_kept(registry, channel, session_id, **args):
    stream = ShellStream(
        channel,
        {"cols": 80, "rows": 24, "session_id": session_id, **args},
        command=["/bin/sh"],
        sessions=registry,
    )
    stream.open()
    outcome: dict = {}
    thread = threading.Thread(target=lambda: outcome.update(stream.run()))
    thread.start()
    return thread, outcome


def test_a_persistent_shell_survives_its_stream_and_is_attached_again():
    registry = ShellSessionRegistry()
    first = FakeChannel()
    thread, outcome = serve_kept(registry, first, "tab-1")
    first.feed(("data", b"echo kept-$((40 + 2))\n"))
    wait_for_output(first, b"kept-42")
    assert registry.persist("tab-1", True)

    first.close_from_hub()
    thread.join(timeout=5)
    assert outcome == {"code": "", "params": {}}
    (listed,) = registry.describe()
    assert listed["is_attached"] is False
    assert listed["account"] == shell_module.shell_account()

    second = FakeChannel()
    thread, outcome = serve_kept(registry, second, "tab-1", is_resumed=True)
    wait_for_output(second, b"kept-42")
    second.feed(("data", b"exit 5\n"))
    thread.join(timeout=5)

    assert outcome == {"code": "", "params": {"exit_code": 5}}
    assert registry.describe() == []


def test_a_kept_shell_that_is_not_persistent_ends_with_its_stream():
    registry = ShellSessionRegistry()
    channel = FakeChannel()
    thread, outcome = serve_kept(registry, channel, "tab-2")
    time.sleep(0.2)

    channel.close_from_hub()
    thread.join(timeout=5)

    assert outcome["params"]["exit_code"] != 0
    assert registry.describe() == []


def test_the_entry_hands_the_registry_to_the_machines_shell():
    registry = ShellSessionRegistry()

    opened = open_shell_stream(
        FakeChannel(), {"cols": 80, "rows": 24, "session_id": "s"}, sessions=registry
    )

    assert opened._sessions is registry


def test_without_pseudo_terminals_a_shell_is_refused(monkeypatch):
    monkeypatch.setattr(shell_module, "pty", None)

    with pytest.raises(StreamRefused) as refused:
        ShellStream(FakeChannel(), {}).open()

    assert refused.value.code == "unsupported_platform"


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


def terminal_stream(channel, settings, platform=None, **args):
    return ShellStream(
        channel,
        {"cols": 80, "rows": 24, **args},
        terminal=lambda: settings,
        platform=platform,
        sessions=args.pop("sessions", None),
    )


def test_a_shell_for_an_account_starts_as_the_platform_steps_down(tmp_path):
    platform = StepDownPlatform(
        tmp_path,
        [
            "/bin/sh",
            "-c",
            'echo "as:$USER:$HOME:$SHELL:$TERM"; pwd; '
            'ls -ln "$(tty)" | awk \'{print "uid:" $3}\'',
        ],
    )
    channel = FakeChannel()
    stream = terminal_stream(
        channel, TerminalConfig(account=ME, shell_path="/bin/sh"), platform
    )

    stream.open()
    closed = stream.run()

    output = channel.output().decode()
    assert platform.asked == [(ME, ["/bin/sh", "-l"])]
    assert f"as:{ME}:{tmp_path}:/bin/sh:xterm-256color" in output
    assert str(tmp_path) in output
    assert f"uid:{pwd.getpwnam(ME).pw_uid}" in output
    assert closed == {"code": "", "params": {"exit_code": 0}}
    assert stream._session.account == ME


def test_an_account_with_no_program_named_gets_its_own_login_shell(tmp_path):
    platform = StepDownPlatform(tmp_path, ["/bin/true"])
    stream = terminal_stream(FakeChannel(), TerminalConfig(account=ME), platform)

    stream.open()
    stream.run()

    own = pwd.getpwnam(ME).pw_shell
    expected = own if os.access(own, os.X_OK) and "nologin" not in own else "/bin/bash"
    assert platform.asked == [(ME, [expected, "-l"])]


def test_the_program_alone_runs_as_the_agent_as_a_login_shell(tmp_path):
    program = tmp_path / "myshell"
    program.write_text('#!/bin/sh\necho "args:$*"\n')
    program.chmod(0o755)
    channel = FakeChannel()
    stream = terminal_stream(channel, TerminalConfig(shell_path=str(program)))

    stream.open()
    stream.run()

    assert b"args:-l" in channel.output()
    assert stream._session.account == shell_module.shell_account()


@pytest.mark.parametrize(
    "settings, code, params",
    [
        (
            TerminalConfig(account="nobody-here-xyz"),
            "account_unknown",
            {"account": "nobody-here-xyz"},
        ),
        (
            TerminalConfig(shell_path="/no/such/shell"),
            "shell_program_unusable",
            {"path": "/no/such/shell"},
        ),
        (
            TerminalConfig(account=ME, shell_path="/no/such/shell"),
            "shell_program_unusable",
            {"path": "/no/such/shell"},
        ),
        (
            TerminalConfig(shell_path="bin/sh"),
            "shell_program_unusable",
            {"path": "bin/sh"},
        ),
    ],
)
def test_what_cannot_run_refuses_the_open_with_no_fallback(
    tmp_path, settings, code, params
):
    platform = StepDownPlatform(tmp_path, ["/bin/true"])
    stream = terminal_stream(FakeChannel(), settings, platform)

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert (refused.value.code, refused.value.params) == (code, params)
    assert platform.asked == []


def test_a_program_with_no_execute_bit_and_a_directory_are_unusable(tmp_path):
    plain = tmp_path / "plain"
    plain.write_text("#!/bin/sh\n")
    for path in (str(plain), str(tmp_path)):
        stream = terminal_stream(FakeChannel(), TerminalConfig(shell_path=path))
        with pytest.raises(StreamRefused) as refused:
            stream.open()
        assert refused.value.code == "shell_program_unusable"


def test_a_session_already_open_keeps_what_it_runs(tmp_path):
    registry = ShellSessionRegistry()
    settings = {"held": TerminalConfig()}
    first = FakeChannel()
    opened = ShellStream(
        first,
        {"cols": 80, "rows": 24, "session_id": "tab-k"},
        sessions=registry,
        terminal=lambda: settings["held"],
        platform=StepDownPlatform(tmp_path, ["/bin/true"]),
    )
    opened.open()
    thread = threading.Thread(target=opened.run)
    thread.start()
    assert registry.persist("tab-k", True)
    settings["held"] = TerminalConfig(account="nobody-here-xyz")

    again = ShellStream(
        FakeChannel(),
        {"cols": 80, "rows": 24, "session_id": "tab-k", "is_resumed": True},
        sessions=registry,
        terminal=lambda: settings["held"],
    )
    again.open()

    assert again._session is opened._session
    assert again._session.account == shell_module.shell_account()
    first.close_from_hub()
    thread.join(timeout=5)
    again._session.end()


def test_a_container_shell_reads_no_terminal_settings():
    inside = open_shell_stream(
        FakeChannel(),
        {"module": "podman", "container": "kuma", "cols": 1, "rows": 1},
        terminal=lambda: TerminalConfig(account="nobody-here-xyz"),
    )

    session = inside._make_session()

    assert type(inside) is ContainerShellStream
    assert session.account == shell_module.shell_account()
    assert inside._command[0].endswith("podman")
