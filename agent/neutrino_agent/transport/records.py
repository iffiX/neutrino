"""The records every stream carries: ``<u8 type><u32 length><payload>``.

A stream's local connection carries the records the transport passes on
unchanged, so this side writes and reads them as the hub's side does. Pure.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import struct

from neutrino_agent.transport.constants import (
    TRANSPORT_RECORD_ACCEPT,
    TRANSPORT_RECORD_BYTES_MAX,
    TRANSPORT_RECORD_CLOSE,
    TRANSPORT_RECORD_DATA,
    TRANSPORT_RECORD_EOF,
    TRANSPORT_RECORD_OPEN,
    TRANSPORT_RECORD_RESIZE,
    TRANSPORT_RECORD_STDERR,
)

# The head of every record: its type and its payload's length, big-endian.
RECORD_HEAD = struct.Struct(">BI")


def encode_record(kind: int, payload: bytes = b"") -> bytes:
    """One record's bytes.

    Args:
        kind: The record's type.
        payload: Its payload, at most ``TRANSPORT_RECORD_BYTES_MAX``.

    Returns:
        The head and the payload.

    Raises:
        ValueError: When the payload is larger than a record holds.
    """
    if len(payload) > TRANSPORT_RECORD_BYTES_MAX:
        raise ValueError(f"a record holds at most {TRANSPORT_RECORD_BYTES_MAX} bytes")
    return RECORD_HEAD.pack(kind, len(payload)) + bytes(payload)


def encode_json(kind: int, value: dict) -> bytes:
    """One record whose payload is a JSON object, ``open``, ``resize`` or ``close``.

    Args:
        kind: The record's type.
        value: The object.

    Returns:
        The record's bytes.
    """
    return encode_record(kind, json.dumps(value, separators=(",", ":")).encode())


def encode_close(code: str = "", params: "dict | None" = None) -> bytes:
    """A ``close`` record.

    Args:
        code: The refusal; empty when the stream did what it was asked.
        params: The result, or what the code's wording names.

    Returns:
        The record's bytes.
    """
    return encode_json(
        TRANSPORT_RECORD_CLOSE, {"code": code or "", "params": dict(params or {})}
    )


def split_data(kind: int, data: bytes) -> list:
    """Bytes as records of one type, none larger than a record holds.

    Args:
        kind: ``data`` or ``stderr``.
        data: The bytes; empty gives no record.

    Returns:
        The records' bytes, in order.
    """
    view = memoryview(data)
    return [
        encode_record(kind, bytes(view[start : start + TRANSPORT_RECORD_BYTES_MAX]))
        for start in range(0, len(view), TRANSPORT_RECORD_BYTES_MAX)
    ]


def decode_item(kind: int, payload: bytes) -> "tuple | None":
    """What one record means to a stream's handler.

    Args:
        kind: The record's type.
        payload: Its payload.

    Returns:
        ``("data", bytes)``, ``("stderr", bytes)``, ``("eof",)``,
        ``("resize", cols, rows)``, ``("accept",)``, ``("open", dict)`` or
        ``("close", code, params)``; None for a type no stream takes, or a
        JSON payload that does not read.
    """
    if kind == TRANSPORT_RECORD_DATA:
        return ("data", bytes(payload))
    if kind == TRANSPORT_RECORD_STDERR:
        return ("stderr", bytes(payload))
    if kind == TRANSPORT_RECORD_EOF:
        return ("eof",)
    if kind == TRANSPORT_RECORD_ACCEPT:
        return ("accept",)
    if kind not in (
        TRANSPORT_RECORD_RESIZE,
        TRANSPORT_RECORD_CLOSE,
        TRANSPORT_RECORD_OPEN,
    ):
        return None
    try:
        value = json.loads(bytes(payload).decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    if kind == TRANSPORT_RECORD_OPEN:
        return ("open", value)
    if kind == TRANSPORT_RECORD_RESIZE:
        try:
            return ("resize", int(value.get("cols", 0)), int(value.get("rows", 0)))
        except (TypeError, ValueError):
            return None
    params = value.get("params")
    return (
        "close",
        str(value.get("code", "") or ""),
        dict(params) if isinstance(params, dict) else {},
    )


class RecordReader:
    """Reads whole records off a connection, one at a time."""

    def __init__(self, connection):
        """
        Args:
            connection: What the records come from, with ``recv(size)``
                returning empty bytes at its end.
        """
        self._connection = connection
        self._buffer = bytearray()

    def take_buffer(self, data: bytes) -> None:
        """Take bytes already read past a line before the records began.

        Args:
            data: The bytes.
        """
        self._buffer.extend(data)

    def read(self) -> "tuple | None":
        """The next record.

        Returns:
            ``(type, payload)``; None at the connection's end, a record cut
            short included.

        Raises:
            OSError: When the connection fails.
        """
        if not self._fill(RECORD_HEAD.size):
            return None
        kind, length = RECORD_HEAD.unpack(bytes(self._buffer[: RECORD_HEAD.size]))
        if length > TRANSPORT_RECORD_BYTES_MAX:
            return None
        if not self._fill(RECORD_HEAD.size + length):
            return None
        payload = bytes(self._buffer[RECORD_HEAD.size : RECORD_HEAD.size + length])
        del self._buffer[: RECORD_HEAD.size + length]
        return kind, payload

    def _fill(self, size: int) -> bool:
        while len(self._buffer) < size:
            chunk = self._connection.recv(TRANSPORT_RECORD_BYTES_MAX)
            if not chunk:
                return False
            self._buffer.extend(chunk)
        return True
