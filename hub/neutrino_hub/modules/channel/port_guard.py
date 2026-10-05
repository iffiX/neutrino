"""The agent port's limits, counted over the whole port.

Every way in reaches the one port, and through the relay every peer comes
from loopback, so no count here is keyed by a peer's address: a connection
is named by its address and port only to find it again.

Bookkeeping: the caller hands in each connection's ``close`` and the
clock, and closes what this says to close. A socket the port closes on its
own is logged, one line of each kind a minute at most.
"""

import collections
import logging
import threading
import time
from typing import Callable

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ADMISSION_FAILURES_MAX,
    CHANNEL_ADMISSION_WINDOW_S,
    CHANNEL_CLOSE_FIRST_BYTE,
    CHANNEL_CLOSE_HANDSHAKE,
    CHANNEL_CLOSE_LOG_INTERVAL_S,
    CHANNEL_CLOSE_ROOM,
    CHANNEL_SOCKETS_MAX,
    CHANNEL_UNADMITTED_MAX,
)

LOGGER = logging.getLogger(__name__)
# What each kind of close says; the room line is told how many were held,
# the two timeouts how long the socket had.
CLOSE_LINES = {
    CHANNEL_CLOSE_ROOM: "agent port full: closed {address} to make room, {count} sockets held",
    CHANNEL_CLOSE_FIRST_BYTE: "agent port: closed {address}, no byte within {count:g} s",
    CHANNEL_CLOSE_HANDSHAKE: "agent port: closed {address}, TLS handshake not done within {count:g} s",
}


class ChannelPortGuard:
    """Open handshakes, admitted sockets and failed admissions on the agent port."""

    def __init__(
        self,
        *,
        unadmitted_max: int = CHANNEL_UNADMITTED_MAX,
        sockets_max: int = CHANNEL_SOCKETS_MAX,
        failures_max: int = CHANNEL_ADMISSION_FAILURES_MAX,
        window_s: float = CHANNEL_ADMISSION_WINDOW_S,
        log_interval_s: float = CHANNEL_CLOSE_LOG_INTERVAL_S,
        clock=time.monotonic,
    ):
        """
        Args:
            unadmitted_max: Connections that have not passed ``hello``.
            sockets_max: Channel sockets past ``hello``.
            failures_max: Failed admissions within the window that pause
                ``join``.
            window_s: The window failed admissions are counted in.
            log_interval_s: The least time between two lines of one kind
                of close.
            clock: The monotonic clock.
        """
        self._unadmitted_max = unadmitted_max
        self._sockets_max = sockets_max
        self._failures_max = failures_max
        self._window_s = window_s
        self._log_interval_s = log_interval_s
        self._clock = clock
        self._lock = threading.Lock()
        # Connection key to its close, its check and whether its TLS
        # handshake is done, oldest first.
        self._unadmitted: collections.OrderedDict = collections.OrderedDict()
        self._admitted: set = set()
        self._failures: collections.deque = collections.deque()
        # Kind of close to when its last line was written and how many of
        # that kind were closed since without a line.
        self._close_lines: dict = {}

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
            held_count = len(self._unadmitted)
            while len(self._unadmitted) >= self._unadmitted_max:
                bare = [k for k, held in self._unadmitted.items() if not held[2]]
                victim = bare[0] if bare else next(iter(self._unadmitted))
                evicted.append((victim, self._unadmitted.pop(victim)[0]))
            self._unadmitted[key] = [close, is_closed, False]
        for victim, victim_close in evicted:
            victim_close()
            self._log_close(CHANNEL_CLOSE_ROOM, victim, held_count)

    def timed_out(self, key, kind: str, limit_s: float) -> None:
        """Forget a connection the port closed for its first byte or its TLS
        handshake taking too long, and log it.

        Args:
            key: The connection's peer address and port.
            kind: ``first_byte`` or ``handshake``.
            limit_s: The time it had.
        """
        self.closed(key)
        self._log_close(kind, key, limit_s)

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

    def _log_close(self, kind: str, key, count) -> None:
        """Write one close's line, unless a line of its kind was written
        within the interval; the next line says how many were closed since."""
        with self._lock:
            now = self._clock()
            last_at, unlogged = self._close_lines.get(kind, (None, 0))
            if last_at is not None and now - last_at < self._log_interval_s:
                self._close_lines[kind] = (last_at, unlogged + 1)
                return
            self._close_lines[kind] = (now, 0)
        line = CLOSE_LINES[kind].format(address=key[0], count=count)
        if unlogged:
            line += f"; {unlogged} more closed since the last such line"
        LOGGER.warning(line)

    def _prune(self, now: float) -> None:
        """Drop the failures older than the window."""
        while self._failures and self._failures[0] <= now - self._window_s:
            self._failures.popleft()
