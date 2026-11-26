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
    cell = data["cells"]["k1|p1|"]
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
            "unpriced_requests": 1,
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
    assert data["cells"]["k1|p1|"]["days"]["2026-09-04"]["requests"] == 0
    assert data["cells"]["k1|p1|"]["hours"] == {}
    assert "malformed" not in data["cells"]
    assert "k2|p1|" not in data["cells"]
    assert data["minutes"] == {"k1": {"2026-09-04T06:15": {"requests": 2, "tokens": 0}}}


def test_every_range_serves_its_bucket_count(tmp_path):
    subject = store(tmp_path)
    for range_name, count in USAGE_RANGE_BUCKETS.items():
        assert len(subject.series(range_name)) == count


# --- the model of a cell, and each record's cost ---


def priced_record(
    *,
    model: str = "deepseek-v4-pro",
    alias: str = "",
    source: str = "upstream-key-a",
    auth_index: str = "",
    provider: str = "openai-compatible-deepseek",
    uncached: int = 400,
    cache_read: int = 600,
    cache_write: int = 0,
    output: int = 50,
    reasoning: int = 0,
    quality: str = "complete",
) -> dict:
    """A record in 7.2.146's v2 shape: the breakdown with no overlap."""
    return {
        "timestamp": "2026-09-04T06:20:00Z",
        "api_key": "client-key-one",
        "source": source,
        "auth_index": auth_index,
        "provider": provider,
        "model": model,
        "alias": alias,
        "failed": False,
        "token_breakdown": {
            "schema_version": 2,
            "quality": quality,
            "input": {
                "total_tokens": uncached + cache_read + cache_write,
                "uncached_tokens": uncached,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
            },
            "output": {
                "total_tokens": output,
                "non_reasoning_tokens": output - reasoning,
                "reasoning_tokens": reasoning,
            },
        },
    }


def pricer(*, set_prices=None, prices=None):
    """A pricer over one DeepSeek provider p1, one Zhipu plan provider p2, one
    custom relay p3, a Claude account and a machine's Ollama."""
    from neutrino_hub.modules.ai.model_prices import AiPriceTable, AiRecordPricer
    from neutrino_hub.modules.ai.registry import AiProviderRecord
    from neutrino_hub.modules.ai.vendors import load_vendors, vendor_endpoints

    return AiRecordPricer(
        table=AiPriceTable(
            prices
            or {
                "deepseek": {
                    "deepseek-v4-pro": {
                        "input": 0.28,
                        "output": 1.1,
                        "cache_read": 0.028,
                    }
                },
                "zhipuai": {"glm-5.3": {"input": 4, "output": 18}},
                "anthropic": {
                    "claude-opus-5-5": {
                        "input": 5,
                        "output": 25,
                        "cache_read": 0.5,
                        "cache_write": 6.25,
                    }
                },
            }
        ),
        set_prices=set_prices or {},
        providers={
            "p1": AiProviderRecord(
                id="p1",
                name="DeepSeek",
                kind="custom",
                base_url="https://api.deepseek.com",
            ),
            "p2": AiProviderRecord(
                id="p2",
                name="GLM plan",
                kind="custom",
                base_url="https://open.bigmodel.cn/api/coding/paas/v4/",
            ),
            "p3": AiProviderRecord(
                id="p3",
                name="Relay",
                kind="custom",
                base_url="https://relay.example/v1",
            ),
        },
        accounts={"claude-person.json": "claude"},
        endpoints=vendor_endpoints(load_vendors()),
        ollama_providers=["openai-compatible-ollama-dev-1"],
        ollama_names=["qwen2.5:7b"],
    )


def fold(tmp_path, records, *, subject_pricer=None):
    subject = store(tmp_path)
    subject.ingest(
        records,
        key_ids=KEY_IDS,
        key_names=KEY_NAMES,
        provider_ids={
            "upstream-key-a": "p1",
            "upstream-key-b": "p2",
            "upstream-key-c": "p3",
        },
        account_ids={"idx-claude": "claude-person.json"},
        ollama_ids={"openai-compatible-ollama-dev-1": "dev-1"},
        pricer=subject_pricer or pricer(),
        now=NOW,
    )
    return subject


def test_a_cell_is_keyed_by_the_served_name_the_alias_else_the_model(tmp_path):
    subject = fold(
        tmp_path,
        [
            priced_record(alias="fast"),
            priced_record(),
        ],
    )
    cells = subject.load()["cells"]
    assert set(cells) == {"k1|p1|fast", "k1|p1|deepseek-v4-pro"}


def test_a_cell_of_the_old_shape_reads_as_model_unknown_with_its_tokens(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text(
        '{"cells": {"k1|p1": {"days": {"2026-09-04": {"requests": 3, '
        '"input_tokens": 900}}, "hours": {}}}}',
        encoding="utf-8",
    )
    subject = CliproxyApiUsageStore(path=path)
    (row,) = subject.model_rows("week", now=NOW)
    assert row["model"] == ""
    assert row["requests"] == 3
    assert row["input_tokens"] == 900
    assert row["cost"] == {}
    assert row["unpriced_requests"] == 0


def test_a_records_cost_is_its_breakdown_at_the_price_in_force_in_millionths(
    tmp_path,
):
    # 400 uncached at 0.28, 600 cached at 0.028 and 50 out at 1.10 per
    # million: 112 + 16.8 + 55 = 183.8 millionths, rounded per record.
    subject = fold(tmp_path, [priced_record(), priced_record()])
    totals = subject.totals("day", now=NOW)
    assert totals["cost"] == {"USD": 368}
    assert totals["api_value"] == {}
    assert totals["unpriced_requests"] == 0


def test_reasoning_is_priced_as_output(tmp_path):
    subject = fold(
        tmp_path,
        [priced_record(uncached=0, cache_read=0, output=1000, reasoning=900)],
    )
    assert subject.totals("day", now=NOW)["cost"] == {"USD": 1100}


def test_a_price_set_in_cny_counts_apart_from_usd(tmp_path):
    subject = fold(
        tmp_path,
        [priced_record(), priced_record(alias="cny-name")],
        subject_pricer=pricer(
            set_prices={"cny-name": {"input": 2, "output": 8, "currency": "CNY"}}
        ),
    )
    totals = subject.totals("day", now=NOW)
    # 400 x 2 + 600 x (2 x 0.028 / 0.28) + 50 x 8 = 800 + 120 + 400.
    assert totals["cost"] == {"USD": 184, "CNY": 1320}


def test_an_account_and_a_plan_endpoint_count_an_api_value_and_no_cost(tmp_path):
    subject = fold(
        tmp_path,
        [
            priced_record(
                model="claude-opus-5-5",
                source="person@example.com",
                auth_index="idx-claude",
                provider="claude",
                uncached=1000,
                cache_read=0,
                cache_write=1000,
                output=100,
            ),
            priced_record(model="glm-5.3", source="upstream-key-b", cache_read=0),
        ],
    )
    totals = subject.totals("day", now=NOW)
    assert totals["cost"] == {}
    # 1000 x 5 + 1000 x 6.25 + 100 x 25 = 13750; 400 x 4 + 50 x 18 = 2500.
    assert totals["api_value"] == {"USD": 16250}


def test_a_record_with_no_price_or_a_breakdown_that_does_not_add_up_is_unpriced(
    tmp_path,
):
    subject = fold(
        tmp_path,
        [
            priced_record(source="upstream-key-c"),
            priced_record(model="not-on-models-dev"),
            priced_record(quality="unclassified"),
            priced_record(quality="inconsistent"),
            {**priced_record(), "token_breakdown": None},
        ],
    )
    totals = subject.totals("day", now=NOW)
    assert totals["cost"] == {}
    assert totals["unpriced_requests"] == 5


def test_an_ollama_record_counts_in_none_of_the_three(tmp_path):
    subject = fold(
        tmp_path,
        [
            priced_record(
                model="qwen2.5:7b",
                source="",
                provider="openai-compatible-ollama-dev-1",
            )
        ],
    )
    totals = subject.totals("day", now=NOW)
    assert totals["requests"] == 1
    assert (totals["cost"], totals["api_value"], totals["unpriced_requests"]) == (
        {},
        {},
        0,
    )


def test_every_range_serves_the_models_rows(tmp_path):
    subject = fold(
        tmp_path, [priced_record(), priced_record(alias="fast"), priced_record()]
    )
    for range_name in USAGE_RANGE_BUCKETS:
        rows = {row["model"]: row for row in subject.model_rows(range_name, now=NOW)}
        assert set(rows) == {"deepseek-v4-pro", "fast"}
        assert rows["deepseek-v4-pro"]["requests"] == 2
        assert rows["deepseek-v4-pro"]["cost"] == {"USD": 368}
    assert subject.model_rows("day", key_id="k2", now=NOW) == []


def test_an_ollama_record_is_the_upstream_of_its_machine(tmp_path):
    subject = fold(
        tmp_path,
        [
            priced_record(
                model="qwen2.5:7b",
                source="",
                provider="OpenAI-Compatible-Ollama-Dev-1",
            ),
            priced_record(model="qwen2.5:7b", source="", provider="unknown"),
        ],
    )

    assert set(subject.load()["cells"]) == {
        "k1|ollama:dev-1|qwen2.5:7b",
        "k1||qwen2.5:7b",
    }


def test_each_models_row_carries_its_upstreams(tmp_path):
    subject = fold(
        tmp_path,
        [
            priced_record(),
            priced_record(),
            priced_record(source="upstream-key-c"),
            priced_record(
                model="qwen2.5:7b",
                source="",
                provider="openai-compatible-ollama-dev-1",
            ),
        ],
    )
    rows = {row["model"]: row for row in subject.model_rows("week", now=NOW)}

    upstreams = {
        entry["upstream"]: entry for entry in rows["deepseek-v4-pro"]["upstreams"]
    }
    assert set(upstreams) == {"p1", "p3"}
    assert upstreams["p1"]["requests"] == 2
    assert upstreams["p1"]["cost"] == {"USD": 368}
    assert upstreams["p3"]["unpriced_requests"] == 1
    assert (
        sum(entry["requests"] for entry in upstreams.values())
        == rows["deepseek-v4-pro"]["requests"]
    )
    ((ollama),) = rows["qwen2.5:7b"]["upstreams"]
    assert (ollama["upstream"], ollama["requests"]) == ("ollama:dev-1", 1)
