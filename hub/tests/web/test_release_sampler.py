"""The daily read of the module version feeds.

What these pin: a panel's first start reads; a start inside a day of the last
good read reads nothing and waits out what is left of the day; a start a day
later reads; a start over an empty list or an unreadable time reads whatever
the time says; and a read that failed leaves the wait at a whole day.
"""

from datetime import datetime, timedelta, timezone

import pytest

from neutrino_hub.modules.devices.module_releases import ModuleReleaseStore
from neutrino_hub.web.release_sampler import PanelReleaseSampler

DAY_S = 24 * 60 * 60
LISTED = {"app": {"linux": [{"version": "1.2.0", "artifacts": {}}]}}


class CountingReader:
    """Stands in for the feeds: each read lands in the store, or fails."""

    def __init__(self, store, *, error=None):
        self.store = store
        self.reads = 0
        self.error = error

    def read(self):
        self.reads += 1
        if self.error is not None:
            raise self.error
        self.store.replace(LISTED)
        return LISTED


class OneRound:
    """The sampler's stop event: a wait of 0 goes on, and any other ends the loop."""

    def __init__(self):
        self.waits: list = []

    def wait(self, timeout):
        self.waits.append(timeout)
        return timeout > 0

    def set(self):
        pass


def panel_start(store, reader) -> list:
    """One panel's start up to its first long wait, in this thread.

    Returns:
        The waits the loop asked for.
    """
    sampler = PanelReleaseSampler(store=store, fetcher=object())
    sampler._reader = reader
    sampler._is_stopped = OneRound()
    sampler._loop()
    return sampler._is_stopped.waits


def hours_ago(hours: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(hours=hours)
    return moment.isoformat(timespec="seconds")


@pytest.fixture
def store(tmp_path):
    return ModuleReleaseStore(path=tmp_path / "module_releases.json")


def test_two_restarts_inside_a_day_read_the_feeds_once(store):
    reader = CountingReader(store)

    panel_start(store, reader)
    panel_start(store, reader)
    panel_start(store, reader)

    assert reader.reads == 1
    assert store.listed_by_key("app", "linux") == LISTED["app"]["linux"]


def test_a_start_inside_a_day_waits_out_what_is_left_of_it(store):
    store.replace(LISTED, read_at=hours_ago(6))
    reader = CountingReader(store)

    waits = panel_start(store, reader)

    assert reader.reads == 0
    assert len(waits) == 1
    assert 18 * 3600 - 60 < waits[0] <= 18 * 3600


def test_a_start_over_a_day_after_the_last_good_read_reads(store):
    store.replace(LISTED, read_at=hours_ago(25))
    reader = CountingReader(store)

    waits = panel_start(store, reader)

    assert reader.reads == 1
    assert waits == [0.0, DAY_S]


@pytest.mark.parametrize("modules", [{}, {"app": {"linux": []}}])
def test_a_start_over_an_empty_list_reads_whatever_its_time_says(store, modules):
    store.replace(modules, read_at=hours_ago(1))
    reader = CountingReader(store)

    panel_start(store, reader)

    assert reader.reads == 1


@pytest.mark.parametrize("read_at", ["yesterday", "2026-10-30T01:02:03"])
def test_a_start_over_a_time_that_does_not_read_reads(store, read_at):
    store.replace(LISTED, read_at=read_at)
    reader = CountingReader(store)

    panel_start(store, reader)

    assert reader.reads == 1


def test_a_time_in_the_future_waits_one_day_at_most(store):
    moment = datetime.now(timezone.utc) + timedelta(days=30)
    store.replace(LISTED, read_at=moment.isoformat(timespec="seconds"))

    assert store.seconds_until_due(DAY_S) == DAY_S


def test_a_read_that_fails_leaves_the_list_and_waits_the_whole_interval(store):
    store.replace(LISTED, read_at=hours_ago(25))
    reader = CountingReader(store, error=OSError("no network"))

    waits = panel_start(store, reader)

    assert waits == [0.0, DAY_S]
    assert store.listed_by_key("app", "linux") == LISTED["app"]["linux"]
