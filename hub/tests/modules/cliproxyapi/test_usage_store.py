"""The usage store: folding queue records, the windows, and hostile files.

The record shapes come from CLIProxyAPI 7.2.146's own ``usage-queue``
answers, trimmed to the fields the store reads.
"""

from datetime import datetime, timedelta, timezone

from neutrino_hub.modules.cliproxyapi.usage_store import (
    USAGE_RANGE_BUCKETS,
    CliproxyApiUsageStore,
    zero_counters,
)

NOW = datetime(2026, 9, 4, 6, 30, tzinfo=timezone.utc)

KEY_IDS = {"client-key-one": "k1", "client-key-two": "k2"}
KEY_NAMES = {"k1": "laptop", "k2": "desktop"}
PROVIDER_IDS = {"upstream-key-a": "p1"}


def record(
    *,
    timestamp: str = "2026-09-04T14:16:24.186798+08:00",
    api_key: str = "client-key-one",
    source: str = "upstream-key-a",
    is_failed: bool = False,
    input_tokens: int = 120,
    output_tokens: int = 30,
    cache_read: int = 40,
    cache_write: int = 25,
) -> dict:
    return {
        "timestamp": timestamp,
        "api_key": api_key,
        "source": source,
        "failed": is_failed,
        "provider": "claude",
        "tokens": {
            "input_tokens": input_tokens - cache_read - cache_write,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_write,
        },
        "token_breakdown": {
            "schema_version": 2,
            "input": {
                "total_tokens": input_tokens,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
            },
            "output": {"total_tokens": output_tokens},
        },
    }


def store(tmp_path) -> CliproxyApiUsageStore:
    return CliproxyApiUsageStore(path=tmp_path / "usage.json")


def test_a_success_and_a_failure_fold_into_every_window(tmp_path):
    subject = store(tmp_path)
    folded = subject.ingest(
        [
            record(),
            record(
                api_key="client-key-two",
                is_failed=True,
                input_tokens=0,
                output_tokens=0,
                cache_read=0,
                cache_write=0,
            ),
        ],
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    assert folded == 2
    totals = subject.totals("day", now=NOW)
    assert totals["requests"] == 2
    assert totals["failed"] == 1
    assert totals["input_tokens"] == 120
    assert totals["output_tokens"] == 30
    assert totals["cache_read_tokens"] == 40
    assert totals["cache_write_tokens"] == 25
    # The timestamp arrived with a +08:00 offset; the bucket is its UTC hour.
    series = subject.series("day", now=NOW)
    assert series[-1]["bucket"] == NOW.strftime("%Y-%m-%dT%H:00:00Z")
    assert series[-1]["requests"] == 2
    rates = subject.rates(now=NOW)
    assert rates["rpm"] == 2 / 60.0
    assert rates["tpm"] == 150 / 60.0
    narrowed = subject.rates(key_id="k1", now=NOW)
    assert narrowed["rpm"] == 1 / 60.0
    assert narrowed["tpm"] == 150 / 60.0
    assert subject.rates(key_id="k2", now=NOW)["tpm"] == 0.0


def test_key_rows_carry_names_and_the_filter_narrows(tmp_path):
    subject = store(tmp_path)
    subject.ingest(
        [record(), record(api_key="client-key-two", input_tokens=10, output_tokens=1)],
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    rows = {row["key_id"]: row for row in subject.key_rows("day", now=NOW)}
    assert rows["k1"]["name"] == "laptop"
    assert rows["k1"]["requests"] == 1
    assert rows["k2"]["input_tokens"] == 10
    assert rows["k1"]["first_seen_at"] == rows["k1"]["last_seen_at"]
    assert subject.totals("day", key_id="k1", now=NOW)["input_tokens"] == 120
    assert subject.totals("day", key_id="k2", now=NOW)["input_tokens"] == 10


def test_provider_rows_sum_health_over_the_last_hours(tmp_path):
    subject = store(tmp_path)
    subject.ingest(
        [record(), record(is_failed=True, input_tokens=0, output_tokens=0)],
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    row = subject.provider_rows("day", now=NOW)["p1"]
    assert row["requests"] == 2
    assert row["failed"] == 1
    assert len(row["health"]) == 5
    assert row["health"][-1]["requests"] == 2
    assert row["health"][-1]["failed"] == 1
    assert sum(entry["requests"] for entry in row["health"][:-1]) == 0


def test_records_without_a_breakdown_fall_back_to_the_flat_tokens(tmp_path):
    subject = store(tmp_path)
    flat = record()
    del flat["token_breakdown"]
    subject.ingest(
        [flat],
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    totals = subject.totals("day", now=NOW)
    assert totals["input_tokens"] == 55
    assert totals["cache_read_tokens"] == 40
    assert totals["cache_write_tokens"] == 25


def test_unusable_records_are_skipped_and_the_rest_still_count(tmp_path):
    subject = store(tmp_path)
    folded = subject.ingest(
        ["not a record", {"timestamp": "yesterday-ish"}, {}, record()],
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    assert folded == 1
    assert subject.totals("day", now=NOW)["requests"] == 1


def test_an_unknown_key_counts_in_totals_but_lists_no_key(tmp_path):
    subject = store(tmp_path)
    subject.ingest(
        [record(api_key="revoked-key", source="unknown-upstream")],
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    assert subject.totals("day", now=NOW)["requests"] == 1
    assert subject.key_rows("day", now=NOW) == []
    assert subject.provider_rows("day", now=NOW) == {}


def test_hours_and_minutes_roll_over_and_days_stay(tmp_path):
    subject = store(tmp_path)
    old = NOW - timedelta(days=3)
    subject.ingest(
        [record(timestamp=old.isoformat())],
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    data = subject.load()
    cell = data["cells"]["k1|p1"]
    assert cell["hours"] == {}
    assert data["minutes"] == {}
    assert cell["days"] == {
        old.strftime("%Y-%m-%d"): {
            **zero_counters(),
            "requests": 1,
            "input_tokens": 120,
            "output_tokens": 30,
            "cache_read_tokens": 40,
            "cache_write_tokens": 25,
        }
    }


def test_a_rename_reaches_the_stored_key(tmp_path):
    subject = store(tmp_path)
    subject.ingest(
        [record()],
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    subject.ingest(
        [],
        key_ids=KEY_IDS,
        key_names={"k1": "renamed", "k2": "desktop"},
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    assert subject.key_rows("day", now=NOW)[0]["name"] == "renamed"


def test_a_corrupt_file_starts_fresh_instead_of_crashing(tmp_path):
    path = tmp_path / "usage.json"
    path.write_bytes(b"\x00 not json at all")
    subject = CliproxyApiUsageStore(path=path)
    assert subject.totals("week", now=NOW) == zero_counters()
    subject.ingest(
        [record()],
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids=PROVIDER_IDS,
        now=NOW,
    )
    assert subject.totals("day", now=NOW)["requests"] == 1


def test_a_hostile_file_is_normalized_field_by_field(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text(
        """
        {
          "keys": {"k1": {"name": 7, "first_seen_at": null}},
          "providers": "nope",
          "cells": {
            "k1|p1": {"days": {"2026-09-04": {"requests": "many"}}, "hours": []},
            "malformed": {"days": {}},
            "k2|p1": "nope"
          },
          "minutes": {"k1": {"2026-09-04T06:15": {"requests": 2, "tokens": -5},
                             "gibberish": {"requests": 1}},
                      "k2": "nope"}
        }
        """,
        encoding="utf-8",
    )
    data = CliproxyApiUsageStore(path=path).load()
    assert data["keys"]["k1"]["name"] == "7"
    assert data["providers"] == {}
    assert data["cells"]["k1|p1"]["days"]["2026-09-04"]["requests"] == 0
    assert data["cells"]["k1|p1"]["hours"] == {}
    assert "malformed" not in data["cells"]
    assert "k2|p1" not in data["cells"]
    assert data["minutes"] == {"k1": {"2026-09-04T06:15": {"requests": 2, "tokens": 0}}}


def test_every_range_serves_its_bucket_count(tmp_path):
    subject = store(tmp_path)
    for range_name, count in USAGE_RANGE_BUCKETS.items():
        assert len(subject.series(range_name)) == count
