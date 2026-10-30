"""A module's task: its steps, its row, its waits, its end.

What these pin: each kind of exception a step raises read as its failure,
an install's keeping its command and the end of its output, and named in
the log; the step's line, written once its locks are taken
and once for a step run again; the row a task publishes, its plan's steps
and the step it is on; ``queued`` while the first step waits
for a step lock, ``installing`` and ``uninstalling`` by the plan's kind and
nothing for a configure plan; a step waiting outside the agent run again
until it takes, holding no lock between its checks; a newer entry taken at
the next boundary; a cut at a boundary ending the task with no step run;
and a task whose planning crashes ending ``apply_failed``.
"""

import threading

from neutrino_agent.core.tasks import (
    PLAN_CONFIGURE,
    PLAN_INSTALL,
    PLAN_UNINSTALL,
    ModuleTask,
    run_step,
    step_failure,
    step_line,
)
from neutrino_agent.exceptions import (
    InstallError,
    ModuleApplyError,
    ModuleInstallPending,
    ModuleSetupError,
    PlatformUnsupportedError,
)
from neutrino_agent.modules.shared.base import ModuleStep
from neutrino_agent.modules.shared.step_locks import StepLocks

SETTLE_S = 5.0


class Context:
    def __init__(self):
        self.lines: list = []

    def log(self, line):
        self.lines.append(line)


class Owner:
    """The applier as a task sees it: plans from a script, records the rest."""

    def __init__(self, plans, *, cut_after=None):
        self.plans = list(plans)
        self.cut_after = cut_after
        self.rows: list = []
        self.ended: list = []
        self.boundaries = 0

    def task_started(self, task):
        pass

    def plan_task(self, task, entry, *, has_installed):
        plan = self.plans.pop(0)
        if isinstance(plan, Exception):
            raise plan
        return plan

    def is_task_cut(self, task):
        self.boundaries += 1
        return self.cut_after is not None and self.boundaries > self.cut_after

    def end_task(self, task, outcome, *, is_cut, is_forced=False):
        if task.has_newer() and not is_forced:
            return False
        task.end()
        self.ended.append((outcome, is_cut))
        return True

    def task_changed(self, task):
        self.rows.append((task.row(), task.state(), task.wait()))

    def pending_wait(self, task):
        return {"code": "waiting_for_check", "params": {"seconds": 0}}

    def open_log(self, name):
        return None

    def closing_state(self, task):
        return "", None


def step(name, run=None, **extra):
    return ModuleStep(name=name, run=run or (lambda context: None), **extra)


def task_of(owner, locks=None, recheck_s=0.01):
    return ModuleTask(
        name="samba",
        entry={"want": "running"},
        entry_hash="h1",
        owner=owner,
        locks=locks or StepLocks(),
        log=lambda message: None,
        recheck_s=recheck_s,
    )


def run_task(task):
    task.start()
    assert task.ended.wait(SETTLE_S)


# --- one step ---


def test_each_kind_of_exception_reads_as_its_failure():
    install = step(
        "packages", failed_state="install_failed", error_code="install_failed"
    )

    assert step_failure(
        install, ModuleApplyError("download_failed", {"file": "x"})
    ) == {
        "state": "install_failed",
        "code": "download_failed",
        "params": {"file": "x"},
    }
    assert step_failure(step("start"), ModuleSetupError("ayakaleaf_setup_failed"))[
        "state"
    ] == ("install_failed")
    assert step_failure(step("start"), PlatformUnsupportedError("no"))["code"] == (
        "unsupported_platform"
    )
    assert step_failure(install, OSError("disk full")) == {
        "state": "install_failed",
        "code": "install_failed",
        "params": {"detail": "disk full"},
    }


def test_an_install_s_failure_keeps_its_command_and_the_end_of_its_output():
    output = "\n".join(f"Reading package lists... {n}" for n in range(500))
    error = InstallError(
        f"apt-get failed: {output}\nE: Unable to locate package nope", exit_code=100
    )

    failure = step_failure(
        step("packages", failed_state="install_failed", error_code="install_failed"),
        error,
    )

    detail = failure["params"]["detail"]
    assert len(detail) <= 500
    assert detail.startswith("apt-get failed: ... ")
    assert detail.endswith("E: Unable to locate package nope")


def test_a_failed_step_names_its_failure_in_the_log():
    context = Context()

    failure = run_step(
        step(
            "configure", run=_raise(ModuleApplyError("share_name_taken", {"name": "x"}))
        ),
        context,
    )

    assert failure["code"] == "share_name_taken"
    assert context.lines == ["configure: share_name_taken name=x"]


def test_a_step_that_took_is_no_failure():
    assert run_step(step("verify"), Context()) is None


def test_the_step_line_names_its_place_and_its_params():
    assert step_line(2, 5, step("pull", params={"image": "app"})) == (
        "step 2/5: pull app"
    )
    assert step_line(1, 1, step("verify")) == "step 1/1: verify"


def _raise(error):
    def run(context):
        raise error

    return run


# --- a task ---


def test_a_task_publishes_its_steps_and_the_step_it_is_on():
    owner = Owner([(PLAN_INSTALL, [step("packages"), step("verify")])])
    task = task_of(owner)

    run_task(task)

    rows = [row for row, _state, _wait in owner.rows]
    assert rows[0]["steps"] == [
        {"name": "packages", "params": {}},
        {"name": "verify", "params": {}},
    ]
    assert [row["index"] for row in rows] == [0, 1, 2]
    assert owner.ended == [(None, False)]
    assert task.row()["is_running"] is False


def test_the_row_reads_by_the_plan_s_kind():
    for kind, wanted in (
        (PLAN_INSTALL, "installing"),
        (PLAN_UNINSTALL, "uninstalling"),
        (PLAN_CONFIGURE, ""),
    ):
        owner = Owner([(kind, [step("one")])])
        run_task(task_of(owner))
        assert {state for _row, state, _wait in owner.rows} == {wanted}


def test_a_first_step_waiting_for_a_lock_reads_queued():
    locks = StepLocks()
    locks.acquire((("package_manager", "alone"),), "gitea")
    locked = (("package_manager", "alone"),)
    owner = Owner([(PLAN_INSTALL, [step("packages", locks=locked), step("verify")])])
    task = task_of(owner, locks=locks)
    task.start()

    queued = threading.Event()

    def look():
        for _row, state, wait in list(owner.rows):
            if state == "queued" and wait["params"]["module"] == "gitea":
                queued.set()

    for _ in range(500):
        look()
        if queued.is_set():
            break
        task.ended.wait(0.01)
    assert queued.is_set()
    locks.release(locked, "gitea")
    assert task.ended.wait(SETTLE_S)
    assert owner.rows[-1][1] == "installing"


def test_a_step_s_line_is_written_once_its_locks_are_taken():
    locks = StepLocks()
    locked = (("package_manager", "alone"),)
    locks.acquire(locked, "gitea")
    logged: list = []
    owner = Owner([(PLAN_INSTALL, [step("packages", locks=locked)])])
    task = ModuleTask(
        name="samba",
        entry={"want": "running"},
        entry_hash="h1",
        owner=owner,
        locks=locks,
        log=logged.append,
        recheck_s=0.01,
    )
    task.start()
    for _ in range(500):
        if task.wait().get("code") == "waiting_for_lock":
            break
        task.ended.wait(0.01)

    assert task.wait()["code"] == "waiting_for_lock"
    assert logged == []
    locks.release(locked, "gitea")
    assert task.ended.wait(SETTLE_S)
    assert logged == ["samba task: step 1/1: packages"]


def test_a_step_run_again_after_its_check_writes_its_line_once():
    logged: list = []
    tries: list = []

    def first_start(context):
        tries.append(1)
        if len(tries) < 3:
            raise ModuleInstallPending("first start")

    owner = Owner([(PLAN_INSTALL, [step("first_start", run=first_start)])])
    task = ModuleTask(
        name="samba",
        entry={"want": "running"},
        entry_hash="h1",
        owner=owner,
        locks=StepLocks(),
        log=logged.append,
        recheck_s=0.01,
    )

    run_task(task)

    assert len(tries) == 3
    assert logged == ["samba task: step 1/1: first_start"]


def test_a_waiting_step_runs_again_until_it_takes_and_holds_no_lock_between():
    locks = StepLocks()
    locked = (("containers", "shared"),)
    tries: list = []

    def first_start(context):
        tries.append(locks.holders("containers"))
        if len(tries) < 3:
            raise ModuleInstallPending("first start")

    owner = Owner(
        [(PLAN_INSTALL, [step("first_start", run=first_start, locks=locked)])]
    )
    task = task_of(owner, locks=locks)

    run_task(task)

    assert tries == [["samba"]] * 3
    assert locks.holders("containers") == []
    assert {"code": "waiting_for_check", "params": {"seconds": 0}} in [
        wait for _row, _state, wait in owner.rows
    ]
    assert owner.ended == [(None, False)]


def test_a_newer_entry_is_taken_at_the_next_boundary():
    gate = threading.Event()
    ran: list = []

    def long_step(context):
        gate.wait(SETTLE_S)
        ran.append("long")

    owner = Owner(
        [
            (PLAN_INSTALL, [step("packages", run=long_step), step("start")]),
            (PLAN_UNINSTALL, [step("uninstall", run=lambda context: ran.append("un"))]),
        ]
    )
    task = task_of(owner)
    task.start()
    task.offer({"want": "absent"}, "h2")
    gate.set()
    assert task.ended.wait(SETTLE_S)

    assert ran == ["long", "un"]
    assert task.planned_hash == "h2"
    assert task.entry == {"want": "absent"}


def test_a_cut_at_a_boundary_ends_the_task_with_no_failure():
    ran: list = []
    owner = Owner(
        [(PLAN_CONFIGURE, [step("configure", run=lambda context: ran.append(1))])],
        cut_after=0,
    )

    run_task(task_of(owner))

    assert ran == []
    assert owner.ended == [(None, True)]


def test_a_task_whose_planning_crashes_ends_apply_failed():
    owner = Owner([RuntimeError("bad plan")])

    run_task(task_of(owner))

    ((outcome, is_cut),) = owner.ended
    assert outcome["code"] == "apply_failed"
    assert is_cut is False
