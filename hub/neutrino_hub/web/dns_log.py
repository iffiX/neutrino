"""Reading dnsmasq's query log out of its unit's journal.

dnsmasq logs to stderr and systemd collects it, so one line is one journal
record and ``journalctl --after-cursor`` is what makes following incremental.
A lookup is a query line and the line that answered it: a `forwarded` to a
resolver, a `cached` hit, a `config` answer dnsmasq gave from its own
configuration, or a `reply` carrying what the resolver said. The answer names
where the name was resolved, which tells a lookup that went through the proxy
from one that did not.
"""

import ipaddress
import json
import re
import time
from dataclasses import dataclass
from typing import Callable

from neutrino_hub.modules.xray.constants import XRAY_DNS_LISTEN, XRAY_DNS_PORT
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
from neutrino_hub.utils.subprocess_run import run
from neutrino_hub.web.constants import (
    WEB_DNS_OUTBOUND_CACHED,
    WEB_DNS_OUTBOUND_CONFIG,
    WEB_DNS_OUTBOUND_DIRECT,
    WEB_DNS_OUTBOUND_PROXY,
)
from neutrino_hub.web.models import DnsLogEntry

DNSMASQ_UNIT = SYSTEM_CORE_UNITS["dnsmasq"]
QUERY_LINE = re.compile(
    r"query\[(?P<type>[A-Z0-9]+)\]\s+(?P<domain>\S+)\s+from\s+(?P<client>\S+)"
)
FORWARDED_LINE = re.compile(r"forwarded\s+(?P<domain>\S+)\s+to\s+(?P<server>\S+)")
LOCAL_ANSWER_LINE = re.compile(
    r"(?P<source>cached|config)\s+(?P<domain>\S+)\s+is\s+(?P<value>\S+)"
)
REPLY_LINE = re.compile(r"reply\s+(?P<domain>\S+)\s+is\s+(?P<value>\S+)")
LOCAL_ANSWER_OUTBOUNDS = {
    "cached": WEB_DNS_OUTBOUND_CACHED,
    "config": WEB_DNS_OUTBOUND_CONFIG,
}
RECORD_TYPE_A = "A"
RECORD_TYPE_AAAA = "AAAA"
# A reverse lookup. dnsmasq answers it from `bogus-priv` and its lease table
# and writes no answer line for it at all.
RECORD_TYPE_PTR = "PTR"
# What an answer whose value is not an address still says about the record
# type it answers: `cached example.com is NODATA-IPv6` answers an AAAA.
NODATA_RECORD_TYPES = {"-IPv4": RECORD_TYPE_A, "-IPv6": RECORD_TYPE_AAAA}
# How many journal records one read asks for. The panel draws a few hundred
# queries and dnsmasq writes two or three records per lookup.
JOURNAL_RECORD_LIMIT = 2000
JOURNAL_TIMEOUT_S = 10
# How many queries may wait for their answer line at once. A read that ends
# mid-lookup leaves one or two; this bounds a journal the parser cannot pair
# at all.
PENDING_LIMIT = 64
# How long one may wait. dnsmasq writes a query and its answer together, so a
# query unanswered three polls later has no answer line coming, and a row
# already drawn cannot be corrected.
PENDING_AGE_S = 3.0
# How many names the resolver of their last `forwarded` is kept for, which is
# what a `reply` line answering one of them is attributed to.
FORWARDED_MEMORY_LIMIT = 256


def _log_clock(realtime_us: int) -> str:
    """Word a journal stamp the way a panel row reads it."""
    return time.strftime("%b %d %H:%M:%S", time.localtime(realtime_us / 1_000_000))


def _answered_record_type(value: str) -> str | None:
    """The record type an answer's value names, or None where it names none."""
    for suffix, record_type in NODATA_RECORD_TYPES.items():
        if value.endswith(suffix):
            return record_type
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    return RECORD_TYPE_A if address.version == 4 else RECORD_TYPE_AAAA


@dataclass
class DnsLogOpenQuery:
    """One query read from the journal, answered or still waiting.

    Attributes:
        entry: The row the panel draws. Its ``outbound`` is None until an
            answer line says where the name was resolved.
        record_type: What was asked for, as dnsmasq spells it in
            ``query[...]``.
        realtime_us: When the journal recorded the query, in microseconds
            since the epoch.
    """

    entry: DnsLogEntry
    record_type: str
    realtime_us: int


class DnsLogReader:
    """Reads recent queries out of dnsmasq's journal, each with where it went."""

    def __init__(self, *, clock: Callable[[], float] = time.time):
        """
        Args:
            clock: Reads the wall clock in seconds. A query waiting for its
                answer line is aged against journald's own stamps, which are
                wall clock too.
        """
        self._clock = clock
        self._cursor: str | None = None
        self._pending: list[DnsLogOpenQuery] = []
        self._forwarded_outbounds: dict[str, str] = {}

    def tail(self, *, entry_limit: int = 200) -> list[DnsLogEntry]:
        """Read the most recent queries.

        Args:
            entry_limit: How many entries to return at most.

        Returns:
            Newest first. Empty when the unit has logged nothing yet, which
            is normal before dnsmasq has served its first query.
        """
        # The window is read whole, so anything held by an earlier call is in
        # these records again.
        self._pending = []
        entries = self._drain(self._read_records(after_cursor=None))
        entries.reverse()
        return entries[:entry_limit]

    def follow(self) -> list[DnsLogEntry]:
        """Read only what the unit has logged since the last call.

        Returns:
            New entries oldest first, plus any query held by an earlier call
            that these records answered. A query still unanswered after
            :data:`PENDING_AGE_S` is dropped rather than returned, since the
            panel has no way to answer a row it has already drawn.
        """
        return self._drain(self._read_records(after_cursor=self._cursor))

    def query_count(self) -> int:
        """Count the queries the recent journal holds.

        Returns:
            How many of the window's records are queries. Not how many
            records it has: dnsmasq writes a `forwarded` and a `reply` for
            most lookups and a line for every DHCP lease, all into the same
            journal, so counting records answers several times over.
        """
        return sum(
            1
            for record in self._read_records(after_cursor=None)
            if QUERY_LINE.match(record["MESSAGE"])
        )

    def _drain(self, records: list[dict[str, str]]) -> list[DnsLogEntry]:
        """Pair this read's queries with their answers, oldest first.

        Queries held by the previous call are paired first, since they are
        the older ones. A query this read leaves unanswered is held rather
        than returned: its answer line is usually the next thing dnsmasq
        writes, and an entry sent without one sits on the panel as pending
        for good.

        Args:
            records: The journal records read this call, oldest first.

        Returns:
            The entries that are settled, oldest first.
        """
        open_queries = list(self._pending)
        for record in records:
            message = record["MESSAGE"]
            query = QUERY_LINE.match(message)
            if query:
                open_queries.append(self._open_query(query, record))
                continue
            answer = self._answer(message)
            if answer is not None:
                self._pair(open_queries, answer)
        if records:
            self._cursor = records[-1]["__CURSOR"]
        return self._settle(open_queries)

    def _open_query(self, query: re.Match, record: dict[str, str]) -> DnsLogOpenQuery:
        """Start an entry for a query line, settling a reverse lookup at once."""
        record_type = query.group("type")
        realtime_us = int(record["__REALTIME_TIMESTAMP"])
        is_answered_locally = record_type == RECORD_TYPE_PTR
        return DnsLogOpenQuery(
            entry=DnsLogEntry(
                timestamp=_log_clock(realtime_us),
                domain=query.group("domain"),
                client=query.group("client"),
                outbound=WEB_DNS_OUTBOUND_CONFIG if is_answered_locally else None,
            ),
            record_type=record_type,
            realtime_us=realtime_us,
        )

    def _answer(self, message: str) -> tuple[str, str, str | None] | None:
        """Read an answer line, keeping where a forward went for its `reply`."""
        forwarded = FORWARDED_LINE.match(message)
        if forwarded:
            domain = forwarded.group("domain")
            outbound = self._forwarded_outbound(forwarded.group("server"))
            self._remember_forward(domain, outbound)
            return domain, outbound, None
        local = LOCAL_ANSWER_LINE.match(message)
        if local:
            return (
                local.group("domain"),
                LOCAL_ANSWER_OUTBOUNDS[local.group("source")],
                _answered_record_type(local.group("value")),
            )
        reply = REPLY_LINE.match(message)
        if reply:
            domain = reply.group("domain")
            outbound = self._forwarded_outbounds.get(domain)
            if outbound is not None:
                return domain, outbound, _answered_record_type(reply.group("value"))
        return None

    def _pair(
        self,
        open_queries: list[DnsLogOpenQuery],
        answer: tuple[str, str, str | None],
    ) -> None:
        """Give an answer to the oldest waiting query it can belong to."""
        domain, outbound, record_type = answer
        for open_query in open_queries:
            if open_query.entry.outbound is not None:
                continue
            if open_query.entry.domain != domain:
                continue
            if record_type is not None and open_query.record_type != record_type:
                continue
            open_query.entry.outbound = outbound
            return

    def _settle(self, open_queries: list[DnsLogOpenQuery]) -> list[DnsLogEntry]:
        """Return the answered entries, holding or dropping the rest."""
        now_us = int(self._clock() * 1_000_000)
        age_limit_us = PENDING_AGE_S * 1_000_000
        settled: list[DnsLogEntry] = []
        for index, open_query in enumerate(open_queries):
            if open_query.entry.outbound is not None:
                settled.append(open_query.entry)
                continue
            is_given_up = (
                now_us - open_query.realtime_us > age_limit_us
                or len(open_queries) - index > PENDING_LIMIT
            )
            if not is_given_up:
                # Everything behind a query still waiting waits with it, so
                # entries reach the panel in the order dnsmasq wrote them.
                self._pending = open_queries[index:]
                return settled
        self._pending = []
        return settled

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

    def _remember_forward(self, domain: str, outbound: str) -> None:
        """Keep where a name last went, for a `reply` line that names no server."""
        self._forwarded_outbounds.pop(domain, None)
        self._forwarded_outbounds[domain] = outbound
        while len(self._forwarded_outbounds) > FORWARDED_MEMORY_LIMIT:
            del self._forwarded_outbounds[next(iter(self._forwarded_outbounds))]

    def _read_records(self, *, after_cursor: str | None) -> list[dict[str, str]]:
        """Read the unit's journal, the recent window or only past a cursor."""
        command = ["journalctl", "-u", DNSMASQ_UNIT, "-o", "json", "--no-pager"]
        command += ["-n", str(JOURNAL_RECORD_LIMIT)]
        if after_cursor is not None:
            command.append(f"--after-cursor={after_cursor}")
        result = run(command, is_checked=False, timeout_s=JOURNAL_TIMEOUT_S)
        if not result.is_success:
            return []
        records: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            # A line journald could not read as text arrives as a list of
            # bytes, and one without a stamp cannot be aged.
            is_readable = (
                isinstance(record.get("MESSAGE"), str)
                and isinstance(record.get("__CURSOR"), str)
                and str(record.get("__REALTIME_TIMESTAMP", "")).isdigit()
            )
            if is_readable:
                records.append(record)
        return records
