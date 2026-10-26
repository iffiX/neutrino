"""The streams this side opens through its transport, their bytes and their closes.

Each stream is one local connection to the transport, opened with an
``open`` line naming the hub's binding and the stream's ``open`` record. The
far side answers first: ``accept``, or a ``close`` that refuses. A ``shell``
and an ``exec`` then carry records both ways until a ``close``, whose
``params`` are the result and whose ``code`` makes it a refusal; a TCP
``connect`` carries its connection's raw bytes after the ``accept``, and
its end is the end of those bytes.

One thread reads the connection into a short queue; a reader that does not
consume holds that thread, and so the transport, the hub and the far end
behind it. Nothing is sent before the far side's ``accept``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import queue
import socket
import threading

from neutrino_client.constants import CLIENT_RECORD_BYTES_MAX, CLIENT_STREAM_TIMEOUT_S
from neutrino_client.core.protocol import (
    RECORD_ACCEPT,
    RECORD_CLOSE,
    RECORD_DATA,
    RECORD_DATAGRAM,
    RECORD_EOF,
    RECORD_RESIZE,
    RECORD_STDERR,
    encode_json_record,
    encode_record,
    json_payload,
    read_record,
)
from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable

# How many pieces the reader holds for a consumer before it stops reading.
STREAM_QUEUE_PIECES = 16
# The bytes one read of a raw connection takes.
STREAM_RAW_READ_BYTES = 64 * 1024
# What an ``exec`` stream's piece starts with, by the output it came from.
STREAM_FD_STDOUT = b"\x01"
STREAM_FD_STDERR = b"\x02"
# The piece that marks the end of the stream in the reader's queue.
STREAM_END = None
# How long one wait for room in the queue lasts before the stream is looked
# at again.
STREAM_HAND_WAIT_S = 0.5


class ClientStream:
    """One stream this side opened: its answer, its bytes and its close.

    Attributes:
        kind: The kind the open named.
    """

    def __init__(
        self,
        *,
        connection,
        kind: str,
        is_raw_after_accept: bool = False,
        is_fd_tagged: bool = False,
        accept_timeout_s: float = CLIENT_STREAM_TIMEOUT_S,
    ):
        """
        Args:
            connection: The local connection, its ``open`` line sent:
                ``recv(size)``, ``sendall(data)``, ``shutdown(how)`` and
                ``close()``.
            kind: The kind the open named.
            is_raw_after_accept: Whether the connection carries raw bytes
                after the ``accept``, as a TCP ``connect`` does.
            is_fd_tagged: Whether each piece read starts with the output it
                came from, ``1`` for ``data`` and ``2`` for ``stderr``, as an
                ``exec`` without a terminal gives them.
            accept_timeout_s: How long a send waits for the far side's
                ``accept``.
        """
        self.kind = kind
        self._connection = connection
        self._is_raw = is_raw_after_accept
        self._is_fd_tagged = is_fd_tagged
        self._accept_timeout_s = accept_timeout_s
        self._pieces: queue.Queue = queue.Queue(maxsize=STREAM_QUEUE_PIECES)
        self._send_lock = threading.Lock()
        self._answered = threading.Event()
        self._closed = threading.Event()
        self._is_accepted = False
        self._is_ended = False
        self._is_closed_here = False
        self._is_drained = False
        self._is_reader_done = False
        self._code = ""
        self._params: dict = {}
        threading.Thread(
            target=self._read_forever, name="client_stream", daemon=True
        ).start()

    @property
    def is_done(self) -> bool:
        """Whether the far side closed the stream, its connection ended, or this side closed it."""
        return self._closed.is_set() or self._is_closed_here

    @property
    def is_accepted(self) -> bool:
        """Whether the far side accepted the stream."""
        return self._is_accepted

    def wait_accept(self, timeout_s: float) -> bool:
        """Wait for the far side's answer.

        Args:
            timeout_s: How long to wait.

        Returns:
            True once the far side accepted; False when it refused, the
            connection ended first, or no answer came in time.
        """
        self._answered.wait(timeout=timeout_s)
        return self._is_accepted

    def wait_close(self, timeout_s: float) -> dict:
        """Wait for the stream's end and read its result.

        Args:
            timeout_s: How long to wait.

        Returns:
            The close's ``params``; empty for a raw stream whose bytes ended.

        Raises:
            GatewayRefusedDetail: When the close carries a code.
            GatewayUnreachable: When no end arrives in time, or the
                connection ended with no close.
        """
        if not self._closed.wait(timeout=timeout_s):
            raise GatewayUnreachable(f"the {self.kind} stream did not end in time")
        if self._code:
            raise GatewayRefusedDetail(code=self._code, params=dict(self._params))
        if self._is_ended:
            raise GatewayUnreachable("the hub's session closed before the stream did")
        return dict(self._params)

    def refusal(self) -> "dict | None":
        """The far side's close as a refusal, once the stream has ended.

        Returns:
            ``{"code", "params"}`` when the close carried a code; None while
            the stream is open, or when it ended without one.
        """
        if not self._closed.is_set() or not self._code:
            return None
        return {"code": self._code, "params": dict(self._params)}

    def read(self, timeout_s: float) -> "bytes | None":
        """The next bytes the far side sent.

        Args:
            timeout_s: How long to wait.

        Returns:
            The bytes, each piece of an fd-tagged stream with its output's
            byte first; empty once the stream is over and nothing is left;
            None when nothing arrived in time.
        """
        if self._is_drained:
            return b""
        try:
            if timeout_s > 0:
                piece = self._pieces.get(timeout=timeout_s)
            else:
                piece = self._pieces.get_nowait()
        except queue.Empty:
            if self._is_closed_here or self._is_reader_done:
                self._is_drained = True
                return b""
            return None
        if piece is STREAM_END:
            self._is_drained = True
            return b""
        return piece

    def send(self, data: bytes) -> None:
        """Send bytes on the stream, once the far side accepted it.

        Args:
            data: The bytes; a record stream cuts them into records of at
                most ``CLIENT_RECORD_BYTES_MAX``.

        Raises:
            GatewayUnreachable: When the stream was refused, has ended, or
                no answer came in time.
        """
        self._wait_open()
        view = memoryview(bytes(data))
        with self._send_lock:
            try:
                if self._is_raw:
                    self._connection.sendall(bytes(view))
                    return
                while view:
                    piece = bytes(view[:CLIENT_RECORD_BYTES_MAX])
                    self._connection.sendall(encode_record(RECORD_DATA, piece))
                    view = view[len(piece) :]
            except OSError as error:
                raise GatewayUnreachable(f"the {self.kind} stream ended") from error

    def send_datagram(self, source: int, datagram: bytes) -> None:
        """Send one datagram on a UDP stream.

        Args:
            source: The port it left from.
            datagram: The datagram.

        Raises:
            GatewayUnreachable: When the stream was refused or has ended.
        """
        self._send_record(
            encode_record(RECORD_DATAGRAM, int(source).to_bytes(2, "big") + datagram)
        )

    def send_eof(self) -> None:
        """Tell the far side no more input follows; the stream stays open the other way.

        Raises:
            GatewayUnreachable: When the stream was refused or has ended.
        """
        self._send_record(encode_record(RECORD_EOF))

    def resize(self, cols: int, rows: int) -> None:
        """Tell the far side the terminal's new size.

        Args:
            cols: The width in columns.
            rows: The height in rows.

        Raises:
            GatewayUnreachable: When the stream was refused or has ended.
        """
        self._send_record(
            encode_json_record(RECORD_RESIZE, {"cols": int(cols), "rows": int(rows)})
        )

    def close(self) -> None:
        """End the stream from this side; the far side sends no close back. Idempotent."""
        if self._is_closed_here:
            return
        self._is_closed_here = True
        try:
            self._pieces.put_nowait(STREAM_END)
        except queue.Full:
            pass
        if not self._is_raw and self._is_accepted and not self._closed.is_set():
            try:
                with self._send_lock:
                    self._connection.sendall(
                        encode_json_record(RECORD_CLOSE, {"code": "", "params": {}})
                    )
            except OSError:
                pass
        _end_connection(self._connection)

    def _wait_open(self) -> None:
        """Wait for the far side's accept before a send.

        Raises:
            GatewayUnreachable: When it refused, ended, or did not answer.
        """
        if self._is_closed_here:
            raise GatewayUnreachable(f"the {self.kind} stream was closed here")
        if not self._answered.wait(timeout=self._accept_timeout_s):
            raise GatewayUnreachable(f"the {self.kind} stream was not answered")
        if not self._is_accepted or self._closed.is_set():
            raise GatewayUnreachable(f"the {self.kind} stream has ended")

    def _send_record(self, record: bytes) -> None:
        """Send one record once the stream is open.

        Raises:
            GatewayUnreachable: When the stream was refused or has ended.
        """
        self._wait_open()
        with self._send_lock:
            try:
                self._connection.sendall(record)
            except OSError as error:
                raise GatewayUnreachable(f"the {self.kind} stream ended") from error

    def _read_forever(self) -> None:
        """Read the answer, then the records or the raw bytes, until the end."""
        try:
            self._read_answer()
            if self._is_accepted:
                if self._is_raw:
                    self._read_raw()
                else:
                    self._read_records()
        except (OSError, ValueError):
            pass
        finally:
            if not self._closed.is_set():
                if not self._is_raw or not self._is_accepted:
                    self._is_ended = True
                self._closed.set()
            self._answered.set()
            self._hand(STREAM_END)
            self._is_reader_done = True
            _end_connection(self._connection)

    def _read_answer(self) -> None:
        """Read records until the far side's accept or its refusing close."""
        while True:
            record = read_record(self._connection.recv)
            if record is None:
                return
            record_type, payload = record
            if record_type == RECORD_ACCEPT:
                self._is_accepted = True
                self._answered.set()
                return
            if record_type == RECORD_CLOSE:
                self._take_close(payload)
                return

    def _read_raw(self) -> None:
        """Hand the raw bytes on until the connection ends."""
        while True:
            data = self._connection.recv(STREAM_RAW_READ_BYTES)
            if not data:
                self._closed.set()
                return
            self._hand(data)

    def _read_records(self) -> None:
        """Hand each record's bytes on until the close."""
        while True:
            record = read_record(self._connection.recv)
            if record is None:
                return
            record_type, payload = record
            if record_type == RECORD_CLOSE:
                self._take_close(payload)
                return
            if record_type == RECORD_DATA and payload:
                self._hand(
                    STREAM_FD_STDOUT + payload if self._is_fd_tagged else payload
                )
            elif record_type == RECORD_STDERR and payload:
                self._hand(
                    STREAM_FD_STDERR + payload if self._is_fd_tagged else payload
                )
            elif record_type == RECORD_DATAGRAM:
                self._hand(payload)

    def _hand(self, piece) -> None:
        """Queue one piece for the reader, waiting while the queue is full;
        a stream closed here takes nothing more."""
        while not self._is_closed_here:
            try:
                self._pieces.put(piece, timeout=STREAM_HAND_WAIT_S)
                return
            except queue.Full:
                continue

    def _take_close(self, payload: bytes) -> None:
        """Record the far side's close."""
        close = json_payload(payload)
        params = close.get("params")
        self._code = str(close.get("code", "") or "")
        self._params = params if isinstance(params, dict) else {}
        self._closed.set()
        self._answered.set()


def _end_connection(connection) -> None:
    """Close a local connection at once, waking a thread blocked on it."""
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass
