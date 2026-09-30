"""The channel's words and its binary frame, as every peer spells them.

A text frame is one JSON object whose ``type`` is one of the words below. A
binary frame is a big-endian u32 stream id, then the bytes. Nothing here
touches a socket.
"""

import struct

FRAME_HELLO = "hello"
FRAME_WELCOME = "welcome"
FRAME_REFUSED = "refused"
FRAME_STATE = "state"
FRAME_REPORT = "report"
FRAME_OPEN = "open"
FRAME_CLOSE = "close"
FRAME_CREDIT = "credit"

STREAM_ID_BYTES = 4
STREAM_ID_MAX = (1 << 32) - 1


def encode_binary(stream_id: int, payload: bytes) -> bytes:
    """One binary frame: the stream id, then the bytes.

    Args:
        stream_id: The stream the bytes belong to.
        payload: The bytes.

    Returns:
        The frame.

    Raises:
        ValueError: When the id is outside u32.
    """
    if not 0 <= stream_id <= STREAM_ID_MAX:
        raise ValueError(f"stream id {stream_id} is outside u32")
    return struct.pack("!I", stream_id) + bytes(payload)


def decode_binary(frame: bytes) -> "tuple[int, bytes]":
    """The stream id and the bytes of one binary frame.

    Args:
        frame: The frame as received.

    Returns:
        ``(stream_id, payload)``.

    Raises:
        ValueError: When the frame is shorter than a stream id.
    """
    if len(frame) < STREAM_ID_BYTES:
        raise ValueError("a binary frame starts with a four-byte stream id")
    return struct.unpack("!I", frame[:STREAM_ID_BYTES])[0], bytes(
        frame[STREAM_ID_BYTES:]
    )
