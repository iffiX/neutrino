"""The Dashboard's traffic history, counted by the hub from the interface counters.

Each reading adds every interface's difference from the reading before to its
hour, day and month, in the machine's local time; loopback is left out, and a
counter that went down was reset and adds nothing. The totals, the last
counters and the boot time are written to ``traffic_history.json``, and a
start in the same boot counts on from the saved counters.
"""

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from neutrino_hub.modules.router.constants import (
    ROUTER_TRAFFIC_BOOT_TIME_TOLERANCE_S,
    ROUTER_TRAFFIC_DAYS_KEPT_MONTHS,
    ROUTER_TRAFFIC_HISTORY_PATH,
    ROUTER_TRAFFIC_HOURS_KEPT_DAYS,
    ROUTER_TRAFFIC_LOOPBACK_NAMES,
    ROUTER_TRAFFIC_MONTHS_KEPT_YEARS,
    ROUTER_TRAFFIC_READ_INTERVAL_S,
    ROUTER_TRAFFIC_WRITE_INTERVAL_S,
)
from neutrino_hub.system.interface_traffic import all_interface_counters
from neutrino_hub.utils.json_file import write_generated

LOGGER = logging.getLogger(__name__)

# Each period's key in the file, and the label its buckets are kept under.
TRAFFIC_HOURS = "hours"
TRAFFIC_DAYS = "days"
TRAFFIC_MONTHS = "months"
TRAFFIC_LABEL_FORMATS = {
    TRAFFIC_HOURS: "%Y-%m-%d %H:00",
    TRAFFIC_DAYS: "%Y-%m-%d",
    TRAFFIC_MONTHS: "%Y-%m",
}
TRAFFIC_FILE_MODE = 0o644


def _grown(current: int, previous: int) -> int:
    """How far a counter moved; nothing when it went down, which is a reset."""
    return current - previous if current >= previous else 0


def _month_label(moment: datetime, month_count: int) -> str:
    """The ``YYYY-MM`` label of the month ``month_count`` months before ``moment``'s."""
    year, month_index = divmod(moment.year * 12 + moment.month - 1 - month_count, 12)
    return f"{year:04d}-{month_index + 1:02d}"


def _read_pair(stored) -> "tuple[int, int] | None":
    """A ``[received, sent]`` pair out of the file, None when it is not one."""
    if not isinstance(stored, list) or len(stored) != 2:
        return None
    if not all(type(value) is int and value >= 0 for value in stored):
        return None
    return stored[0], stored[1]


def _read_counters(stored) -> dict[str, tuple[int, int]]:
    """The saved last counters, the unreadable entries dropped."""
    if not isinstance(stored, dict):
        return {}
    counters = {}
    for name, entry in stored.items():
        pair = _read_pair(entry)
        if isinstance(name, str) and pair is not None:
            counters[name] = pair
    return counters


def _read_totals(stored) -> dict[str, dict[str, dict[str, list[int]]]]:
    """The saved totals, the unreadable interfaces, periods and buckets dropped."""
    if not isinstance(stored, dict):
        return {}
    totals = {}
    for name, periods in stored.items():
        if not isinstance(name, str) or not isinstance(periods, dict):
            continue
        kept = {}
        for period in TRAFFIC_LABEL_FORMATS:
            buckets = periods.get(period)
            if not isinstance(buckets, dict):
                continue
            for label, entry in buckets.items():
                pair = _read_pair(entry)
                if isinstance(label, str) and pair is not None:
                    kept.setdefault(period, {})[label] = list(pair)
        if kept:
            totals[name] = kept
    return totals


def _read_seen(stored, names, moment: datetime) -> dict[str, datetime]:
    """When each of ``names`` was last read, or ``moment`` where the file has none."""
    seen = {}
    for name in names:
        try:
            seen[name] = datetime.fromisoformat(stored[name]).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError):
            seen[name] = moment
    return seen


@dataclass
class RouterTrafficTotal:
    """Traffic totals of one interface for one hour, day or month.

    Attributes:
        label: The period in local time: ``2026-10-15 14:00``, ``2026-10-15``
            or ``2026-10``.
        received_bytes: Bytes received in it.
        sent_bytes: Bytes sent in it.
    """

    label: str
    received_bytes: int
    sent_bytes: int


class RouterTrafficHistory:
    """Counts every interface's traffic by hour, day and month, kept in one file."""

    def __init__(
        self,
        *,
        path: Path | None = None,
        interval_s: float = ROUTER_TRAFFIC_READ_INTERVAL_S,
        drawn_interface: Callable[[], str] | None = None,
    ):
        """
        Args:
            path: The history file; None is ``traffic_history.json`` under the
                state root.
            interval_s: Seconds between two readings.
            drawn_interface: Called with nothing, returns the interface the
                history card draws, which a write never drops; None protects
                no interface.
        """
        self._path = path or ROUTER_TRAFFIC_HISTORY_PATH
        self._interval_s = interval_s
        self._drawn_interface = drawn_interface
        self._lock = threading.Lock()
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None
        # Interface name to period to label to ``[received, sent]``.
        self._totals: dict[str, dict[str, dict[str, list[int]]]] = {}
        # The reading the next one is measured from, interface name to
        # ``(received, sent)``.
        self._counters: dict[str, tuple[int, int]] = {}
        # When each interface was last in a reading.
        self._seen: dict[str, datetime] = {}
        self._boot_time = 0.0
        # None until the file is read, and nothing is written before that.
        self._written_at: datetime | None = None

    def start(self) -> None:
        """Read the file and count on a daemon thread; a second start is a no-op."""
        if self._thread is not None:
            return
        self.load()
        self._thread = threading.Thread(
            target=self._loop, name="router_traffic_history", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop counting and write the file, when counting was started."""
        if self._thread is None:
            return
        self._is_stopped.set()
        self._thread.join(timeout=self._interval_s)
        try:
            self.save()
        except OSError as error:
            LOGGER.warning("the traffic history was not written: %s", error)

    def load(self, *, now: datetime | None = None) -> None:
        """Read the file, tolerant of anything on disk.

        The saved counters are what the first reading is measured from while
        the boot time is the saved one, and are dropped after a reboot. A
        file that is missing, unreadable or not shaped like the history reads
        as empty.

        Args:
            now: When the file is read, which the next write is due 5 minutes
                after; None is the real clock.
        """
        moment = now or datetime.now()
        boot_time = psutil.boot_time()
        stored = self._read()
        saved_boot_time = stored.get("boot_time")
        is_same_boot = isinstance(saved_boot_time, (int, float)) and (
            abs(saved_boot_time - boot_time) <= ROUTER_TRAFFIC_BOOT_TIME_TOLERANCE_S
        )
        with self._lock:
            self._totals = _read_totals(stored.get("interfaces"))
            self._seen = _read_seen(stored.get("seen"), self._totals, moment)
            self._counters = (
                _read_counters(stored.get("counters")) if is_same_boot else {}
            )
            self._boot_time = boot_time
            self._written_at = moment

    def count(self, *, now: datetime | None = None) -> None:
        """Read every interface's counters once and add each difference.

        An interface with no reading before this one adds nothing. The file
        is written when 5 minutes have passed since the last write, or the
        clock went back past it.

        Args:
            now: The reading's moment in local time; None is the real clock.

        Raises:
            OSError: When the file is due and cannot be written.
        """
        moment = now or datetime.now()
        readings = {
            name: counters
            for name, counters in all_interface_counters().items()
            if name not in ROUTER_TRAFFIC_LOOPBACK_NAMES
        }
        with self._lock:
            for name, (received, sent) in readings.items():
                previous = self._counters.get(name)
                if previous is not None:
                    self._add(
                        name,
                        _grown(received, previous[0]),
                        _grown(sent, previous[1]),
                        moment,
                    )
            self._counters = readings
            self._seen.update(dict.fromkeys(readings, moment))
            written_at = self._written_at
        if written_at is None:
            return
        elapsed = moment - written_at
        if elapsed < timedelta(0) or elapsed >= timedelta(
            seconds=ROUTER_TRAFFIC_WRITE_INTERVAL_S
        ):
            self.save(now=moment)

    def save(self, *, now: datetime | None = None) -> None:
        """Drop what is past its keeping time and write the file.

        An interface no reading has held for 8 days goes with all its totals,
        unless it is the one the card draws; while that cannot be read, no
        interface goes.

        Args:
            now: The moment each keeping time reaches back from; None is the
                real clock.

        Raises:
            OSError: When the file cannot be written.
        """
        moment = now or datetime.now()
        drawn = self._drawn_name()
        with self._lock:
            self._trim(moment, drawn)
            data = {
                "boot_time": self._boot_time,
                "counters": {
                    name: list(counters) for name, counters in self._counters.items()
                },
                "interfaces": self._totals,
                "seen": {
                    name: self._seen[name].isoformat(timespec="seconds")
                    for name in self._totals
                },
            }
            write_generated(
                self._path,
                json.dumps(data, sort_keys=True) + "\n",
                mode=TRAFFIC_FILE_MODE,
            )
            self._written_at = moment

    def hourly(
        self, interface: str, *, hour_count: int = 24, now: datetime | None = None
    ) -> list[RouterTrafficTotal]:
        """One interface's hours.

        Args:
            interface: The interface's name.
            hour_count: How many hours back from ``now``'s, which counts as
                the last.
            now: The moment the hours end at; None is the real clock.

        Returns:
            The hours that counted any traffic, oldest first.
        """
        moment = now or datetime.now()
        floor = moment - timedelta(hours=hour_count)
        return self._totals_after(
            interface,
            TRAFFIC_HOURS,
            floor.strftime(TRAFFIC_LABEL_FORMATS[TRAFFIC_HOURS]),
        )

    def daily(
        self, interface: str, *, day_count: int = 30, now: datetime | None = None
    ) -> list[RouterTrafficTotal]:
        """One interface's days.

        Args:
            interface: The interface's name.
            day_count: How many days back from ``now``'s, which counts as the
                last; 1 is today alone.
            now: The moment the days end at; None is the real clock.

        Returns:
            The days that counted any traffic, oldest first.
        """
        moment = now or datetime.now()
        floor = moment - timedelta(days=day_count)
        return self._totals_after(
            interface, TRAFFIC_DAYS, floor.strftime(TRAFFIC_LABEL_FORMATS[TRAFFIC_DAYS])
        )

    def monthly(
        self, interface: str, *, month_count: int = 12, now: datetime | None = None
    ) -> list[RouterTrafficTotal]:
        """One interface's months.

        Args:
            interface: The interface's name.
            month_count: How many months back from ``now``'s, which counts as
                the last.
            now: The moment the months end at; None is the real clock.

        Returns:
            The months that counted any traffic, oldest first.
        """
        moment = now or datetime.now()
        return self._totals_after(
            interface, TRAFFIC_MONTHS, _month_label(moment, month_count)
        )

    def _loop(self) -> None:
        while not self._is_stopped.wait(self._interval_s):
            try:
                self.count()
            except Exception:  # noqa: BLE001 - the count must outlive one reading
                LOGGER.exception("traffic reading failed")

    def _add(self, name: str, received: int, sent: int, moment: datetime) -> None:
        """Add one difference to the interface's hour, day and month."""
        if not received and not sent:
            return
        periods = self._totals.setdefault(name, {})
        for period, label_format in TRAFFIC_LABEL_FORMATS.items():
            bucket = periods.setdefault(period, {}).setdefault(
                moment.strftime(label_format), [0, 0]
            )
            bucket[0] += received
            bucket[1] += sent

    def _drawn_name(self) -> "str | None":
        """The interface the card draws, empty for none; None when unreadable."""
        if self._drawn_interface is None:
            return ""
        try:
            return self._drawn_interface()
        except (OSError, ValueError) as error:
            LOGGER.warning("the traffic interface is unreadable: %s", error)
            return None

    def _trim(self, moment: datetime, drawn: "str | None") -> None:
        """Drop old buckets, what that empties, and unseen interfaces but ``drawn``."""
        floors = {
            TRAFFIC_HOURS: (
                moment - timedelta(days=ROUTER_TRAFFIC_HOURS_KEPT_DAYS)
            ).strftime(TRAFFIC_LABEL_FORMATS[TRAFFIC_HOURS]),
            TRAFFIC_DAYS: _month_label(moment, ROUTER_TRAFFIC_DAYS_KEPT_MONTHS)
            + f"-{moment.day:02d}",
            TRAFFIC_MONTHS: _month_label(moment, ROUTER_TRAFFIC_MONTHS_KEPT_YEARS * 12),
        }
        unseen_floor = moment - timedelta(days=ROUTER_TRAFFIC_HOURS_KEPT_DAYS)
        totals = {}
        for name, periods in self._totals.items():
            if (
                drawn is not None
                and name != drawn
                and self._seen.get(name, moment) <= unseen_floor
            ):
                continue
            kept = {}
            for period, buckets in periods.items():
                newer = {
                    label: pair
                    for label, pair in buckets.items()
                    if label > floors[period]
                }
                if newer:
                    kept[period] = newer
            if kept:
                totals[name] = kept
        self._totals = totals
        self._seen = {
            name: seen
            for name, seen in self._seen.items()
            if name in totals or name in self._counters
        }

    def _totals_after(
        self, interface: str, period: str, floor: str
    ) -> list[RouterTrafficTotal]:
        """One interface's buckets of one period after ``floor``, oldest first."""
        with self._lock:
            buckets = self._totals.get(interface, {}).get(period, {})
            return [
                RouterTrafficTotal(
                    label=label, received_bytes=pair[0], sent_bytes=pair[1]
                )
                for label, pair in sorted(buckets.items())
                if label > floor
            ]

    def _read(self) -> dict:
        """The file's object, empty when it is missing or unreadable."""
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            LOGGER.warning(
                "the traffic history is unreadable, starting empty: %s", error
            )
            return {}
        if not isinstance(stored, dict):
            LOGGER.warning("the traffic history is not an object, starting empty")
            return {}
        return stored
