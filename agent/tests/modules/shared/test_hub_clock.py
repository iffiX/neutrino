"""The hub's time on this machine: the welcome's offset, a set clock taken up.

What these pin: the hub's time is this machine's clock plus the offset the
last welcome gave, and zero offset for a welcome naming none; a setting of
this machine's clock between two readings, told from the monotonic clock,
moves the offset by it, and a difference under the jump leaves it; a
welcome's ``time`` is read only as a positive number; and the process has
one hub clock.
"""

import time

import pytest

from neutrino_agent.constants import AGENT_HUB_CLOCK_JUMP_S
from neutrino_agent.modules.shared.hub_clock import (
    HubClock,
    hub_clock,
    hub_time,
    welcome_time,
)

HUB_NOW = 1_800_000_000.0
# How far behind the hub's clock nmxwin's was.
BEHIND_S = 13 * 3600.0


class Clocks:
    """This machine's clock and the monotonic clock, moved by hand."""

    def __init__(self, machine_now: float):
        self.machine_now = machine_now
        self.monotonic_now = 1000.0

    def machine(self) -> float:
        return self.machine_now

    def monotonic(self) -> float:
        return self.monotonic_now

    def run(self, seconds: float) -> None:
        """Both clocks move on together."""
        self.machine_now += seconds
        self.monotonic_now += seconds

    def set(self, seconds: float) -> None:
        """This machine's clock is set; the monotonic clock does not move."""
        self.machine_now += seconds


def clock_on(clocks: Clocks) -> HubClock:
    return HubClock(clock=clocks.machine, monotonic=clocks.monotonic)


def test_the_hubs_time_is_this_machines_clock_plus_the_welcomes_offset():
    clocks = Clocks(HUB_NOW - BEHIND_S)
    clock = clock_on(clocks)

    clock.take(HUB_NOW)
    clocks.run(30)

    assert clock.offset == BEHIND_S
    assert clock.now() == HUB_NOW + 30


def test_a_welcome_naming_no_time_leaves_this_machine_on_its_own_clock():
    clocks = Clocks(HUB_NOW - BEHIND_S)
    clock = clock_on(clocks)
    clock.take(HUB_NOW)

    clock.take(None)

    assert clock.offset == 0.0
    assert clock.now() == HUB_NOW - BEHIND_S


def test_a_clock_set_while_the_socket_stays_open_leaves_the_hubs_time():
    """A machine whose clock is set right after it connected, as a board
    without a battery clock is at boot, keeps the hub's time."""
    clocks = Clocks(HUB_NOW - BEHIND_S)
    clock = clock_on(clocks)
    clock.take(HUB_NOW)
    clocks.run(5)
    assert clock.now() == HUB_NOW + 5

    clocks.set(BEHIND_S)
    clocks.run(5)

    assert clock.now() == HUB_NOW + 10
    assert clock.offset == 0.0
    clocks.run(5)
    assert clock.now() == HUB_NOW + 15


def test_a_clock_set_backwards_is_taken_up_as_well():
    clocks = Clocks(HUB_NOW)
    clock = clock_on(clocks)
    clock.take(HUB_NOW)

    clocks.set(-BEHIND_S)
    clocks.run(5)

    assert clock.now() == HUB_NOW + 5
    assert clock.offset == BEHIND_S


def test_a_difference_under_the_jump_follows_this_machines_clock():
    clocks = Clocks(HUB_NOW)
    clock = clock_on(clocks)
    clock.take(HUB_NOW)
    clocks.run(5)

    clocks.set(AGENT_HUB_CLOCK_JUMP_S / 2)

    assert clock.now() == HUB_NOW + 5 + AGENT_HUB_CLOCK_JUMP_S / 2
    assert clock.offset == 0.0


@pytest.mark.parametrize(
    "welcome, read",
    [
        ({"time": 1_800_000_000}, 1_800_000_000.0),
        ({"time": 1_800_000_000.25}, 1_800_000_000.25),
        ({}, None),
        ({"time": None}, None),
        ({"time": True}, None),
        ({"time": "1800000000"}, None),
        ({"time": 0}, None),
        ({"time": -5}, None),
        ({"time": float("inf")}, None),
        ({"time": float("nan")}, None),
    ],
)
def test_a_welcomes_time_is_read_only_as_a_positive_number(welcome, read):
    assert welcome_time(welcome) == read


def test_the_process_has_one_hub_clock_at_offset_zero_before_a_welcome():
    assert hub_clock() is hub_clock()
    assert hub_clock().offset == 0.0
    assert abs(hub_time() - time.time()) < 1.0
