"""The streams this side opens: odd ids counting up, and the close each waits for.

The registry is driven with a recording sender: what is pinned is the open
frame's shape, a close whose params come back to the waiter, a close whose
code is the hub's refusal, a wait that runs out, and the socket ending under
an open stream. A byte stream is pinned both ways: the window granted at the
open and again as the reader consumes, a send cut into chunks and held to
the hub's credit, and a close from this side.
"""

import json
import threading
import time

import pytest

import neutrino_client.core.streams as streams_module
from neutrino_client.constants import CLIENT_STREAM_CREDIT_BYTES
from neutrino_client.core.protocol import decode_binary
from neutrino_client.core.streams import ClientStream, ClientStreamRegistry
from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable
from tests.conftest import discard


class Sender:
    """Keeps every text frame sent, or refuses when the socket is gone."""

    def __init__(self, error=None):
        self.frames = []
        self.error = error

    def __call__(self, text: str) -> None:
        if self.error is not None:
            raise self.error
        self.frames.append(json.loads(text))


@pytest.fixture
def registry():
    sender = Sender()
    return ClientStreamRegistry(send_text=sender, log=discard), sender


def test_ids_are_odd_and_count_upward(registry):
    subject, sender = registry

    first = subject.open("service", {"id": "rdp_s9"})
    second = subject.open("service", {"id": "ai"})
    third = subject.open("service", {})

    assert (first.stream_id, second.stream_id, third.stream_id) == (1, 3, 5)
    assert sender.frames[0] == {
        "type": "open",
        "stream": 1,
        "kind": "service",
        "id": "rdp_s9",
    }
    assert sender.frames[2] == {"type": "open", "stream": 5, "kind": "service"}


def test_a_close_with_params_resolves_the_wait(registry):
    subject, _sender = registry
    stream = subject.open("service", {"id": "rdp_s9"})

    subject.take_close({"type": "close", "stream": 1, "params": {"host": "h"}})

    assert stream.wait_close(timeout_s=1) == {"host": "h"}


def test_a_close_with_a_code_is_the_hubs_refusal(registry):
    subject, _sender = registry
    stream = subject.open("service", {"id": "rdp_s9"})

    subject.take_close(
        {"type": "close", "stream": 1, "code": "rdp_not_shared", "params": {"id": "x"}}
    )

    with pytest.raises(GatewayRefusedDetail) as refused:
        stream.wait_close(timeout_s=1)
    assert refused.value.code == "rdp_not_shared"
    assert refused.value.params == {"id": "x"}


def test_a_close_that_names_no_params_resolves_to_nothing(registry):
    subject, _sender = registry
    stream = subject.open("service", {})

    subject.take_close({"type": "close", "stream": 1})

    assert stream.wait_close(timeout_s=1) == {}


def test_a_wait_that_runs_out_is_unreachable(registry):
    subject, _sender = registry
    stream = subject.open("service", {"id": "ai"})

    with pytest.raises(GatewayUnreachable):
        stream.wait_close(timeout_s=0.05)


def test_the_close_reaches_a_waiter_on_another_thread(registry):
    subject, _sender = registry
    stream = subject.open("service", {"id": "ai"})
    outcome = {}

    def wait() -> None:
        outcome["params"] = stream.wait_close(timeout_s=5)

    waiter = threading.Thread(target=wait)
    waiter.start()
    subject.take_close({"type": "close", "stream": 1, "params": {"api_key": "k"}})
    waiter.join(timeout=5)

    assert outcome == {"params": {"api_key": "k"}}


def test_the_socket_ending_wakes_every_waiter_unreachable(registry):
    subject, _sender = registry
    first = subject.open("service", {})
    second = subject.open("service", {})

    subject.end_all()

    for stream in (first, second):
        with pytest.raises(GatewayUnreachable):
            stream.wait_close(timeout_s=1)
    with pytest.raises(GatewayUnreachable):
        subject.open("service", {})


def test_a_close_for_a_stream_nobody_opened_is_dropped(registry):
    subject, _sender = registry
    lines = []
    subject._log = lines.append

    subject.take_close({"type": "close", "stream": 7, "params": {}})

    assert lines and "7" in lines[0]


def test_a_close_that_names_no_integer_stream_is_typed(registry):
    subject, _sender = registry

    with pytest.raises(TypeError):
        subject.take_close({"type": "close", "stream": "one"})


def test_an_open_the_socket_cannot_carry_holds_no_stream():
    sender = Sender(error=GatewayUnreachable("gone"))
    subject = ClientStreamRegistry(send_text=sender, log=discard)

    with pytest.raises(GatewayUnreachable):
        subject.open("service", {})

    assert subject._streams == {}


def test_a_stream_reads_its_own_close_once():
    stream = ClientStream(stream_id=1, kind="service")

    stream.take_close(code="", params={"port": 21118})

    assert stream.wait_close(timeout_s=0) == {"port": 21118}
    assert stream.wait_close(timeout_s=0) == {"port": 21118}


# --- byte streams ---


class ByteSender:
    """Keeps every binary frame sent, decoded."""

    def __init__(self):
        self.frames = []

    def __call__(self, data: bytes) -> None:
        self.frames.append(decode_binary(data))


@pytest.fixture
def byte_registry():
    sender = Sender()
    byte_sender = ByteSender()
    subject = ClientStreamRegistry(
        send_text=sender, send_bytes=byte_sender, log=discard
    )
    return subject, sender, byte_sender


def test_a_byte_stream_grants_the_window_as_it_opens(byte_registry):
    subject, sender, _bytes = byte_registry

    subject.open("shell", {"device_id": "d"}, has_bytes=True)

    assert sender.frames[1] == {
        "type": "credit",
        "stream": 1,
        "bytes": CLIENT_STREAM_CREDIT_BYTES,
    }


def test_a_stream_without_bytes_grants_nothing(byte_registry):
    subject, sender, _bytes = byte_registry

    stream = subject.open("service", {"id": "ai"})

    assert [frame["type"] for frame in sender.frames] == ["open"]
    with pytest.raises(GatewayUnreachable):
        stream.send(b"x")


def test_odd_stream_bytes_reach_the_reader_in_order(byte_registry):
    subject, _sender, _bytes = byte_registry
    stream = subject.open("shell", {}, has_bytes=True)

    subject.take_bytes(1, b"one")
    subject.take_bytes(1, b"two")

    assert stream.read(timeout_s=1) == b"one"
    assert stream.read(timeout_s=1) == b"two"
    assert stream.read(timeout_s=0.01) is None


def test_consuming_half_the_window_grants_it_again(byte_registry):
    subject, sender, _bytes = byte_registry
    stream = subject.open("shell", {}, has_bytes=True)
    half = CLIENT_STREAM_CREDIT_BYTES // 2

    subject.take_bytes(1, b"a" * (half - 1))
    stream.read(timeout_s=1)
    assert len(sender.frames) == 2
    subject.take_bytes(1, b"b")
    stream.read(timeout_s=1)

    assert sender.frames[-1] == {"type": "credit", "stream": 1, "bytes": half}


def test_a_send_waits_for_credit_and_spends_it(byte_registry):
    subject, _sender, byte_sender = byte_registry
    stream = subject.open("shell", {}, has_bytes=True)
    sending = threading.Thread(target=stream.send, args=(b"hello",))

    sending.start()
    sending.join(timeout=0.05)
    assert byte_sender.frames == []
    subject.take_credit({"type": "credit", "stream": 1, "bytes": 3})
    while not byte_sender.frames:
        time.sleep(0.01)
    subject.take_credit({"type": "credit", "stream": 1, "bytes": 10})
    sending.join(timeout=5)

    assert byte_sender.frames == [(1, b"hel"), (1, b"lo")]


def test_a_send_is_cut_into_chunks(byte_registry, monkeypatch):
    monkeypatch.setattr(streams_module, "CLIENT_WS_CHUNK_BYTES", 4)
    subject, _sender, byte_sender = byte_registry
    stream = subject.open("shell", {}, has_bytes=True)
    subject.take_credit({"type": "credit", "stream": 1, "bytes": 100})

    stream.send(b"abcdefghij")

    assert byte_sender.frames == [(1, b"abcd"), (1, b"efgh"), (1, b"ij")]


def test_a_send_with_no_credit_in_time_times_out(byte_registry, monkeypatch):
    monkeypatch.setattr(streams_module, "CLIENT_WS_CREDIT_TIMEOUT_S", 0.05)
    subject, _sender, _bytes = byte_registry
    stream = subject.open("shell", {}, has_bytes=True)

    with pytest.raises(TimeoutError):
        stream.send(b"x")


def test_the_socket_ending_wakes_a_reader_and_a_sender(byte_registry):
    subject, _sender, _bytes = byte_registry
    stream = subject.open("shell", {}, has_bytes=True)
    outcome = {}

    def send() -> None:
        try:
            stream.send(b"x")
        except GatewayUnreachable as error:
            outcome["send"] = error

    def read() -> None:
        outcome["read"] = stream.read(timeout_s=5)

    threads = [threading.Thread(target=send), threading.Thread(target=read)]
    for thread in threads:
        thread.start()
    subject.end_all()
    for thread in threads:
        thread.join(timeout=5)

    assert outcome["read"] == b""
    assert isinstance(outcome["send"], GatewayUnreachable)


def test_bytes_before_the_close_are_still_read(byte_registry):
    subject, _sender, _bytes = byte_registry
    stream = subject.open("shell", {}, has_bytes=True)

    subject.take_bytes(1, b"bye")
    subject.take_close({"type": "close", "stream": 1, "params": {"exit_code": 0}})

    assert stream.read(timeout_s=1) == b"bye"
    assert stream.read(timeout_s=1) == b""
    assert stream.wait_close(timeout_s=0) == {"exit_code": 0}


def test_a_close_from_this_side_tells_the_hub_once(byte_registry):
    subject, sender, _bytes = byte_registry
    stream = subject.open("shell", {}, has_bytes=True)

    stream.close()
    stream.close()

    closes = [frame for frame in sender.frames if frame["type"] == "close"]
    assert closes == [{"type": "close", "stream": 1, "code": "", "params": {}}]
    assert stream.read(timeout_s=1) == b""
    assert subject._streams == {}


def test_a_credit_naming_no_integer_is_typed(byte_registry):
    subject, _sender, _bytes = byte_registry

    with pytest.raises(TypeError):
        subject.take_credit({"type": "credit", "stream": 1, "bytes": "many"})
