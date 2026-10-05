"""The streams this side opens on the channel, their bytes and their closes.

A client opens a stream with ``open {stream, kind, ...args}`` and waits for
the hub's ``close {stream, code, params}``: the ``params`` are the result,
and a ``code`` makes the close a refusal. The client opens odd ids counting
upward; the hub's are even, so the two never collide.

A byte stream, a ``shell``, carries binary frames both ways under credit:
this side sends no more than the hub has granted, in frames of at most
``CLIENT_WS_CHUNK_BYTES``, and grants the hub more as its reader consumes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import collections
import json
import threading
import time

from neutrino_client.constants import (
    CLIENT_STREAM_CREDIT_BYTES,
    CLIENT_WS_CHUNK_BYTES,
    CLIENT_WS_CREDIT_TIMEOUT_S,
)
from neutrino_client.core.protocol import (
    FRAME_CLOSE,
    FRAME_CREDIT,
    FRAME_OPEN,
    encode_binary,
)
from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable

FIRST_STREAM_ID = 1
STREAM_ID_STEP = 2


def _nobody(*_args) -> None:
    """Nobody listening."""


class ClientStream:
    """One stream this side opened: its close, and on a byte stream its bytes.

    Attributes:
        stream_id: The id the open named.
        kind: The kind the open named.
    """

    def __init__(
        self,
        *,
        stream_id: int,
        kind: str,
        send_bytes=None,
        grant=None,
        close=None,
    ):
        """
        Args:
            stream_id: The id the open named.
            kind: The kind the open named.
            send_bytes: Sends one binary frame on the socket; raises
                :class:`GatewayUnreachable` when the socket is gone. None
                for a stream that sends no bytes.
            grant: ``grant(nbytes)`` sends the hub a credit frame for this
                stream; None for a stream that takes no bytes.
            close: Sends this side's close for this stream; None for nobody.
        """
        self.stream_id = stream_id
        self.kind = kind
        self._send_bytes = send_bytes
        self._grant = grant if grant is not None else _nobody
        self._close = close if close is not None else _nobody
        self._closed = threading.Event()
        self._code = ""
        self._params: dict = {}
        self._is_ended = False
        self._condition = threading.Condition()
        self._incoming: collections.deque = collections.deque()
        self._credit = 0
        # Set once the hub has granted any credit.
        self._is_credited = False
        self._consumed = 0
        self._is_closed_here = False

    @property
    def is_done(self) -> bool:
        """Whether the hub closed the stream, the socket ended, or this side closed it."""
        return self._closed.is_set() or self._is_closed_here

    def wait_close(self, timeout_s: float) -> dict:
        """Wait for the hub's close and read it.

        Args:
            timeout_s: How long to wait.

        Returns:
            The close's ``params``.

        Raises:
            GatewayRefusedDetail: When the close carries a code.
            GatewayUnreachable: When no close arrives in time, or the socket
                ends first.
        """
        if not self._closed.wait(timeout=timeout_s):
            raise GatewayUnreachable(f"the hub did not close the {self.kind} stream")
        if self._is_ended:
            raise GatewayUnreachable("the hub socket closed before the stream did")
        if self._code:
            raise GatewayRefusedDetail(code=self._code, params=dict(self._params))
        return dict(self._params)

    def read(self, timeout_s: float) -> "bytes | None":
        """The next bytes the hub sent on this stream.

        Consuming them grants the hub more once half the window is used.

        Args:
            timeout_s: How long to wait for bytes.

        Returns:
            The bytes; empty once the stream is over and nothing is left;
            None when nothing arrived in time.
        """
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while not self._incoming:
                if self.is_done:
                    return b""
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)
            data = self._incoming.popleft()
            self._consumed += len(data)
            renewal = 0
            if self._consumed >= CLIENT_STREAM_CREDIT_BYTES // 2 and not self.is_done:
                renewal, self._consumed = self._consumed, 0
        if renewal:
            try:
                self._grant(renewal)
            except GatewayUnreachable:
                # The reader sees the socket's end on its next read.
                pass
        return data

    def send(self, data: bytes) -> None:
        """Send bytes on this stream, no faster than the hub's credit.

        Args:
            data: The bytes, cut into frames of at most
                ``CLIENT_WS_CHUNK_BYTES``.

        Raises:
            GatewayUnreachable: When the stream or the socket has ended, or
                the stream sends no bytes.
            TimeoutError: When the hub grants no credit within
                ``CLIENT_WS_CREDIT_TIMEOUT_S``.
        """
        if self._send_bytes is None:
            raise GatewayUnreachable(f"a {self.kind} stream carries no bytes")
        view = memoryview(bytes(data))
        while view:
            size = self._take_credit(min(len(view), CLIENT_WS_CHUNK_BYTES))
            self._send_bytes(encode_binary(self.stream_id, bytes(view[:size])))
            view = view[size:]

    def try_send(self, data: bytes) -> bool:
        """Send one frame now if the hub's credit covers it, never waiting.

        Args:
            data: The frame's bytes, at most ``CLIENT_WS_CHUNK_BYTES``.

        Returns:
            Whether it went; False when the credit is short, the stream has
            ended, or the socket is gone.
        """
        if self._send_bytes is None or len(data) > CLIENT_WS_CHUNK_BYTES:
            return False
        with self._condition:
            if self.is_done or self._credit < len(data):
                return False
            self._credit -= len(data)
        try:
            self._send_bytes(encode_binary(self.stream_id, bytes(data)))
        except GatewayUnreachable:
            return False
        return True

    def wait_credit(self, timeout_s: float) -> bool:
        """Wait until the hub has granted any credit, or the stream ends.

        Args:
            timeout_s: How long to wait.

        Returns:
            True once the hub has granted credit while the stream is open.
        """
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while not self._is_credited and not self.is_done:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return self._is_credited and not self.is_done

    def read_frame(self, timeout_s: float) -> "bytes | None":
        """The next binary frame the hub sent, its bytes granted back at once.

        Args:
            timeout_s: How long to wait for a frame.

        Returns:
            The frame's bytes; empty once the stream is over and nothing is
            left; None when nothing arrived in time.
        """
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while not self._incoming:
                if self.is_done:
                    return b""
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)
            data = self._incoming.popleft()
        if data and not self.is_done:
            try:
                self._grant(len(data))
            except GatewayUnreachable:
                pass
        return data

    def refusal(self) -> "dict | None":
        """The hub's close as a refusal, once the stream has ended.

        Returns:
            ``{"code", "params"}`` when the hub closed the stream with a
            code; None while it is open, or when it ended without one.
        """
        if not self._closed.is_set() or self._is_ended or not self._code:
            return None
        return {"code": self._code, "params": dict(self._params)}

    def close(self) -> None:
        """End the stream from this side; the hub sends no close back. Idempotent."""
        with self._condition:
            if self.is_done:
                return
            self._is_closed_here = True
            self._condition.notify_all()
        try:
            self._close()
        except GatewayUnreachable:
            pass

    def take_bytes(self, data: bytes) -> None:
        """Queue bytes the hub sent, for the reader.

        Args:
            data: The binary frame's bytes, without the stream id.
        """
        with self._condition:
            self._incoming.append(bytes(data))
            self._condition.notify_all()

    def take_credit(self, nbytes: int) -> None:
        """Add the hub's grant to what this side may send.

        Args:
            nbytes: How many more bytes the hub takes.
        """
        with self._condition:
            self._credit += max(int(nbytes), 0)
            if self._credit > 0:
                self._is_credited = True
            self._condition.notify_all()

    def take_close(self, *, code: str, params: dict) -> None:
        """Record the hub's close and wake every waiter.

        Args:
            code: The close's code, empty for a result.
            params: The close's params.
        """
        self._code = code
        self._params = dict(params)
        with self._condition:
            self._closed.set()
            self._condition.notify_all()

    def end(self) -> None:
        """Wake every waiter with no close: the socket ended first."""
        self._is_ended = True
        with self._condition:
            self._closed.set()
            self._condition.notify_all()

    def _take_credit(self, wanted: int) -> int:
        """Wait for credit, then spend up to ``wanted`` of it.

        Raises:
            GatewayUnreachable: When the stream ends while waiting.
            TimeoutError: When no credit arrives in time.
        """
        deadline = time.monotonic() + CLIENT_WS_CREDIT_TIMEOUT_S
        with self._condition:
            while self._credit <= 0:
                if self.is_done:
                    raise GatewayUnreachable(f"the {self.kind} stream has ended")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"the hub granted no credit on {self.kind}")
                self._condition.wait(timeout=remaining)
            if self.is_done:
                raise GatewayUnreachable(f"the {self.kind} stream has ended")
            size = min(wanted, self._credit)
            self._credit -= size
            return size


class ClientStreamRegistry:
    """The streams open on one socket, by id."""

    def __init__(self, *, send_text, send_bytes=None, log=print):
        """
        Args:
            send_text: Sends one text frame on the socket; raises
                :class:`GatewayUnreachable` when the socket is gone.
            send_bytes: Sends one binary frame on the socket, likewise;
                None for a socket that carries no byte stream.
            log: Callable used for progress messages.
        """
        self._send_text = send_text
        self._send_bytes = send_bytes
        self._log = log
        self._lock = threading.Lock()
        self._next_id = FIRST_STREAM_ID
        self._streams: dict = {}
        self._is_ended = False

    def open(self, kind: str, args: dict, *, has_bytes: bool = False) -> ClientStream:
        """Open one stream: the next odd id, and the open frame sent.

        Args:
            kind: The stream kind.
            args: The kind's own arguments, sent beside ``stream`` and
                ``kind``.
            has_bytes: Whether the stream carries bytes both ways; such a
                stream is granted ``CLIENT_STREAM_CREDIT_BYTES`` at once.

        Returns:
            The stream, to wait on.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        with self._lock:
            if self._is_ended:
                raise GatewayUnreachable("the socket is closed")
            stream_id = self._next_id
            self._next_id += STREAM_ID_STEP
            stream = ClientStream(
                stream_id=stream_id,
                kind=kind,
                send_bytes=self._send_bytes if has_bytes else None,
                grant=self._granter(stream_id) if has_bytes else None,
                close=self._closer(stream_id),
            )
            self._streams[stream_id] = stream
        frame = {"type": FRAME_OPEN, "stream": stream_id, "kind": kind, **dict(args)}
        try:
            self._send_text(json.dumps(frame))
            if has_bytes:
                self.grant(stream_id, CLIENT_STREAM_CREDIT_BYTES)
        except GatewayUnreachable:
            with self._lock:
                self._streams.pop(stream_id, None)
            raise
        return stream

    def grant(self, stream_id: int, nbytes: int) -> None:
        """Grant the hub more bytes on one stream.

        Args:
            stream_id: The stream.
            nbytes: How many more bytes this side takes.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        self._send_text(
            json.dumps({"type": FRAME_CREDIT, "stream": stream_id, "bytes": nbytes})
        )

    def take_bytes(self, stream_id: int, data: bytes) -> None:
        """Hand bytes the hub sent to the stream they belong to.

        Args:
            stream_id: The binary frame's stream id.
            data: The bytes after the id.
        """
        with self._lock:
            stream = self._streams.get(stream_id)
        if stream is None:
            self._log(f"dropping {len(data)} bytes the hub sent on stream {stream_id}")
            return
        stream.take_bytes(data)

    def take_credit(self, message: dict) -> None:
        """Hand one credit frame to the stream it grants.

        Args:
            message: The credit frame; ``stream`` names the id and ``bytes``
                the grant.

        Raises:
            TypeError: When ``stream`` or ``bytes`` is not an integer.
        """
        stream_id = message.get("stream")
        nbytes = message.get("bytes")
        if not isinstance(stream_id, int) or not isinstance(nbytes, int):
            raise TypeError("a credit names its stream and bytes by integers")
        with self._lock:
            stream = self._streams.get(stream_id)
        if stream is None:
            self._log(f"dropping credit on stream {stream_id}")
            return
        stream.take_credit(nbytes)

    def take_close(self, message: dict) -> None:
        """Hand one close to the stream it ends.

        Args:
            message: The close frame; ``stream`` names the id.

        Raises:
            TypeError: When ``stream`` is not an integer.
        """
        stream_id = message.get("stream")
        if not isinstance(stream_id, int):
            raise TypeError("a close names its stream by an integer id")
        params = message.get("params")
        with self._lock:
            stream = self._streams.pop(stream_id, None)
        if stream is None:
            self._log(f"dropping a close for stream {stream_id}, which is not open")
            return
        stream.take_close(
            code=str(message.get("code", "") or ""),
            params=params if isinstance(params, dict) else {},
        )

    def end_all(self) -> None:
        """End every open stream: the socket is gone."""
        with self._lock:
            self._is_ended = True
            streams = list(self._streams.values())
            self._streams = {}
        for stream in streams:
            stream.end()

    def _granter(self, stream_id: int):
        """The grant callback of one stream."""

        def grant(nbytes: int) -> None:
            self.grant(stream_id, nbytes)

        return grant

    def _closer(self, stream_id: int):
        """The close callback of one stream: forget it, then tell the hub."""

        def close() -> None:
            with self._lock:
                self._streams.pop(stream_id, None)
            self._send_text(
                json.dumps(
                    {"type": FRAME_CLOSE, "stream": stream_id, "code": "", "params": {}}
                )
            )

        return close
