"""Reading the dnsmasq query log for the dashboard's DNS panel.

dnsmasq writes a query line and, next to it, the line that answered it: a
`forwarded` to a resolver, a `cached` hit, or a `config` answer it gave from
its own configuration. The query names what was asked and who asked; the
answer beside it names where the name was resolved, which is what tells a
lookup that went through the proxy from one that did not.
"""

import re
from pathlib import Path

from neutrino_hub.modules.xray.constants import XRAY_DNS_LISTEN, XRAY_DNS_PORT
from neutrino_hub.web.constants import (
    WEB_DNS_LOG_PATH,
    WEB_DNS_OUTBOUND_CACHED,
    WEB_DNS_OUTBOUND_CONFIG,
    WEB_DNS_OUTBOUND_DIRECT,
    WEB_DNS_OUTBOUND_PROXY,
)
from neutrino_hub.web.models import DnsLogEntry

LINE_PREFIX = (
    r"^(?P<month>\w{3})\s+(?P<day>\d+)\s+(?P<time>[\d:]+)\s+dnsmasq\[\d+\]:\s+"
)
QUERY_LINE = re.compile(
    LINE_PREFIX
    + r"query\[(?P<type>[A-Z]+)\]\s+(?P<domain>\S+)\s+from\s+(?P<client>\S+)"
)
FORWARDED_LINE = re.compile(
    LINE_PREFIX + r"forwarded\s+(?P<domain>\S+)\s+to\s+(?P<server>\S+)"
)
LOCAL_ANSWER_LINE = re.compile(
    LINE_PREFIX + r"(?P<source>cached|config)\s+(?P<domain>\S+)\s+is\s"
)
LOCAL_ANSWER_OUTBOUNDS = {
    "cached": WEB_DNS_OUTBOUND_CACHED,
    "config": WEB_DNS_OUTBOUND_CONFIG,
}
TAIL_READ_BYTES = 256 * 1024
# How many queries may wait for their answer line at once. A read that ends
# mid-lookup leaves one or two; this bounds a log the parser cannot pair at all.
PENDING_LIMIT = 64


def _held_from(entries: list[DnsLogEntry], carried_count: int) -> int:
    """Where the settled entries end and the held ones begin.

    Args:
        entries: Every open entry, oldest first.
        carried_count: How many at the front were held by the previous call.
            Those are settled whether they were answered or not.

    Returns:
        The index the held set starts at. Everything from the first unanswered
        query of this call onwards is held with it, so entries reach the panel
        in the order dnsmasq wrote them, and the held set never grows past
        :data:`PENDING_LIMIT`.
    """
    held_from = len(entries)
    for index in range(carried_count, len(entries)):
        if entries[index].outbound is None:
            held_from = index
            break
    return max(held_from, len(entries) - PENDING_LIMIT)


class DnsLogReader:
    """Reads recent queries out of the dnsmasq log, each with where it went."""

    def __init__(self, *, log_path: Path | None = None):
        """
        Args:
            log_path: Log file to read; defaults to the configured location.
        """
        self._log_path = log_path or WEB_DNS_LOG_PATH
        self._last_size = 0
        self._pending: list[DnsLogEntry] = []

    def tail(self, *, entry_limit: int = 200) -> list[DnsLogEntry]:
        """Read the most recent queries.

        Args:
            entry_limit: How many entries to return at most.

        Returns:
            Newest first. Empty when the log does not exist yet, which is
            normal before dnsmasq has served its first query.
        """
        # The backlog is read whole, so anything held from an earlier read is
        # in these lines again.
        self._pending = []
        entries = self._drain(self._read_tail_lines())
        # Where the tail ends is where following starts. Without this the
        # first `follow` after a `tail` re-reads the file from the beginning
        # and sends the whole backlog a second time, as new arrivals.
        self._last_size = self._size()
        entries.reverse()
        return entries[:entry_limit]

    def follow(self) -> list[DnsLogEntry]:
        """Read only what has been appended since the last call.

        Returns:
            New entries oldest first, plus any query held by the previous call
            that this one could not pair. A truncated or rotated log resets the
            position and returns nothing new that call.
        """
        if not self._log_path.is_file():
            return self._flush_pending()
        size = self._size()
        if size < self._last_size:
            # Rotated or truncated. Start from the new end rather than from
            # the beginning, which would replay the whole file as arrivals.
            self._last_size = size
            return self._flush_pending()
        if size == self._last_size:
            return self._flush_pending()
        with self._log_path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(self._last_size)
            new_text = stream.read()
        self._last_size = size
        return self._drain(new_text.splitlines())

    def query_count(self) -> int:
        """Count the queries the log tail holds.

        Returns:
            How many of the tail's lines are queries. Not how many lines it
            has: dnsmasq writes a `forwarded` and a `reply` for most lookups
            and a `dnsmasq-dhcp` line for every lease, all into this same
            file, so counting lines answers several times over.
        """
        return sum(1 for line in self._read_tail_lines() if QUERY_LINE.match(line))

    def _drain(self, lines: list[str]) -> list[DnsLogEntry]:
        """Pair this chunk's queries with their answers, oldest first.

        Queries held by the previous call are paired first, since they are the
        older ones, and are returned whether this chunk answered them or not.
        A query this chunk leaves unanswered is held instead of returned: its
        answer line is usually the next thing dnsmasq writes, and an entry sent
        without it would sit on the dashboard as pending for good.

        Args:
            lines: The log lines read this call.

        Returns:
            The entries that are settled, oldest first.
        """
        entries = list(self._pending)
        carried_count = len(entries)
        for line in lines:
            query = QUERY_LINE.match(line)
            if query:
                entries.append(
                    DnsLogEntry(
                        timestamp=f"{query.group('month')} {query.group('day')} "
                        f"{query.group('time')}",
                        domain=query.group("domain"),
                        client=query.group("client"),
                        outbound=None,
                    )
                )
                continue
            answer = self._answer(line)
            if answer is None:
                continue
            domain, outbound = answer
            for entry in entries:
                if entry.domain == domain and entry.outbound is None:
                    entry.outbound = outbound
                    break
        held_from = _held_from(entries, carried_count)
        self._pending = entries[held_from:]
        return entries[:held_from]

    def _flush_pending(self) -> list[DnsLogEntry]:
        """Give up on the held queries and return them unanswered."""
        flushed = self._pending
        self._pending = []
        return flushed

    def _answer(self, line: str) -> tuple[str, str] | None:
        """Read an answer line.

        Args:
            line: One log line.

        Returns:
            The domain answered and where it was resolved, or None when the
            line answers nothing — a `reply`, a lease, anything else dnsmasq
            shares this file with.
        """
        forwarded = FORWARDED_LINE.match(line)
        if forwarded:
            return (
                forwarded.group("domain"),
                self._forwarded_outbound(forwarded.group("server")),
            )
        local = LOCAL_ANSWER_LINE.match(line)
        if local:
            return local.group("domain"), LOCAL_ANSWER_OUTBOUNDS[local.group("source")]
        return None

    def _forwarded_outbound(self, server: str) -> str:
        """Tell a forward to the proxy's resolver from any other.

        Args:
            server: The resolver dnsmasq named, as ``address`` or
                ``address#port``.

        Returns:
            ``proxy`` for xray's DNS inbound, which is the one resolver the
            router configures on loopback, ``direct`` for every other.
        """
        address, _, port = server.partition("#")
        # Older dnsmasq builds log the resolver without its port.
        is_proxy_resolver = address == XRAY_DNS_LISTEN and port in (
            "",
            str(XRAY_DNS_PORT),
        )
        return WEB_DNS_OUTBOUND_PROXY if is_proxy_resolver else WEB_DNS_OUTBOUND_DIRECT

    def _size(self) -> int:
        return self._log_path.stat().st_size if self._log_path.is_file() else 0

    def _read_tail_lines(self) -> list[str]:
        if not self._log_path.is_file():
            return []
        size = self._log_path.stat().st_size
        with self._log_path.open("r", encoding="utf-8", errors="replace") as stream:
            if size > TAIL_READ_BYTES:
                stream.seek(size - TAIL_READ_BYTES)
                stream.readline()
            return stream.read().splitlines()
