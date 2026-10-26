"""The channel's words and its stream records, as every peer spells them.

A frame is one JSON object whose ``type`` is one of the frame words below;
the control stream carries one per line. Every other stream carries
records: ``<u8 type><u32 length, big-endian><payload>``, a payload at most
``CLIENT_RECORD_BYTES_MAX``. Nothing here touches a socket but the reader
given to :func:`read_record`.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import struct

from neutrino_client.constants import CLIENT_RECORD_BYTES_MAX

FRAME_HELLO = "hello"
FRAME_WELCOME = "welcome"
FRAME_REFUSED = "refused"
FRAME_STATE = "state"
FRAME_REPORT = "report"
FRAME_PING = "ping"
FRAME_PONG = "pong"
FRAME_SERVICE = "service"
FRAME_PERSIST = "persist"
FRAME_STOP_SESSION = "stop_session"
FRAME_REPLY = "reply"

RECORD_OPEN = 1
RECORD_ACCEPT = 2
RECORD_DATA = 3
RECORD_STDERR = 4
RECORD_EOF = 5
RECORD_RESIZE = 6
RECORD_DATAGRAM = 7
RECORD_CLOSE = 8
RECORD_TYPES = (
    RECORD_OPEN,
    RECORD_ACCEPT,
    RECORD_DATA,
    RECORD_STDERR,
    RECORD_EOF,
    RECORD_RESIZE,
    RECORD_DATAGRAM,
    RECORD_CLOSE,
)
RECORD_HEADER = struct.Struct("!BI")


def encode_record(record_type: int, payload: bytes = b"") -> bytes:
    """One record: its type, its length, then its payload.

    Args:
        record_type: One of ``RECORD_TYPES``.
        payload: The payload.

    Returns:
        The record's bytes.

    Raises:
        ValueError: When the type is unknown or the payload is longer than
            ``CLIENT_RECORD_BYTES_MAX``.
    """
    if record_type not in RECORD_TYPES:
        raise ValueError(f"no record of type {record_type}")
    if len(payload) > CLIENT_RECORD_BYTES_MAX:
        raise ValueError(f"a record carries at most {CLIENT_RECORD_BYTES_MAX} bytes")
    return RECORD_HEADER.pack(record_type, len(payload)) + bytes(payload)


def encode_json_record(record_type: int, value: dict) -> bytes:
    """One record whose payload is a JSON object.

    Args:
        record_type: ``RECORD_OPEN``, ``RECORD_RESIZE`` or ``RECORD_CLOSE``.
        value: The object.

    Returns:
        The record's bytes.

    Raises:
        ValueError: When the type is unknown or the object is too long.
    """
    return encode_record(
        record_type, json.dumps(value, separators=(",", ":")).encode("utf-8")
    )


def read_record(read) -> "tuple[int, bytes] | None":
    """The next record from a reader.

    Args:
        read: ``read(size)`` returns at most ``size`` bytes, empty at the
            end; an ``OSError`` passes through.

    Returns:
        ``(type, payload)``; None once the reader ended, or ended inside a
        record.

    Raises:
        ValueError: When the length is past ``CLIENT_RECORD_BYTES_MAX``.
        OSError: When ``read`` raised it.
    """
    header = read_exactly(read, RECORD_HEADER.size)
    if header is None:
        return None
    record_type, length = RECORD_HEADER.unpack(header)
    if length > CLIENT_RECORD_BYTES_MAX:
        raise ValueError(f"a record of {length} bytes is past the limit")
    if not length:
        return record_type, b""
    payload = read_exactly(read, length)
    if payload is None:
        return None
    return record_type, payload


def read_exactly(read, size: int) -> "bytes | None":
    """``size`` bytes from a reader.

    Args:
        read: ``read(size)`` returns at most ``size`` bytes, empty at the end.
        size: How many bytes.

    Returns:
        The bytes; None when the reader ends first.

    Raises:
        OSError: When ``read`` raised it.
    """
    data = b""
    while len(data) < size:
        more = read(size - len(data))
        if not more:
            return None
        data += more
    return data


def json_payload(payload: bytes) -> dict:
    """A record's payload as a JSON object.

    Args:
        payload: The payload.

    Returns:
        The object; empty for a payload that is not one.
    """
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
