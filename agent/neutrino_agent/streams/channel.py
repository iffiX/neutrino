"""One stream's two directions, between its local connection and its handler.

Every stream is one connection to the agent's transport, which passes the
stream's records on unchanged: a stream the hub opened is taken with an
``attach`` connection, and one this side opens with an ``open`` connection.
A reader thread turns each record into an item on the handler's queue; what
the handler sends goes out at once as records. yamux's window behind the
transport paces both directions, so no credit is kept here.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import queue
import threading

from neutrino_agent.exceptions import GatewayUnreachable, StreamClosed
from neutrino_agent.transport.constants import (
    TRANSPORT_RECORD_ACCEPT,
    TRANSPORT_RECORD_DATA,
    TRANSPORT_RECORD_STDERR,
)
from neutrino_agent.transport.records import (
    RecordReader,
    decode_item,
    encode_close,
    encode_record,
    split_data,
)


class StreamChannel:
    """One stream, as its handler sees it.

    What the far side sends queues up in order: ``("data", bytes)`` for a
    ``data`` record, ``("resize", cols, rows)`` for a ``resize``,
    ``("eof",)`` once no more input follows, and ``("close", code, params)``
    once the far side closed the stream or the connection ended. A record
    of a type no handler takes is dropped.

    Attributes:
        id: The stream's id as the transport named it; empty for a stream
            this side opened.
    """

    def __init__(self, connection, stream_id: str = "", *, reader=None):
        """
        Args:
            connection: The stream's local connection, with ``sendall``,
                ``recv`` and ``close``, its first line already written.
            stream_id: The id the transport gave the stream.
            reader: A :class:`RecordReader` already holding bytes read past
                the first line; None reads from the connection afresh.
        """
        self.id = str(stream_id)
        self._connection = connection
        self._reader = reader if reader is not None else RecordReader(connection)
        self._write_lock = threading.Lock()
        self._inbound: queue.Queue = queue.Queue()
        self._is_closed = False
        self._is_ended = False
        self._thread: "threading.Thread | None" = None

    @property
    def is_closed(self) -> bool:
        """Whether the stream ended, from either side, or its connection did."""
        return self._is_closed

    def start(self) -> None:
        """Read the far side's records onto the queue from now on."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._read_forever,
            name=f"agent_stream_{self.id or 'own'}",
            daemon=True,
        )
        self._thread.start()

    def take_answer(self) -> tuple:
        """The far side's answer to an open this side made: its first record.

        A refusal also lands on the queue, so a handler reading the channel
        meets it as the stream's close.

        Returns:
            ``("accept",)``, or ``("close", code, params)`` for a refusal or
            a connection that ended first, ``hub_unreachable`` then.
        """
        while True:
            try:
                record = self._reader.read()
            except OSError:
                record = None
            item = decode_item(*record) if record is not None else None
            if record is None:
                item = ("close", "hub_unreachable", {})
            if item is None:
                continue
            if item[0] == "accept":
                return item
            if item[0] == "close":
                self._end(item[1], item[2])
                with contextlib.suppress(OSError):
                    self._connection.close()
                return item

    def accept(self) -> None:
        """Answer the hub's open with ``accept``.

        Raises:
            GatewayUnreachable: When the connection is gone.
        """
        self._write(encode_record(TRANSPORT_RECORD_ACCEPT))

    def recv(self, timeout: "float | None" = None) -> "tuple | None":
        """The next item from the far side.

        Args:
            timeout: How long to wait for one.

        Returns:
            The item, or None when nothing arrived in time.
        """
        try:
            return self._inbound.get(timeout=timeout)
        except queue.Empty:
            return None

    def send_bytes(self, data: bytes) -> None:
        """Send bytes as ``data`` records.

        Args:
            data: The bytes, split into records of at most 64 KiB.

        Raises:
            StreamClosed: When the stream ended before they were sent.
            GatewayUnreachable: When the connection is gone.
        """
        self._send(TRANSPORT_RECORD_DATA, data)

    def send_stderr(self, data: bytes) -> None:
        """Send what a process wrote to stderr as ``stderr`` records.

        Args:
            data: The bytes.

        Raises:
            StreamClosed: When the stream ended before they were sent.
            GatewayUnreachable: When the connection is gone.
        """
        self._send(TRANSPORT_RECORD_STDERR, data)

    def send_line(self, text: str) -> None:
        """Send one line of text as ``data``.

        Args:
            text: The line, without its newline.

        Raises:
            StreamClosed: When the stream ended before it was sent.
            GatewayUnreachable: When the connection is gone.
        """
        self.send_bytes((text + "\n").encode("utf-8"))

    def close(self, code: str = "", params: "dict | None" = None) -> None:
        """End the stream from this side, with its result.

        A stream the far side already closed sends nothing; the connection
        is closed either way.

        Args:
            code: The refusal; empty when the stream did what it was asked.
            params: The result, or what the code's wording names.
        """
        with self._write_lock:
            is_sent = self._is_closed
            self._is_closed = True
            if not is_sent:
                with contextlib.suppress(OSError):
                    self._connection.sendall(encode_close(code, params))
        with contextlib.suppress(OSError):
            self._connection.close()

    def _send(self, kind: int, data: bytes) -> None:
        if self._is_closed:
            raise StreamClosed(self.id)
        for record in split_data(kind, data):
            self._write(record)

    def _write(self, data: bytes) -> None:
        with self._write_lock:
            if self._is_closed:
                raise StreamClosed(self.id)
            try:
                self._connection.sendall(data)
            except OSError as error:
                raise GatewayUnreachable(
                    f"the stream's connection failed: {error}"
                ) from error

    def _read_forever(self) -> None:
        while True:
            try:
                record = self._reader.read()
            except OSError:
                record = None
            if record is None:
                self._end("", {})
                return
            item = decode_item(*record)
            if item is None or item[0] in ("accept", "open", "stderr"):
                continue
            if item[0] == "close":
                self._end(item[1], item[2])
                return
            self._inbound.put(item)

    def _end(self, code: str, params: dict) -> None:
        """The far side closed, or the connection ended: say so once."""
        self._mark_closed()
        if not self._is_ended:
            self._is_ended = True
            self._inbound.put(("close", code, dict(params)))

    def _mark_closed(self) -> None:
        with self._write_lock:
            self._is_closed = True
