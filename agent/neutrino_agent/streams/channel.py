"""One stream's two directions, between the session and its handler.

A handler reads what the hub sent off the channel's queue and sends what it
produced through it. Bytes go out no faster than the hub's credit allows;
bytes come in no faster than the credit this side offers, granted as the
handler consumes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import queue
import threading

from neutrino_agent.constants import AGENT_WS_CHUNK_BYTES, AGENT_WS_CREDIT_TIMEOUT_S
from neutrino_agent.exceptions import StreamClosed


class StreamChannel:
    """One stream, as its handler sees it.

    The session hands items in and takes frames out; a handler reads the
    queue, sends, offers credit, and closes.

    What the hub sends queues up in order: ``("data", bytes)`` for a binary
    frame, ``("resize", cols, rows)`` for a resize, and ``("close", code,
    params)`` once the hub closed the stream or the socket went away. What
    the handler sends goes out at once, except bytes, which wait for the
    hub's credit.

    Attributes:
        id: The stream id.
    """

    def __init__(self, session, stream_id: int, credit: int = 0):
        """
        Args:
            session: The session the stream rides, which sends its frames.
            stream_id: The stream id.
            credit: How many bytes the hub will take before granting more.
        """
        self.id = int(stream_id)
        self._session = session
        self._credit = max(0, int(credit))
        self._granted = threading.Condition()
        self._inbound: queue.Queue = queue.Queue()
        self._is_closed = False

    @property
    def is_closed(self) -> bool:
        """Whether the stream ended, from either side, or the socket is gone."""
        return self._is_closed

    def recv(self, timeout: "float | None" = None) -> "tuple | None":
        """The next item from the hub.

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
        """Send bytes to the hub, as far as its credit allows.

        Args:
            data: The bytes; sent in chunks, waiting on credit between them.

        Raises:
            StreamClosed: When the stream ended before everything was sent.
            GatewayUnreachable: When the socket is gone.
        """
        view = memoryview(data)
        while view:
            with self._granted:
                while self._credit <= 0 and not self._is_closed:
                    if not self._granted.wait(timeout=AGENT_WS_CREDIT_TIMEOUT_S):
                        raise StreamClosed(self.id)
                if self._is_closed:
                    raise StreamClosed(self.id)
                size = min(self._credit, AGENT_WS_CHUNK_BYTES, len(view))
                self._credit -= size
            self._session._send_bytes(self.id, bytes(view[:size]))
            view = view[size:]

    def send_line(self, text: str) -> None:
        """Send one line of text as one binary frame.

        Args:
            text: The line, without its newline.

        Raises:
            StreamClosed: When the stream ended before it was sent.
            GatewayUnreachable: When the socket is gone.
        """
        self.send_bytes((text + "\n").encode("utf-8"))

    def offer_credit(self, size: int) -> None:
        """Let the hub send this many more bytes.

        Args:
            size: The bytes granted.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        self._session._send({"type": "credit", "stream": self.id, "bytes": int(size)})

    def close(self, code: str = "", params: "dict | None" = None) -> None:
        """End the stream from this side, with its result.

        A stream the hub already ended sends nothing.

        Args:
            code: The refusal; empty when the stream did what it was asked.
            params: The result, or what the code's wording names.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        with self._granted:
            if self._is_closed:
                return
            self._is_closed = True
            self._granted.notify_all()
        self._session._close_stream(self.id, code, dict(params or {}))

    def _grant(self, size: int) -> None:
        with self._granted:
            self._credit += max(0, int(size))
            self._granted.notify_all()

    def _feed(self, item: tuple) -> None:
        self._inbound.put(item)

    def _end(self, code: str = "", params: "dict | None" = None) -> None:
        with self._granted:
            self._is_closed = True
            self._granted.notify_all()
        self._inbound.put(("close", code, dict(params or {})))
