"""One connection to the hub, driven with a scripted socket client.

What these pin: the hello card and the welcome card, a refusal at the door
raised with its code, a report on the interval and at once when something
changed, the stream layer as protocol.md draws it: an even id from the hub
served, odd ids counting up for the streams this side opens, a binary
frame as a big-endian u32 id and bytes, a short or unaddressed frame
dropped, no ``opened`` frame ever, an unknown kind closed ``kind_unknown``,
a close whose params are the result and whose code is a refusal, credit
holding bytes back, and how the socket's end is reported to the loop that
owns it.
"""

import json
import queue
import threading
import time

import pytest

from neutrino_agent.constants import AGENT_WS_STREAM_ID_BYTES
from neutrino_agent.core.session import AgentSession
from neutrino_agent.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    SocketClosed,
    StreamRefused,
)

HELLO = {
    "protocol": 1,
    "role": "agent",
    "id": "dev-1",
    "name": "box",
    "software": "neutrino_agent/0.0.0",
    "token": "tok",
}


def frame(stream_id: int, data: bytes) -> bytes:
    """One binary frame as the wire carries it."""
    return stream_id.to_bytes(AGENT_WS_STREAM_ID_BYTES, "big") + data


class ScriptedClient:
    """A socket client whose inbound frames a test feeds one by one.

    Attributes:
        drop_after_report: When set, the first report sent makes the reader
            see the hub hanging up, so a scripted connection ends after the
            report it was opened to observe.
    """

    def __init__(self):
        self.inbound: queue.Queue = queue.Queue()
        self.sent: list = []
        self.sent_bytes: list = []
        self.is_connected = False
        self.is_closed = False
        self.connect_error = None
        self.drop_after_report = False
        self.local_address = ""

    def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.is_connected = True

    def send_text(self, text: str) -> None:
        if self.is_closed:
            raise GatewayUnreachable("the socket is closed")
        message = json.loads(text)
        self.sent.append(message)
        if self.drop_after_report and message.get("type") == "report":
            self.drop_after_report = False
            self.inbound.put(GatewayUnreachable("hung up"))

    def send_bytes(self, data: bytes) -> None:
        if self.is_closed:
            raise GatewayUnreachable("the socket is closed")
        self.sent_bytes.append(bytes(data))

    def recv(self):
        item = self.inbound.get()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, bytes):
            return "binary", item
        return "text", json.dumps(item)

    def close(self, code: int = 1000, reason: str = "") -> None:
        self.is_closed = True
        self.inbound.put(GatewayUnreachable("closed from here"))

    def feed(self, message) -> None:
        """Deliver one frame, or one exception, to the reader."""
        self.inbound.put(message)

    def frames(self, kind: str) -> list:
        return [message for message in self.sent if message["type"] == kind]

    def wait_for(self, kind: str, count: int = 1, timeout_s: float = 3.0) -> list:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            found = self.frames(kind)
            if len(found) >= count:
                return found
            time.sleep(0.005)
        raise AssertionError(f"no {kind} frame in {timeout_s}s: {self.sent}")

    def wait_for_bytes(self, count: int = 1, timeout_s: float = 3.0) -> list:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if len(self.sent_bytes) >= count:
                return list(self.sent_bytes)
            time.sleep(0.005)
        raise AssertionError(f"no binary frame in {timeout_s}s: {self.sent_bytes}")


def make_session(client, **overrides):
    """A session over one scripted client with recording callbacks."""
    orders: list = []
    commands: list = []
    news = threading.Event()

    def run_order(order, on_line):
        orders.append(order)
        on_line("step one")
        on_line("step two")
        return {"state": "done", "code": "", "params": {}, "output": "step one"}

    def run_command(action, args, on_line=None):
        commands.append((action, args))
        if on_line is not None:
            on_line("running")
        return {"exit_code": 0, "code": "", "params": {}, "output": "ran"}

    fields = dict(
        client=client,
        hello=dict(HELLO),
        report=lambda: {"metrics": {"cpu_percent": 1}},
        run_order=run_order,
        run_command=run_command,
        news=news,
        log=lambda message: None,
        interval_s=0.05,
    )
    fields.update(overrides)
    session = AgentSession(**fields)
    return session, orders, commands, news


def welcome(**fields) -> dict:
    return {
        "type": "welcome",
        "protocol": 1,
        "role": "hub",
        "id": "hub-1",
        "name": "hub",
        "software": "neutrino_hub/0.2.0",
        **fields,
    }


class EchoStream:
    """A byte-carrying handler: sends back what it was given, records the
    rest, and returns on ``quit`` or the hub's close."""

    instances: list = []

    def __init__(self, channel, args):
        self.channel = channel
        self.args = args
        self.items: list = []
        EchoStream.instances.append(self)

    def open(self):
        if self.args.get("refuse"):
            raise StreamRefused("container_unknown", {"name": "kuma"})
        self.channel.offer_credit(1024)

    def run(self):
        while True:
            item = self.channel.recv(timeout=3)
            if item is None:
                return {"code": "", "params": {"exit_code": 9}}
            self.items.append(item)
            if item == ("data", b"quit"):
                return {"code": "", "params": {"exit_code": 0}}
            if item[0] == "data":
                self.channel.send_bytes(b"echo:" + item[1])
            if item[0] == "close":
                return {"code": "", "params": {"exit_code": 0}}


def serving(session):
    """Run serve() on a thread; returns the thread and the outcome holder."""
    outcome: dict = {}

    def run():
        outcome["failure"] = session.serve()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


def connected(client, **overrides):
    """A welcomed session serving on a thread, with its serve thread."""
    session, orders, commands, news = make_session(client, **overrides)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)
    return session, thread, orders, commands


def wait_until(condition, timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("the condition never held")


# --- hello and welcome ---


def test_connect_says_hello_with_the_card_and_takes_the_welcome():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome())

    session.connect()

    (hello,) = client.frames("hello")
    assert hello == {"type": "hello", **HELLO}
    assert session.hub_id == "hub-1"
    assert session.hub_name == "hub"
    assert session.hub_software == "neutrino_hub/0.2.0"
    assert session.is_open
    session.close()


def test_a_first_frame_that_is_no_welcome_is_unreachable():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed({"type": "state", "hash": "", "modules": {}})

    with pytest.raises(GatewayUnreachable) as caught:
        session.connect()

    assert not isinstance(caught.value, GatewayRefusedDetail)
    assert client.is_closed


def test_a_welcome_from_something_other_than_a_hub_is_unreachable():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome(role="agent"))

    with pytest.raises(GatewayUnreachable) as caught:
        session.connect()

    assert not isinstance(caught.value, GatewayRefusedDetail)
    assert client.is_closed


def test_a_refused_first_frame_raises_its_code_and_params():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(
        {
            "type": "refused",
            "code": "protocol_too_new",
            "params": {"peer": 2, "hub": 1, "min": 1},
        }
    )

    with pytest.raises(GatewayRefusedDetail) as refused:
        session.connect()

    assert refused.value.code == "protocol_too_new"
    assert refused.value.params == {"peer": 2, "hub": 1, "min": 1}
    assert client.is_closed
    assert not session.is_open


@pytest.mark.parametrize(
    "frame_sent",
    [
        {"type": "refused"},
        {"type": "refused", "code": "", "params": {}},
        {"type": "refused", "code": "binding_unknown", "params": "words"},
    ],
)
def test_a_refused_frame_is_read_tolerantly(frame_sent):
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(frame_sent)

    with pytest.raises(GatewayRefusedDetail) as refused:
        session.connect()

    assert refused.value.code == (frame_sent.get("code") or "channel_refused")
    assert refused.value.params == {}


def test_a_close_4000_before_any_frame_is_channel_refused():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(SocketClosed(4000, "binding_unknown"))

    with pytest.raises(GatewayRefusedDetail) as refused:
        session.connect()

    assert refused.value.code == "channel_refused"


def test_a_connect_error_passes_straight_through():
    client = ScriptedClient()
    client.connect_error = GatewayUnreachable("no route")
    session, _, _, _ = make_session(client)

    with pytest.raises(GatewayUnreachable):
        session.connect()


def test_the_sessions_local_address_is_the_sockets_own():
    client = ScriptedClient()
    client.local_address = "192.0.2.10"
    session, _, _, _ = make_session(client)

    assert session.local_address == "192.0.2.10"


# --- reports ---


def test_a_report_goes_up_at_once_then_on_the_interval():
    client = ScriptedClient()
    session, _, _, _ = make_session(client, interval_s=0.05)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    reports = client.wait_for("report", count=3)

    assert reports[0]["metrics"] == {"cpu_percent": 1}
    session.close()
    thread.join(timeout=2)


def test_news_cuts_the_wait_short():
    client = ScriptedClient()
    session, _, _, news = make_session(client, interval_s=60)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)
    client.wait_for("report", count=1)

    news.set()

    client.wait_for("report", count=2, timeout_s=2)
    session.close()
    thread.join(timeout=2)


def test_the_tick_hook_runs_once_per_interval():
    client = ScriptedClient()
    ticks: list = []
    session, _, _, _ = make_session(
        client, interval_s=0.02, on_tick=lambda: ticks.append(1)
    )
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.wait_for("report", count=3)

    assert ticks
    session.close()
    thread.join(timeout=2)


def test_a_state_frame_hands_the_document_on():
    """The frame's sections are the document, ``{hash, modules, desktop}``;
    the frame's own type is not part of it."""
    client = ScriptedClient()
    taken: list = []
    session, thread, _, _ = connected(client, on_state=taken.append)

    client.feed(
        {
            "type": "state",
            "hash": "h3",
            "modules": {"samba": {"want": "running", "config": {}}},
            "desktop": {"seat_password": ""},
        }
    )
    client.feed({"type": "state", "hash": "h4"})
    client.feed({"type": "open", "stream": 2, "kind": "command"})
    client.feed({"type": "credit", "stream": 2, "bytes": 4096})

    client.wait_for("close")
    assert taken == [
        {
            "hash": "h3",
            "modules": {"samba": {"want": "running", "config": {}}},
            "desktop": {"seat_password": ""},
        },
        {"hash": "h4"},
    ]
    assert session.state_hash == "h4"
    assert client.frames("state_request") == []
    session.close()
    thread.join(timeout=2)


def test_state_frames_are_taken_and_nothing_else_is_fatal():
    client = ScriptedClient()
    session, thread, _, _ = connected(client)

    client.feed({"type": "state", "hash": "h2", "modules": {}})
    client.feed({"type": "resize", "stream": "x", "cols": 1, "rows": 1})
    client.feed({"type": "credit", "stream": "x", "bytes": 1})
    client.feed({"type": "whatever"})
    client.feed({"type": "open", "stream": "00000006", "kind": "command"})
    client.feed({"type": "open", "stream": 2, "kind": "command"})
    client.feed({"type": "credit", "stream": 2, "bytes": 4096})

    (closed,) = client.wait_for("close")
    assert closed["stream"] == 2
    assert session.state_hash == "h2"
    assert session.is_open
    session.close()
    thread.join(timeout=2)


# --- the one-call kinds: order, command, validate ---


def test_an_order_stream_runs_the_engine_and_closes_with_its_state():
    client = ScriptedClient()
    session, thread, orders, _ = connected(client)

    client.feed(
        {
            "type": "open",
            "stream": 2,
            "kind": "order",
            "id": "o1",
            "module": "fakedesk",
            "action": "install",
        }
    )
    client.feed({"type": "credit", "stream": 2, "bytes": 4096})

    assert client.wait_for_bytes(count=2) == [
        frame(2, b"step one\n"),
        frame(2, b"step two\n"),
    ]
    (closed,) = client.wait_for("close")
    assert closed == {
        "type": "close",
        "stream": 2,
        "code": "",
        "params": {"state": "done", "output": "step one"},
    }
    assert orders == [{"id": "o1", "module": "fakedesk", "action": "install"}]
    assert client.frames("opened") == []
    assert client.frames("event") == []
    session.close()
    thread.join(timeout=2)


def test_a_command_stream_closes_with_its_exit_in_the_params():
    client = ScriptedClient()
    session, thread, _, commands = connected(client)

    client.feed(
        {
            "type": "open",
            "stream": 4,
            "kind": "command",
            "action": "reboot",
            "args": {"when": "now"},
        }
    )
    client.feed({"type": "credit", "stream": 4, "bytes": 4096})

    (closed,) = client.wait_for("close")
    assert closed == {
        "type": "close",
        "stream": 4,
        "code": "",
        "params": {"exit_code": 0, "output": "ran"},
    }
    assert client.sent_bytes == [frame(4, b"running\n")]
    assert commands == [("reboot", {"when": "now"})]
    session.close()
    thread.join(timeout=2)


def test_a_commands_lines_wait_for_the_hubs_credit():
    client = ScriptedClient()
    session, thread, _, _ = connected(client)

    client.feed({"type": "open", "stream": 6, "kind": "command", "action": "x"})
    time.sleep(0.1)
    assert client.sent_bytes == []
    assert client.frames("close") == []

    client.feed({"type": "credit", "stream": 6, "bytes": 3})
    assert client.wait_for_bytes(count=1) == [frame(6, b"run")]
    client.feed({"type": "credit", "stream": 6, "bytes": 1024})

    assert client.wait_for_bytes(count=2) == [frame(6, b"run"), frame(6, b"ning\n")]
    client.wait_for("close")
    session.close()
    thread.join(timeout=2)


def test_a_reading_command_closes_with_its_result():
    client = ScriptedClient()

    def run_command(action, args, on_line=None):
        return {
            "exit_code": 0,
            "code": "",
            "params": {},
            "output": "",
            "result": {"is_installed": True},
        }

    session, thread, _, _ = connected(client, run_command=run_command)

    client.feed(
        {
            "type": "open",
            "stream": 2,
            "kind": "command",
            "action": "remote_desktop_status",
        }
    )

    (closed,) = client.wait_for("close")
    assert closed["params"] == {
        "exit_code": 0,
        "output": "",
        "result": {"is_installed": True},
    }
    session.close()
    thread.join(timeout=2)


def test_a_validate_stream_closes_with_the_verdict():
    client = ScriptedClient()
    checked: list = []

    def validate(module, config):
        checked.append((module, config))
        if config.get("bad"):
            return {"code": "share_name_invalid", "params": {"name": "x"}}
        return {}

    session, thread, _, _ = connected(client, validate=validate)

    client.feed(
        {
            "type": "open",
            "stream": 10,
            "kind": "validate",
            "module": "samba",
            "config": {"shares": []},
        }
    )
    client.feed(
        {
            "type": "open",
            "stream": 12,
            "kind": "validate",
            "module": "samba",
            "config": {"bad": True},
        }
    )

    closes = {c["stream"]: c for c in client.wait_for("close", count=2)}
    assert closes[10] == {
        "type": "close",
        "stream": 10,
        "code": "",
        "params": {"is_valid": True},
    }
    assert closes[12] == {
        "type": "close",
        "stream": 12,
        "code": "share_name_invalid",
        "params": {"name": "x", "is_valid": False},
    }
    assert checked == [("samba", {"shares": []}), ("samba", {"bad": True})]
    session.close()
    thread.join(timeout=2)


def test_without_a_validator_the_validate_kind_is_unknown():
    client = ScriptedClient()
    session, thread, _, _ = connected(client)

    client.feed({"type": "open", "stream": 12, "kind": "validate"})

    (closed,) = client.wait_for("close")
    assert closed == {
        "type": "close",
        "stream": 12,
        "code": "kind_unknown",
        "params": {"kind": "validate"},
    }
    session.close()
    thread.join(timeout=2)


def test_a_stream_kind_this_build_cannot_serve_is_closed_kind_unknown():
    client = ScriptedClient()
    session, thread, _, _ = connected(client)

    client.feed({"type": "open", "stream": 8, "kind": "tunnel"})

    (closed,) = client.wait_for("close")
    assert closed == {
        "type": "close",
        "stream": 8,
        "code": "kind_unknown",
        "params": {"kind": "tunnel"},
    }
    assert client.frames("refused") == []
    assert client.frames("opened") == []
    assert session.is_open
    session.close()
    thread.join(timeout=2)


def test_a_handler_that_raises_closes_the_stream_typed():
    client = ScriptedClient()

    def broken(order, on_line):
        raise RuntimeError("boom")

    session, thread, _, _ = connected(client, run_order=broken)

    client.feed({"type": "open", "stream": 4, "kind": "order"})

    (closed,) = client.wait_for("close")
    assert closed == {
        "type": "close",
        "stream": 4,
        "code": "agent_internal",
        "params": {"error": "RuntimeError"},
    }
    session.close()
    thread.join(timeout=2)


def test_a_stream_the_hub_closed_sends_no_more_lines_and_no_close():
    client = ScriptedClient()
    gate = threading.Event()
    done = threading.Event()

    def slow(order, on_line):
        gate.wait(timeout=3)
        on_line("late")
        done.set()
        return {"state": "done", "code": "", "params": {}, "output": ""}

    session, thread, _, _ = connected(client, run_order=slow)
    client.feed({"type": "open", "stream": 6, "kind": "order"})
    client.feed({"type": "credit", "stream": 6, "bytes": 4096})
    time.sleep(0.05)

    client.feed({"type": "close", "stream": 6, "code": "", "params": {}})
    time.sleep(0.05)
    gate.set()
    assert done.wait(timeout=3)
    time.sleep(0.05)

    assert client.sent_bytes == []
    assert client.frames("close") == []
    assert session.is_open
    session.close()
    thread.join(timeout=2)


# --- the byte-carrying kinds ---


def channel_session(client, **overrides):
    EchoStream.instances = []
    return connected(client, stream_kinds={"shell": EchoStream}, **overrides)


def open_shell(client, stream_id=2, **args):
    client.feed(
        {
            "type": "open",
            "stream": stream_id,
            "kind": "shell",
            "cols": 80,
            "rows": 24,
            **args,
        }
    )


def test_an_even_id_from_the_hub_is_served_and_its_credit_is_the_first_frame_back():
    client = ScriptedClient()
    session, thread, _, _ = channel_session(client)

    open_shell(client)

    assert client.wait_for("credit") == [{"type": "credit", "stream": 2, "bytes": 1024}]
    assert client.frames("opened") == []
    assert client.sent[-1] == {"type": "credit", "stream": 2, "bytes": 1024}
    assert EchoStream.instances[0].args == {"cols": 80, "rows": 24}
    assert EchoStream.instances[0].channel.id == 2
    session.close()
    thread.join(timeout=2)


def test_the_hubs_bytes_resizes_and_close_reach_the_handler():
    client = ScriptedClient()
    session, thread, _, _ = channel_session(client)
    open_shell(client)
    client.wait_for("credit")
    client.feed({"type": "credit", "stream": 2, "bytes": 1024})

    client.feed(frame(2, b"ls\n"))
    client.feed({"type": "resize", "stream": 2, "cols": 120, "rows": 40})
    assert client.wait_for_bytes(count=1) == [frame(2, b"echo:ls\n")]
    client.feed({"type": "close", "stream": 2, "code": "", "params": {}})

    wait_until(lambda: len(EchoStream.instances[0].items) == 3)
    assert EchoStream.instances[0].items == [
        ("data", b"ls\n"),
        ("resize", 120, 40),
        ("close", "", {}),
    ]
    time.sleep(0.05)
    assert client.frames("close") == []
    session.close()
    thread.join(timeout=2)


def test_a_handlers_result_is_the_closes_params():
    client = ScriptedClient()
    session, thread, _, _ = channel_session(client)
    open_shell(client)
    client.wait_for("credit")

    client.feed(frame(2, b"bye"))
    client.feed({"type": "credit", "stream": 2, "bytes": 1024})
    assert client.wait_for_bytes(count=1) == [frame(2, b"echo:bye")]
    client.feed(frame(2, b"quit"))

    (closed,) = client.wait_for("close")
    assert closed == {
        "type": "close",
        "stream": 2,
        "code": "",
        "params": {"exit_code": 0},
    }
    session.close()
    thread.join(timeout=2)


def test_bytes_wait_for_the_hubs_credit():
    client = ScriptedClient()
    session, thread, _, _ = channel_session(client)
    open_shell(client)
    client.wait_for("credit")
    client.feed({"type": "credit", "stream": 2, "bytes": 4})

    client.feed(frame(2, b"abcdef"))
    time.sleep(0.1)
    assert client.sent_bytes == [frame(2, b"echo")]

    client.feed({"type": "credit", "stream": 2, "bytes": 1024})

    assert client.wait_for_bytes(count=2) == [frame(2, b"echo"), frame(2, b":abcdef")]
    session.close()
    thread.join(timeout=2)


def test_a_handler_that_refuses_closes_with_the_code_and_grants_nothing():
    client = ScriptedClient()
    session, thread, _, _ = channel_session(client)

    open_shell(client, refuse=True)

    (closed,) = client.wait_for("close")
    assert closed == {
        "type": "close",
        "stream": 2,
        "code": "container_unknown",
        "params": {"name": "kuma"},
    }
    assert client.frames("credit") == []
    assert client.frames("refused") == []
    assert client.frames("opened") == []
    session.close()
    thread.join(timeout=2)


def test_a_short_binary_frame_is_dropped_with_a_log_line():
    client = ScriptedClient()
    logged: list = []
    session, thread, _, _ = channel_session(client, log=logged.append)

    client.feed(b"\x00\x02")
    client.feed(b"")
    open_shell(client)

    client.wait_for("credit")
    assert [line for line in logged if "binary frame" in line] == [
        "dropping a binary frame of 2 bytes",
        "dropping a binary frame of 0 bytes",
    ]
    assert session.is_open
    session.close()
    thread.join(timeout=2)


def test_a_frame_for_a_stream_nobody_opened_is_dropped():
    client = ScriptedClient()
    session, thread, _, _ = channel_session(client)

    client.feed(frame(99, b"stray"))
    client.feed({"type": "credit", "stream": 99, "bytes": 5})
    client.feed({"type": "resize", "stream": 99, "cols": 1, "rows": 1})
    client.feed({"type": "close", "stream": 99, "code": "", "params": {}})
    client.feed({"type": "open", "stream": "2", "kind": "shell"})
    client.feed({"type": "open", "stream": -1, "kind": "shell"})
    client.feed({"type": "open", "stream": 1 << 32, "kind": "shell"})
    open_shell(client)

    client.wait_for("credit")
    assert client.sent_bytes == []
    assert client.frames("close") == []
    assert len(EchoStream.instances) == 1
    assert session.is_open
    session.close()
    thread.join(timeout=2)


def test_the_socket_ending_closes_every_channel():
    client = ScriptedClient()
    session, thread, _, _ = channel_session(client)
    open_shell(client)
    client.wait_for("credit")

    client.feed(GatewayUnreachable("hung up"))
    thread.join(timeout=3)

    wait_until(lambda: EchoStream.instances[0].items)
    assert EchoStream.instances[0].items == [("close", "", {})]


# --- the streams this side opens ---


def test_open_stream_allots_odd_ids_counting_up_and_sends_the_open():
    client = ScriptedClient()
    session, thread, _, _ = connected(client)

    first = session.open_stream("log", module="samba")
    second = session.open_stream("package")

    assert (first.id, second.id) == (1, 3)
    assert client.frames("open") == [
        {"type": "open", "stream": 1, "kind": "log", "module": "samba"},
        {"type": "open", "stream": 3, "kind": "package"},
    ]
    assert client.frames("opened") == []
    session.close()
    thread.join(timeout=2)


def test_an_own_streams_lines_go_up_on_its_id_and_its_close_is_its_result():
    client = ScriptedClient()
    session, thread, _, _ = connected(client)
    log = session.open_stream("log", module="samba")
    sent = threading.Event()

    def push():
        log.send_line("installing")
        sent.set()

    threading.Thread(target=push, daemon=True).start()
    time.sleep(0.05)
    assert client.sent_bytes == []
    client.feed({"type": "credit", "stream": 1, "bytes": 4096})
    assert sent.wait(timeout=3)

    log.close(params={"state": "done"})

    assert client.sent_bytes == [frame(1, b"installing\n")]
    assert client.frames("close") == [
        {"type": "close", "stream": 1, "code": "", "params": {"state": "done"}}
    ]
    assert log.is_closed
    session.close()
    thread.join(timeout=2)


def test_an_own_stream_closed_by_the_hub_hands_over_the_closes_params():
    client = ScriptedClient()
    session, thread, _, _ = connected(client)
    package = session.open_stream("package")

    client.feed(frame(1, b"deb bytes"))
    client.feed({"type": "close", "stream": 1, "code": "", "params": {"sha256": "abc"}})

    assert package.recv(timeout=3) == ("data", b"deb bytes")
    assert package.recv(timeout=3) == ("close", "", {"sha256": "abc"})
    assert package.is_closed
    package.close()
    assert client.frames("close") == []
    session.close()
    thread.join(timeout=2)


def test_an_own_stream_refused_by_the_hub_carries_the_code():
    client = ScriptedClient()
    session, thread, _, _ = connected(client)
    package = session.open_stream("package", module="nothing")

    client.feed(
        {
            "type": "close",
            "stream": 1,
            "code": "kind_unknown",
            "params": {"kind": "package"},
        }
    )

    assert package.recv(timeout=3) == ("close", "kind_unknown", {"kind": "package"})
    session.close()
    thread.join(timeout=2)


# --- the socket ending ---


@pytest.mark.parametrize(
    "closed, expected, code",
    [
        (
            SocketClosed(4000, "binding_unknown"),
            GatewayRefusedDetail,
            "channel_refused",
        ),
        (SocketClosed(4010, "replaced"), GatewayRefusedDetail, "replaced"),
        (SocketClosed(1001, "going away"), GatewayUnreachable, ""),
        (GatewayUnreachable("hung up"), GatewayUnreachable, ""),
    ],
)
def test_serve_returns_what_ended_the_socket(closed, expected, code):
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome())
    session.connect()
    thread, outcome = serving(session)
    client.wait_for("report")

    client.feed(closed)
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert isinstance(outcome["failure"], expected)
    assert getattr(outcome["failure"], "code", "") == code
    assert not session.is_open


def test_closing_from_here_ends_serve_with_no_failure():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome())
    session.connect()
    thread, outcome = serving(session)
    client.wait_for("report")

    session.close()
    thread.join(timeout=3)

    assert outcome["failure"] is None
    assert client.is_closed


def test_the_session_asks_the_hub_for_nothing():
    """The hub pushes the state; there is no word for asking for it."""
    assert not hasattr(AgentSession, "request_state")
