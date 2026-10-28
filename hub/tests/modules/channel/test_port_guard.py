"""The failed admissions on the agent port, counted over the whole port.

Every peer through the relay comes from loopback, so these pin that nothing
is counted per address: the failed admissions pause join for the rest of
their window.
"""

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ADMISSION_FAILURES_MAX,
    CHANNEL_ADMISSION_WINDOW_S,
)
from neutrino_hub.modules.channel.port_guard import ChannelPortGuard
from tests.conftest import FakeClock


def test_the_limits_are_the_ones_the_standard_names():
    assert CHANNEL_ADMISSION_FAILURES_MAX == 30
    assert CHANNEL_ADMISSION_WINDOW_S == 60


def test_failures_at_the_limit_pause_join_until_the_oldest_leaves_the_window():
    clock = FakeClock()
    guard = ChannelPortGuard(failures_max=3, window_s=60, clock=clock)
    guard.record_failure()
    clock.now += 10
    guard.record_failure()
    assert guard.pause_remaining_s() == 0

    guard.record_failure()

    assert guard.pause_remaining_s() == 50
    clock.now += 49
    assert guard.pause_remaining_s() == 1
    clock.now += 1
    assert guard.pause_remaining_s() == 0
