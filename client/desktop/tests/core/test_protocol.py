"""The channel's words and the record layout every stream but the control one carries."""

import io
import json
import struct

import pytest

from neutrino_client.constants import CLIENT_RECORD_BYTES_MAX
from neutrino_client.core import protocol


def test_the_frame_words_are_the_channels():
    assert (
        protocol.FRAME_HELLO,
        protocol.FRAME_WELCOME,
        protocol.FRAME_REFUSED,
        protocol.FRAME_STATE,
        protocol.FRAME_REPORT,
        protocol.FRAME_PING,
        protocol.FRAME_PONG,
        protocol.FRAME_SERVICE,
        protocol.FRAME_PERSIST,
        protocol.FRAME_STOP_SESSION,
        protocol.FRAME_REPLY,
    ) == (
        "hello",
        "welcome",
        "refused",
        "state",
        "report",
        "ping",
        "pong",
        "service",
        "persist",
        "stop_session",
        "reply",
    )


def test_the_record_types_are_the_standards_numbers():
    assert protocol.RECORD_TYPES == (1, 2, 3, 4, 5, 6, 7, 8)
    assert protocol.RECORD_ACCEPT == 2
    assert protocol.RECORD_CLOSE == 8


def test_a_record_is_a_type_byte_a_big_endian_u32_length_and_the_payload():
    record = protocol.encode_record(protocol.RECORD_DATA, b"abc")
    assert record == struct.pack("!BI", 3, 3) + b"abc"


def test_a_record_round_trips_through_a_reader():
    stream = io.BytesIO(
        protocol.encode_record(protocol.RECORD_DATA, b"one")
        + protocol.encode_record(protocol.RECORD_EOF)
    )
    assert protocol.read_record(stream.read) == (protocol.RECORD_DATA, b"one")
    assert protocol.read_record(stream.read) == (protocol.RECORD_EOF, b"")
    assert protocol.read_record(stream.read) is None


def test_a_json_record_carries_compact_json():
    record = protocol.encode_json_record(
        protocol.RECORD_RESIZE, {"cols": 80, "rows": 24}
    )
    assert record[5:] == b'{"cols":80,"rows":24}'
    assert protocol.json_payload(record[5:]) == {"cols": 80, "rows": 24}


def test_a_payload_past_the_limit_is_refused():
    with pytest.raises(ValueError):
        protocol.encode_record(
            protocol.RECORD_DATA, b"x" * (CLIENT_RECORD_BYTES_MAX + 1)
        )


def test_an_unknown_type_is_refused():
    with pytest.raises(ValueError):
        protocol.encode_record(9, b"")


def test_a_length_past_the_limit_is_refused_when_read():
    stream = io.BytesIO(struct.pack("!BI", 3, CLIENT_RECORD_BYTES_MAX + 1))
    with pytest.raises(ValueError):
        protocol.read_record(stream.read)


def test_a_reader_that_ends_inside_a_record_reads_as_its_end():
    stream = io.BytesIO(struct.pack("!BI", 3, 10) + b"short")
    assert protocol.read_record(stream.read) is None


@pytest.mark.parametrize("payload", [b"", b"not json", b"[1]", "é".encode("latin-1")])
def test_a_payload_that_is_no_object_reads_as_empty(payload):
    assert protocol.json_payload(payload) == {}


def test_a_close_payload_reads_back():
    payload = json.dumps({"code": "x", "params": {"a": 1}}).encode()
    assert protocol.json_payload(payload) == {"code": "x", "params": {"a": 1}}
