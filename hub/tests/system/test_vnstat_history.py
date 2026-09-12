"""Reading vnstat's JSON into history buckets: one label shape per mode."""

import json

from neutrino_hub.system import vnstat_history
from neutrino_hub.system.vnstat_history import VnstatHistoryReader


class _Ran:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.stderr = ""
        self.is_success = True
        self.exit_code = 0


def _vnstat(monkeypatch, key: str, buckets: list) -> list:
    """A vnstat answering the given buckets under one mode key, recording its call."""
    calls = []

    def run(command, **keywords):
        calls.append(command)
        payload = {"interfaces": [{"name": "enp2s0", "traffic": {key: buckets}}]}
        return _Ran(json.dumps(payload))

    monkeypatch.setattr(vnstat_history, "run", run)
    return calls


def test_a_month_is_labelled_by_its_year_and_month(monkeypatch):
    calls = _vnstat(
        monkeypatch,
        "month",
        [{"date": {"year": 2026, "month": 9}, "rx": 10, "tx": 3}],
    )

    samples = VnstatHistoryReader(interface="enp2s0").monthly(month_count=12)

    assert calls[0][:4] == ["vnstat", "--json", "m", "12"]
    assert [(s.label, s.received_bytes, s.sent_bytes) for s in samples] == [
        ("2026-09", 10, 3)
    ]


def test_an_hour_is_labelled_to_the_hour(monkeypatch):
    _vnstat(
        monkeypatch,
        "hour",
        [
            {
                "date": {"year": 2026, "month": 9, "day": 12},
                "time": {"hour": 7},
                "rx": 1,
                "tx": 2,
            }
        ],
    )

    samples = VnstatHistoryReader(interface="enp2s0").hourly(hour_count=24)

    assert samples[0].label == "2026-09-12 07:00"


def test_a_day_is_labelled_by_its_date(monkeypatch):
    _vnstat(
        monkeypatch,
        "day",
        [{"date": {"year": 2026, "month": 9, "day": 12}, "rx": 1, "tx": 2}],
    )

    samples = VnstatHistoryReader(interface="enp2s0").daily(day_count=7)

    assert samples[0].label == "2026-09-12"
