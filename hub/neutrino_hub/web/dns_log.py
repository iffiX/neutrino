"""Reading the dnsmasq query log for the dashboard's DNS panel.

dnsmasq writes one line per query and per answer. Only the query lines are
interesting here: they carry the name asked for and which LAN client asked.
"""

import re
from pathlib import Path

from neutrino_hub.web.constants import WEB_DNS_LOG_PATH
from neutrino_hub.web.models import DnsLogEntry

QUERY_LINE = re.compile(
    r"^(?P<month>\w{3})\s+(?P<day>\d+)\s+(?P<time>[\d:]+)\s+dnsmasq\[\d+\]:\s+"
    r"query\[(?P<type>[A-Z]+)\]\s+(?P<domain>\S+)\s+from\s+(?P<client>\S+)"
)
TAIL_READ_BYTES = 256 * 1024


class DnsLogReader:
    """Reads recent queries out of the dnsmasq log."""

    def __init__(self, *, log_path: Path | None = None):
        """
        Args:
            log_path: Log file to read; defaults to the configured location.
        """
        self._log_path = log_path or WEB_DNS_LOG_PATH
        self._last_size = 0

    def tail(self, *, entry_limit: int = 200) -> list[DnsLogEntry]:
        """Read the most recent queries.

        Args:
            entry_limit: How many entries to return at most.

        Returns:
            Newest first. Empty when the log does not exist yet, which is
            normal before dnsmasq has served its first query.
        """
        lines = self._read_tail_lines()
        entries = [
            entry
            for entry in (self._parse(line) for line in lines)
            if entry is not None
        ]
        entries.reverse()
        return entries[:entry_limit]

    def follow(self) -> list[DnsLogEntry]:
        """Read only what has been appended since the last call.

        Returns:
            New entries oldest first. A truncated or rotated log resets the
            position and returns nothing that call.
        """
        if not self._log_path.is_file():
            return []
        size = self._log_path.stat().st_size
        if size < self._last_size:
            self._last_size = 0
        if size == self._last_size:
            return []
        with self._log_path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(self._last_size)
            new_text = stream.read()
        self._last_size = size
        entries = [
            entry
            for entry in (self._parse(line) for line in new_text.splitlines())
            if entry is not None
        ]
        return entries

    def query_count(self) -> int:
        """Count the queries currently visible in the log tail.

        Returns:
            How many query lines the tail holds.
        """
        return len(self._read_tail_lines())

    def _read_tail_lines(self) -> list[str]:
        if not self._log_path.is_file():
            return []
        size = self._log_path.stat().st_size
        with self._log_path.open("r", encoding="utf-8", errors="replace") as stream:
            if size > TAIL_READ_BYTES:
                stream.seek(size - TAIL_READ_BYTES)
                stream.readline()
            return stream.read().splitlines()

    def _parse(self, line: str) -> DnsLogEntry | None:
        match = QUERY_LINE.match(line)
        if not match:
            return None
        return DnsLogEntry(
            timestamp=f"{match.group('month')} {match.group('day')} "
            f"{match.group('time')}",
            domain=match.group("domain"),
            client=match.group("client"),
            outbound=None,
        )
