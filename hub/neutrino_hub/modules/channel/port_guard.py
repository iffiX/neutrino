"""The agent port's limits, counted over the whole port.

Every way in reaches the one port, and through the relay every peer comes
from loopback, so no count here is keyed by a peer's address: a connection
is named by its address and port only to find it again.

Pure bookkeeping: the caller hands in each connection's ``close`` and the
clock, and closes what this says to close.
"""

import collections
import threading
import time
from typing import Callable

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ADMISSION_FAILURES_MAX,
    CHANNEL_ADMISSION_WINDOW_S,
    CHANNEL_SOCKETS_MAX,
    CHANNEL_UNADMITTED_MAX,
)


class ChannelPortGuard:
    """Open handshakes, admitted sockets and failed admissions on the agent port."""

    def __init__(
        self,
        *,
        unadmitted_max: int = CHANNEL_UNADMITTED_MAX,
        sockets_max: int = CHANNEL_SOCKETS_MAX,
        failures_max: int = CHANNEL_ADMISSION_FAILURES_MAX,
        window_s: float = CHANNEL_ADMISSION_WINDOW_S,
        clock=time.monotonic,
    ):
        """
        Args:
            unadmitted_max: Connections that have not passed ``hello``.
            sockets_max: Channel sockets past ``hello``.
            failures_max: Failed admissions within the window that pause
                ``join``.
            window_s: The window failed admissions are counted in.
            clock: The monotonic clock.
        """
        self._unadmitted_max = unadmitted_max
        self._sockets_max = sockets_max
        self._failures_max = failures_max
        self._window_s = window_s
        self._clock = clock
        self._lock = threading.Lock()
        # Connection key to its close, its check and whether its TLS
        # handshake is done, oldest first.
        self._unadmitted: collections.OrderedDict = collections.OrderedDict()
        self._admitted: set = set()
        self._failures: collections.deque = collections.deque()

    @property
    def sockets_max(self) -> int:
        """The cap on admitted channel sockets."""
        return self._sockets_max

    def accepted(self, key, close: Callable[[], None], is_closed: Callable[[], bool]):
        """Count a new connection, closing one to make room at the cap: the
        oldest that has not finished TLS, else the oldest of all.

        Args:
            key: The connection's peer address and port.
            close: Ends the connection at once.
            is_closed: Whether the connection has already ended.
        """
        with self._lock:
            for known in [k for k, held in self._unadmitted.items() if held[1]()]:
                del self._unadmitted[known]
            evicted = []
            while len(self._unadmitted) >= self._unadmitted_max:
                bare = [k for k, held in self._unadmitted.items() if not held[2]]
                victim = bare[0] if bare else next(iter(self._unadmitted))
                evicted.append(self._unadmitted.pop(victim)[0])
            self._unadmitted[key] = [close, is_closed, False]
        for victim_close in evicted:
            victim_close()

    def handshaken(self, key) -> None:
        """Mark a connection whose TLS handshake is done.

        Args:
            key: The connection's peer address and port.
        """
        with self._lock:
            held = self._unadmitted.get(key)
            if held is not None:
                held[2] = True

    def closed(self, key) -> None:
        """Forget a connection that ended before its ``hello`` passed.

        Args:
            key: The connection's peer address and port.
        """
        with self._lock:
            self._unadmitted.pop(key, None)

    def expire(self, key, close: Callable[[], None]) -> bool:
        """Close a connection whose admission ran out of time.

        Args:
            key: The connection's peer address and port.
            close: The close it was counted with, so a later connection
                from the same address and port is left alone.

        Returns:
            True when it was still waiting and is closed now.
        """
        with self._lock:
            entry = self._unadmitted.get(key)
            if entry is None or entry[0] != close:
                return False
            del self._unadmitted[key]
        if entry[1]():
            return False
        close()
        return True

    def admit(self, key) -> "object | None":
        """Take a socket whose ``hello`` passed into the admitted count.

        Args:
            key: The connection's peer address and port.

        Returns:
            The admission, handed back to :meth:`release` when the socket
            ends; None when the port already holds its cap of admitted
            sockets.
        """
        with self._lock:
            if len(self._admitted) >= self._sockets_max:
                return None
            self._unadmitted.pop(key, None)
            admission = object()
            self._admitted.add(admission)
            return admission

    def release(self, admission) -> None:
        """Forget an admitted socket that ended.

        Args:
            admission: What :meth:`admit` returned for it.
        """
        with self._lock:
            self._admitted.discard(admission)

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

    @property
    def unadmitted_count(self) -> int:
        """Connections counted as not yet past ``hello``."""
        with self._lock:
            return len(self._unadmitted)

    @property
    def admitted_count(self) -> int:
        """Sockets counted as past ``hello``."""
        with self._lock:
            return len(self._admitted)

    def _prune(self, now: float) -> None:
        """Drop the failures older than the window."""
        while self._failures and self._failures[0] <= now - self._window_s:
            self._failures.popleft()
