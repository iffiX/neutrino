"""One service's single lane: idle, working on one step, or failed.

A service does one thing at a time. A request that arrives while a step is
running is refused as ``busy``, never queued: the page greys the control
while the lane works, and a person who keeps pressing gets the same answer
each time. The one exception is a change the hub sends, which must not be
lost: it is kept as the one job to run once the lane is free.

The lane's standing is what the page draws as a spinner or a failure, and
every change of it is announced so the window redraws at once.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import threading

WORK_IDLE = "idle"
WORK_WORKING = "working"
WORK_FAILED = "failed"

# What a request gets while the lane works: refused, or kept as the one
# job to run next.
IF_BUSY_REFUSE = "refuse"
IF_BUSY_KEEP_ONE = "keep_one"


class ServiceWorker:
    """One service's lane, running one job at a time on its own thread."""

    def __init__(self, *, name: str, on_change, log=print, start_thread=None):
        """
        Args:
            name: The service, for the log.
            on_change: Called with no arguments after every change of
                standing.
            log: Callable used for progress messages.
            start_thread: ``start_thread(target)`` runs the target on a
                thread of its own; None uses a daemon thread. Tests pass
                one that runs inline.
        """
        self._name = name
        self._on_change = on_change
        self._log = log
        self._start_thread = (
            start_thread if start_thread is not None else _start_daemon_thread
        )
        self._lock = threading.Lock()
        self._state = WORK_IDLE
        self._step = ""
        self._failure: dict = {}
        self._kept: "tuple | None" = None

    def status(self) -> dict:
        """The lane's standing, for the state payload.

        Returns:
            ``{"state", "step", "code", "params"}``; ``code`` and ``params``
            are the last failure's, empty otherwise.
        """
        with self._lock:
            return {
                "state": self._state,
                "step": self._step,
                "code": str(self._failure.get("code", "")),
                "params": dict(self._failure.get("params", {})),
            }

    @property
    def is_working(self) -> bool:
        """Whether a step is running."""
        with self._lock:
            return self._state == WORK_WORKING

    def submit(self, step: str, job, *, if_busy: str = IF_BUSY_REFUSE) -> dict:
        """Run one job on the lane.

        Args:
            step: What the job does, in the page's vocabulary.
            job: Callable returning None or ``{"code", "params"}`` on a
                refusal; an exception counts as ``{"code": "crashed"}``.
            if_busy: ``IF_BUSY_REFUSE`` answers ``busy`` while a step runs;
                ``IF_BUSY_KEEP_ONE`` keeps the job to run once the lane is
                free, replacing any job kept before it.

        Returns:
            Empty when the job was taken, ``{"code": "busy", "params":
            {"step"}}`` when the lane refused it.
        """
        with self._lock:
            if self._state == WORK_WORKING:
                if if_busy == IF_BUSY_KEEP_ONE:
                    self._kept = (step, job)
                    return {}
                return {"code": "busy", "params": {"step": self._step}}
            self._begin(step)
        self._on_change()
        self._start_thread(lambda: self._run(step, job))
        return {}

    def clear_failure(self) -> None:
        """Forget the last failure; the lane is idle again."""
        with self._lock:
            if self._state != WORK_FAILED:
                return
            self._state = WORK_IDLE
            self._failure = {}
        self._on_change()

    def _begin(self, step: str) -> None:
        self._state = WORK_WORKING
        self._step = step
        self._failure = {}

    def _run(self, step: str, job) -> None:
        while True:
            refusal = self._perform(step, job)
            with self._lock:
                if refusal:
                    self._state = WORK_FAILED
                    self._failure = refusal
                else:
                    self._state = WORK_IDLE
                self._step = ""
                kept = self._kept
                self._kept = None
                if kept is not None:
                    step, job = kept
                    self._begin(step)
            self._on_change()
            if kept is None:
                return

    def _perform(self, step: str, job) -> dict:
        try:
            refusal = job()
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            self._log(f"{self._name}: {step} crashed: {error}")
            return {"code": "crashed", "params": {"detail": str(error)[:200]}}
        return dict(refusal) if refusal else {}


def _start_daemon_thread(target) -> None:
    threading.Thread(target=target, daemon=True).start()
