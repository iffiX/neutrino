"""Shells kept by id, driven through a fake terminal and a fake channel.

What these pin: a stream opened with a new id starts a shell under it and a
held id is attached to; a resumed id the agent does not hold is refused
``session_unknown``; a closed stream ends a shell unless it is persistent,
and a persistent one keeps its output while nobody watches; attaching again
sends the kept output first, at most 256 KB of it, then resizes the
terminal away and back; a second stream takes the shell and the first
closes ``session_taken``; ending a shell closes its stream with the exit
code and drops it from the list; and the list the report carries names each
session's account, start, title and whether it is attached and persistent.
"""

import queue
import threading
import time

import pytest

from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.streams import shell_session as session_module
from neutrino_agent.streams.shell_session import (
    SessionShellStream,
    ShellSession,
    ShellSessionRegistry,
)
from tests.streams.fake_channel import FakeChannel


class FakeTerminal:
    """A shell that prints what a test gives it and exits when told."""

    def __init__(self, *, start_error=None):
        self.written: list = []
        self.resizes: list = []
        self.is_started = False
        self._output: queue.Queue = queue.Queue()
        self._exit_code = 0
        self._start_error = start_error

    def start(self):
        if self._start_error is not None:
            raise self._start_error
        self.is_started = True

    def read(self):
        return self._output.get()

    def write(self, data):
        self.written.append(bytes(data))

    def resize(self, cols, rows):
        self.resizes.append((cols, rows))

    def terminate(self):
        self.exit(129)

    def finish(self):
        return self._exit_code

    def say(self, data: bytes):
        self._output.put(bytes(data))

    def exit(self, code: int):
        self._exit_code = code
        self._output.put(b"")


class FakeShellStream(SessionShellStream):
    """The session stream on a fake terminal the test holds."""

    def __init__(self, channel, args, *, terminal, sessions=None):
        super().__init__(channel, args, sessions=sessions)
        self.terminal = terminal

    def _make_session(self, *, on_change=None, on_end=None):
        return ShellSession(
            session_id=self._session_id,
            terminal=self.terminal,
            account="root",
            title="bash",
            on_change=on_change,
            on_end=on_end,
            clock=lambda: 1700000000.0,
        )


class Served:
    """One stream served on its own thread, the way the session serves it."""

    def __init__(self, stream):
        self.stream = stream
        self.result: dict = {}
        self.thread = threading.Thread(target=self._serve)
        stream.open()
        self.thread.start()

    def _serve(self):
        self.result.update(self.stream.run())

    def join(self) -> dict:
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        return self.result


def wait_until(check, timeout_s: float = 3.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("the condition never held")


def serve(registry, terminal, channel, **args) -> Served:
    stream = FakeShellStream(
        channel,
        {"cols": 80, "rows": 24, **args},
        terminal=terminal,
        sessions=registry,
    )
    return Served(stream)


@pytest.fixture(autouse=True)
def _quick_polls(monkeypatch):
    monkeypatch.setattr(session_module, "SESSION_POLL_S", 0.02)


@pytest.fixture
def registry():
    changes = []
    held = ShellSessionRegistry(on_change=lambda: changes.append(1))
    held.changes = changes
    return held


def test_a_new_id_starts_a_shell_and_its_exit_closes_the_stream(registry):
    terminal = FakeTerminal()
    channel = FakeChannel()
    served = serve(registry, terminal, channel, session_id="s1")
    terminal.say(b"hello\r\n")
    wait_until(lambda: b"hello" in channel.output())

    (listed,) = registry.describe()
    terminal.exit(3)

    assert served.join() == {"code": "", "params": {"exit_code": 3}}
    assert listed == {
        "session_id": "s1",
        "account": "root",
        "started_at": 1700000000,
        "title": "bash",
        "is_attached": True,
        "is_persistent": False,
    }
    wait_until(lambda: registry.describe() == [])
    assert registry.changes


def test_a_resumed_id_the_agent_does_not_hold_is_refused(registry):
    stream = FakeShellStream(
        FakeChannel(),
        {"session_id": "gone", "is_resumed": True},
        terminal=FakeTerminal(),
        sessions=registry,
    )

    with pytest.raises(StreamRefused) as refused:
        stream.open()

    assert refused.value.code == "session_unknown"
    assert refused.value.params == {"session_id": "gone"}


def test_a_closed_stream_ends_a_shell_that_is_not_persistent(registry):
    terminal = FakeTerminal()
    channel = FakeChannel()
    served = serve(registry, terminal, channel, session_id="s1")
    wait_until(lambda: registry.describe() != [])

    channel.close_from_hub()

    assert served.join()["params"] == {"exit_code": 129}
    wait_until(lambda: registry.describe() == [])


def test_a_persistent_shell_outlives_its_stream_and_keeps_its_output(registry):
    terminal = FakeTerminal()
    first = FakeChannel()
    served = serve(registry, terminal, first, session_id="s1")
    terminal.say(b"before\r\n")
    wait_until(lambda: b"before" in first.output())
    assert registry.persist("s1", True)

    first.close_from_hub()
    assert served.join() == {"code": "", "params": {}}
    terminal.say(b"while away\r\n")

    (listed,) = registry.describe()
    assert listed["is_attached"] is False
    assert listed["is_persistent"] is True

    second = FakeChannel()
    again = serve(registry, terminal, second, session_id="s1", cols=100, rows=30)
    wait_until(lambda: b"while away" in second.output())
    terminal.say(b"after\r\n")
    wait_until(lambda: b"after" in second.output())

    assert second.output().startswith(b"before\r\nwhile away\r\n")
    assert terminal.resizes[-2:] == [(100, 31), (100, 30)]
    assert registry.describe()[0]["is_attached"] is True
    terminal.exit(0)
    assert again.join()["params"] == {"exit_code": 0}


def test_a_second_stream_takes_the_shell_and_the_first_closes_taken(registry):
    terminal = FakeTerminal()
    first = FakeChannel()
    held = serve(registry, terminal, first, session_id="s1")
    wait_until(lambda: registry.describe() != [])

    taker = serve(registry, terminal, FakeChannel(), session_id="s1")

    assert held.join() == {"code": "session_taken", "params": {"session_id": "s1"}}
    assert registry.describe()[0]["is_attached"] is True
    terminal.exit(0)
    assert taker.join()["params"] == {"exit_code": 0}


def test_the_hubs_bytes_and_resizes_reach_the_kept_shell(registry):
    terminal = FakeTerminal()
    channel = FakeChannel()
    served = serve(registry, terminal, channel, session_id="s1")
    channel.feed(("data", b"ls\r"))
    channel.feed(("resize", 132, 50))
    wait_until(lambda: terminal.written and terminal.resizes)

    assert terminal.written == [b"ls\r"]
    assert terminal.resizes == [(132, 50)]
    assert channel.credits[1:] == [3]
    terminal.exit(0)
    served.join()


def test_stopping_a_session_closes_its_stream_with_the_exit_code(registry):
    terminal = FakeTerminal()
    served = serve(registry, terminal, FakeChannel(), session_id="s1")
    wait_until(lambda: registry.describe() != [])

    assert registry.stop("s1") is True

    assert served.join() == {"code": "", "params": {"exit_code": 129}}
    wait_until(lambda: registry.describe() == [])
    assert registry.stop("s1") is False
    assert registry.persist("s1", True) is False


def test_at_most_the_latest_256_kb_is_kept(registry, monkeypatch):
    monkeypatch.setattr(session_module, "AGENT_SHELL_KEPT_BYTES", 8)
    terminal = FakeTerminal()
    first = FakeChannel()
    served = serve(registry, terminal, first, session_id="s1")
    registry.persist("s1", True)
    terminal.say(b"0123456789abcdef")
    wait_until(lambda: b"cdef" in first.output())
    first.close_from_hub()
    served.join()

    second = FakeChannel()
    again = serve(registry, terminal, second, session_id="s1")
    wait_until(lambda: second.output() != b"")

    assert second.output() == b"89abcdef"
    terminal.exit(0)
    again.join()


def test_the_title_is_the_last_one_the_shell_set(registry):
    terminal = FakeTerminal()
    served = serve(registry, terminal, FakeChannel(), session_id="s1")
    terminal.say(b"\x1b]0;first\x07text\x1b]2;vim notes.md\x1b\\")
    wait_until(lambda: registry.describe()[0]["title"] == "vim notes.md")

    terminal.exit(0)
    served.join()


def test_sessions_are_listed_oldest_first():
    registry = ShellSessionRegistry()
    for session_id, started in (("late", 20.0), ("early", 10.0)):
        registry.take(
            session_id,
            is_resumed=False,
            make=lambda on_change, on_end, sid=session_id, at=started: ShellSession(
                session_id=sid,
                terminal=FakeTerminal(),
                account="root",
                title="bash",
                clock=lambda: at,
            ),
        )

    assert [entry["session_id"] for entry in registry.describe()] == [
        "early",
        "late",
    ]


def test_a_shell_that_cannot_start_is_refused_and_forgotten(registry):
    channel = FakeChannel()
    stream = FakeShellStream(
        channel,
        {"session_id": "s1"},
        terminal=FakeTerminal(start_error=OSError("no such shell")),
        sessions=registry,
    )
    stream.open()

    closed = stream.run()

    assert closed["code"] == "shell_failed"
    assert registry.describe() == []


def test_a_stream_without_an_id_keeps_nothing(registry):
    terminal = FakeTerminal()
    channel = FakeChannel()
    served = serve(registry, terminal, channel)

    channel.close_from_hub()

    assert served.join()["params"] == {"exit_code": 129}
    assert registry.describe() == []
