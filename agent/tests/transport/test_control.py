"""The control connection to the transport, and the streams beside it.

What these pin: every connection opening with the secret line, a command
answered by the line of its own id and failing when the connection ends,
events and frames handed on in order away from the reading thread, a
question answered under its id, ``attach`` and ``open`` connections with
their first lines, and an ``open`` the hub refused holding its close.
"""

import json
import threading

import pytest

from neutrino_agent.exceptions import GatewayUnreachable
from neutrino_agent.transport.connection import open_local
from neutrino_agent.transport.control import LineReader, TransportControlClient
from neutrino_agent.transport.records import encode_close, encode_record
from tests.transport.fake_transport import FakeTransport


@pytest.fixture
def fake():
    transport = FakeTransport().start()
    yield transport
    transport.close()


class Recorder:
    def __init__(self):
        self.lines: list = []
        self.threads: list = []
        self.closed = threading.Event()
        self.questions: list = []

    def on_event(self, event):
        self.threads.append(threading.current_thread().name)
        self.lines.append(("event", event))

    def on_frame(self, frame):
        self.lines.append(("frame", frame))

    def on_question(self, question):
        self.questions.append(question)
        return {"address": "127.0.0.1"}

    def on_closed(self):
        self.closed.set()


def client_for(fake, recorder, secret=None, **kwargs) -> TransportControlClient:
    client = TransportControlClient(
        connect=lambda: open_local(fake.listen),
        secret=secret or fake.secret,
        on_event=recorder.on_event,
        on_frame=recorder.on_frame,
        on_question=recorder.on_question,
        on_closed=recorder.on_closed,
        log=lambda line: None,
        **kwargs,
    )
    client.start()
    return client


def test_a_command_is_answered_by_the_line_of_its_own_id(fake):
    fake.answers["dial"] = {"code": "", "params": {}}
    fake.answers["forward_start"] = lambda line: {"listen": line["listen"]}
    client = client_for(fake, Recorder())

    dialled = client.command("dial", hub_key="ab", addresses=["tcp://h:1"])
    forward = client.command("forward_start", listen="127.0.0.1:0")

    assert dialled == {"code": "", "params": {}}
    assert forward == {"listen": "127.0.0.1:0"}
    first, second = fake.commands
    assert first["command"] == "dial" and first["addresses"] == ["tcp://h:1"]
    assert first["id"] != second["id"]


def test_a_wrong_secret_gets_no_answer_and_the_command_fails(fake):
    recorder = Recorder()
    client = client_for(fake, recorder, secret="00" * 32)

    with pytest.raises(GatewayUnreachable):
        client.command("dial", timeout_s=2)
    assert recorder.closed.wait(5)
    assert fake.refused_connections == 1


def test_a_command_with_no_answer_in_time_fails():
    near, far = __import__("socket").socketpair()
    from neutrino_agent.transport.connection import LocalSocketConnection

    client = TransportControlClient(
        connect=lambda: LocalSocketConnection("", sock=near),
        secret="5e" * 32,
        on_event=lambda e: None,
        on_frame=lambda f: None,
        on_question=lambda q: {},
        log=lambda line: None,
    )
    client.start()
    try:
        with pytest.raises(GatewayUnreachable):
            client.command("dial", timeout_s=0.2)
    finally:
        far.close()


def test_the_end_of_the_connection_fails_waiting_commands_and_says_so(fake):
    recorder = Recorder()
    fake.answers["slow"] = lambda line: fake.drop_control() or {}
    client = client_for(fake, recorder)

    with pytest.raises(GatewayUnreachable):
        client.command("slow", timeout_s=5)
    assert recorder.closed.wait(5)
    assert not client.is_open
    with pytest.raises(GatewayUnreachable):
        client.command("dial")


def test_events_and_frames_reach_the_callbacks_in_order_off_the_reader(fake):
    recorder = Recorder()
    client_for(fake, recorder)

    fake.send_event("session_open", address="tcp://h:1", local_address="a:2")
    fake.send_frame({"type": "welcome"})
    fake.send_event("session_end", code="")
    fake.wait_for(lambda: len(recorder.lines) == 3)

    assert [kind for kind, _ in recorder.lines] == ["event", "frame", "event"]
    assert recorder.lines[1][1] == {"type": "welcome"}
    assert recorder.threads == ["agent_transport_dispatch"] * 2


def test_a_question_is_answered_under_its_id(fake):
    recorder = Recorder()
    client_for(fake, recorder)

    answer = fake.ask("port", port=445, protocol="tcp")

    assert answer["address"] == "127.0.0.1"
    assert recorder.questions[0]["port"] == 445


def test_a_question_whose_answer_fails_is_control_unavailable(fake):
    recorder = Recorder()

    def broken(question):
        raise LookupError("broken")

    recorder.on_question = broken
    client_for(fake, recorder)

    answer = fake.ask("port", port=1)

    assert answer["code"] == "control_unavailable"


def test_a_frame_goes_down_as_a_frame_line(fake):
    client = client_for(fake, Recorder())

    client.send_frame({"type": "hello", "id": "dev-1"})
    client.send_frame({"type": "left"}, is_last=True)

    assert fake.wait_for(lambda: fake.frames[1:]) and fake.frames == [
        {"type": "hello", "id": "dev-1"},
        {"type": "left"},
    ]


def test_attach_opens_a_connection_of_its_own_naming_the_stream(fake):
    client = client_for(fake, Recorder())

    channel = client.attach("s7")
    channel.accept()
    channel.send_bytes(b"out")

    far = fake.wait_attached("s7")
    assert far.first == {"secret": fake.secret, "op": "attach", "stream": "s7"}
    assert far.read_record() == (2, b"")
    assert far.read_record() == (3, b"out")


def test_open_waits_for_the_accept_and_then_reads_the_hubs_records(fake):
    client = client_for(fake, Recorder())

    def accept_then_send(connection):
        connection.write(encode_record(2) + encode_record(3, b"bytes"))
        connection.write(encode_close("", {"sha256": "x"}))

    fake.on_open = accept_then_send
    channel = client.open_stream({"kind": "package", "module": "m"})

    assert fake.wait_opened().first["open"] == {"kind": "package", "module": "m"}
    assert channel.recv(timeout=5) == ("data", b"bytes")
    assert channel.recv(timeout=5) == ("close", "", {"sha256": "x"})


def test_an_open_the_hub_refused_holds_its_close(fake):
    client = client_for(fake, Recorder())
    fake.on_open = lambda connection: connection.write(
        encode_close("download_failed", {"file": "f"})
    )

    channel = client.open_stream({"kind": "package"})

    assert channel.is_closed
    assert channel.recv(timeout=1) == ("close", "download_failed", {"file": "f"})


def test_an_open_the_transport_drops_reads_hub_unreachable(fake):
    client = client_for(fake, Recorder())
    fake.on_open = lambda connection: connection.close()

    channel = client.open_stream({"kind": "log", "module": "m"})

    assert channel.recv(timeout=1) == ("close", "hub_unreachable", {})


class Lines:
    def __init__(self, data: bytes):
        self.data = data

    def recv(self, size):
        chunk, self.data = self.data[:2], self.data[2:]
        return chunk


def test_the_line_reader_skips_a_line_that_is_no_object():
    reader = LineReader(Lines(b'[1]\nnot json\n{"a": 1}\n'))

    assert reader.read() == {"a": 1}
    assert reader.read() is None


def test_a_line_is_json_and_a_newline():
    from neutrino_agent.transport.control import encode_line

    assert json.loads(encode_line({"a": 1})) == {"a": 1}
    assert encode_line({}).endswith(b"\n")
