"""Accumulated AI gateway usage, persisted under the state root.

One JSON file holds everything the usage answers are built from. The unit of
storage is a cell — one client key crossed with one upstream — with per-day
counters kept forever and per-hour counters kept two days; every total,
series and filter is a sum over cells. An upstream is an API-key provider or
a subscription account, and both are named by id in the same slot. A minute
ring beside them carries the rpm/tpm window. The gateway's queue records
arrive already mapped to ids; unknown keys and upstreams land in a cell with
an empty id, so the totals stay honest when a key is revoked mid-flight.

Reads tolerate anything: a corrupt or hostile file is logged and replaced by
a fresh store, never a crashed panel.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_USAGE_HOURS_KEPT,
    CLIPROXYAPI_USAGE_MINUTES_KEPT,
    CLIPROXYAPI_USAGE_RELATIVE,
)
from neutrino_hub.utils import constants

LOGGER = logging.getLogger(__name__)

USAGE_VERSION = 1
USAGE_COUNTER_FIELDS = (
    "requests",
    "failed",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)
# Buckets per range: day is hourly, the rest are daily.
USAGE_RANGE_BUCKETS = {"day": 24, "week": 7, "month": 30, "year": 365}
USAGE_HEALTH_HOURS = 5


def zero_counters() -> dict:
    """A fresh counter set.

    Returns:
        Every counter field at zero.
    """
    return {field: 0 for field in USAGE_COUNTER_FIELDS}


class CliproxyApiUsageStore:
    """Folds queue records in, and answers the usage queries."""

    def __init__(self, *, path: Path | None = None):
        """
        Args:
            path: The store file; None resolves it under the state root per
                call, so a test points the whole store elsewhere by path.
        """
        self._path = path

    def ingest(
        self,
        records: list,
        *,
        key_ids: dict[str, str],
        key_names: dict[str, str],
        provider_ids: dict[str, str],
        account_ids: dict[str, str] | None = None,
        now: datetime | None = None,
    ) -> int:
        """Fold popped queue records into the store and persist it.

        Args:
            records: What the gateway's usage queue returned.
            key_ids: Client key value to key id, from the stored config.
            key_names: Key id to its current name, refreshed on every poll so
                a renamed key keeps its history under the new name.
            provider_ids: Upstream key value (the record's ``source``) to
                provider id, resolved from the registry.
            account_ids: Credential handle (the record's ``auth_index``) to
                account id, resolved from the gateway's auth files; None where
                the gateway could not be asked.
            now: The poll moment; None is the real clock.

        Returns:
            How many records were usable.
        """
        now = now or datetime.now(timezone.utc)
        data = self.load()
        folded = 0
        for record in records:
            if self._fold(
                data,
                record,
                key_ids=key_ids,
                provider_ids=provider_ids,
                account_ids=account_ids or {},
            ):
                folded += 1
        for key_id, name in key_names.items():
            if key_id in data["keys"]:
                data["keys"][key_id]["name"] = str(name)
        self._prune(data, now=now)
        self._save(data)
        return folded

    def load(self) -> dict:
        """Read the store, tolerant of anything on disk.

        Returns:
            The normalized store; fresh and empty when the file is missing,
            corrupt, or not shaped like a store.
        """
        try:
            raw = json.loads(self._resolved_path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._fresh()
        except (OSError, ValueError) as error:
            LOGGER.warning("usage store unreadable, starting fresh: %s", error)
            return self._fresh()
        if not isinstance(raw, dict):
            LOGGER.warning("usage store is not an object, starting fresh")
            return self._fresh()
        return self._normalized(raw)

    def totals(
        self,
        range_name: str,
        *,
        key_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Counters summed over one range.

        Args:
            range_name: One of :data:`USAGE_RANGE_BUCKETS`.
            key_id: Narrow to one client key; None sums every key.
            now: The moment the range ends at; None is the real clock.

        Returns:
            One counter set.
        """
        data = self.load()
        wanted = set(self._bucket_keys(range_name, now=now))
        is_hourly = range_name == "day"
        summed = zero_counters()
        for cell_key, cell in data["cells"].items():
            if not self._cell_matches(cell_key, key_id):
                continue
            buckets = cell["hours"] if is_hourly else cell["days"]
            for bucket, counters in buckets.items():
                if bucket in wanted:
                    self._add(summed, counters)
        return summed

    def series(
        self,
        range_name: str,
        *,
        key_id: str | None = None,
        now: datetime | None = None,
    ) -> list[dict]:
        """The zero-filled bucket series for one range, oldest first.

        Args:
            range_name: One of :data:`USAGE_RANGE_BUCKETS`.
            key_id: Narrow to one client key; None sums every key.
            now: The moment the range ends at; None is the real clock.

        Returns:
            One ``{"bucket", **counters}`` entry per bucket.
        """
        data = self.load()
        keys = self._bucket_keys(range_name, now=now)
        is_hourly = range_name == "day"
        series = {bucket: zero_counters() for bucket in keys}
        for cell_key, cell in data["cells"].items():
            if not self._cell_matches(cell_key, key_id):
                continue
            buckets = cell["hours"] if is_hourly else cell["days"]
            for bucket, counters in buckets.items():
                if bucket in series:
                    self._add(series[bucket], counters)
        return [{"bucket": bucket, **series[bucket]} for bucket in keys]

    def key_rows(self, range_name: str, *, now: datetime | None = None) -> list[dict]:
        """Every client key that has recorded usage, with range counters.

        Args:
            range_name: One of :data:`USAGE_RANGE_BUCKETS`.
            now: The moment the range ends at; None is the real clock.

        Returns:
            One row per key: id, name, counters, first and last seen.
        """
        data = self.load()
        wanted = set(self._bucket_keys(range_name, now=now))
        is_hourly = range_name == "day"
        rows = []
        for key_id, meta in data["keys"].items():
            summed = zero_counters()
            for cell_key, cell in data["cells"].items():
                if cell_key.split("|", 1)[0] != key_id:
                    continue
                buckets = cell["hours"] if is_hourly else cell["days"]
                for bucket, counters in buckets.items():
                    if bucket in wanted:
                        self._add(summed, counters)
            rows.append(
                {
                    "key_id": key_id,
                    "name": meta["name"],
                    "first_seen_at": meta["first_seen_at"],
                    "last_seen_at": meta["last_seen_at"],
                    **summed,
                }
            )
        return rows

    def provider_rows(
        self,
        range_name: str,
        *,
        key_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, dict]:
        """Range counters and health per provider that has recorded usage.

        Args:
            range_name: One of :data:`USAGE_RANGE_BUCKETS`.
            key_id: Narrow to one client key; None sums every key.
            now: The moment the range ends at; None is the real clock.

        Returns:
            Provider id to row: counters, first and last seen, and ``health``
            — the last :data:`USAGE_HEALTH_HOURS` hours as
            ``{"bucket", "requests", "failed"}``, zero-filled.
        """
        data = self.load()
        wanted = set(self._bucket_keys(range_name, now=now))
        is_hourly = range_name == "day"
        health_keys = self._hour_keys(USAGE_HEALTH_HOURS, now=now)
        rows: dict[str, dict] = {}
        for provider_id, meta in data["providers"].items():
            summed = zero_counters()
            health = {bucket: {"requests": 0, "failed": 0} for bucket in health_keys}
            for cell_key, cell in data["cells"].items():
                if cell_key.split("|", 1)[1] != provider_id:
                    continue
                if not self._cell_matches(cell_key, key_id):
                    continue
                buckets = cell["hours"] if is_hourly else cell["days"]
                for bucket, counters in buckets.items():
                    if bucket in wanted:
                        self._add(summed, counters)
                for bucket, counters in cell["hours"].items():
                    if bucket in health:
                        health[bucket]["requests"] += counters["requests"]
                        health[bucket]["failed"] += counters["failed"]
            rows[provider_id] = {
                "first_seen_at": meta["first_seen_at"],
                "last_seen_at": meta["last_seen_at"],
                "health": [
                    {"bucket": bucket, **health[bucket]} for bucket in health_keys
                ],
                **summed,
            }
        return rows

    def empty_provider_row(self, *, now: datetime | None = None) -> dict:
        """A zero row shaped like :meth:`provider_rows` builds, for a
        provider nothing has been recorded for.

        Args:
            now: The moment the health window ends at; None is the real clock.

        Returns:
            Zero counters, empty seen timestamps, zero-filled health.
        """
        return {
            "first_seen_at": "",
            "last_seen_at": "",
            "health": [
                {"bucket": bucket, "requests": 0, "failed": 0}
                for bucket in self._hour_keys(USAGE_HEALTH_HOURS, now=now)
            ],
            **zero_counters(),
        }

    def rates(self, *, key_id: str | None = None, now: datetime | None = None) -> dict:
        """Requests and tokens per minute, averaged over the last hour.

        Args:
            key_id: Narrow to one client key; None sums every key.
            now: The moment to average back from; None is the real clock.

        Returns:
            ``{"rpm", "tpm"}``; tokens are input plus output.
        """
        now = now or datetime.now(timezone.utc)
        oldest = now - timedelta(minutes=60)
        requests = 0
        tokens = 0
        for ring_key, ring in self.load()["minutes"].items():
            if key_id is not None and ring_key != key_id:
                continue
            for bucket, counters in ring.items():
                moment = self._parse_minute(bucket)
                if moment is None or moment <= oldest or moment > now:
                    continue
                requests += counters["requests"]
                tokens += counters["tokens"]
        return {"rpm": requests / 60.0, "tpm": tokens / 60.0}

    def today_counters(self, *, now: datetime | None = None) -> dict:
        """The current UTC day's counters across every key and provider.

        Args:
            now: The moment whose UTC day counts; None is the real clock.

        Returns:
            One counter set.
        """
        today = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        summed = zero_counters()
        for cell in self.load()["cells"].values():
            counters = cell["days"].get(today)
            if counters:
                self._add(summed, counters)
        return summed

    def _fold(
        self,
        data: dict,
        record,
        *,
        key_ids: dict[str, str],
        provider_ids: dict[str, str],
        account_ids: dict[str, str],
    ) -> bool:
        if not isinstance(record, dict):
            return False
        moment = self._parse_timestamp(record.get("timestamp"))
        if moment is None:
            return False
        key_id = key_ids.get(str(record.get("api_key", "")), "")
        # An API-key provider is named by the key it was served with. An
        # account is named by the credential handle instead: its ``source`` is
        # the account's email, which a login need not carry, and which the
        # gateway then fills with the client's own key.
        provider_id = provider_ids.get(
            str(record.get("source", "")), ""
        ) or account_ids.get(str(record.get("auth_index", "")), "")
        counters = self._record_counters(record)

        cell = data["cells"].setdefault(
            f"{key_id}|{provider_id}", {"days": {}, "hours": {}}
        )
        day = moment.strftime("%Y-%m-%d")
        hour = moment.strftime("%Y-%m-%dT%H:00:00Z")
        minute = moment.strftime("%Y-%m-%dT%H:%M")
        self._add(cell["days"].setdefault(day, zero_counters()), counters)
        self._add(cell["hours"].setdefault(hour, zero_counters()), counters)
        ring = (
            data["minutes"]
            .setdefault(key_id, {})
            .setdefault(minute, {"requests": 0, "tokens": 0})
        )
        ring["requests"] += 1
        ring["tokens"] += counters["input_tokens"] + counters["output_tokens"]

        seen = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        if key_id:
            self._touch(data["keys"], key_id, seen)
        if provider_id:
            self._touch(data["providers"], provider_id, seen)
        return True

    def _record_counters(self, record: dict) -> dict:
        """One queue record's contribution.

        The v2 ``token_breakdown`` is authoritative when it is there — its
        input total includes what the cache served — and the flat ``tokens``
        object covers records from before it existed.
        """
        counters = zero_counters()
        counters["requests"] = 1
        counters["failed"] = 1 if record.get("failed") else 0
        breakdown = record.get("token_breakdown")
        if isinstance(breakdown, dict) and isinstance(breakdown.get("input"), dict):
            input_block = breakdown.get("input") or {}
            output_block = breakdown.get("output") or {}
            counters["input_tokens"] = _int(input_block.get("total_tokens"))
            counters["output_tokens"] = _int(output_block.get("total_tokens"))
            counters["cache_read_tokens"] = _int(input_block.get("cache_read_tokens"))
            counters["cache_write_tokens"] = _int(input_block.get("cache_write_tokens"))
            return counters
        tokens = record.get("tokens")
        if isinstance(tokens, dict):
            counters["input_tokens"] = _int(tokens.get("input_tokens"))
            counters["output_tokens"] = _int(tokens.get("output_tokens"))
            counters["cache_read_tokens"] = _int(
                tokens.get("cache_read_tokens", tokens.get("cached_tokens"))
            )
            counters["cache_write_tokens"] = _int(tokens.get("cache_creation_tokens"))
        return counters

    def _touch(self, table: dict, entry_id: str, seen: str) -> None:
        meta = table.setdefault(
            entry_id, {"name": "", "first_seen_at": seen, "last_seen_at": seen}
        )
        if seen < meta["first_seen_at"]:
            meta["first_seen_at"] = seen
        if seen > meta["last_seen_at"]:
            meta["last_seen_at"] = seen

    def _prune(self, data: dict, *, now: datetime) -> None:
        oldest_hour = (now - timedelta(hours=CLIPROXYAPI_USAGE_HOURS_KEPT)).strftime(
            "%Y-%m-%dT%H:00:00Z"
        )
        for cell in data["cells"].values():
            cell["hours"] = {
                bucket: counters
                for bucket, counters in cell["hours"].items()
                if bucket >= oldest_hour
            }
        oldest_minute = now - timedelta(minutes=CLIPROXYAPI_USAGE_MINUTES_KEPT)
        rings = {}
        for ring_key, ring in data["minutes"].items():
            kept = {}
            for bucket, counters in ring.items():
                moment = self._parse_minute(bucket)
                if moment is not None and moment > oldest_minute:
                    kept[bucket] = counters
            if kept:
                rings[ring_key] = kept
        data["minutes"] = rings

    def _bucket_keys(self, range_name: str, *, now: datetime | None) -> list[str]:
        count = USAGE_RANGE_BUCKETS[range_name]
        if range_name == "day":
            return self._hour_keys(count, now=now)
        today = (now or datetime.now(timezone.utc)).date()
        return [
            (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(count - 1, -1, -1)
        ]

    def _hour_keys(self, count: int, *, now: datetime | None = None) -> list[str]:
        head = (now or datetime.now(timezone.utc)).replace(
            minute=0, second=0, microsecond=0
        )
        return [
            (head - timedelta(hours=offset)).strftime("%Y-%m-%dT%H:00:00Z")
            for offset in range(count - 1, -1, -1)
        ]

    def _cell_matches(self, cell_key: str, key_id: str | None) -> bool:
        return key_id is None or cell_key.split("|", 1)[0] == key_id

    def _add(self, into: dict, counters: dict) -> None:
        for field in USAGE_COUNTER_FIELDS:
            into[field] += counters[field]

    def _parse_timestamp(self, value) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)

    def _parse_minute(self, bucket: str) -> datetime | None:
        try:
            return datetime.strptime(bucket, "%Y-%m-%dT%H:%M").replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            return None

    def _fresh(self) -> dict:
        return {
            "version": USAGE_VERSION,
            "keys": {},
            "providers": {},
            "cells": {},
            "minutes": {},
        }

    def _normalized(self, raw: dict) -> dict:
        """Rebuild the store from whatever was read, dropping the malformed.

        Every id, bucket and counter is retyped rather than trusted; a value
        that does not fit is left out, and the rest of the file still counts.
        """
        data = self._fresh()
        for table in ("keys", "providers"):
            entries = raw.get(table)
            if not isinstance(entries, dict):
                continue
            for entry_id, meta in entries.items():
                if not isinstance(meta, dict):
                    continue
                data[table][str(entry_id)] = {
                    "name": str(meta.get("name", "")),
                    "first_seen_at": str(meta.get("first_seen_at", "")),
                    "last_seen_at": str(meta.get("last_seen_at", "")),
                }
        cells = raw.get("cells")
        if isinstance(cells, dict):
            for cell_key, cell in cells.items():
                if not isinstance(cell_key, str) or "|" not in cell_key:
                    continue
                if not isinstance(cell, dict):
                    continue
                data["cells"][cell_key] = {
                    "days": self._normalized_buckets(cell.get("days")),
                    "hours": self._normalized_buckets(cell.get("hours")),
                }
        minutes = raw.get("minutes")
        if isinstance(minutes, dict):
            for ring_key, ring in minutes.items():
                if not isinstance(ring_key, str) or not isinstance(ring, dict):
                    continue
                normalized = {}
                for bucket, counters in ring.items():
                    if self._parse_minute(bucket) is None or not isinstance(
                        counters, dict
                    ):
                        continue
                    normalized[bucket] = {
                        "requests": _int(counters.get("requests")),
                        "tokens": _int(counters.get("tokens")),
                    }
                if normalized:
                    data["minutes"][ring_key] = normalized
        return data

    def _normalized_buckets(self, buckets) -> dict:
        if not isinstance(buckets, dict):
            return {}
        normalized = {}
        for bucket, counters in buckets.items():
            if not isinstance(bucket, str) or not isinstance(counters, dict):
                continue
            normalized[bucket] = {
                field: _int(counters.get(field)) for field in USAGE_COUNTER_FIELDS
            }
        return normalized

    def _save(self, data: dict) -> None:
        path = self._resolved_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, staged = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream)
            os.chmod(staged, 0o600)
            os.replace(staged, path)
        except BaseException:
            Path(staged).unlink(missing_ok=True)
            raise

    def _resolved_path(self) -> Path:
        # Resolved per call, against the state root as it is right now.
        return self._path or constants.UTILS_STATE_ROOT / CLIPROXYAPI_USAGE_RELATIVE


def _int(value) -> int:
    """A counter value, or zero for anything that is not a whole number."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0
