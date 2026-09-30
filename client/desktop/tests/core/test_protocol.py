"""The frame codec: the words, and the binary frame's u32 stream id prefix."""

import pytest

from neutrino_client.core import protocol


def test_the_eight_words_are_the_channels():
    assert (
        protocol.FRAME_HELLO,
        protocol.FRAME_WELCOME,
        protocol.FRAME_REFUSED,
        protocol.FRAME_STATE,
        protocol.FRAME_REPORT,
        protocol.FRAME_OPEN,
        protocol.FRAME_CLOSE,
        protocol.FRAME_CREDIT,
    ) == ("hello", "welcome", "refused", "state", "report", "open", "close", "credit")


@pytest.mark.parametrize("stream_id", [0, 1, 2, 255, 256, 65536, (1 << 32) - 1])
def test_a_binary_frame_round_trips(stream_id):
    frame = protocol.encode_binary(stream_id, b"\x00line\n")

    assert protocol.decode_binary(frame) == (stream_id, b"\x00line\n")


def test_the_id_is_a_big_endian_u32_prefix():
    assert protocol.encode_binary(1, b"x") == b"\x00\x00\x00\x01x"
    assert protocol.encode_binary(258, b"") == b"\x00\x00\x01\x02"


def test_an_id_outside_u32_is_refused():
    with pytest.raises(ValueError):
        protocol.encode_binary(1 << 32, b"")
    with pytest.raises(ValueError):
        protocol.encode_binary(-1, b"")


@pytest.mark.parametrize("frame", [b"", b"\x00", b"\x00\x00\x00"])
def test_a_frame_shorter_than_an_id_is_refused(frame):
    with pytest.raises(ValueError):
        protocol.decode_binary(frame)


def test_the_payload_comes_back_as_bytes_whatever_was_given():
    stream_id, payload = protocol.decode_binary(bytearray(b"\x00\x00\x00\x03ab"))

    assert (stream_id, payload) == (3, b"ab")
    assert isinstance(payload, bytes)
