"""One stream through the transport: its answer, its bytes, its close.

A socket pair stands in for the local connection: the test is the
transport's end and writes the records the far side would. What is pinned:
nothing is sent before the accept, a refusing close before the accept is the
stream's refusal, a record stream's data and stderr pieces in order (tagged
by output on an exec without a terminal), its close's params as the result
and its code as a refusal, a connection that ends with no close as an end
of the hub's session, a raw ``connect`` whose bytes follow the accept and
whose end is the end of its bytes, eof and resize as records, a close from
this side sent once, and a send cut into records of the largest size.
"""

import json
import socket
import struct
import threading

import pytest

from neutrino_client.constants import CLIENT_RECORD_BYTES_MAX
from neutrino_client.core import protocol
from neutrino_client.core.streams import ClientStream
from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable

WAIT_S = 2


def record(record_type: int, payload: bytes = b"") -> bytes:
    return struct.pack("!BI", record_type, len(payload)) + payload


def close_record(code: str = "", params=None) -> bytes:
    return record(
        protocol.RECORD_CLOSE,
        json.dumps({"code": code, "params": params or {}}).encode(),
    )


def read_record(peer) -> "tuple[int, bytes]":
    return protocol.read_record(peer.recv)


@pytest.fixture
def pair():
    near, far = socket.socketpair()
    yield near, far
    for end in (near, far):
        try:
            end.close()
        except OSError:
            pass


def make(near, **kwargs) -> ClientStream:
    kwargs.setdefault("accept_timeout_s", WAIT_S)
    return ClientStream(connection=near, kind=kwargs.pop("kind", "shell"), **kwargs)


def test_nothing_is_sent_before_the_far_side_accepts(pair):
    near, far = pair
    stream = make(near)
    sent = threading.Thread(target=stream.send, args=(b"ls\n",))
    sent.start()
    far.settimeout(0.2)
    with pytest.raises(socket.timeout):
        far.recv(10)
    far.sendall(record(protocol.RECORD_ACCEPT))
    sent.join(WAIT_S)
    far.settimeout(WAIT_S)
    assert read_record(far) == (protocol.RECORD_DATA, b"ls\n")


def test_a_refusing_close_before_the_accept_is_the_streams_refusal(pair):
    near, far = pair
    stream = make(near)
    far.sendall(close_record("permission_denied", {"kind": "terminal"}))
    assert stream.wait_accept(WAIT_S) is False
    with pytest.raises(GatewayRefusedDetail) as refused:
        stream.wait_close(WAIT_S)
    assert refused.value.code == "permission_denied"
    assert refused.value.params == {"kind": "terminal"}
    assert stream.refusal() == {
        "code": "permission_denied",
        "params": {"kind": "terminal"},
    }
    assert stream.read(WAIT_S) == b""
    with pytest.raises(GatewayUnreachable):
        stream.send(b"x")


def test_data_and_stderr_reach_the_reader_in_order(pair):
    near, far = pair
    stream = make(near)
    far.sendall(
        record(protocol.RECORD_ACCEPT)
        + record(protocol.RECORD_DATA, b"one")
        + record(protocol.RECORD_STDERR, b"two")
    )
    assert stream.read(WAIT_S) == b"one"
    assert stream.read(WAIT_S) == b"two"


def test_an_exec_without_a_terminal_tags_each_piece_with_its_output(pair):
    near, far = pair
    stream = make(near, kind="exec", is_fd_tagged=True)
    far.sendall(
        record(protocol.RECORD_ACCEPT)
        + record(protocol.RECORD_DATA, b"out")
        + record(protocol.RECORD_STDERR, b"err")
    )
    assert stream.read(WAIT_S) == b"\x01out"
    assert stream.read(WAIT_S) == b"\x02err"


def test_the_close_carries_the_result(pair):
    near, far = pair
    stream = make(near)
    far.sendall(
        record(protocol.RECORD_ACCEPT)
        + record(protocol.RECORD_DATA, b"bye")
        + close_record("", {"exit_code": 3})
    )
    assert stream.read(WAIT_S) == b"bye"
    assert stream.read(WAIT_S) == b""
    assert stream.wait_close(WAIT_S) == {"exit_code": 3}
    assert stream.is_done


def test_a_connection_that_ends_with_no_close_is_the_sessions_end(pair):
    near, far = pair
    stream = make(near)
    far.sendall(record(protocol.RECORD_ACCEPT))
    far.close()
    assert stream.read(WAIT_S) == b""
    with pytest.raises(GatewayUnreachable):
        stream.wait_close(WAIT_S)


def test_a_raw_connect_carries_its_bytes_after_the_accept(pair):
    near, far = pair
    stream = make(near, kind="connect", is_raw_after_accept=True)
    far.sendall(record(protocol.RECORD_ACCEPT) + b"SSH-2.0-banner\r\n")
    assert stream.wait_accept(WAIT_S)
    assert stream.read(WAIT_S) == b"SSH-2.0-banner\r\n"
    stream.send(b"SSH-2.0-client\r\n")
    assert far.recv(100) == b"SSH-2.0-client\r\n"
    far.close()
    assert stream.read(WAIT_S) == b""
    assert stream.wait_close(WAIT_S) == {}


def test_a_raw_connect_refused_before_the_accept_says_why(pair):
    near, far = pair
    stream = make(near, kind="connect", is_raw_after_accept=True)
    far.sendall(close_record("agent_offline", {"device": "lab"}))
    assert stream.wait_accept(WAIT_S) is False
    assert stream.refusal() == {"code": "agent_offline", "params": {"device": "lab"}}


def test_eof_and_resize_go_as_records(pair):
    near, far = pair
    stream = make(near, kind="exec")
    far.sendall(record(protocol.RECORD_ACCEPT))
    stream.resize(120, 40)
    stream.send_eof()
    assert read_record(far) == (protocol.RECORD_RESIZE, b'{"cols":120,"rows":40}')
    assert read_record(far) == (protocol.RECORD_EOF, b"")


def test_a_send_is_cut_into_records_of_the_largest_size(pair):
    near, far = pair
    stream = make(near)
    far.sendall(record(protocol.RECORD_ACCEPT))
    data = b"x" * (CLIENT_RECORD_BYTES_MAX + 10)
    sender = threading.Thread(target=stream.send, args=(data,))
    sender.start()
    first = read_record(far)
    second = read_record(far)
    sender.join(WAIT_S)
    assert (first[0], len(first[1])) == (protocol.RECORD_DATA, CLIENT_RECORD_BYTES_MAX)
    assert (second[0], len(second[1])) == (protocol.RECORD_DATA, 10)


def test_a_close_from_this_side_is_sent_once_and_ends_the_connection(pair):
    near, far = pair
    stream = make(near)
    far.sendall(record(protocol.RECORD_ACCEPT))
    assert stream.wait_accept(WAIT_S)
    stream.close()
    stream.close()
    assert read_record(far) == (
        protocol.RECORD_CLOSE,
        b'{"code":"","params":{}}',
    )
    assert far.recv(10) == b""
    assert stream.is_done


def test_a_read_that_runs_out_answers_none(pair):
    near, far = pair
    stream = make(near)
    far.sendall(record(protocol.RECORD_ACCEPT))
    assert stream.read(0.05) is None


def test_an_unanswered_send_gives_up(pair):
    near, _far = pair
    stream = make(near, accept_timeout_s=0.05)
    with pytest.raises(GatewayUnreachable):
        stream.send(b"x")
