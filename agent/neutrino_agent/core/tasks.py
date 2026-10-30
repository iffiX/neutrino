"""A module's task: the steps that bring one module to its entry in the state.

A task belongs to one module, or to the ``ai_tools`` section. Its owner, the
desired state applier, hands it the module's entry and plans its steps from
what the machine shows; the task runs them one after another on a thread of
its own, each under the step locks it names, and holds no lock between two
steps. A step that waits for something outside the agent runs again every
recheck interval. At each boundary between two steps, and at each such
check, a newer entry the owner handed over makes the task plan again from
what the machine shows. The task's row, ``{steps, index, wait,
is_running}``, goes onto the module's report row, and its lines go up one
``log {module}`` stream for its whole run.

Not pure: runs the steps on a thread and blocks on the step locks.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import threading

from neutrino_agent.constants import (
    AGENT_MODULE_INSTALL_RECHECK_S,
    AGENT_MODULE_STATE_FAILED,
    AGENT_MODULE_STATE_INSTALL_FAILED,
    AGENT_MODULE_STATE_INSTALLING,
    AGENT_MODULE_STATE_QUEUED,
    AGENT_MODULE_STATE_UNINSTALLING,
    AGENT_WAIT_LOCK,
    AGENT_WAIT_MODULE,
)
from neutrino_agent.exceptions import (
    ModuleApplyError,
    ModuleInstallPending,
    ModuleSetupError,
    PlatformUnsupportedError,
    StepSuperseded,
)

# The kinds of plan, by what the task does to the module.
PLAN_INSTALL = "install"
PLAN_SWITCH = "switch"
PLAN_UNINSTALL = "uninstall"
PLAN_CONFIGURE = "configure"
# The transient state a row reads while a task of each kind runs.
PLAN_STATES = {
    PLAN_INSTALL: AGENT_MODULE_STATE_INSTALLING,
    PLAN_SWITCH: AGENT_MODULE_STATE_INSTALLING,
    PLAN_UNINSTALL: AGENT_MODULE_STATE_UNINSTALLING,
}
# How a plan's run ended.
RUN_DONE = "done"
RUN_REPLANNED = "replanned"
RUN_CUT = "cut"
# How long a step that waits for another module's task looks at its own
# newer entry between two looks at the other task.
MODULE_WAIT_LOOK_S = 0.5
# How much of an unexpected exception's words a failure keeps, and how much
# of a failure's line the log stream takes.
DETAIL_CHARS = 200
DETAIL_LINE_CHARS = 500


def step_failure(step, error: Exception) -> dict:
    """The failure one step's exception is reported as.

    Args:
        step: The :class:`ModuleStep` that raised.
        error: What it raised.

    Returns:
        ``{"state", "code", "params"}``: the module's own code from
        :class:`ModuleApplyError`, ``install_failed`` for
        :class:`ModuleSetupError`, ``unsupported_platform``, and the step's
        ``error_code`` with ``{detail}`` for anything else.
    """
    if isinstance(error, ModuleSetupError):
        state = AGENT_MODULE_STATE_INSTALL_FAILED
        return {"state": state, "code": error.code, "params": dict(error.params)}
    if isinstance(error, ModuleApplyError):
        return {
            "state": step.failed_state,
            "code": error.code,
            "params": dict(error.params),
        }
    if isinstance(error, PlatformUnsupportedError):
        return {"state": step.failed_state, "code": error.code, "params": {}}
    return {
        "state": step.failed_state,
        "code": step.error_code,
        "params": {"detail": str(error)[:DETAIL_CHARS]},
    }


def run_step(step, context) -> "dict | None":
    """Run one step once.

    Args:
        step: The :class:`ModuleStep`.
        context: What the step is handed: logs a line, receives an
            artifact, waits for another module.

    Returns:
        None when it took; its failure, as :func:`step_failure` gives it,
        when it did not, after one line naming it to the context's log.

    Raises:
        ModuleInstallPending: While what the step waits for outside the
            agent has not happened.
        StepSuperseded: When a step waiting for another module finds its
            task holds a newer entry.
    """
    try:
        step.run(context)
    except (ModuleInstallPending, StepSuperseded):
        raise
    except Exception as error:  # noqa: BLE001 - reported, never raised
        failure = step_failure(step, error)
        said = " ".join(f"{key}={value}" for key, value in failure["params"].items())
        context.log(
            f"{step.name}: {failure['code']} {said}".rstrip()[:DETAIL_LINE_CHARS]
        )
        return failure
    return None


def step_line(index: int, count: int, step) -> str:
    """The line the log stream reads at a step's start: ``step <i>/<n>: <name> <params>``.

    Args:
        index: The step's 1-based place in the plan.
        count: The plan's length.
        step: The :class:`ModuleStep`.

    Returns:
        The line, the params' values after the name.
    """
    said = " ".join(str(value) for value in step.params.values())
    return f"step {index}/{count}: {step.name} {said}".rstrip()


def module_wait(module: str) -> dict:
    """The wait a step names while it waits for another module's task.

    Args:
        module: The module waited for.

    Returns:
        ``waiting_for_module {module}``.
    """
    return {"code": AGENT_WAIT_MODULE, "params": {"module": module}}


class ModuleTask:
    """One module's task: its entry, its plan, the step it is on, its thread.

    Attributes:
        name: The module's name, or ``ai_tools``.
        ended: Set once the task has ended.
    """

    def __init__(
        self,
        *,
        name: str,
        entry: dict,
        entry_hash: str,
        owner,
        locks,
        log=print,
        recheck_s: float = AGENT_MODULE_INSTALL_RECHECK_S,
    ):
        """
        Args:
            name: The module's name, or ``ai_tools``.
            entry: The state's entry the task starts from.
            entry_hash: That entry's hash.
            owner: The desired state applier: plans the task, receives its
                artifacts, opens its log, waits for Containers, publishes
                its row and ends it.
            locks: The agent's :class:`StepLocks`.
            log: Callable used for progress messages.
            recheck_s: How often a step that waits for something outside
                the agent runs again.
        """
        self.name = name
        self.ended = threading.Event()
        self._owner = owner
        self._locks = locks
        self._log = log
        self._recheck_s = recheck_s
        self._lock = threading.Lock()
        self._entry = dict(entry)
        self._hash = entry_hash
        # The newer entry handed over while the task runs, ``(entry, hash)``.
        self._newer: "tuple | None" = None
        self._has_newer = threading.Event()
        self._kind = PLAN_CONFIGURE
        self._steps: list = []
        self._index = 0
        self._wait: dict = {}
        self._is_running = True
        self._has_installed = False
        self._log_stream = None
        self._thread: "threading.Thread | None" = None

    @property
    def entry(self) -> dict:
        """The entry the running plan was made from."""
        with self._lock:
            return dict(self._entry)

    @property
    def entry_hash(self) -> str:
        """The hash of the newest entry the task holds, a newer one handed over among them."""
        with self._lock:
            return self._newer[1] if self._newer is not None else self._hash

    @property
    def planned_hash(self) -> str:
        """The hash of the entry the running plan was made from."""
        with self._lock:
            return self._hash

    @property
    def is_running(self) -> bool:
        """Whether the task has not ended."""
        with self._lock:
            return self._is_running

    @property
    def kind(self) -> str:
        """What the running plan does to the module: install, switch, uninstall or configure."""
        with self._lock:
            return self._kind

    def start(self) -> None:
        """Run the task on a thread of its own."""
        self._thread = threading.Thread(
            target=self._run, name=f"task_{self.name}", daemon=True
        )
        self._thread.start()

    def offer(self, entry: dict, entry_hash: str) -> None:
        """Hand the task a newer entry, which replaces its plan at the next step boundary.

        A second entry handed over before that boundary replaces the first.

        Args:
            entry: The state's newer entry.
            entry_hash: Its hash.
        """
        with self._lock:
            self._newer = (dict(entry), entry_hash)
        self._has_newer.set()

    def has_newer(self) -> bool:
        """Whether a newer entry waits for the next step boundary."""
        with self._lock:
            return self._newer is not None

    def end(self) -> None:
        """Mark the task ended. The owner calls it under its own lock."""
        with self._lock:
            self._is_running = False

    def row(self) -> dict:
        """The task as a module's row carries it.

        Returns:
            ``{steps, index, wait, is_running}``, each step ``{name,
            params}``.
        """
        with self._lock:
            return {
                "steps": [
                    {"name": step.name, "params": dict(step.params)}
                    for step in self._steps
                ],
                "index": self._index,
                "wait": dict(self._wait),
                "is_running": self._is_running,
            }

    def state(self) -> str:
        """The transient state the module's row reads while the task runs.

        Returns:
            ``queued`` while the first step waits for a step lock,
            ``installing`` or ``uninstalling`` by the plan's kind, else
            empty, which keeps the state the machine shows.
        """
        with self._lock:
            if not self._is_running:
                return ""
            if self._index == 1 and self._wait.get("code") == AGENT_WAIT_LOCK:
                return AGENT_MODULE_STATE_QUEUED
            return PLAN_STATES.get(self._kind, "")

    def wait(self) -> dict:
        """What the running step waits for now, ``{code, params}``; empty while it works."""
        with self._lock:
            return dict(self._wait)

    def set_wait(self, wait: dict) -> None:
        """Name what the running step waits for, and publish the row.

        Args:
            wait: ``{code, params}``; empty while the step works.
        """
        with self._lock:
            if self._wait == wait:
                return
            self._wait = dict(wait)
        self._owner.task_changed(self)

    def log(self, line: str) -> None:
        """Hand one line to the task's log stream.

        Args:
            line: The line.
        """
        stream = self._log_stream
        if stream is not None:
            stream.send(str(line))

    def receive(self, artifact: dict) -> dict:
        """One artifact's bytes for this module, down a ``package`` stream.

        Args:
            artifact: The recipe's artifact.

        Returns:
            ``{"path", "sha256"}`` or ``{"code", "params"}``.
        """
        return self._owner.receive(self.name, artifact)

    def wait_for_containers(self) -> None:
        """Wait until Containers reads ``running`` and has no task.

        Raises:
            ModuleApplyError: ``module_needed {module, state}`` when
                Containers will not run.
            StepSuperseded: When this task holds a newer entry meanwhile.
        """
        self._owner.wait_for_containers(self)

    def render_containers(self) -> None:
        """Ask Containers for a configure task, and wait for it to end.

        Raises:
            ModuleApplyError: ``module_needed {module, state}`` when
                Containers does not run afterwards.
            StepSuperseded: When this task holds a newer entry meanwhile.
        """
        self._owner.render_containers(self)

    def wait_for_task(self, other: "ModuleTask") -> None:
        """Wait until another module's task has ended, looking at this task's newer entry meanwhile.

        Args:
            other: The other task.

        Raises:
            StepSuperseded: When this task holds a newer entry first.
        """
        while not other.ended.wait(MODULE_WAIT_LOOK_S):
            if self.has_newer():
                raise StepSuperseded(self.name)

    def _run(self) -> None:
        self._owner.task_started(self)
        try:
            while True:
                self._take_newer()
                kind, steps = self._owner.plan_task(
                    self, self.entry, has_installed=self._has_installed
                )
                self._set_plan(kind, steps)
                outcome, how = self._run_plan(kind, steps)
                if how == RUN_REPLANNED:
                    continue
                if self._owner.end_task(self, outcome, is_cut=how == RUN_CUT):
                    break
        except Exception as error:  # noqa: BLE001 - the task must end
            self._log(f"{self.name}: the task crashed: {error}")
            failure = {
                "state": AGENT_MODULE_STATE_FAILED,
                "code": "apply_failed",
                "params": {"detail": str(error)[:DETAIL_CHARS]},
            }
            self._owner.end_task(self, failure, is_cut=False, is_forced=True)
        finally:
            self._close_log()
            self.ended.set()

    def _run_plan(self, kind: str, steps: list) -> tuple:
        """Run a plan's steps in order.

        Returns:
            ``(failure, how)``: the first failure, None when none failed;
            ``how`` being ``done``, ``replanned`` for a newer entry taken at
            a boundary, or ``cut`` when the owner ends the task there.
        """
        count = len(steps)
        for index, step in enumerate(steps, 1):
            if self.has_newer():
                return None, RUN_REPLANNED
            if self._owner.is_task_cut(self):
                return None, RUN_CUT
            self._begin(index, count, step)
            while True:
                self._locks.acquire(step.locks, self.name, on_wait=self.set_wait)
                try:
                    if self.has_newer():
                        return None, RUN_REPLANNED
                    if self._owner.is_task_cut(self):
                        return None, RUN_CUT
                    self.set_wait({})
                    if kind == PLAN_INSTALL:
                        self._has_installed = True
                    failure = run_step(step, self)
                except ModuleInstallPending:
                    failure = None
                    is_pending = True
                except StepSuperseded:
                    return None, RUN_REPLANNED
                else:
                    is_pending = False
                finally:
                    self._locks.release(step.locks, self.name)
                if not is_pending:
                    break
                self.set_wait(self._owner.pending_wait(self))
                if self._has_newer.wait(self._recheck_s):
                    return None, RUN_REPLANNED
            if failure is not None:
                failure["step"] = {
                    "name": step.name,
                    "params": dict(step.params),
                    "index": index,
                    "count": count,
                }
                return failure, RUN_DONE
        return None, RUN_DONE

    def _take_newer(self) -> None:
        """Make the newer entry the one the next plan is made from."""
        with self._lock:
            if self._newer is not None:
                self._entry, self._hash = self._newer
                self._newer = None
            self._has_newer.clear()

    def _set_plan(self, kind: str, steps: list) -> None:
        """Take a new plan, and publish the row."""
        with self._lock:
            self._kind = kind
            self._steps = list(steps)
            self._index = 0
            self._wait = {}
        self._owner.task_changed(self)

    def _begin(self, index: int, count: int, step) -> None:
        """Mark one step as the running one, and write its line."""
        with self._lock:
            self._index = index
            self._wait = {}
        if self._log_stream is None:
            self._log_stream = self._owner.open_log(self.name)
        line = step_line(index, count, step)
        self._log(f"{self.name}: {line}")
        self.log(line)
        self._owner.task_changed(self)

    def _close_log(self) -> None:
        """End the log stream with the module's state, and its failure's code."""
        stream = self._log_stream
        if stream is None:
            return
        self._log_stream = None
        state, failure = self._owner.closing_state(self)
        stream.close(
            state,
            str((failure or {}).get("code", "") or ""),
            dict((failure or {}).get("params") or {}),
        )
