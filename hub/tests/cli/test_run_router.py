"""`nhub run --only-router`: the resident unit that keeps the routing state.

READY reaches systemd once, whatever a pass did; a pass that fails is
journaled and the unit stays up; a stop ends it with nothing torn down; and
the journal says what changed, not every pass.
"""

import os
import queue
import sys
import threading

import pytest

from neutrino_hub.cli import run
from neutrino_hub.modules.router.constants import (
    ROUTER_STEP_APPLIED,
    ROUTER_STEP_PENDING,
    ROUTER_STEP_UNCHANGED,
)
from neutrino_hub.modules.router.steps import RouterStepResult


@pytest.fixture
def notified(monkeypatch):
    """What reached systemd's notify socket."""
    said = []
    monkeypatch.setattr(
        run, "notify_ready", lambda address: said.append("READY") or True
    )
    return said


@pytest.fixture
def handlers(monkeypatch):
    """The signal handlers the unit installed, by signal."""
    installed = {}
    monkeypatch.setattr(
        run.signal,
        "signal",
        lambda number, handler: installed.update({number: handler}),
    )
    return installed


def test_the_router_is_served_before_the_set_up_check(monkeypatch):
    """Exiting 1 on a box that is not set up would restart the unit forever."""
    monkeypatch.setattr(sys, "argv", ["nhub-run", "--only-router"])
    monkeypatch.setattr(run, "_serve_router", lambda: 7)
    monkeypatch.setattr(run, "_is_set_up", lambda: False)

    assert run.main() == 7


def test_a_box_that_is_not_set_up_is_ready_and_done(monkeypatch, notified, handlers):
    monkeypatch.setattr(run, "_is_set_up", lambda: False)

    assert run._serve_router() == 0
    assert notified == ["READY"]


class _Monitor:
    def __init__(self, *, on_change, on_gone):
        self.on_change = on_change
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True


class _Controller:
    passes = 0
    failure = None

    def __init__(self, *, trigger, on_base_ready):
        self.on_base_ready = on_base_ready

    def reconcile_locked(self, only=None):
        _Controller.passes += 1
        if _Controller.failure is not None:
            raise _Controller.failure
        self.on_base_ready()
        return [RouterStepResult(name="ruleset", state=ROUTER_STEP_APPLIED)]


@pytest.fixture
def resident(monkeypatch, notified, handlers):
    """The unit with its monitor and pass replaced, set up and ready to stop."""
    _Controller.passes, _Controller.failure = 0, None
    monkeypatch.setattr(run, "_is_set_up", lambda: True)
    monkeypatch.setattr(run, "RouterLinkMonitor", _Monitor)
    monkeypatch.setattr(run, "RouterStateController", _Controller)
    monkeypatch.setattr(run, "link_fingerprint", lambda: ("same",))
    return notified, handlers


def _stop_soon(handlers) -> threading.Thread:
    def stop():
        while run.signal.SIGTERM not in handlers:
            pass
        handlers[run.signal.SIGTERM](run.signal.SIGTERM, None)

    thread = threading.Thread(target=stop, daemon=True)
    thread.start()
    return thread


def test_a_stop_ends_the_unit_cleanly_after_one_pass(resident):
    notified, handlers = resident
    _stop_soon(handlers)

    assert run._serve_router() == 0
    assert _Controller.passes == 1
    assert notified == ["READY"]


def test_a_pass_that_fails_is_journaled_and_the_unit_stays(resident, capsys):
    notified, handlers = resident
    _Controller.failure = RuntimeError("system user 'xray' does not exist")
    _stop_soon(handlers)

    assert run._serve_router() == 0
    assert notified == ["READY"]
    assert "does not exist" in capsys.readouterr().err


def test_a_busy_lock_at_start_says_ready_and_waits(monkeypatch, notified):
    """Another apply holding the lock is applying the same state; the units
    ordered after this one must not wait for it."""
    tries = []

    class Busy:
        def __init__(self, *, timeout_s):
            tries.append(timeout_s)

        def __enter__(self):
            if len(tries) == 1:
                raise TimeoutError("busy")

        def __exit__(self, *arguments):
            return False

    monkeypatch.setattr(run, "router_lock", Busy)
    stopping = threading.Event()
    controller = _Controller(trigger="event", on_base_ready=None)
    _Controller.passes = 0
    readiness = run._Readiness()
    controller.on_base_ready = readiness.send

    run._reconcile_resident(
        controller, run._StepLog(), readiness, stopping, is_first=True
    )

    assert tries[0] == 0.0
    assert notified == ["READY"]
    assert _Controller.passes == 1


def test_the_notify_socket_is_kept_from_every_child(monkeypatch):
    """systemd refuses a message from anything but the unit's own process,
    and journals every child that tries."""
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    told = []
    monkeypatch.setattr(run, "notify_ready", lambda address: told.append(address))

    readiness = run._Readiness()
    assert "NOTIFY_SOCKET" not in os.environ
    readiness.send()

    assert told == ["/run/systemd/notify"]


def test_a_burst_settles_after_it_goes_quiet(monkeypatch):
    changes: queue.Queue = queue.Queue()
    for _ in range(3):
        changes.put(True)
    monkeypatch.setattr(run, "ROUTER_DEBOUNCE_QUIET_S", 0.05)

    assert run._settle(changes, threading.Event()) is True
    assert changes.empty()


def test_a_monitor_that_stops_mid_burst_is_said(monkeypatch):
    changes: queue.Queue = queue.Queue()
    changes.put(False)
    monkeypatch.setattr(run, "ROUTER_DEBOUNCE_QUIET_S", 0.05)

    assert run._settle(changes, threading.Event()) is False


def test_the_journal_says_what_moved_and_not_every_pass(capsys):
    log = run._StepLog()
    quiet = RouterStepResult(name="ruleset", state=ROUTER_STEP_UNCHANGED)
    waiting = RouterStepResult(
        name="served_route wlp3s0", state=ROUTER_STEP_PENDING, code="interface_down"
    )

    log.record([quiet, waiting])
    log.record([quiet, waiting])
    log.record([quiet, RouterStepResult(name="served_route wlp3s0", state="unchanged")])

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "router: served_route wlp3s0: pending interface_down",
        "router: served_route wlp3s0: unchanged",
    ]
