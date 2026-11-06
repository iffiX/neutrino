"""Reading xray's log: the lines that go on to the journal, and the failed dials.

xray writes a failed dial only at log level info, beside four or five info
lines for every connection. The run filter drops the info lines and keeps a
failed dial, at most once in ``XRAY_FAILED_DIAL_GAP_S`` for each address, and
the panel reads the failed dials back.

Pure: reads lines handed to it and keeps the time each address was last kept.
"""

from neutrino_hub.modules.xray.constants import (
    XRAY_FAILED_DIAL_GAP_S,
    XRAY_FAILED_DIAL_PATTERN,
    XRAY_LOG_DROPPED_LEVEL,
)


def failed_dial(line: str) -> "tuple[str, int] | None":
    """The address and the port of a failed dial in one line of xray's log.

    Args:
        line: One line as xray writes it.

    Returns:
        ``(host, port)``, an IPv6 address without its brackets; None for a
        line that is no failed dial.
    """
    match = XRAY_FAILED_DIAL_PATTERN.search(line)
    if match is None:
        return None
    return match.group(1).strip("[]"), int(match.group(2))


class XrayLogFilter:
    """Decides which lines of xray's log the run filter writes on."""

    def __init__(self):
        # When a failed dial of each address was last kept, by ``(host, port)``.
        self._kept_at: dict = {}

    def is_kept(self, line: str, *, now: float) -> bool:
        """Whether one line of xray's log goes on to the journal.

        Args:
            line: One line as xray writes it.
            now: The moment it was read, in seconds of a monotonic clock.

        Returns:
            True for a line of no dropped level, and for a failed dial when its
            address was not kept in the last ``XRAY_FAILED_DIAL_GAP_S``.
        """
        address = failed_dial(line)
        if address is None:
            return XRAY_LOG_DROPPED_LEVEL.match(line) is None
        kept_at = self._kept_at.get(address)
        if kept_at is not None and now - kept_at < XRAY_FAILED_DIAL_GAP_S:
            return False
        self._kept_at[address] = now
        return True
