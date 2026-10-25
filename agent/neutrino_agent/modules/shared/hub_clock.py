"""The hub's time on this machine, which every token check reads.

The hub mints a token with an expiry by its own clock, and this machine's
clock may be hours off. Each ``welcome`` names the hub's ``time``: the offset
between it and this machine's clock is kept, and the hub's time is this
machine's clock plus that offset. Each reading also compares how far this
machine's clock moved with how far the monotonic clock moved since the last
reading; a difference of :data:`AGENT_HUB_CLOCK_JUMP_S` or more is this
machine's clock being set, and the offset takes it up, so the hub's time goes
on unchanged.

Not pure: reads the clocks.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import threading
import time

from neutrino_agent.constants import AGENT_HUB_CLOCK_JUMP_S

_HUB_CLOCK: "HubClock | None" = None
_HUB_CLOCK_LOCK = threading.Lock()


def hub_clock() -> "HubClock":
    """The one hub clock of this process, made on first use.

    Returns:
        The clock.
    """
    global _HUB_CLOCK
    with _HUB_CLOCK_LOCK:
        if _HUB_CLOCK is None:
            _HUB_CLOCK = HubClock()
        return _HUB_CLOCK


def hub_time() -> float:
    """The hub's time now, by this process's hub clock.

    Returns:
        Seconds since the epoch.
    """
    return hub_clock().now()


def welcome_time(welcome: dict) -> "float | None":
    """The hub's clock a welcome names.

    Args:
        welcome: The hub's identity card.

    Returns:
        Its ``time`` in seconds since the epoch; None when it names none, or
        names something other than a positive number.
    """
    value = welcome.get("time")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not 0 < value < float("inf"):
        return None
    return float(value)


class HubClock:
    """The hub's time: this machine's clock plus the offset the last welcome gave."""

    def __init__(self, *, clock=time.time, monotonic=time.monotonic):
        """
        Args:
            clock: This machine's clock, in seconds since the epoch.
            monotonic: Seconds that only go forward.
        """
        self._clock = clock
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._offset = 0.0
        self._clock_at = clock()
        self._monotonic_at = monotonic()

    @property
    def offset(self) -> float:
        """How many seconds the hub's clock is ahead of this machine's."""
        with self._lock:
            return self._offset

    def take(self, hub_time: "float | None") -> None:
        """Keep the offset a welcome's ``time`` gives.

        Args:
            hub_time: The hub's clock as it sent the welcome, in seconds
                since the epoch; None, from a hub that names none, makes
                the offset zero.
        """
        with self._lock:
            now = self._clock()
            self._offset = 0.0 if hub_time is None else float(hub_time) - now
            self._clock_at = now
            self._monotonic_at = self._monotonic()

    def now(self) -> float:
        """The hub's time now, with any setting of this machine's clock since
        the last reading taken up by the offset.

        Returns:
            Seconds since the epoch, by the hub's clock.
        """
        with self._lock:
            now = self._clock()
            monotonic = self._monotonic()
            jump = (now - self._clock_at) - (monotonic - self._monotonic_at)
            if abs(jump) >= AGENT_HUB_CLOCK_JUMP_S:
                self._offset -= jump
            self._clock_at = now
            self._monotonic_at = monotonic
            return now + self._offset
