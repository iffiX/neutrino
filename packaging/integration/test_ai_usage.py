"""The AI usage data path against a live box.

What no unit test can promise: that the installed panel answers the usage
contract end to end — the store behind it, the journal, the served order —
on the box the collector actually runs on. Everything here is read-only
except the order roundtrip, which puts the original order back.
"""

USAGE_RANGES = {"day": 24, "week": 7, "month": 30, "year": 365}
COUNTER_FIELDS = (
    "requests",
    "failed",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)


def test_usage_answers_the_contract_shape(panel):
    for range_name, bucket_count in USAGE_RANGES.items():
        status, body = panel.call("GET", f"/cliproxyapi/usage?range={range_name}")
        assert status == 200, body
        assert body["range"] == range_name
        assert body["generated_at"].endswith("Z")
        assert set(body["rates"]) == {"rpm", "tpm"}
        for field in COUNTER_FIELDS:
            assert body["totals"][field] >= 0
        assert len(body["series"]) == bucket_count
        for entry in body["series"]:
            assert set(entry) == {"bucket", *COUNTER_FIELDS}
        for key in body["keys"]:
            assert key["key_id"]
            assert "device_name" in key
        for provider in body["providers"]:
            assert provider["provider_id"]
            assert len(provider["health"]) == 5


def test_usage_providers_come_in_served_order(panel):
    status, listed = panel.call("GET", "/ai/providers")
    assert status == 200, listed
    status, body = panel.call("GET", "/cliproxyapi/usage?range=day")
    assert status == 200, body
    assert [entry["provider_id"] for entry in body["providers"]] == [
        provider["id"] for provider in listed["providers"]
    ]


def test_usage_refusals_are_coded(panel):
    status, body = panel.call("GET", "/cliproxyapi/usage?range=fortnight")
    assert status == 422
    assert body["detail"] == {
        "code": "invalid_range",
        "params": {"range": "fortnight"},
    }

    status, body = panel.call("GET", "/cliproxyapi/usage?range=day&key_id=no-such")
    assert status == 404
    assert body["detail"]["code"] == "unknown_key"


def test_the_journal_serves_lines(panel):
    status, body = panel.call("GET", "/cliproxyapi/journal?lines=5")
    assert status == 200, body
    assert isinstance(body["lines"], list)
    assert all(isinstance(line, str) for line in body["lines"])


def test_the_status_carries_the_day_counters(panel):
    status, body = panel.call("GET", "/cliproxyapi")
    assert status == 200, body
    assert body["requests_today"] >= 0
    assert body["tokens_today"] >= 0


def test_the_order_roundtrip_and_its_refusal(panel):
    status, listed = panel.call("GET", "/ai/providers")
    assert status == 200, listed
    original = [provider["id"] for provider in listed["providers"]]

    status, body = panel.call(
        "PUT", "/ai/providers/order", {"provider_ids": ["no-such", *original]}
    )
    assert status == 422
    assert body["detail"]["code"] == "provider_order_mismatch"
    assert body["detail"]["params"]["unknown"] == ["no-such"]

    reordered = list(reversed(original))
    status, body = panel.call(
        "PUT", "/ai/providers/order", {"provider_ids": reordered}
    )
    assert status == 200, body
    assert [provider["id"] for provider in body["providers"]] == reordered
    try:
        status, body = panel.call("GET", "/ai/providers")
        assert [provider["id"] for provider in body["providers"]] == reordered
    finally:
        status, body = panel.call(
            "PUT", "/ai/providers/order", {"provider_ids": original}
        )
        assert status == 200, body
    status, listed = panel.call("GET", "/ai/providers")
    assert [provider["id"] for provider in listed["providers"]] == original
