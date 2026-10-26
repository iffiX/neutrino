"""The records every stream carries, as the transport passes them on."""

import io

import pytest

from neutrino_agent.transport.records import (
    RecordReader,
    decode_item,
    encode_close,
    encode_json,
    encode_record,
    split_data,
)


class Chunks:
    """A connection that hands its bytes back a few at a time."""

    def __init__(self, data: bytes, size: int = 3):
        self._stream = io.BytesIO(data)
        self._size = size

    def recv(self, size: int) -> bytes:
        return self._stream.read(min(size, self._size))


def test_a_record_is_its_type_a_big_endian_length_and_its_payload():
    assert encode_record(3, b"hi") == b"\x03\x00\x00\x00\x02hi"


def test_a_payload_past_64_kib_is_refused():
    with pytest.raises(ValueError):
        encode_record(3, b"x" * (64 * 1024 + 1))


def test_bytes_are_split_into_records_no_larger_than_64_kib():
    records = split_data(3, b"x" * (64 * 1024 + 5))

    assert [len(record) - 5 for record in records] == [64 * 1024, 5]
    assert split_data(3, b"") == []


@pytest.mark.parametrize(
    "kind, payload, item",
    [
        (1, b'{"kind":"shell"}', ("open", {"kind": "shell"})),
        (2, b"", ("accept",)),
        (3, b"abc", ("data", b"abc")),
        (4, b"err", ("stderr", b"err")),
        (5, b"", ("eof",)),
        (6, b'{"cols":120,"rows":40}', ("resize", 120, 40)),
        (8, b'{"code":"x","params":{"a":1}}', ("close", "x", {"a": 1})),
        (8, b'{"params":[]}', ("close", "", {})),
        (7, b"\x00\x01d", None),
        (9, b"", None),
        (6, b"not json", None),
    ],
)
def test_each_record_type_is_one_item_and_any_other_is_dropped(kind, payload, item):
    assert decode_item(kind, payload) == item


def test_a_close_record_carries_its_code_and_params():
    assert decode_item(8, encode_close("nope", {"port": 1})[5:]) == (
        "close",
        "nope",
        {"port": 1},
    )


def test_the_reader_takes_whole_records_from_any_chunking():
    data = encode_json(6, {"cols": 1, "rows": 2}) + encode_record(3, b"hello")
    reader = RecordReader(Chunks(data))

    assert reader.read() == (6, b'{"cols":1,"rows":2}')
    assert reader.read() == (3, b"hello")
    assert reader.read() is None


def test_a_record_cut_short_ends_the_reader():
    assert RecordReader(Chunks(encode_record(3, b"hello")[:-1])).read() is None


def test_bytes_read_past_a_first_line_are_the_first_records():
    reader = RecordReader(Chunks(b""))
    reader.take_buffer(encode_record(5))

    assert reader.read() == (5, b"")
