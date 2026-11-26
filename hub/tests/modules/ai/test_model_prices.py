"""Model prices: the models.dev list kept and checked, the copy in force, each upstream's price, and a person's price.

The recorded list is a trimmed copy of ``https://models.dev/api.json`` of
2026-11-26: each entry keeps the fields models.dev gives it, the ones the
hub does not read among them.
"""

import json
import logging
from datetime import datetime, timezone

import pytest

from neutrino_hub.modules.ai import model_prices
from neutrino_hub.modules.ai.constants import AI_PRICES_SNAPSHOT_PATH
from neutrino_hub.modules.ai.model_prices import (
    PRICES_FAILED,
    PRICES_REFUSED,
    PRICES_WRITTEN,
    AiPriceTable,
    AiRecordPricer,
    checked_prices,
    kept_prices,
    kept_providers,
    next_read_wait_s,
    priced_count,
    prices_in_force,
    read_snapshot,
    read_stored_prices,
    refresh_model_prices,
    seconds_until_due,
)
from neutrino_hub.modules.ai.registry import AiProviderRecord
from neutrino_hub.modules.ai.vendors import load_vendors, vendor_endpoints

RECORDED = {
    "deepseek": {
        "id": "deepseek",
        "api": "https://api.deepseek.com",
        "name": "DeepSeek",
        "models": {
            "deepseek-v4-pro": {
                "id": "deepseek-v4-pro",
                "reasoning": True,
                "limit": {"context": 1048576, "output": 393216},
                "cost": {
                    "input": 0.28,
                    "output": 1.1,
                    "reasoning": 1.1,
                    "cache_read": 0.028,
                    "context_over_200k": {"input": 0.56, "output": 2.2},
                },
            },
            "deepseek-unpriced": {"id": "deepseek-unpriced", "limit": {}},
            "deepseek-negative": {
                "id": "deepseek-negative",
                "cost": {"input": -1, "output": 1},
            },
            "deepseek-text": {
                "id": "deepseek-text",
                "cost": {"input": 1, "output": 2, "cache_write": "free"},
            },
            "deepseek-half": {"id": "deepseek-half", "cost": {"input": 1}},
        },
    },
    "zhipuai": {
        "id": "zhipuai",
        "models": {
            "glm-5.2": {
                "id": "glm-5.2",
                "cost": {
                    "input": 1.4,
                    "output": 4.4,
                    "cache_read": 0.28,
                    "cache_write": 0,
                },
            }
        },
    },
    "kitani": {
        "id": "kitani",
        "models": {"k-1": {"id": "k-1", "cost": {"input": 1, "output": 1}}},
    },
}


def big_list(count: int) -> dict:
    """A list whose kept providers hold this many priced models."""
    return {
        "openrouter": {
            "models": {
                f"m-{index}": {"cost": {"input": 1, "output": 2}}
                for index in range(count)
            }
        }
    }


def body_of(document) -> bytes:
    return json.dumps(document).encode()


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.setattr(model_prices.constants, "UTILS_STATE_ROOT", tmp_path)
    return tmp_path


def test_a_recorded_list_is_kept_down_to_the_priced_providers_and_four_prices():
    kept = kept_prices(RECORDED, {"deepseek", "zhipuai", "anthropic"})

    assert kept == {
        "deepseek": {
            "deepseek-v4-pro": {"input": 0.28, "output": 1.1, "cache_read": 0.028}
        },
        "zhipuai": {
            "glm-5.2": {
                "input": 1.4,
                "output": 4.4,
                "cache_read": 0.28,
                "cache_write": 0,
            }
        },
    }
    assert priced_count(kept) == 2


def test_the_kept_providers_are_each_endpoints_and_each_logins():
    providers = kept_providers(load_vendors())

    assert providers == {
        "deepseek",
        "moonshotai-cn",
        "moonshotai",
        "zhipuai",
        "zai",
        "alibaba-cn",
        "alibaba",
        "volcengine",
        "minimax-cn",
        "minimax",
        "openrouter",
        "siliconflow-cn",
        "siliconflow",
        "mistral",
        "xai",
        "anthropic",
        "openai",
        "google",
    }


@pytest.mark.parametrize(
    "limit, body, reason",
    [
        (1000, b"x" * 1001, "larger than 1000 bytes"),
        (None, b"<html>not json</html>", "not JSON"),
        (None, b"[1, 2, 3]", "no object at the top level"),
        (None, body_of(big_list(49)), "fewer than 50 priced models"),
        (None, body_of(big_list(60)), "fewer than half the snapshot's priced models"),
    ],
    ids=["too large", "no JSON", "no object", "below 50", "below half"],
)
def test_a_download_is_refused_above_the_limit_as_no_json_no_object_or_too_few(
    monkeypatch, limit, body, reason
):
    if limit is not None:
        monkeypatch.setattr(model_prices, "AI_PRICES_LIMIT_BYTES", limit)

    document, refused, _count = checked_prices(
        body,
        providers={"openrouter"},
        snapshot_count=121,
        fetched_at="2026-11-26T00:00:00Z",
    )

    assert document is None
    assert refused == reason


def test_a_passing_download_is_written_by_a_rename_and_is_then_in_force(
    state, monkeypatch
):
    monkeypatch.setattr(
        model_prices,
        "read_snapshot",
        lambda: {"fetched_at": "2026-11-20T00:00:00Z", "providers": {}},
    )

    outcome = refresh_model_prices(
        providers={"openrouter"},
        download=lambda: body_of(big_list(60)),
        now=datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc),
    )

    assert outcome == PRICES_WRITTEN
    stored = state / "cliproxyapi/model_prices.json"
    assert stored.stat().st_mode & 0o777 == 0o600
    assert [path.name for path in stored.parent.iterdir()] == ["model_prices.json"]
    assert read_stored_prices()["fetched_at"] == "2026-11-26T08:00:00Z"
    assert priced_count(read_stored_prices()["providers"]) == 60


def test_a_refused_download_keeps_the_copy_in_force_and_logs_one_line(
    state, monkeypatch, caplog
):
    monkeypatch.setattr(
        model_prices,
        "read_snapshot",
        lambda: {"fetched_at": "2026-11-20T00:00:00Z", "providers": {}},
    )
    refresh_model_prices(
        providers={"openrouter"}, download=lambda: body_of(big_list(60))
    )
    before = read_stored_prices()

    with caplog.at_level(logging.WARNING, logger=model_prices.__name__):
        outcome = refresh_model_prices(
            providers={"openrouter"}, download=lambda: body_of(big_list(3))
        )

    assert outcome == PRICES_REFUSED
    assert read_stored_prices() == before
    (line,) = [record.getMessage() for record in caplog.records]
    assert "fewer than 50 priced models" in line
    assert "3 priced models kept" in line


def test_a_read_that_does_not_complete_fails_and_writes_nothing(state):
    def unreachable():
        raise OSError("no route to host")

    assert refresh_model_prices(providers={"openrouter"}, download=unreachable) == (
        PRICES_FAILED
    )
    assert read_stored_prices() is None


def test_the_copy_in_force_is_the_later_of_the_stored_copy_and_the_snapshot(
    state, monkeypatch
):
    snapshot = {"fetched_at": "2026-11-26T06:41:54Z", "providers": {"a": {}}}
    monkeypatch.setattr(model_prices, "read_snapshot", lambda: snapshot)
    stored = state / "cliproxyapi/model_prices.json"
    stored.parent.mkdir(parents=True)

    stored.write_text(
        json.dumps({"fetched_at": "2026-11-25T00:00:00Z", "providers": {}})
    )
    assert prices_in_force() == snapshot

    stored.write_text(
        json.dumps({"fetched_at": "2026-11-27T00:00:00Z", "providers": {}})
    )
    assert prices_in_force()["fetched_at"] == "2026-11-27T00:00:00Z"


def test_a_failed_read_is_tried_again_in_an_hour_and_a_refused_one_the_next_day():
    assert next_read_wait_s(PRICES_FAILED, interval_s=86400, retry_s=3600) == 3600
    assert next_read_wait_s(PRICES_REFUSED, interval_s=86400, retry_s=3600) == 86400
    assert next_read_wait_s(PRICES_WRITTEN, interval_s=86400, retry_s=3600) == 86400


def test_the_panels_start_reads_when_the_copy_in_force_is_a_day_old():
    now = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)

    assert seconds_until_due("2026-11-26T06:00:00Z", interval_s=86400, now=now) == 0
    assert seconds_until_due("2026-11-27T06:00:00Z", interval_s=86400, now=now) == 64800
    assert seconds_until_due("", interval_s=86400, now=now) == 0


def test_the_shipped_snapshot_passes_the_same_checks():
    snapshot = read_snapshot()
    raw = json.loads(AI_PRICES_SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert datetime.strptime(snapshot["fetched_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert set(snapshot["providers"]) <= kept_providers(load_vendors())
    # Each model kept again from its own prices is the same: every price is
    # a number of at least 0, and input and output are there.
    as_list = {
        provider: {
            "models": {model: {"cost": price} for model, price in models.items()}
        }
        for provider, models in raw["providers"].items()
    }
    assert kept_prices(as_list, set(raw["providers"])) == raw["providers"]
    document, reason, count = checked_prices(
        json.dumps(as_list).encode(),
        providers=kept_providers(load_vendors()),
        snapshot_count=count_of_snapshot(),
        fetched_at=snapshot["fetched_at"],
    )
    assert reason == ""
    assert count == count_of_snapshot() == 784


def count_of_snapshot() -> int:
    return priced_count(read_snapshot()["providers"])


# --- each record's price, by its upstream ---


TABLE = AiPriceTable(
    {
        "deepseek": {
            "DeepSeek-V4-Pro": {"input": 0.28, "output": 1.1, "cache_read": 0.028}
        },
        "anthropic": {
            "claude-opus-5-5": {"input": 5, "output": 25, "cache_write": 6.25}
        },
        "openai": {"gpt-6.2-astra": {"input": 1.25, "output": 10}},
        "google": {"gemini-4-neon": {"input": 2, "output": 12}},
        "moonshotai": {"kimi-k3": {"input": 0.6, "output": 2.5}},
        "xai": {"grok-4.7": {"input": 3, "output": 15}},
    }
)


def record(model: str, **fields) -> dict:
    """One request of 1000 uncached tokens, 100 cache reads, 10 cache writes and 100 out."""
    return {
        "model": model,
        "alias": "",
        "provider": "",
        "token_breakdown": {
            "schema_version": 2,
            "quality": "complete",
            "input": {
                "total_tokens": 1110,
                "uncached_tokens": 1000,
                "cache_read_tokens": 100,
                "cache_write_tokens": 10,
            },
            "output": {"total_tokens": 100},
        },
        **fields,
    }


def pricer(set_prices=None) -> AiRecordPricer:
    return AiRecordPricer(
        table=TABLE,
        set_prices=set_prices or {},
        providers={
            "ds": AiProviderRecord(
                id="ds", name="DS", kind="custom", base_url="https://api.deepseek.com/"
            ),
            "relay": AiProviderRecord(
                id="relay", name="Relay", kind="custom", base_url="https://r.example/v1"
            ),
            "claude-key": AiProviderRecord(id="claude-key", name="C", kind="anthropic"),
        },
        accounts={
            "c.json": "claude",
            "x.json": "codex",
            "g.json": "antigravity",
            "k.json": "kimi",
            "grok.json": "xai",
        },
        endpoints=vendor_endpoints(load_vendors()),
        ollama_providers=["openai-compatible-ollama-dev"],
        ollama_names=["qwen2.5:7b"],
    )


@pytest.mark.parametrize(
    "upstream, model, kind, amount",
    [
        # 1000 x 0.28 + 100 x 0.028 + 10 x 0.28 + 100 x 1.1
        ("ds", "deepseek-v4-pro", "cost", 396),
        ("claude-key", "claude-opus-5-5", "cost", 8063),
        ("c.json", "claude-opus-5-5", "api_value", 8063),
        ("x.json", "gpt-6.2-astra", "api_value", 2388),
        ("g.json", "gemini-4-neon", "api_value", 3420),
        ("k.json", "kimi-k3", "api_value", 916),
        ("grok.json", "grok-4.7", "api_value", 4830),
    ],
)
def test_each_upstream_is_priced_at_its_models_dev_provider(
    upstream, model, kind, amount
):
    charge = pricer().charge(record(model), upstream)

    assert (charge.kind, charge.currency, charge.amount) == (kind, "USD", amount)


def test_the_model_is_matched_whole_and_without_case():
    assert pricer().charge(record("DEEPSEEK-V4-PRO"), "ds").kind == "cost"
    assert pricer().charge(record("deepseek-v4"), "ds").kind == "unpriced"
    assert pricer().charge(record("deepseek-v4-pro"), "relay").kind == "unpriced"


def test_an_ollama_record_has_no_price_and_no_count():
    charge = pricer().charge(
        record("qwen2.5:7b", provider="openai-compatible-ollama-dev"), ""
    )

    assert charge.kind == "none"


def test_a_persons_price_keeps_models_devs_cache_ratio_in_the_persons_currency():
    charge = pricer(
        {"deepseek-v4-pro": {"input": 2, "output": 8, "currency": "CNY"}}
    ).charge(record("deepseek-v4-pro"), "ds")

    # Cache read at 2 x 0.028 / 0.28 = 0.2; models.dev gives no cache write,
    # so it is the person's input price: 2000 + 20 + 20 + 800.
    assert (charge.kind, charge.currency, charge.amount) == ("cost", "CNY", 2840)


def test_a_persons_price_prices_a_name_models_dev_does_not():
    charge = pricer(
        {"relay-model": {"input": 1, "output": 3, "currency": "USD"}}
    ).charge(record("upstream-name", alias="relay-model"), "relay")

    assert (charge.kind, charge.amount) == ("cost", 1000 + 100 + 10 + 300)


def test_a_cache_price_models_dev_does_not_give_is_the_input_price():
    # gpt-6.2-astra names no cache price: 1110 x 1.25 + 100 x 10.
    assert pricer().charge(record("gpt-6.2-astra"), "x.json").amount == 2388
