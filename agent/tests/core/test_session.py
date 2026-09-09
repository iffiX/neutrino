"""One connection to the hub, driven with a scripted socket client.

What these pin: the hello and the welcome, a report on the interval and at
once when something changed, an order stream running the engine and closing
with its state, a command stream closing with its exit, a stream kind this
build has no handler for refused typed, and how the socket's end is
reported to the loop that owns it.
"""

import json
import queue
import threading
import time

import pytest

from neutrino_agent.core.channel import (
    GatewayRefused,
    GatewayUnreachable,
    GatewayVersionRefused,
    GatewayWireStale,
)
from neutrino_agent.core.session import AgentSession
from neutrino_agent.core.ws_client import SocketClosed


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
        self.is_connected = False
        self.is_closed = False
        self.connect_error = None
        self.drop_after_report = False

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

    def recv(self):
        item = self.inbound.get()
        if isinstance(item, Exception):
            raise item
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
        token="tok",
        hello={"hostname": "box", "state_hash": ""},
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
    return {"type": "welcome", "hub_version": "0.2.0", "device_id": "d", **fields}


def serving(session):
    """Run serve() on a thread; returns the thread and the outcome holder."""
    outcome: dict = {}

    def run():
        outcome["failure"] = session.serve()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


# --- hello and welcome ---


def test_connect_says_hello_with_the_token_and_takes_the_welcome():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome(state_hash=""))

    session.connect()

    (hello,) = client.frames("hello")
    assert hello["token"] == "tok"
    assert hello["hostname"] == "box"
    assert hello["client_version"]
    assert hello["wire"]
    assert hello["state_hash"] == ""
    assert session.hub_version == "0.2.0"
    assert session.is_open
    session.close()


def test_a_welcome_naming_another_state_hash_asks_for_the_state():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome(state_hash="h1"))

    session.connect()

    assert client.wait_for("state_request") == [{"type": "state_request"}]
    assert session.state_hash == "h1"
    session.close()


def test_a_first_frame_that_is_no_welcome_is_unreachable():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed({"type": "state", "hash": "", "desired": {}})

    with pytest.raises(GatewayUnreachable):
        session.connect()

    assert client.is_closed


def test_a_close_before_the_welcome_maps_to_its_refusal():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(SocketClosed(4401, "unknown_token"))

    with pytest.raises(GatewayRefused):
        session.connect()


def test_a_connect_error_passes_straight_through():
    client = ScriptedClient()
    client.connect_error = GatewayUnreachable("no route")
    session, _, _, _ = make_session(client)

    with pytest.raises(GatewayUnreachable):
        session.connect()


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


# --- streams ---


def test_an_order_stream_runs_the_engine_and_closes_with_its_state():
    client = ScriptedClient()
    session, orders, _, _ = make_session(client)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.feed(
        {
            "type": "open",
            "stream": "00000001",
            "kind": "order",
            "args": {"id": "o1", "module": "fakedesk", "action": "install"},
            "credit": 1024,
        }
    )

    assert client.wait_for("opened") == [{"type": "opened", "stream": "00000001"}]
    events = client.wait_for("event", count=2)
    assert [event["line"] for event in events] == ["step one", "step two"]
    assert all(event["stream"] == "00000001" for event in events)
    (closed,) = client.wait_for("close")
    assert closed == {
        "type": "close",
        "stream": "00000001",
        "state": "done",
        "code": "",
        "params": {},
        "output": "step one",
    }
    assert orders == [{"id": "o1", "module": "fakedesk", "action": "install"}]
    session.close()
    thread.join(timeout=2)


def test_a_command_stream_closes_with_its_exit():
    client = ScriptedClient()
    session, _, commands, _ = make_session(client)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.feed(
        {
            "type": "open",
            "stream": "00000002",
            "kind": "command",
            "args": {"action": "reboot", "args": {"when": "now"}},
            "credit": 0,
        }
    )

    (closed,) = client.wait_for("close")
    assert closed == {
        "type": "close",
        "stream": "00000002",
        "exit_code": 0,
        "code": "",
        "params": {},
        "output": "ran",
    }
    assert commands == [("reboot", {"when": "now"})]
    session.close()
    thread.join(timeout=2)


def test_a_command_streams_its_lines_before_the_close():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.feed(
        {
            "type": "open",
            "stream": "00000009",
            "kind": "command",
            "args": {"action": "podman_journal", "args": {"name": "web"}},
            "credit": 0,
        }
    )

    (event,) = client.wait_for("event")
    assert event == {"type": "event", "stream": "00000009", "line": "running"}
    client.wait_for("close")
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

    session, _, _, _ = make_session(client, validate=validate)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.feed(
        {
            "type": "open",
            "stream": "00000010",
            "kind": "validate",
            "args": {"module": "samba", "config": {"shares": []}},
            "credit": 0,
        }
    )
    client.feed(
        {
            "type": "open",
            "stream": "00000011",
            "kind": "validate",
            "args": {"module": "samba", "config": {"bad": True}},
            "credit": 0,
        }
    )

    closes = {c["stream"]: c for c in client.wait_for("close", count=2)}
    assert closes["00000010"] == {
        "type": "close",
        "stream": "00000010",
        "is_valid": True,
        "code": "",
        "params": {},
    }
    assert closes["00000011"] == {
        "type": "close",
        "stream": "00000011",
        "is_valid": False,
        "code": "share_name_invalid",
        "params": {"name": "x"},
    }
    assert checked == [("samba", {"shares": []}), ("samba", {"bad": True})]
    session.close()
    thread.join(timeout=2)


def test_without_a_validator_the_validate_kind_is_refused():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.feed({"type": "open", "stream": "00000012", "kind": "validate", "args": {}})

    (refused,) = client.wait_for("refused")
    assert refused["code"] == "unknown_stream_kind"
    session.close()
    thread.join(timeout=2)


def test_a_state_frame_hands_the_desired_state_on():
    client = ScriptedClient()
    taken: list = []
    session, _, _, _ = make_session(
        client, on_state=lambda state_hash, desired: taken.append((state_hash, desired))
    )
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.feed({"type": "state", "hash": "h3", "desired": {"modules": {}}})
    client.feed({"type": "state", "hash": "h4", "desired": "not an object"})
    client.feed({"type": "open", "stream": "00000013", "kind": "command", "args": {}})

    client.wait_for("close")
    assert taken == [("h3", {"modules": {}})]
    assert session.state_hash == "h4"
    session.close()
    thread.join(timeout=2)


def test_a_stream_kind_this_build_cannot_serve_is_refused_typed():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.feed({"type": "open", "stream": "00000003", "kind": "shell", "args": {}})

    (refused,) = client.wait_for("refused")
    assert refused == {
        "type": "refused",
        "stream": "00000003",
        "code": "unknown_stream_kind",
        "params": {"kind": "shell"},
    }
    session.close()
    thread.join(timeout=2)


def test_a_handler_that_raises_closes_the_stream_typed():
    client = ScriptedClient()

    def broken(order, on_line):
        raise RuntimeError("boom")

    session, _, _, _ = make_session(client, run_order=broken)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.feed({"type": "open", "stream": "00000004", "kind": "order", "args": {}})

    (closed,) = client.wait_for("close")
    assert closed["code"] == "agent_internal"
    assert closed["params"] == {"error": "RuntimeError"}
    assert closed["state"] == "failed"
    session.close()
    thread.join(timeout=2)


def test_a_stream_the_hub_closed_sends_no_more_events():
    client = ScriptedClient()
    gate = threading.Event()

    def slow(order, on_line):
        gate.wait(timeout=3)
        on_line("late")
        return {"state": "done", "code": "", "params": {}, "output": ""}

    session, _, _, _ = make_session(client, run_order=slow)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)
    client.feed({"type": "open", "stream": "00000005", "kind": "order", "args": {}})
    client.wait_for("opened")

    client.feed({"type": "close", "stream": "00000005"})
    time.sleep(0.05)
    gate.set()

    client.wait_for("close")
    assert client.frames("event") == []
    session.close()
    thread.join(timeout=2)


def test_state_frames_are_taken_and_nothing_else_is_fatal():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome())
    session.connect()
    thread, _ = serving(session)

    client.feed({"type": "state", "hash": "h2", "desired": {}})
    client.feed({"type": "resize", "stream": "x", "cols": 1, "rows": 1})
    client.feed({"type": "credit", "stream": "x", "bytes": 1})
    client.feed({"type": "whatever"})
    client.feed({"type": "open", "stream": "00000006", "kind": "command", "args": {}})

    client.wait_for("close")
    assert session.state_hash == "h2"
    assert session.is_open
    session.close()
    thread.join(timeout=2)


# --- the socket ending ---


@pytest.mark.parametrize(
    "closed, expected",
    [
        (SocketClosed(4401, "unknown_token"), GatewayRefused),
        (SocketClosed(4409, "agent_wire_stale"), GatewayWireStale),
        (SocketClosed(4409, "agent_newer_than_hub"), GatewayVersionRefused),
        (SocketClosed(4410, "replaced"), GatewayUnreachable),
        (GatewayUnreachable("hung up"), GatewayUnreachable),
    ],
)
def test_serve_returns_what_ended_the_socket(closed, expected):
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


def test_request_state_with_the_socket_gone_is_unreachable():
    client = ScriptedClient()
    session, _, _, _ = make_session(client)
    client.feed(welcome())
    session.connect()
    session.close()

    with pytest.raises(GatewayUnreachable):
        session.request_state()
