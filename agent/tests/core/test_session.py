"""One session the transport opened, driven with a control client a test plays.

What these pin: the protocol number this build speaks, the hello card with
no token, the welcome taken from a hub and the hub's time it names, a
``refused`` frame ending the session with its code and params, read
tolerantly; the ``state`` frame handed on, ``persist`` and
``stop_session`` answered with a ``reply`` of the same ``request``, ``pong``
taken quietly and a frame this build cannot read a typed
``frame_unreadable``, never a dead session; and the streams the hub opens:
each attached on a connection of its own, ``accept`` written before the
handler's records and its result the ``close``, a kind outside the table
closed ``kind_unknown``, a handler's refusal closing with its code and no
``accept``, a handler that raises closing ``agent_internal``, and a
command stream's lines and its exit code: a journal of 200 lines and 61 KB
up as 200 ``data`` records and a small close, a line past a record masked
whole and then cut with ``…``, and a close too large for a record sent as
``result_too_large`` with the stream's thread ending.
"""

import json
import socket
import threading

import pytest

from neutrino_agent.constants import PROTOCOL
from neutrino_agent.core.session import AgentSession
from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.streams import STREAM_KINDS
from neutrino_agent.streams.channel import StreamChannel
from neutrino_agent.transport.connection import LocalSocketConnection
from neutrino_agent.transport.records import RecordReader, decode_item, encode_json

HELLO = {
    "protocol": 4,
    "role": "agent",
    "id": "dev-1",
    "name": "box",
    "software": "neutrino_agent/0.0.0",
}
WELCOME = {
    "type": "welcome",
    "protocol": 4,
    "role": "hub",
    "id": "hub-1",
    "name": "lab-hub",
    "software": "neutrino_hub/0.6.0",
    "time": 1_700_000_000.5,
}


class PairControl:
    """The control client as a session reaches it: frames recorded, each
    attached stream one end of a socket pair whose other end the test reads."""

    def __init__(self):
        self.frames: list = []
        self.far_ends: dict = {}
        self.attached = threading.Event()

    def send_frame(self, frame, *, is_last=False):
        self.frames.append(frame)

    def attach(self, stream_id):
        near, far = socket.socketpair()
        self.far_ends[stream_id] = far
        self.attached.set()
        return StreamChannel(LocalSocketConnection("", sock=near), stream_id)

    def items(self, stream_id, timeout=5.0) -> list:
        """Every record the agent wrote on one stream, until it closed."""
        assert self.attached.wait(timeout)
        far = self.far_ends[stream_id]
        far.settimeout(timeout)
        reader = RecordReader(far)
        items = []
        while True:
            record = reader.read()
            if record is None:
                return items
            items.append(decode_item(*record))
            if items[-1][0] == "close":
                return items

    def feed(self, stream_id, data: bytes) -> None:
        self.far_ends[stream_id].sendall(data)


class RecordedShells:
    """The kept shells as ``persist`` and ``stop_session`` reach them."""

    def __init__(self, known=("tab-1",)):
        self.known = set(known)
        self.calls: list = []

    def persist(self, session_id, *, is_persistent=None, is_shared=None):
        self.calls.append(("persist", session_id, is_persistent, is_shared))
        return session_id in self.known

    def stop(self, session_id):
        self.calls.append(("stop", session_id))
        return session_id in self.known


def session_with(control=None, **kwargs) -> AgentSession:
    return AgentSession(
        control=control or PairControl(),
        hello=HELLO,
        log=lambda line: None,
        **kwargs,
    )


def test_this_build_speaks_protocol_four():
    assert PROTOCOL == 4


def test_hello_is_the_identity_card_and_carries_no_token():
    control = PairControl()

    session_with(control).say_hello()

    assert control.frames == [{"type": "hello", **HELLO}]
    assert "token" not in control.frames[0]


def test_the_welcome_opens_the_session_with_the_hubs_card_and_time():
    session = session_with()

    session.take(dict(WELCOME))

    assert session.is_open
    assert session.wait_welcome(0)
    assert (session.hub_id, session.hub_name, session.hub_software) == (
        "hub-1",
        "lab-hub",
        "neutrino_hub/0.6.0",
    )
    assert session.hub_time == 1_700_000_000.5


def test_a_welcome_without_time_names_no_hub_time():
    session = session_with()

    session.take({key: value for key, value in WELCOME.items() if key != "time"})

    assert session.is_open
    assert session.hub_time is None


def test_a_welcome_from_something_other_than_a_hub_is_unreadable():
    errors: list = []
    session = session_with(on_unreadable=errors.append)

    session.take(dict(WELCOME, role="client"))

    assert not session.is_open
    assert errors == [{"code": "frame_unreadable", "params": {"type": "welcome"}}]


@pytest.mark.parametrize(
    "frame, code, params",
    [
        (
            {"type": "refused", "code": "protocol_too_old", "params": {"min": 4}},
            "protocol_too_old",
            {"min": 4},
        ),
        ({"type": "refused", "code": "replaced"}, "replaced", {}),
        ({"type": "refused", "params": "nonsense"}, "channel_refused", {}),
    ],
)
def test_a_refused_frame_ends_the_session_with_its_code(frame, code, params):
    session = session_with()
    session.take(dict(WELCOME))

    session.take(frame)

    assert session.is_ended and not session.is_open
    assert (session.refusal.code, session.refusal.params) == (code, params)
    assert not session.wait_welcome(0)


def test_a_state_frame_hands_the_document_on_without_its_type():
    documents: list = []
    session = session_with(on_state=documents.append)

    session.take({"type": "state", "hash": "h1", "modules": {}})

    assert documents == [{"hash": "h1", "modules": {}}]


@pytest.mark.parametrize(
    "frame",
    [{"type": "mystery"}, {"type": 7}, {}, {"hello": "there"}],
)
def test_a_frame_this_build_cannot_read_is_a_typed_error_and_nothing_ends(frame):
    errors: list = []
    session = session_with(on_unreadable=errors.append)
    session.take(dict(WELCOME))

    session.take(frame)

    assert session.is_open
    assert errors and errors[0]["code"] == "frame_unreadable"


def test_a_pong_is_taken_quietly():
    errors: list = []
    session = session_with(on_unreadable=errors.append)

    session.take({"type": "pong", "nonce": "n"})

    assert errors == []


def test_persist_is_answered_with_a_reply_of_its_request():
    control = PairControl()
    shells = RecordedShells()
    session = session_with(control, shells=shells)

    session.take(
        {
            "type": "persist",
            "request": "r1",
            "session_id": "tab-1",
            "is_shared": True,
        }
    )
    session.take({"type": "persist", "request": "r2", "session_id": "gone"})

    assert shells.calls[0] == ("persist", "tab-1", None, True)
    assert control.frames == [
        {"type": "reply", "request": "r1", "code": "", "params": {}},
        {
            "type": "reply",
            "request": "r2",
            "code": "session_unknown",
            "params": {"session_id": "gone"},
        },
    ]


def test_stop_session_ends_the_kept_shell_and_replies():
    control = PairControl()
    shells = RecordedShells()
    session = session_with(control, shells=shells)

    session.take({"type": "stop_session", "request": "r3", "session_id": "tab-1"})

    assert shells.calls == [("stop", "tab-1")]
    assert control.frames == [
        {"type": "reply", "request": "r3", "code": "", "params": {}}
    ]


def test_a_report_is_one_report_frame():
    control = PairControl()

    session_with(control).report({"state_hash": "h", "modules": {}})

    assert control.frames == [{"type": "report", "state_hash": "h", "modules": {}}]


def test_the_kind_table_is_shell_exec_file_and_command_and_nothing_else():
    assert set(STREAM_KINDS) == {"shell", "exec", "file", "command"}


@pytest.mark.parametrize("kind", ["connect", "order", "", "log"])
def test_a_kind_outside_the_table_is_closed_kind_unknown(kind):
    control = PairControl()
    session = session_with(control, stream_kinds={})

    session.serve_stream("s2", {"kind": kind})

    assert control.items("s2") == [("close", "kind_unknown", {"kind": kind})]


class EchoHandler:
    """A handler that sends back what it was opened with, then closes."""

    def __init__(self, channel, args):
        self.channel = channel
        self.args = args

    def open(self):
        if self.args.get("is_refused"):
            raise StreamRefused("account_not_enabled", {"account": "eve"})

    def run(self):
        if self.args.get("is_broken"):
            raise LookupError("broken")
        self.channel.send_bytes(json.dumps(self.args).encode())
        self.channel.send_stderr(b"warning")
        item = self.channel.recv(timeout=5)
        return {"code": "", "params": {"exit_code": 0, "got": list(item[1:2])}}


def test_a_stream_is_attached_accepted_served_and_closed_with_its_result():
    control = PairControl()
    session = session_with(control, stream_kinds={"echo": EchoHandler})

    session.serve_stream("s4", {"kind": "echo", "cols": 80})
    assert control.attached.wait(5)
    control.feed("s4", encode_json(6, {"cols": 100, "rows": 30}))
    items = control.items("s4")

    assert items[0] == ("accept",)
    assert items[1] == ("data", b'{"cols": 80}')
    assert items[2] == ("stderr", b"warning")
    assert items[3] == ("close", "", {"exit_code": 0, "got": [100]})


def test_a_handlers_refusal_closes_with_its_code_and_no_accept():
    control = PairControl()
    session = session_with(control, stream_kinds={"echo": EchoHandler})

    session.serve_stream("s6", {"kind": "echo", "is_refused": True})

    assert control.items("s6") == [("close", "account_not_enabled", {"account": "eve"})]


def test_a_handler_that_raises_closes_agent_internal():
    control = PairControl()
    session = session_with(control, stream_kinds={"echo": EchoHandler})

    session.serve_stream("s8", {"kind": "echo", "is_broken": True})

    items = control.items("s8")
    assert items[0] == ("accept",)
    assert items[-1] == ("close", "agent_internal", {"error": "LookupError"})


def test_a_command_stream_sends_its_lines_and_closes_with_its_exit():
    control = PairControl()

    def run(module, verb, args, on_line):
        on_line("one")
        return {"exit_code": 0, "output": "done", "params": {}, "code": ""}

    session = session_with(control, run_command=run)

    session.serve_stream("s10", {"kind": "command", "module": "agent", "verb": "x"})

    items = control.items("s10")
    assert items == [
        ("accept",),
        ("data", b"one\n"),
        ("data", b"done\n"),
        ("close", "", {"exit_code": 0, "result": {}}),
    ]


class CodegLog(ModuleRunner):
    """A module whose log is the lines it was handed."""

    name = "codeg"

    def __init__(self, lines):
        super().__init__(platform=None)
        self._lines = lines

    def journal_text(self, lines):
        return list(self._lines)


def serve_journal(control, log_lines, stream_id) -> list:
    """A ``journal`` command of 200 lines on a runner of those log lines."""
    runner = CodegLog(log_lines)

    def run(module, verb, args, on_line):
        return runner.command(verb, args, on_line)

    session_with(control, run_command=run).serve_stream(
        stream_id,
        {"kind": "command", "module": "codeg", "verb": "journal", "lines": 200},
    )
    return control.items(stream_id)


def test_a_journal_of_200_lines_and_61_kb_goes_up_as_200_records_and_its_exit():
    lines = [
        f"\x1b[2m2026-11-07T10:{n // 60:02d}:{n % 60:02d}Z\x1b[0m \x1b[32mINFO\x1b[0m "
        f'codeg_server: "GET /api/sessions" ' + "x" * 240
        for n in range(200)
    ]
    # As one close's JSON, these lines are past a record's 64 KiB.
    assert sum(len(line) + 1 for line in lines) > 61_000
    assert len(json.dumps({"output": "\n".join(lines)})) > 64 * 1024

    items = serve_journal(PairControl(), lines, "s12")

    assert items[0] == ("accept",)
    assert [item[1] for item in items[1:-1]] == [
        (line + "\n").encode("utf-8") for line in lines
    ]
    assert items[-1] == ("close", "", {"exit_code": 0, "result": {}})


def test_a_journal_line_past_a_record_goes_up_masked_whole_then_cut():
    token_line = "x" * 65500 + ": " + "abc123" * 10
    long_line = "codeg: " + "y" * (100 * 1024)

    items = serve_journal(PairControl(), [token_line, long_line], "s14")

    assert items[1] == ("data", ("x" * 65500 + ": ***\n").encode("utf-8"))
    assert len(items[2][1]) == 64 * 1024
    assert items[2][1].startswith(b"codeg: yyy")
    assert items[2][1].endswith("…\n".encode("utf-8"))
    assert items[-1] == ("close", "", {"exit_code": 0, "result": {}})


def test_a_close_too_large_for_a_record_is_sent_as_result_too_large():
    control = PairControl()

    def run(module, verb, args, on_line):
        return {
            "exit_code": 0,
            "code": "",
            "params": {},
            "output": "",
            "result": {"lines": ["x" * 300] * 300},
        }

    session_with(control, run_command=run).serve_stream(
        "s16", {"kind": "command", "module": "podman", "verb": "machine_read"}
    )

    assert control.items("s16") == [
        ("accept",),
        ("close", "result_too_large", {"limit": 64 * 1024}),
    ]
