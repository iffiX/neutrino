"""The failed admissions on the agent port, counted over the whole port.

Every way in reaches the one port, and through the relay every peer comes
from loopback, so no count here is keyed by a peer's address.
"""

import collections
import threading
import time

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ADMISSION_FAILURES_MAX,
    CHANNEL_ADMISSION_WINDOW_S,
)


class ChannelPortGuard:
    """Failed admissions on the agent port, and the pause of join they cause."""

    def __init__(
        self,
        *,
        failures_max: int = CHANNEL_ADMISSION_FAILURES_MAX,
        window_s: float = CHANNEL_ADMISSION_WINDOW_S,
        clock=time.monotonic,
    ):
        """
        Args:
            failures_max: Failed admissions within the window that pause
                ``join``.
            window_s: The window failed admissions are counted in.
            clock: The monotonic clock.
        """
        self._failures_max = failures_max
        self._window_s = window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: collections.deque = collections.deque()

    def record_failure(self) -> None:
        """Count one failed admission now."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._failures.append(now)

    def pause_remaining_s(self) -> float:
        """How long ``join`` stays paused.

        Returns:
            Seconds until the oldest failure leaves the window while the
            window holds the cap of failures; 0 when ``join`` is open.
        """
        with self._lock:
            now = self._clock()
            self._prune(now)
            if len(self._failures) < self._failures_max:
                return 0.0
            return max(0.0, self._failures[0] + self._window_s - now)

    def _prune(self, now: float) -> None:
        """Drop the failures older than the window."""
        while self._failures and self._failures[0] <= now - self._window_s:
            self._failures.popleft()
