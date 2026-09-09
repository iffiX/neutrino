"""A shell on a real pseudo-terminal, served through a fake channel.

What these pin: the shell's output arrives as bytes, its exit status is
the close, the first size and a resize both reach the terminal, the hub's
bytes reach the shell's input with credit offered back, a close from the
hub ends a shell that would run on, and a container shell is refused
typed when podman does not list the container.
"""

import threading
import time

import pytest

from neutrino_agent.streams import shell as shell_module
from neutrino_agent.streams.channel import StreamRefused
from neutrino_agent.streams.shell import ContainerShellStream, ShellStream
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
    assert closed == {"exit_code": 3, "code": "", "params": {}}
    assert channel.credits[0] > 0


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
    assert closed["exit_code"] == 4
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
    assert outcome["exit_code"] != 0


def test_a_command_that_cannot_start_closes_typed():
    channel = FakeChannel()

    closed = run_shell(channel, ["/nonexistent/shell"])

    assert closed["exit_code"] == 1
    assert closed["code"] == "shell_failed"


def test_login_shell_is_usable_and_absolute():
    shell = shell_module.login_shell()

    assert shell.startswith("/")
    assert "nologin" not in shell


def test_a_container_podman_does_not_list_is_refused(monkeypatch):
    monkeypatch.setattr(shell_module, "listed_containers", lambda: ["web"])
    stream = ContainerShellStream(FakeChannel(), {"name": "kuma"})

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.code == "container_unknown"
    assert refused.value.params == {"name": "kuma"}


def test_a_listed_container_is_opened_with_podman_exec(monkeypatch):
    monkeypatch.setattr(shell_module, "listed_containers", lambda: ["kuma"])
    stream = ContainerShellStream(FakeChannel(), {"name": "kuma"})

    stream.open()

    assert stream._command[:4] == [shell_module.PODMAN_BINARY, "exec", "-it", "kuma"]
    assert stream._command[4:6] == ["sh", "-c"]


def test_without_pseudo_terminals_a_shell_is_refused(monkeypatch):
    monkeypatch.setattr(shell_module, "pty", None)

    with pytest.raises(StreamRefused) as refused:
        ShellStream(FakeChannel(), {}).open()

    assert refused.value.code == "unsupported_platform"
