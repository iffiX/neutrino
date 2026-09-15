"""The streams this side opens on the channel, and the closes that end them.

A client opens a stream with ``open {stream, kind, ...args}`` and waits for
the hub's ``close {stream, code, params}``: the ``params`` are the result,
and a ``code`` makes the close a refusal. The client opens odd ids counting
upward; the hub's are even, so the two never collide. The 0.3.0 client sends
no bytes on a stream and grants no credit.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import threading

from neutrino_client.core.protocol import FRAME_OPEN
from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable

FIRST_STREAM_ID = 1
STREAM_ID_STEP = 2


class ClientStream:
    """One stream this side opened, waiting for the hub's close.

    Attributes:
        stream_id: The id the open named.
        kind: The kind the open named.
    """

    def __init__(self, *, stream_id: int, kind: str):
        """
        Args:
            stream_id: The id the open named.
            kind: The kind the open named.
        """
        self.stream_id = stream_id
        self.kind = kind
        self._closed = threading.Event()
        self._code = ""
        self._params: dict = {}
        self._is_ended = False

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

    def take_close(self, *, code: str, params: dict) -> None:
        """Record the hub's close and wake the waiter.

        Args:
            code: The close's code, empty for a result.
            params: The close's params.
        """
        self._code = code
        self._params = dict(params)
        self._closed.set()

    def end(self) -> None:
        """Wake the waiter with no close: the socket ended first."""
        self._is_ended = True
        self._closed.set()


class ClientStreamRegistry:
    """The streams open on one socket, by id."""

    def __init__(self, *, send_text, log=print):
        """
        Args:
            send_text: Sends one text frame on the socket; raises
                :class:`GatewayUnreachable` when the socket is gone.
            log: Callable used for progress messages.
        """
        self._send_text = send_text
        self._log = log
        self._lock = threading.Lock()
        self._next_id = FIRST_STREAM_ID
        self._streams: dict = {}
        self._is_ended = False

    def open(self, kind: str, args: dict) -> ClientStream:
        """Open one stream: the next odd id, and the open frame sent.

        Args:
            kind: The stream kind.
            args: The kind's own arguments, sent beside ``stream`` and
                ``kind``.

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
            stream = ClientStream(stream_id=stream_id, kind=kind)
            self._streams[stream_id] = stream
        frame = {"type": FRAME_OPEN, "stream": stream_id, "kind": kind, **dict(args)}
        try:
            self._send_text(json.dumps(frame))
        except GatewayUnreachable:
            with self._lock:
                self._streams.pop(stream_id, None)
            raise
        return stream

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
