"""The panel's invalidation channel.

Nothing in the panel polls. Whatever moves on the box — a machine's channel
opening, a report saying something new, an order changing state, a write
under ``config/`` — publishes a coarse event here, and every open panel is
told. An event names what changed and which one; the page that draws it asks for
it again over HTTP. The exception is a reading a page redraws several times
a second, which rides the event as ``data`` rather than costing a request.

Publishing is safe from any thread; delivery happens on each subscriber's
own loop, which is what lets the agent channel's server and the panel's
share one bus.
"""

import asyncio
import threading
import time
from datetime import datetime, timezone

from neutrino_hub.web.constants import (
    WEB_EVENT_COALESCE_WINDOW_S,
    WEB_EVENT_QUEUE_LIMIT,
)


def event_frame(event_type: str, key: str = "", data: "dict | None" = None) -> dict:
    """One event as the socket sends it.

    Args:
        event_type: One of the ``WEB_EVENT_*`` types.
        key: The one thing the event is about; empty where the type names
            the whole of it.
        data: The reading the event carries, for the types that carry one.

    Returns:
        ``{"type", "key", "at"}``, with ``data`` beside them where the event
        carries a reading.
    """
    frame = {
        "type": event_type,
        "key": key,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if data is not None:
        frame["data"] = data
    return frame


def _offer(queue: asyncio.Queue, event: dict) -> None:
    """Put one event on a queue, dropping the oldest when it is full."""
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass


class PanelEventBus:
    """Fans invalidation events out to every open panel socket."""

    def __init__(self, *, queue_limit: int = WEB_EVENT_QUEUE_LIMIT):
        """
        Args:
            queue_limit: How many events one subscriber may fall behind by.
        """
        self._queue_limit = queue_limit
        self._lock = threading.Lock()
        self._subscribers: list[tuple] = []
        self._published_at: dict[tuple, float] = {}

    def publish(
        self, event_type: str, key: str = "", data: "dict | None" = None
    ) -> None:
        """Tell every subscriber that one thing moved.

        Args:
            event_type: One of the ``WEB_EVENT_*`` types.
            key: The one thing the event is about, or empty.
            data: The reading to carry, for the types that carry one. An
                event carrying one is never coalesced: a repeated hint says
                nothing new, a repeated reading is the new value.
        """
        if data is None and not self._claim(event_type, key):
            return
        event = event_frame(event_type, key, data)
        with self._lock:
            subscribers = list(self._subscribers)
        for queue, loop in subscribers:
            if loop.is_closed():
                continue
            try:
                loop.call_soon_threadsafe(_offer, queue, event)
            except RuntimeError:
                continue

    def subscribe(self) -> asyncio.Queue:
        """Take a queue of every event from now on.

        Call from the loop the queue is read on.

        Returns:
            The bounded queue, to be handed back to :meth:`unsubscribe`.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_limit)
        with self._lock:
            self._subscribers.append((queue, asyncio.get_running_loop()))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Stop delivering to one queue.

        Args:
            queue: What :meth:`subscribe` returned.
        """
        with self._lock:
            self._subscribers = [
                entry for entry in self._subscribers if entry[0] is not queue
            ]

    def _claim(self, event_type: str, key: str) -> bool:
        """Whether this event is outside the coalescing window."""
        now = time.monotonic()
        pair = (event_type, key)
        with self._lock:
            published_at = self._published_at.get(pair)
            if (
                published_at is not None
                and now - published_at < WEB_EVENT_COALESCE_WINDOW_S
            ):
                return False
            self._published_at = {
                seen: at
                for seen, at in self._published_at.items()
                if now - at < WEB_EVENT_COALESCE_WINDOW_S
            }
            self._published_at[pair] = now
        return True
