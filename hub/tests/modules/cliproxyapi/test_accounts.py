"""An account's quota windows: from the gateway's signals and from a vendor's usage answer.

The auth-file entries are shaped as CLIProxyAPI 7.2.146 lists them
(``internal/api/handlers/management/auth_files.go``): the signals under
their canonical header names, ``observed_at`` and ``next_retry_after`` with
nanoseconds, a Codex ID token already reduced to its claims. The vendor
answers are shaped as each vendor's usage endpoint answers, trimmed to the
fields the read takes.
"""

from datetime import datetime, timezone

from neutrino_hub.modules.cliproxyapi import accounts as accounts_module
from neutrino_hub.modules.cliproxyapi.accounts import (
    _account,
    forget_quota_read,
    merged_windows,
    read_quota_store,
    read_windows,
    signal_windows,
    store_quota_read,
)

CLAUDE_ENTRY = {
    "name": "claude-person.json",
    "auth_index": "a14afd0dfcb7d3e3",  # scan: allow
    "provider": "claude",
    "status": "active",
    "unavailable": False,
    "next_retry_after": "2026-11-26T09:00:00.123456789Z",
    "quota": {
        "observed_at": "2026-11-26T08:10:05.987654321Z",
        "signals": {
            "Anthropic-Ratelimit-Unified-5h-Utilization": "0.23",
            "Anthropic-Ratelimit-Unified-5h-Reset": "1795680000",
            "Anthropic-Ratelimit-Unified-7d-Utilization": "0.61",
            "Anthropic-Ratelimit-Unified-7d-Reset": "1796112000",
            "Anthropic-Ratelimit-Unified-Status": "allowed",
        },
    },
}

CODEX_ENTRY = {
    "name": "codex-person.json",
    "auth_index": "b25bfe1e0dc8e4f4",  # scan: allow
    "provider": "codex",
    "unavailable": True,
    "next_retry_after": "2026-11-26T09:30:00Z",
    "id_token": {
        "chatgpt_account_id": "acct-1",
        "plan_type": "plus",
        "chatgpt_subscription_active_start": "2026-11-01T00:00:00Z",
        "chatgpt_subscription_active_until": "2026-12-01T00:00:00+00:00",
    },
    "quota": {
        "observed_at": "2026-11-26T08:00:00Z",
        "signals": {
            "X-Codex-Primary-Used-Percent": "42",
            "X-Codex-Primary-Window-Minutes": "300",
            "X-Codex-Primary-Reset-At": "1795680000",
            "X-Codex-Secondary-Used-Percent": "7.5",
            "X-Codex-Secondary-Window-Minutes": "10080",
            "X-Codex-Secondary-Reset-At": "1796112000",
            "X-Codex-Plan-Type": "plus",
        },
    },
}


def test_claudes_windows_come_from_its_signals_with_the_time_they_were_seen():
    account = _account(CLAUDE_ENTRY)

    assert account.signal_windows == [
        {
            "name": "5h",
            "used_share": 0.23,
            "resets_at": "2026-11-26T08:00:00Z",
            "seen_at": "2026-11-26T08:10:05Z",
            "origin": "signal",
        },
        {
            "name": "7d",
            "used_share": 0.61,
            "resets_at": "2026-12-01T08:00:00Z",
            "seen_at": "2026-11-26T08:10:05Z",
            "origin": "signal",
        },
    ]
    # A time the gateway names is kept only while it cools the account.
    assert account.next_retry_after == ""
    assert (account.plan, account.subscription_ends_at) == ("", "")


def test_codexs_windows_are_named_by_their_minutes_and_its_plan_read_from_its_token():
    account = _account(CODEX_ENTRY)

    assert [
        (window["name"], window["used_share"]) for window in account.signal_windows
    ] == [("5h", 0.42), ("7d", 0.075)]
    assert account.next_retry_after == "2026-11-26T09:30:00Z"
    assert account.plan == "plus"
    assert account.subscription_ends_at == "2026-12-01T00:00:00Z"
    assert account.vendor_account_id == "acct-1"


def test_a_codex_window_of_another_length_is_named_by_its_minutes():
    windows = signal_windows(
        "codex",
        {
            "observed_at": "2026-11-26T08:00:00Z",
            "signals": {
                "X-Codex-Primary-Used-Percent": "10",
                "X-Codex-Primary-Window-Minutes": "1440",
            },
        },
    )

    assert [(window["name"], window["resets_at"]) for window in windows] == [
        ("1440", "")
    ]


def test_a_signal_that_does_not_parse_drops_its_window_and_other_logins_have_none():
    windows = signal_windows(
        "claude",
        {
            "signals": {
                "Anthropic-Ratelimit-Unified-5h-Utilization": "most",
                "Anthropic-Ratelimit-Unified-7d-Utilization": "0.5",
                "Anthropic-Ratelimit-Unified-7d-Reset": "soon",
            }
        },
    )

    assert windows == []
    assert signal_windows("kimi", CLAUDE_ENTRY["quota"]) == []


def test_claudes_read_takes_its_percent_as_a_share():
    answer = {
        "five_hour": {"utilization": 12.0, "resets_at": "2026-11-26T15:00:00Z"},
        "seven_day": {"utilization": 25.0, "resets_at": None},
        "seven_day_opus": {"utilization": 8.0},
    }

    assert read_windows("claude", answer) == [
        {"name": "5h", "used_share": 0.12, "resets_at": "2026-11-26T15:00:00Z"},
        {"name": "7d", "used_share": 0.25, "resets_at": ""},
    ]


def test_codexs_read_names_each_window_by_its_seconds():
    answer = {
        "plan_type": "plus",
        "rate_limit": {
            "primary_window": {
                "used_percent": 42,
                "limit_window_seconds": 18000,
                "reset_at": 1795680000,
            },
            "secondary_window": {
                "used_percent": 100,
                "limit_window_seconds": 604800,
                "reset_at": 1796112000,
            },
        },
    }

    assert read_windows("codex", answer) == [
        {"name": "5h", "used_share": 0.42, "resets_at": "2026-11-26T08:00:00Z"},
        {"name": "7d", "used_share": 1.0, "resets_at": "2026-12-01T08:00:00Z"},
    ]


def test_kimis_read_takes_its_ratio_as_it_is():
    answer = {
        "usages": {
            "limit_5h": {"used_ratio": 0, "reset_time": "2026-10-06T13:23:46Z"},
            "limit_7d": {"used_ratio": 0.3, "reset_time": "2026-10-09T00:00:00Z"},
            "limit_month_total": {
                "used_ratio": 0.5531,
                "reset_time": "2026-10-22T14:26:29Z",
            },
        }
    }

    assert read_windows("kimi", answer) == [
        {"name": "5h", "used_share": 0.0, "resets_at": "2026-10-06T13:23:46Z"},
        {"name": "7d", "used_share": 0.3, "resets_at": "2026-10-09T00:00:00Z"},
        {"name": "month", "used_share": 0.5531, "resets_at": "2026-10-22T14:26:29Z"},
    ]


def test_antigravitys_read_is_one_window_per_model_of_what_is_used():
    answer = {
        "models": {
            "gemini-4-neon": {
                "quotaInfo": {
                    "remainingFraction": 0.8,
                    "resetTime": "2026-11-26T12:00:00Z",
                }
            },
            "claude-opus-5-5": {"quotaInfo": {"remainingFraction": 1}},
            "no-quota-model": {"displayName": "No quota"},
        }
    }

    assert read_windows("antigravity", answer) == [
        {"name": "claude-opus-5-5", "used_share": 0.0, "resets_at": ""},
        {
            "name": "gemini-4-neon",
            "used_share": 0.2,
            "resets_at": "2026-11-26T12:00:00Z",
        },
    ]


def test_a_field_that_does_not_parse_drops_its_window_and_none_left_reads_as_none():
    answer = {
        "usages": {
            "limit_5h": {"used_ratio": "half", "reset_time": "2026-10-06T13:23:46Z"},
            "limit_7d": {"used_ratio": 0.3, "reset_time": "next week"},
            "limit_month_total": {
                "used_ratio": 0.5,
                "reset_time": "2026-10-22T14:26:29Z",
            },
        }
    }

    assert [window["name"] for window in read_windows("kimi", answer)] == ["month"]
    assert read_windows("kimi", {"usages": {"limit_5h": {"used": 3}}}) == []
    assert read_windows("codex", {"error": "moved"}) == []
    assert read_windows("claude", "not an object") == []


def test_the_later_of_a_signal_and_a_read_wins_for_a_window_both_name():
    signals = signal_windows("claude", CLAUDE_ENTRY["quota"])
    later_read = {
        "read_at": "2026-11-26T08:30:00Z",
        "windows": [{"name": "5h", "used_share": 0.4, "resets_at": ""}],
    }
    earlier_read = {
        "read_at": "2026-11-26T08:00:00Z",
        "windows": [
            {"name": "5h", "used_share": 0.1, "resets_at": ""},
            {"name": "month", "used_share": 0.9, "resets_at": ""},
        ],
    }

    merged = merged_windows(signals, later_read)
    assert [(w["name"], w["used_share"], w["origin"]) for w in merged] == [
        ("5h", 0.4, "read"),
        ("7d", 0.61, "signal"),
    ]
    merged = merged_windows(signals, earlier_read)
    assert [(w["name"], w["used_share"], w["origin"]) for w in merged] == [
        ("5h", 0.23, "signal"),
        ("7d", 0.61, "signal"),
        ("month", 0.9, "read"),
    ]


def test_a_read_is_stored_by_token_file_and_removed_with_its_account(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(accounts_module.constants, "UTILS_STATE_ROOT", tmp_path)
    windows = [{"name": "5h", "used_share": 0.12, "resets_at": ""}]

    store_quota_read(
        "claude-person.json",
        windows,
        now=datetime(2026, 11, 26, 8, 30, tzinfo=timezone.utc),
    )
    store_quota_read("kimi-person.json", windows)

    assert read_quota_store()["claude-person.json"] == {
        "read_at": "2026-11-26T08:30:00Z",
        "windows": windows,
    }
    assert (tmp_path / "cliproxyapi/account_quota.json").stat().st_mode & 0o777 == 0o600
    forget_quota_read("claude-person.json")
    assert set(read_quota_store()) == {"kimi-person.json"}
