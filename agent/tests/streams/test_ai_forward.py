"""The AI gateway forward: the machine's AI tools reach the hub's gateway.

What these pin: the forward is wanted while the state's ``ai_tools`` section
says ``is_forwarded``, with the AI tools setting on or off, since a
container module that uses the gateway asks for it too, and on the hub's
own machine, where the hub sends ``is_forwarded`` false, it is not; it
listens on ``127.0.0.1`` alone, at 8317 unless told otherwise,
while wanted, and on nothing once the section is off; each connection it
accepts opens one ``connect {id: ai}`` to the hub and its bytes cross both
ways, up no faster than the hub's credit and down no faster than the credit
offered; while the agent has no channel nothing is accepted and the waiting
connections are served once it is back; either end's end of file ends the
other, a refusal is one line in the log however often it comes, and closing
the forward closes every connection; a port that cannot be had is one line
in the log and is tried again.
"""

import inspect
import socket
import time

import pytest

from neutrino_agent.constants import (
    AGENT_AI_FORWARD_HOST,
    AGENT_AI_FORWARD_PORT,
    AGENT_WS_STREAM_CREDIT_BYTES,
)
from neutrino_agent.exceptions import GatewayUnreachable
from neutrino_agent.streams.ai_forward import AiGatewayForward, is_forward_wanted
from neutrino_agent.streams.channel import StreamChannel
from tests.streams.fake_channel import FakeChannel

ON = {"ai_tools": {"is_enabled": True, "is_forwarded": True}}
OFF = {"ai_tools": {"is_enabled": False}}
# The hub's own machine: the tools reach the gateway itself.
OWN = {"ai_tools": {"is_enabled": True, "is_forwarded": False}}


class FakeHub:
    """The hub's end: the streams the forward opens, and whether it is online."""

    def __init__(self, *, is_online: bool = True):
        self.is_online = is_online
        self.opened: list = []
        self.channels: list = []
        self.is_refusing = False

    def open_stream(self, kind, **args):
        if not self.is_online or self.is_refusing:
            raise GatewayUnreachable("no socket to the hub")
        self.opened.append((kind, dict(args)))
        channel = FakeChannel(stream_id=len(self.channels) * 2 + 1)
        self.channels.append(channel)
        return channel

    def online(self) -> bool:
        return self.is_online


def until(predicate, timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("never happened")


@pytest.fixture
def hub():
    return FakeHub()


@pytest.fixture
def lines():
    return []


@pytest.fixture
def forward(hub, lines):
    made = AiGatewayForward(
        open_stream=hub.open_stream,
        is_online=hub.online,
        log=lines.append,
        port=0,
        poll_s=0.02,
    )
    yield made
    made.stop()


def dial(forward) -> socket.socket:
    connection = socket.create_connection(("127.0.0.1", forward.local_port), 2)
    connection.settimeout(3)
    return connection


@pytest.mark.parametrize(
    "document, is_wanted",
    [
        (ON, True),
        (OFF, False),
        (OWN, False),
        ({}, False),
        ({"ai_tools": {"is_enabled": True}}, False),
        ({"ai_tools": {"is_enabled": False, "is_forwarded": True}}, True),
        ({"ai_tools": {"is_enabled": True, "is_forwarded": "yes"}}, False),
    ],
)
def test_the_forward_is_wanted_while_the_section_says_forwarded(document, is_wanted):
    assert is_forward_wanted(document) is is_wanted


def test_it_listens_on_8317_on_loopback_alone_unless_told_otherwise():
    port = inspect.signature(AiGatewayForward).parameters["port"].default

    assert (AGENT_AI_FORWARD_HOST, port) == ("127.0.0.1", 8317)
    assert AGENT_AI_FORWARD_PORT == 8317


def test_it_listens_while_the_section_is_on_and_on_nothing_once_it_is_off(forward):
    forward.take(ON)
    port = forward.local_port
    address = forward._listener.getsockname()

    forward.take(ON)
    again = forward.local_port
    forward.take(OFF)

    assert address == ("127.0.0.1", port)
    assert port != 0 and again == port
    assert forward.local_port == 0
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), 1)


@pytest.mark.parametrize("document", [OWN, None, {}])
def test_it_listens_on_nothing_on_the_hubs_own_machine_or_with_no_state(
    forward, document
):
    forward.take(document)

    assert forward.local_port == 0


def test_each_connection_opens_one_connect_to_the_ai_entry_and_bytes_cross(
    forward, hub
):
    forward.take(ON)
    first = dial(forward)
    second = dial(forward)
    try:
        first.sendall(b"GET /v1/models")
        until(lambda: len(hub.channels) == 2)
        until(lambda: any(c.output() == b"GET /v1/models" for c in hub.channels))
        channel = next(c for c in hub.channels if c.output())
        channel.feed(("data", b"200 OK"))
        answer = first.recv(1024)
    finally:
        first.close()
        second.close()

    assert hub.opened == [("connect", {"id": "ai"}), ("connect", {"id": "ai"})]
    assert answer == b"200 OK"
    until(lambda: channel.credits == [AGENT_WS_STREAM_CREDIT_BYTES, 6])


class RecordingSession:
    """The session under a real stream channel: every frame it would send."""

    def __init__(self):
        self.frames: list = []

    def _send_bytes(self, stream_id, data):
        self.frames.append(bytes(data))

    def _send(self, message):
        self.frames.append(dict(message))

    def _close_stream(self, stream_id, code, params):
        self.frames.append({"type": "close", "code": code, "params": params})


def test_the_tools_bytes_go_up_only_as_the_hubs_credit_allows(lines):
    session = RecordingSession()
    channel = StreamChannel(session, 1, credit=0)
    forward = AiGatewayForward(
        open_stream=lambda kind, **args: channel,
        is_online=lambda: True,
        log=lines.append,
        port=0,
        poll_s=0.02,
    )
    forward.take(ON)
    connection = dial(forward)
    try:
        connection.sendall(b"ping")
        time.sleep(0.2)
        before = [frame for frame in session.frames if isinstance(frame, bytes)]
        channel._grant(2)
        until(lambda: any(isinstance(frame, bytes) for frame in session.frames))
        time.sleep(0.1)
        partway = [frame for frame in session.frames if isinstance(frame, bytes)]
        channel._grant(10)
        until(
            lambda: b"".join(f for f in session.frames if isinstance(f, bytes))
            == b"ping"
        )
    finally:
        connection.close()
        forward.stop()

    assert before == []
    assert partway == [b"pi"]


def test_nothing_is_accepted_without_a_channel_and_the_waiting_are_served_after(
    forward, hub
):
    hub.is_online = False
    forward.take(ON)
    connection = dial(forward)
    try:
        connection.sendall(b"queued")
        time.sleep(0.2)
        opened_offline = list(hub.opened)

        hub.is_online = True
        until(lambda: hub.channels and hub.channels[0].output() == b"queued")
        hub.channels[0].feed(("data", b"served"))
        answer = connection.recv(1024)
    finally:
        connection.close()

    assert opened_offline == []
    assert forward.local_port != 0
    assert answer == b"served"


def test_the_tools_end_of_file_closes_the_stream_empty(forward, hub):
    forward.take(ON)
    connection = dial(forward)
    connection.sendall(b"last")
    until(lambda: hub.channels and hub.channels[0].output() == b"last")
    connection.close()

    until(lambda: hub.channels[0].closed is not None)
    assert hub.channels[0].closed == {"code": "", "params": {}}


def test_the_hubs_refusal_closes_the_connection_and_is_one_line(forward, hub, lines):
    forward.take(ON)
    answers = []
    for _ in range(2):
        connection = dial(forward)
        try:
            until(lambda: len(hub.channels) == len(answers) + 1)
            hub.channels[-1].close_from_hub("permission_denied", {"kind": "ai"})
            answers.append(connection.recv(1024))
        finally:
            connection.close()

    assert answers == [b"", b""]
    refusals = [line for line in lines if "permission_denied" in line]
    assert len(refusals) == 1


def test_closing_the_forward_closes_every_connection(forward, hub):
    forward.take(ON)
    connection = dial(forward)
    try:
        until(lambda: len(hub.channels) == 1)
        forward.take(OFF)
        answer = connection.recv(1024)
    finally:
        connection.close()

    assert answer == b""
    until(lambda: hub.channels[0].is_closed)


def test_a_port_that_cannot_be_had_is_one_line_and_is_tried_again(hub, lines):
    taken = socket.create_server(("127.0.0.1", 0))
    port = taken.getsockname()[1]
    forward = AiGatewayForward(
        open_stream=hub.open_stream,
        is_online=hub.online,
        log=lines.append,
        port=port,
        poll_s=0.02,
    )
    try:
        forward.take(ON)
        forward.ensure()
        refused = forward.local_port
        taken.close()
        forward.ensure()
        listening = forward.local_port
    finally:
        forward.stop()
        taken.close()

    assert refused == 0
    assert len([line for line in lines if "cannot listen" in line]) == 1
    assert listening == port


def test_a_stream_that_cannot_be_opened_closes_the_connection(forward, hub, lines):
    hub.is_refusing = True
    forward.take(ON)
    connection = dial(forward)
    try:
        answer = connection.recv(1024)
    finally:
        connection.close()

    assert answer == b""
    assert any("opened no stream" in line for line in lines)
