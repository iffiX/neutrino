"""Shells kept by id, driven through a fake terminal and a fake channel.

What these pin: a stream opened with a new id starts a shell under it and a
held id is attached to; a resumed id the agent does not hold is refused
``session_unknown``; a closed stream ends a shell unless it is persistent,
and a persistent one keeps its output while nobody watches; attaching again
sends the kept output first, at most 256 KB of it and without any sequence
that asks the terminal to answer, nor the rest of one its cut start split,
while live output keeps them, then resizes the
terminal away and back; streams attached together each get the output,
each one's input reaches the shell, the terminal takes the smallest window,
and one leaving leaves the others; a shared shell outlives its last stream;
ending a shell closes its streams with the exit code and drops it from the
list; and the list the report carries names each session's account, start,
title, owner, sharing, persistence and how many streams are attached.
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
    strip_queries,
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
    served = serve(registry, terminal, channel, session_id="s1", owner="client:7")
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
        "owner": "client:7",
        "is_attached": True,
        "is_persistent": False,
        "is_shared": False,
        "attached_count": 1,
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


def test_two_streams_both_get_the_output_and_both_type_into_the_shell(registry):
    terminal = FakeTerminal()
    first, second = FakeChannel(), FakeChannel()
    held = serve(registry, terminal, first, session_id="s1")
    wait_until(lambda: registry.describe() != [])
    joined = serve(registry, terminal, second, session_id="s1")
    wait_until(lambda: registry.describe()[0]["attached_count"] == 2)

    terminal.say(b"shown to both\r\n")
    wait_until(lambda: b"shown to both" in first.output())
    wait_until(lambda: b"shown to both" in second.output())
    first.feed(("data", b"ls\r"))
    second.feed(("data", b"pwd\r"))
    wait_until(lambda: len(terminal.written) == 2)

    assert sorted(terminal.written) == [b"ls\r", b"pwd\r"]
    terminal.exit(0)
    assert held.join()["params"] == {"exit_code": 0}
    assert joined.join()["params"] == {"exit_code": 0}


def test_one_stream_leaving_leaves_the_other_attached(registry):
    terminal = FakeTerminal()
    first, second = FakeChannel(), FakeChannel()
    held = serve(registry, terminal, first, session_id="s1")
    wait_until(lambda: registry.describe() != [])
    joined = serve(registry, terminal, second, session_id="s1")
    wait_until(lambda: registry.describe()[0]["attached_count"] == 2)

    first.close_from_hub()

    assert held.join() == {"code": "", "params": {}}
    (listed,) = registry.describe()
    assert listed["attached_count"] == 1
    assert listed["is_attached"] is True
    terminal.say(b"still here\r\n")
    wait_until(lambda: b"still here" in second.output())
    second.close_from_hub()
    assert joined.join()["params"] == {"exit_code": 129}
    wait_until(lambda: registry.describe() == [])


def test_the_terminal_takes_the_smallest_attached_window(registry):
    terminal = FakeTerminal()
    first, second = FakeChannel(), FakeChannel()
    held = serve(registry, terminal, first, session_id="s1", cols=120, rows=40)
    wait_until(lambda: registry.describe() != [])
    joined = serve(registry, terminal, second, session_id="s1", cols=100, rows=50)
    wait_until(lambda: registry.describe()[0]["attached_count"] == 2)

    assert terminal.resizes == [(100, 41), (100, 40)]
    first.feed(("resize", 90, 60))
    wait_until(lambda: terminal.resizes[-1] == (90, 50))
    first.close_from_hub()
    held.join()
    wait_until(lambda: terminal.resizes[-1] == (100, 50))

    terminal.exit(0)
    joined.join()


def test_a_late_stream_gets_the_kept_output_before_the_live_stream(registry):
    terminal = FakeTerminal()
    first, late = FakeChannel(), FakeChannel()
    held = serve(registry, terminal, first, session_id="s1")
    terminal.say(b"earlier\r\n")
    wait_until(lambda: b"earlier" in first.output())

    joined = serve(registry, terminal, late, session_id="s1", is_resumed=True)
    wait_until(lambda: b"earlier" in late.output())
    terminal.say(b"live\r\n")
    wait_until(lambda: b"live" in late.output())

    assert late.output() == b"earlier\r\nlive\r\n"
    assert first.output() == b"earlier\r\nlive\r\n"
    terminal.exit(0)
    held.join()
    joined.join()


def test_a_shared_shell_outlives_its_last_stream(registry):
    terminal = FakeTerminal()
    channel = FakeChannel()
    served = serve(registry, terminal, channel, session_id="s1", is_shared=True)
    wait_until(lambda: registry.describe() != [])

    channel.close_from_hub()

    assert served.join() == {"code": "", "params": {}}
    (listed,) = registry.describe()
    assert listed["is_shared"] is True
    assert listed["attached_count"] == 0
    assert registry.stop("s1") is True
    wait_until(lambda: registry.describe() == [])


def test_persist_sets_each_flag_it_names_and_keeps_the_other(registry):
    terminal = FakeTerminal()
    served = serve(registry, terminal, FakeChannel(), session_id="s1")
    wait_until(lambda: registry.describe() != [])

    assert registry.persist("s1", is_shared=True)
    assert registry.persist("s1", is_persistent=True)
    assert registry.persist("s1", is_shared=False)

    (listed,) = registry.describe()
    assert (listed["is_persistent"], listed["is_shared"]) == (True, False)
    terminal.exit(0)
    served.join()


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


# --- the terminal's queries in the replay ---

# What vim 8.2 printed on a pseudo-terminal with TERM=xterm-256color, from its
# start to its first screen: two cursor position reports, the secondary
# device attributes and the foreground and background colour queries.
VIM_START = (
    b"\x1b[?1049h\x1b[22;0;0t\x1b[>4;2m\x1b[?1h\x1b=\x1b[?2004h\x1b[?1004h"
    b"\x1b[1;24r\x1b[?12h\x1b[?12l\x1b[22;2t\x1b[22;1t\x1b[27m\x1b[23m\x1b[29m"
    b"\x1b[m\x1b[H\x1b[2J\x1b[2;1H\xe2\x96\xbd\x1b[6n\x1b[2;1H  \x1b[3;1H"
    b"\x1bPzz\x1b\\\x1b[0%m\x1b[6n\x1b[3;1H           \x1b[1;1H\x1b[>c"
    b"\x1b]10;?\x07\x1b]11;?\x07\x1b[?25l\x1b[2;1H\x1b[94m~"
)
VIM_START_ANSWERED_NOTHING = (
    b"\x1b[?1049h\x1b[22;0;0t\x1b[>4;2m\x1b[?1h\x1b=\x1b[?2004h\x1b[?1004h"
    b"\x1b[1;24r\x1b[?12h\x1b[?12l\x1b[22;2t\x1b[22;1t\x1b[27m\x1b[23m\x1b[29m"
    b"\x1b[m\x1b[H\x1b[2J\x1b[2;1H\xe2\x96\xbd\x1b[2;1H  \x1b[3;1H"
    b"\x1bPzz\x1b\\\x1b[0%m\x1b[3;1H           \x1b[1;1H"
    b"\x1b[?25l\x1b[2;1H\x1b[94m~"
)


def test_the_queries_a_terminal_answers_are_taken_out_of_vims_start():
    assert strip_queries(VIM_START) == VIM_START_ANSWERED_NOTHING


@pytest.mark.parametrize(
    "query",
    [
        b"\x1b[c",
        b"\x1b[0c",
        b"\x1b[>c",
        b"\x1b[>0c",
        b"\x1b[=c",
        b"\x1b[5n",
        b"\x1b[6n",
        b"\x1b[?6n",
        b"\x1b]10;?\x07",
        b"\x1b]11;?\x1b\\",
        b"\x1b]12;?\x07",
        b"\x1b]4;1;?\x07",
    ],
)
def test_each_query_is_taken_out(query):
    assert strip_queries(b"a" + query + b"b") == b"ab"


def test_what_draws_and_what_sets_stays():
    drawn = b"\x1b[31mred\x1b[m\x1b]0;title\x07\x1b]11;#000000\x07\x1b[2J\x1b[?1;2c"

    assert strip_queries(drawn) == drawn


# What the same vim printed once its secondary device attributes were
# answered as xterm.js answers them: the XTGETTCAP requests it sends next.
VIM_TERMCAP = (
    b"\x1b[1;1H\x1b[?25h\x1bP+q436f\x1b\\\x1bP+q6b75\x1b\\\x1bP+q6b64\x1b\\"
    b"\x1bP+q6b72\x1b\\\x1bP+q6b6c\x1b\\\x1bP+q2332\x1b\\\x1bP+q2334\x1b\\"
    b"\x1bP+q2569\x1b\\\x1bP+q2a37\x1b\\\x1bP+q6b31\x1b\\\x1b[27m\x1b[23m"
    b"\x1b[29m\x1b[m\x1b[H\x1b[2J\x1b[?25l\x1b[2;1H\x1b[94m~"
)
VIM_TERMCAP_ANSWERED_NOTHING = (
    b"\x1b[1;1H\x1b[?25h\x1b[27m\x1b[23m"
    b"\x1b[29m\x1b[m\x1b[H\x1b[2J\x1b[?25l\x1b[2;1H\x1b[94m~"
)
# The cursor blink mode request vim 9 sends on macOS, answered ``ESC[?12;2$y``.
VIM_MODE_REQUEST = b"\x1b[?12$p"
# What htop 3 printed on the same terminal from its start: nothing it asks.
HTOP_START = (
    b"\x1b[?1049h\x1b[22;0;0t\x1b[1;24r\x1b(B\x1b[m\x1b[4l\x1b[?7h\x1b[?1h"
    b"\x1b=\x1b[?25l\x1b[39;49m\x1b[?1006;1000h\x1b[39;49m\x1b(B\x1b[m\x1b[H"
    b"\x1b[2J\x1b[2d  \x1b[36m  0\x1b[39m\x1b(B\x1b[0;1m[\x1b(B\x1b[0m\x1b[31m3"
    b"\x1b[33m3\x1b(B\x1b[0;1m\x1b[90m.\x1b[39m]\x1b(B\x1b[m"
)


def test_vims_capability_requests_are_taken_out():
    assert strip_queries(VIM_TERMCAP) == VIM_TERMCAP_ANSWERED_NOTHING


def test_vims_mode_request_is_taken_out_and_the_rest_of_its_start_stays():
    replay = strip_queries(VIM_START + VIM_MODE_REQUEST + VIM_TERMCAP)

    assert replay == VIM_START_ANSWERED_NOTHING + VIM_TERMCAP_ANSWERED_NOTHING
    assert b"$p" not in replay


def test_htops_start_asks_nothing_and_stays_whole():
    assert strip_queries(HTOP_START) == HTOP_START


@pytest.mark.parametrize(
    "query",
    [
        b"\x1b[?15n",
        b"\x1b[?26n",
        b"\x1b[?996n",
        b"\x1b[2$p",
        b"\x1b[20$p",
        b"\x1b[?1049$p",
        b"\x1b[?2026$p",
        b"\x1b[>q",
        b"\x1b[>0q",
        b"\x1b[?u",
        b"\x1b[11t",
        b"\x1b[13t",
        b"\x1b[13;2t",
        b"\x1b[14t",
        b"\x1b[14;2t",
        b"\x1b[16t",
        b"\x1b[18t",
        b"\x1b[19t",
        b"\x1b[20t",
        b"\x1b[21t",
        b"\x1bP$q m\x1b\\",
        b'\x1bP$q"q\x1b\\',
        b"\x1bP$qr\x07",
        b"\x1bP+q544e\x1b\\",
        b"\x1bP+q436f;6b75\x1b\\",
        b"\x1b]10;?;?\x07",
        b"\x1b]17;?\x1b\\",
        b"\x1b]19;?\x07",
        b"\x1b]4;1;?;2;?\x07",
        b"\x1b]5;0;?\x1b\\",
        b"\x1b]52;c;?\x07",
        b"\x1b]52;;?\x1b\\",
    ],
)
def test_each_family_of_request_is_taken_out(query):
    replay = strip_queries(b"a" + query + b"b")

    assert replay == b"ab", query


@pytest.mark.parametrize(
    "answer",
    [
        b"\x1b[?64;1;2;6;9;15;18;21;22c",
        b"\x1b[>0;276;0c",
        b"\x1b[0n",
        b"\x1b[3;1R",
        b"\x1b[?12;2$y",
        b"\x1b[12;2$y",
        b"\x1bP>|XTerm(380)\x1b\\",
        b"\x1b[?1u",
        b"\x1b[>1u",
        b"\x1b[8;24;80t",
        b"\x1b[4;600;800t",
        b"\x1b[22;0;0t",
        b"\x1b[23;0;0t",
        b"\x1bP1$r0m\x1b\\",
        b"\x1bP1+r544e=787465726d\x1b\\",
        b"\x1b]11;rgb:0000/0000/0000\x07",
        b"\x1b]4;1;rgb:cdcd/0000/0000\x1b\\",
        b"\x1b]52;c;aGVsbG8=\x07",
        b"\x1b[?1;2c",
    ],
)
def test_answers_and_settings_stay(answer):
    assert strip_queries(b"a" + answer + b"b") == b"a" + answer + b"b"


@pytest.mark.parametrize(
    "rest",
    [b"[?12$p", b"?12$p", b"12$p", b"$p", b"+q6b75\x1b\\", b"]11;?\x07", b"6n"],
)
def test_the_rest_of_a_request_the_cut_split_is_dropped(rest):
    replay = strip_queries(rest + b"\x1b[31mred\r\nnext", is_cut=True)

    assert replay == b"\x1b[31mred\r\nnext"


def test_an_uncut_head_is_kept_whole():
    assert strip_queries(b"12$p\x1b[31mred", is_cut=False) == b"12$p\x1b[31mred"


def test_a_cut_head_that_starts_a_sequence_is_kept():
    assert strip_queries(b"\x1b[31mred", is_cut=True) == b"\x1b[31mred"


def test_the_replay_drops_a_request_the_window_cut_in_two(registry, monkeypatch):
    monkeypatch.setattr(session_module, "AGENT_SHELL_KEPT_BYTES", 16)
    terminal = FakeTerminal()
    first = FakeChannel()
    served = serve(registry, terminal, first, session_id="s1")
    registry.persist("s1", True)
    terminal.say(b"\x1b[?12$p\x1b[31mred\r\n$ ")
    wait_until(lambda: first.output().endswith(b"$ "))
    first.close_from_hub()
    served.join()

    second = FakeChannel()
    again = serve(registry, terminal, second, session_id="s1", is_resumed=True)
    wait_until(lambda: second.output() != b"")

    assert second.output() == b"\x1b[31mred\r\n$ "
    terminal.exit(0)
    again.join()


def test_the_replay_has_no_queries_and_the_live_output_keeps_them(registry):
    started = VIM_START + VIM_MODE_REQUEST + VIM_TERMCAP
    live = VIM_MODE_REQUEST + VIM_TERMCAP + b"\x1b[c"
    terminal = FakeTerminal()
    first, late = FakeChannel(), FakeChannel()
    held = serve(registry, terminal, first, session_id="s1")
    terminal.say(started)
    wait_until(lambda: first.output().endswith(b"~"))

    joined = serve(registry, terminal, late, session_id="s1", is_resumed=True)
    wait_until(lambda: late.output().endswith(b"~"))
    terminal.say(live)
    wait_until(lambda: late.output().endswith(b"\x1b[c"))

    assert late.output() == (
        VIM_START_ANSWERED_NOTHING + VIM_TERMCAP_ANSWERED_NOTHING + live
    )
    assert first.output() == started + live
    terminal.exit(0)
    held.join()
    joined.join()
