"""The service lane: one job at a time, busy refused, the hub's kept once."""

import pytest

from neutrino_client.services import worker as worker_module
from neutrino_client.services.worker import (
    IF_BUSY_KEEP_ONE,
    WORK_FAILED,
    WORK_IDLE,
    WORK_WORKING,
    ServiceWorker,
)


class Inline:
    """A thread starter that runs targets when the test says so."""

    def __init__(self):
        self.targets = []

    def __call__(self, target):
        self.targets.append(target)

    def run_all(self):
        while self.targets:
            self.targets.pop(0)()


@pytest.fixture
def lane():
    changes = []
    starter = Inline()
    made = ServiceWorker(
        name="ai", on_change=lambda: changes.append(1), log=print, start_thread=starter
    )
    return made, starter, changes


def test_a_job_runs_on_the_lane_and_ends_idle(lane):
    made, starter, changes = lane
    done = []

    assert made.submit("switching", lambda: done.append(1)) == {}
    assert made.status()["state"] == WORK_WORKING
    assert made.status()["step"] == "switching"
    assert made.is_working
    assert changes == [1]

    starter.run_all()

    assert done == [1]
    assert made.status() == {"state": WORK_IDLE, "step": "", "code": "", "params": {}}
    assert changes == [1, 1]


def test_a_second_request_while_working_is_busy_with_the_step_named(lane):
    made, starter, _ = lane
    made.submit("switching", lambda: None)

    refusal = made.submit("switching", lambda: pytest.fail("ran"))

    assert refusal == {"code": "busy", "params": {"step": "switching"}}
    starter.run_all()
    assert made.status()["state"] == WORK_IDLE


def test_a_refusal_from_the_job_is_the_lanes_failure(lane):
    made, starter, _ = lane
    made.submit("mounting", lambda: {"code": "mount_failed", "params": {"d": 1}})
    starter.run_all()

    assert made.status() == {
        "state": WORK_FAILED,
        "step": "",
        "code": "mount_failed",
        "params": {"d": 1},
    }
    # A failed lane takes the next job.
    assert made.submit("mounting", lambda: None) == {}
    starter.run_all()
    assert made.status()["state"] == WORK_IDLE


def test_a_crash_in_the_job_is_typed_and_the_lane_survives(lane):
    made, starter, _ = lane

    def explode():
        raise RuntimeError("boom")

    made.submit("connecting", explode)
    starter.run_all()

    assert made.status()["code"] == "crashed"
    assert made.status()["params"] == {"detail": "boom"}


def test_a_kept_job_runs_once_after_the_lane_frees(lane):
    made, starter, changes = lane
    order = []
    made.submit("switching", lambda: order.append("first"))
    assert (
        made.submit(
            "switching", lambda: order.append("kept-a"), if_busy=IF_BUSY_KEEP_ONE
        )
        == {}
    )
    assert (
        made.submit(
            "switching", lambda: order.append("kept-b"), if_busy=IF_BUSY_KEEP_ONE
        )
        == {}
    )

    starter.run_all()

    # The later kept job replaced the earlier one; only it ran, once.
    assert order == ["first", "kept-b"]
    assert made.status()["state"] == WORK_IDLE
    assert changes.count(1) >= 3


def test_clearing_a_failure_returns_to_idle_and_announces_it(lane):
    made, starter, changes = lane
    made.submit("switching", lambda: {"code": "x", "params": {}})
    starter.run_all()
    before = len(changes)

    made.clear_failure()
    assert made.status()["state"] == WORK_IDLE
    assert len(changes) == before + 1

    made.clear_failure()
    assert len(changes) == before + 1


def test_the_real_starter_is_a_daemon_thread(monkeypatch):
    made_threads = []

    class Thread:
        def __init__(self, *, target, daemon):
            made_threads.append((target, daemon))

        def start(self):
            self.__dict__["started"] = True

    monkeypatch.setattr(worker_module.threading, "Thread", Thread)

    worker_module._start_daemon_thread(lambda: None)

    assert made_threads[0][1] is True
