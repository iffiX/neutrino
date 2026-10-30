"""The step locks: the order, shared and alone takers, and the wait a taker names.

What these pin: a step's locks put in the one order with alone winning over
shared, a lock outside the order refused, two shared takers of
``containers`` at once, a taker alone waiting for the shared ones and
keeping new shared takers out meanwhile, every other lock taken alone, the
wait naming the module that holds the lock, a taker that never waits, and
locks let go the last taken first and on a failed take.
"""

import threading
import time

import pytest

from neutrino_agent.modules.shared.step_locks import (
    StepLock,
    StepLocks,
    is_in_order,
    lock_wait,
    ordered,
)

CONTAINERS_SHARED = (("containers", "shared"),)
CONTAINERS_ALONE = (("containers", "alone"),)
PACKAGES = (("package_manager", "alone"),)


def wait_until(check, timeout_s: float = 5.0) -> bool:
    """Whether a check passes within the time."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.005)
    return False


def taker(locks, pairs, holder, taken, waits):
    """A thread that takes locks, records it, and waits to be let go."""
    release = threading.Event()

    def run():
        locks.acquire(pairs, holder, on_wait=waits.append)
        taken.append(holder)
        release.wait(5)
        locks.release(pairs, holder)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return release, thread


def test_a_step_s_locks_come_in_the_one_order_and_alone_wins():
    locks = [
        ("system_accounts", "shared"),
        ("containers", "shared"),
        ("package_manager", "alone"),
        ("containers", "alone"),
    ]

    assert ordered(locks) == (
        ("containers", "alone"),
        ("package_manager", "alone"),
        ("system_accounts", "alone"),
    )


def test_a_lock_outside_the_order_is_refused():
    with pytest.raises(KeyError):
        ordered([("disk", "alone")])


def test_the_order_check_reads_names_once_each_in_the_order():
    assert is_in_order((("containers", "shared"), ("package_manager", "alone")))
    assert is_in_order(())
    assert not is_in_order((("package_manager", "alone"), ("containers", "alone")))
    assert not is_in_order((("containers", "alone"), ("containers", "shared")))
    assert not is_in_order((("disk", "alone"),))


def test_two_shared_takers_of_containers_hold_it_at_once():
    locks = StepLocks()

    locks.acquire(CONTAINERS_SHARED, "hermes_webui")
    locks.acquire(CONTAINERS_SHARED, "ayakaleaf")

    assert locks.holders("containers") == ["hermes_webui", "ayakaleaf"]


def test_every_other_lock_is_taken_alone():
    locks = StepLocks()
    locks.acquire((("package_manager", "shared"),), "samba")

    assert not locks.try_acquire((("package_manager", "shared"),), "gitea")
    assert locks.holders("package_manager") == ["samba"]


def test_a_taker_alone_waits_for_the_shared_ones_and_names_the_holder():
    locks = StepLocks()
    locks.acquire(CONTAINERS_SHARED, "ayakaleaf")
    taken: list = []
    waits: list = []

    release, thread = taker(locks, CONTAINERS_ALONE, "podman", taken, waits)

    assert wait_until(lambda: waits == [lock_wait("containers", "ayakaleaf")])
    assert taken == []
    locks.release(CONTAINERS_SHARED, "ayakaleaf")
    assert wait_until(lambda: taken == ["podman"])
    release.set()
    thread.join(5)


def test_a_taker_waiting_alone_keeps_new_shared_takers_out():
    """A run of pulls never holds a Stop of Containers back for ever."""
    locks = StepLocks()
    locks.acquire(CONTAINERS_SHARED, "ayakaleaf")
    taken: list = []
    stop_waits: list = []
    pull_waits: list = []
    stop_release, stop = taker(locks, CONTAINERS_ALONE, "podman", taken, stop_waits)
    assert wait_until(lambda: stop_waits)

    pull_release, pull = taker(
        locks, CONTAINERS_SHARED, "hermes_webui", taken, pull_waits
    )

    assert wait_until(lambda: pull_waits == [lock_wait("containers", "podman")])
    locks.release(CONTAINERS_SHARED, "ayakaleaf")
    assert wait_until(lambda: taken == ["podman"])
    stop_release.set()
    assert wait_until(lambda: taken == ["podman", "hermes_webui"])
    pull_release.set()
    stop.join(5)
    pull.join(5)


def test_a_taker_that_never_waits_takes_nothing_while_a_lock_is_held():
    locks = StepLocks()
    locks.acquire(PACKAGES, "agent")

    assert not locks.try_acquire(CONTAINERS_ALONE + PACKAGES, "podman")
    # A failed take keeps none of the locks it did get.
    assert locks.holders("containers") == []
    locks.release(PACKAGES, "agent")
    assert locks.try_acquire(CONTAINERS_ALONE + PACKAGES, "podman")


def test_held_takes_and_lets_go_the_locks_around_its_block():
    locks = StepLocks()

    with locks.held(CONTAINERS_ALONE + PACKAGES, "podman"):
        assert locks.holders("containers") == ["podman"]
        assert locks.holders("package_manager") == ["podman"]

    assert locks.holders("containers") == []
    assert locks.holders("package_manager") == []


def test_letting_go_a_lock_not_held_is_refused():
    with pytest.raises(RuntimeError):
        StepLock("containers").release("podman")


def test_the_wait_names_the_lock_and_the_module():
    assert lock_wait("package_manager", "samba") == {
        "code": "waiting_for_lock",
        "params": {"lock": "package_manager", "module": "samba"},
    }
