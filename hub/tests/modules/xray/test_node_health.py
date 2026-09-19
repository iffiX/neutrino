"""What a node's window says, and what survives a restart.

The three readings a node has are pinned here: down is the newest sample
failing, alive is the newest sample answering, and unknown is a window with
nothing in it — which is what a node nobody has measured for hours reads as,
whatever the file still holds for it.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from neutrino_hub.modules.xray.constants import (
    XRAY_HEALTH_FAILURE_PENALTY_MS,
    XRAY_HEALTH_SAMPLE_MAX_AGE_S,
    XRAY_HEALTH_WINDOW_SAMPLES,
    XRAY_NODE_HEALTH_RELATIVE,
)
from neutrino_hub.modules.xray.node_health import XrayNodeHealthStore

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
TAG = "node_hk1"


def store_at(tmp_path) -> XrayNodeHealthStore:
    """A store with its file inside the test's own directory."""
    return XrayNodeHealthStore(path=tmp_path / "xray_node_health.json")


def test_the_window_keeps_only_the_newest_samples(tmp_path):
    """The count bounds the file and the arithmetic."""
    store = store_at(tmp_path)
    for index in range(XRAY_HEALTH_WINDOW_SAMPLES + 5):
        store.record(TAG, connect_ms=10, request_ms=index, now=NOW)

    health = store.health_of(TAG, now=NOW)

    assert health.sample_count == XRAY_HEALTH_WINDOW_SAMPLES
    assert health.samples[-1].request_ms == XRAY_HEALTH_WINDOW_SAMPLES + 4


def test_a_sample_older_than_the_window_is_not_in_it(tmp_path):
    """The age bounds how stale a reading may be after the box was off,
    whatever the interval is set to."""
    store = store_at(tmp_path)
    store.record(
        TAG,
        connect_ms=10,
        request_ms=100,
        now=NOW - timedelta(seconds=XRAY_HEALTH_SAMPLE_MAX_AGE_S + 60),
    )
    store.record(TAG, connect_ms=10, request_ms=200, now=NOW)

    health = store.health_of(TAG, now=NOW)

    assert health.sample_count == 1
    assert health.samples[0].request_ms == 200


def test_a_node_nobody_measured_for_days_is_neither_alive_nor_down(tmp_path):
    """Unknown is a third reading, and it must never move the exit."""
    probed_at = NOW - timedelta(days=3)
    store = store_at(tmp_path)
    store.record(TAG, connect_ms=10, request_ms=100, now=probed_at)

    health = store.health_of(TAG, now=NOW)

    assert health.sample_count == 0
    assert health.is_alive is False
    assert health.is_down is False
    assert health.probed_at == probed_at
    assert health.succeeded_at == probed_at
    assert health.score_ms is None


def test_the_score_is_the_median_the_spread_and_what_the_failures_cost(tmp_path):
    store = store_at(tmp_path)
    for request_ms in (100, 100, 100):
        store.record(TAG, connect_ms=10, request_ms=request_ms, now=NOW)
    store.record(TAG, connect_ms=10, request_ms=None, now=NOW)
    store.record(TAG, connect_ms=10, request_ms=100, now=NOW)

    health = store.health_of(TAG, now=NOW)

    assert health.success_rate == 0.8
    assert health.median_ms == 100
    assert health.jitter_ms == 0
    assert health.score_ms == pytest.approx(100 + XRAY_HEALTH_FAILURE_PENALTY_MS * 0.2)


def test_one_slow_answer_does_not_move_the_score(tmp_path):
    """A median, not a mean: a single spike would otherwise cost a good node
    the exit for a whole window."""
    store = store_at(tmp_path)
    for request_ms in (100, 100, 100, 100, 5000):
        store.record(TAG, connect_ms=10, request_ms=request_ms, now=NOW)

    health = store.health_of(TAG, now=NOW)

    assert health.median_ms == 100
    assert health.jitter_ms == 0
    assert health.score_ms == 100


def test_the_spread_of_a_node_is_the_deviation_around_its_median(tmp_path):
    store = store_at(tmp_path)
    for request_ms in (100, 120, 140):
        store.record(TAG, connect_ms=10, request_ms=request_ms, now=NOW)

    health = store.health_of(TAG, now=NOW)

    assert health.median_ms == 120
    assert health.jitter_ms == 20
    assert health.score_ms == 140


def test_a_node_whose_newest_sample_failed_is_down(tmp_path):
    store = store_at(tmp_path)
    store.record(TAG, connect_ms=10, request_ms=100, now=NOW)
    store.record(TAG, connect_ms=None, request_ms=None, now=NOW)

    health = store.health_of(TAG, now=NOW)

    assert health.is_down
    assert health.is_alive is False
    assert health.succeeded_at == NOW
    assert health.probed_at == NOW


def test_what_was_measured_and_pinned_survives_a_restart(tmp_path):
    store = store_at(tmp_path)
    store.record(TAG, connect_ms=42, request_ms=186, now=NOW)
    store.set_exit(TAG, now=NOW)
    store.save()

    reloaded = store_at(tmp_path)
    reloaded.load()

    assert reloaded.exit_tag == TAG
    assert reloaded.exit_since == NOW
    health = reloaded.health_of(TAG, now=NOW)
    assert health.sample_count == 1
    assert health.samples[0].connect_ms == 42
    assert health.samples[0].request_ms == 186
    assert health.probed_at == NOW
    assert health.succeeded_at == NOW


def test_a_failed_measurement_is_stored_as_a_missing_number(tmp_path):
    store = store_at(tmp_path)
    store.record(TAG, connect_ms=42, request_ms=None, now=NOW)
    store.save()

    written = json.loads((tmp_path / "xray_node_health.json").read_text())

    assert written["nodes"][TAG]["samples"][0]["request_ms"] is None
    assert written["nodes"][TAG]["succeeded_at"] is None


def test_a_file_that_will_not_parse_loads_as_empty(tmp_path):
    """A state file is never worth refusing to start over: measuring again
    costs one round."""
    (tmp_path / "xray_node_health.json").write_text("{not json at all")
    store = store_at(tmp_path)

    store.load()

    assert store.exit_tag == ""
    assert store.health() == {}


def test_a_sample_with_an_unreadable_stamp_is_dropped_and_the_rest_kept(tmp_path):
    (tmp_path / "xray_node_health.json").write_text(
        json.dumps(
            {
                "exit": {"tag": TAG, "since": "not a stamp"},
                "nodes": {
                    TAG: {
                        "probed_at": NOW.isoformat(),
                        "samples": [
                            {"at": "yesterday", "request_ms": 1},
                            {"at": NOW.isoformat(), "connect_ms": 4, "request_ms": 9},
                        ],
                    }
                },
            }
        )
    )
    store = store_at(tmp_path)

    store.load()

    assert store.exit_tag == TAG
    assert store.exit_since is None
    assert store.health_of(TAG, now=NOW).sample_count == 1


def test_a_node_the_list_no_longer_names_is_dropped_on_the_next_save(tmp_path):
    store = store_at(tmp_path)
    store.record(TAG, connect_ms=10, request_ms=100, now=NOW)
    store.record("node_gone", connect_ms=10, request_ms=100, now=NOW)

    store.save(tags=[TAG])

    written = json.loads((tmp_path / "xray_node_health.json").read_text())
    assert list(written["nodes"]) == [TAG]


def test_the_pin_stamp_moves_only_when_the_pin_does(tmp_path):
    """The dwell time measures how long this exit has held, so a round that
    chose the same node again must not restart it."""
    store = store_at(tmp_path)
    store.set_exit(TAG, now=NOW)

    store.set_exit(TAG, now=NOW + timedelta(minutes=10))

    assert store.exit_since == NOW


def test_the_file_is_found_under_the_state_root_as_it_is_now(tmp_path, monkeypatch):
    """The root is redirected while the process runs, so a path bound at import
    would write to the real machine."""
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path)
    store = XrayNodeHealthStore()
    store.record(TAG, connect_ms=10, request_ms=100, now=NOW)

    store.save()

    assert (tmp_path / XRAY_NODE_HEALTH_RELATIVE).is_file()
