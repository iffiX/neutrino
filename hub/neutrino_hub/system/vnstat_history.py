"""Reading long-term interface traffic history from vnstat.

xray's own counters reset whenever the service restarts, so the dashboard's
"past traffic" view comes from vnstatd, which keeps per-interface totals across
reboots in its own database.
"""

import json
from dataclasses import dataclass

from neutrino_hub.utils.subprocess_run import run

# vnstat's mode letter, and the key its JSON lists that mode's buckets under.
VNSTAT_BUCKET_KEYS = {"h": "hour", "d": "day", "m": "month"}


@dataclass
class TrafficSample:
    """Traffic totals for one time bucket.

    Attributes:
        label: ISO-like label for the bucket, for example ``2026-08-27`` or
            ``2026-08-27 14:00``.
        received_bytes: Bytes received in the bucket.
        sent_bytes: Bytes sent in the bucket.
    """

    label: str
    received_bytes: int
    sent_bytes: int


class VnstatHistoryReader:
    """Reads per-interface traffic history."""

    def __init__(self, *, interface: str):
        """
        Args:
            interface: Interface to report on, normally the WAN.
        """
        self._interface = interface

    def daily(self, *, day_count: int = 30) -> list[TrafficSample]:
        """Read daily totals.

        Args:
            day_count: How many recent days to return.

        Returns:
            Samples oldest first. Empty when vnstat has no data for the
            interface yet, which is normal for the first day after install.
        """
        return self._read("d", day_count)

    def hourly(self, *, hour_count: int = 24) -> list[TrafficSample]:
        """Read hourly totals.

        Args:
            hour_count: How many recent hours to return.

        Returns:
            Samples oldest first.
        """
        return self._read("h", hour_count)

    def monthly(self, *, month_count: int = 12) -> list[TrafficSample]:
        """Read monthly totals.

        Args:
            month_count: How many recent months to return.

        Returns:
            Samples oldest first.
        """
        return self._read("m", month_count)

    def _read(self, mode: str, count: int) -> list[TrafficSample]:
        result = run(
            ["vnstat", "--json", mode, str(count), "-i", self._interface],
            is_checked=False,
            timeout_s=15,
        )
        if not result.is_success or not result.stdout.strip():
            return []
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        interfaces = payload.get("interfaces", [])
        if not interfaces:
            return []
        buckets = interfaces[0].get("traffic", {}).get(VNSTAT_BUCKET_KEYS[mode], [])
        return [self._to_sample(bucket, mode) for bucket in buckets[-count:]]

    def _to_sample(self, bucket: dict, mode: str) -> TrafficSample:
        date = bucket.get("date", {})
        label = f"{date.get('year', 0):04d}-{date.get('month', 0):02d}"
        if mode != "m":
            label = f"{label}-{date.get('day', 0):02d}"
        if mode == "h":
            label = f"{label} {bucket.get('time', {}).get('hour', 0):02d}:00"
        return TrafficSample(
            label=label,
            received_bytes=int(bucket.get("rx", 0)),
            sent_bytes=int(bucket.get("tx", 0)),
        )
