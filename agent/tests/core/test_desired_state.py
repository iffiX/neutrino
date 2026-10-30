"""The hub's state: kept root-only, made true by one task per module, hashed honestly.

What these pin: what each ``want`` plans (absent uninstalls and clears the
mark, installed puts the software there and nothing else, stopped and
running install what is missing then configure and settle the unit, with
the mark written once the task took), a module the state does not mention
untouched, an install's bytes asked for down a ``package {module, artifact,
digest}`` stream, one ``log {module}`` stream per task with a ``step
<i>/<n>`` line per step and closed with the module's state, the applied
hash moving only when every mentioned module's task ended with no failure,
the tried hash written at a task's end and none for ``hub_unreachable``, a
failed module tried again only when its own entry changes, the hub's retry
mark being such a change, the first failure in ``APPLY_ORDER`` naming the
state error, the hashes kept under the agent's build, the tasks of two
modules running at once, a newer entry taken at the next step boundary and
at a waiting step's check, a step that waits for something outside the
agent run again every recheck interval with no lock held, the wait of a
step lock naming the module that holds it and a first step's wait reading
``queued``, ``settle`` waiting for one module's task alone, a restart's
replan from what the machine shows, and a container module waiting for
Containers, asking it to render, and ending quietly while Containers is not
to run.
"""

import functools
import hashlib
import json
import os
import stat
import threading
import time

import neutrino_agent.core.desired_state as desired_state_module
from neutrino_agent.core.desired_state import (
    APPLY_ORDER,
    DesiredStateApplier,
    DesiredStateStore,
    apply_order,
)
from neutrino_agent.exceptions import (
    GatewayUnreachable,
    ModuleApplyError,
    ModuleInstallPending,
    ModuleSetupError,
)
from neutrino_agent.modules.shared.base import ModuleStep
from neutrino_agent.modules.shared.step_locks import StepLocks
from tests.streams.fake_channel import FakeChannel

INSTALL = {
    "runner": "samba",
    "method": "system",
    "params": {
        "packages": ["x"],
        "verify": "",
        "uninstall": {"packages": ["x"], "post_uninstall": []},
    },
}
CONTAINER_INSTALL = {"runner": "container", "method": "container", "params": {}}
# The artifact a module's recipe receives in these tests.
ARTIFACT = {"name": "gitea", "kind": "binary", "digest": "sha256:" + "ab" * 32}
# The module whose recipe installs from bytes; the rest install by name.
BYTE_MODULES = ("gitea",)
# How long a test waits for the tasks to end.
SETTLE_S = 5.0
PACKAGE_LOCKS = (("package_manager", "alone"),)


def wait_for_containers(context):
    context.wait_for_containers()


def render_containers(context):
    context.render_containers()


class FakeEngine:
    """Observes a scripted set of installed modules and builds steps that record what runs."""

    def __init__(self, runners, *, absent=(), install_refusal=None):
        self.runners = dict(runners)
        self.names = list(runners)
        self.installed = {name for name in self.names if name not in absent}
        self.configured: set = set()
        self.states: list = []
        self.source_sets = None
        self.results: dict = {}
        self.failures: dict = {}
        self.installs: list = []
        self.uninstalls: list = []
        self.switching: set = set()
        self.switches: list = []
        self.switch_refusal = None
        self.install_refusal = install_refusal
        # Module name to what its install step waits on before it ends.
        self.install_gates: dict = {}
        # Module name to every row published for it, in order.
        self.published: dict = {}
        self.containers_state = "running"
        self.lock = threading.Lock()

    def take_state(self, modules, source_sets=None):
        self.states.append(modules)
        self.source_sets = source_sets

    def container_runners(self):
        return {}

    def runner_of(self, name):
        return self.runners.get(name)

    def is_installed(self, name, entry=None):
        return name in self.installed

    def is_install_failed(self, name):
        return (self.failures.get(name) or {}).get("state") == "install_failed"

    def take_version_switch(self, name, entry):
        return name in self.switching

    def install_steps(self, name, entry):
        steps = [
            ModuleStep(
                name="packages",
                run=functools.partial(self._install, name),
                locks=PACKAGE_LOCKS,
                failed_state="install_failed",
                error_code="install_failed",
            )
        ]
        if entry.get("install", {}).get("method") == "container":
            steps = [
                ModuleStep(
                    name="wait_containers",
                    run=wait_for_containers,
                    failed_state="install_failed",
                ),
                *steps,
                ModuleStep(
                    name="render", run=render_containers, failed_state="install_failed"
                ),
            ]
        return steps

    def switch_steps(self, name, entry):
        return [
            ModuleStep(
                name="switch",
                params={"version": "2"},
                run=functools.partial(self._switch, name),
                error_code="version_switch_failed",
            )
        ]

    def configure_steps(self, name, entry, want):
        runner = self.runners[name]
        config = dict(entry.get("config") or {})
        steps = []
        if entry.get("install", {}).get("method") == "container":
            steps.append(ModuleStep(name="wait_containers", run=wait_for_containers))
        steps.append(
            ModuleStep(name="configure", run=functools.partial(_apply, runner, config))
        )
        if want == "running":
            steps.append(
                ModuleStep(name="start", run=functools.partial(_start, runner))
            )
        else:
            steps.append(ModuleStep(name="stop", run=functools.partial(_stop, runner)))
        return steps

    def uninstall_steps(self, name, entry):
        return [
            ModuleStep(
                name="uninstall",
                run=functools.partial(self._uninstall, name),
                locks=PACKAGE_LOCKS,
                error_code="uninstall_failed",
            )
        ]

    def mark_configured(self, name):
        self.configured.add(name)

    def clear_configured(self, name):
        self.configured.discard(name)

    def record_failure(self, name, failure):
        if failure:
            self.results[name] = (failure["code"], dict(failure["params"]))
            self.failures[name] = dict(failure)
        else:
            self.results[name] = ("", {})
            self.failures.pop(name, None)

    def publish_task(self, name, task, state, wait):
        with self.lock:
            self.published.setdefault(name, []).append((dict(task), state, dict(wait)))

    def set_line_sink(self, on_line):
        pass

    def refresh_now(self):
        pass

    def refresh_one(self, name):
        pass

    def report(self):
        rows = {"podman": {"state": self.containers_state}}
        for name in self.names:
            failure = self.failures.get(name)
            if failure:
                rows[name] = {"state": failure["state"]}
            elif name == "podman":
                continue
            elif name in self.installed:
                rows[name] = {"state": "installed"}
            else:
                rows[name] = {"state": "absent"}
        return rows

    def last(self, name):
        """The last row published for one module, ``(task, state, wait)``."""
        with self.lock:
            rows = self.published.get(name) or []
            return rows[-1] if rows else ({}, "", {})

    def states_of(self, name):
        with self.lock:
            return [state for _task, state, _wait in self.published.get(name, [])]

    def _install(self, name, context):
        gate = self.install_gates.get(name)
        if gate is not None:
            gate.wait(SETTLE_S)
        received = context.receive(ARTIFACT) if name in BYTE_MODULES else {}
        self.installs.append((name, received))
        context.log(f"{name}: installing")
        if "code" in received:
            raise ModuleApplyError(received["code"], received.get("params"))
        if self.install_refusal is not None:
            raise ModuleApplyError(
                self.install_refusal["code"], self.install_refusal["params"]
            )
        self.installed.add(name)

    def _switch(self, name, context):
        self.switches.append(name)
        self.switching.discard(name)
        if self.switch_refusal:
            raise ModuleApplyError(
                self.switch_refusal["code"], self.switch_refusal["params"]
            )

    def _uninstall(self, name, context):
        self.uninstalls.append(name)
        context.log(f"{name}: uninstalling")
        self.installed.discard(name)
        self.configured.discard(name)


def _apply(runner, config, context):
    runner.apply(config)


def _start(runner, context):
    runner.start()


def _stop(runner, context):
    runner.stop()


class FakeShareHost:
    """A desktop host that records the seat passwords it was handed."""

    def __init__(self):
        self.passwords: list = []

    def take_seat_password(self, password):
        self.passwords.append(password)


class FakeRunner:
    """A runner that records the verbs it is asked, and refuses on cue."""

    def __init__(self, *, failure=None, journal=None, wait=None):
        self.failure = failure
        self.journal = journal if journal is not None else []
        self.applied: list = []
        self.stops = 0
        self.wait = wait or {}

    def apply(self, config):
        if self.failure is not None:
            raise self.failure
        self.applied.append(config)
        self.journal.append(("apply", id(self)))

    def start(self):
        self.journal.append(("start", id(self)))

    def stop(self):
        self.stops += 1
        self.journal.append(("stop", id(self)))

    def install_wait(self):
        return dict(self.wait)


class FakeSocket:
    """Opens channels the way the session would, and keeps them."""

    def __init__(self):
        self.opened: list = []
        self.channels: list = []
        self.next_id = 1

    def __call__(self, kind, **args):
        self.opened.append((kind, args))
        channel = FakeChannel(stream_id=self.next_id)
        self.next_id += 2
        self.channels.append(channel)
        return channel


def lines_of(channel) -> list:
    """The lines a log stream sent, without their newlines."""
    return [line.decode("utf-8").rstrip("\n") for line in channel.sent]


def state(state_hash: str = "h1", **wants) -> dict:
    """One state document naming each module with its want."""
    return {
        "hash": state_hash,
        "modules": {
            name: {
                "want": want,
                "config": {"n": name},
                "install": dict(INSTALL),
            }
            for name, want in wants.items()
        },
        "desktop": {"seat_password": ""},
    }


def marked(document: dict, name: str, mark: str = "a1b2c3d4") -> dict:
    """The same state with the hub's retry mark on one module's entry."""
    document["modules"][name]["retry_mark"] = mark
    return document


def applier(runners, engine=None, tmp_path=None, rdp=None, open_stream=None, **extra):
    engine = engine if engine is not None else FakeEngine(runners)
    held = DesiredStateApplier(
        engine=engine,
        runners=runners,
        store=DesiredStateStore(path=str(tmp_path / "desired.json")),
        rdp=rdp,
        log=lambda message: None,
        open_stream=open_stream,
        package_dir=str(tmp_path / "packages"),
        **extra,
    )
    return held, engine


def run(held, document) -> None:
    """Make the state's tasks and wait for every one of them to end."""
    held.apply(document)
    assert held.settle("", SETTLE_S)


def wait_until(check, timeout_s: float = SETTLE_S) -> bool:
    """Whether a check passes within the time, looked at every few milliseconds."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.005)
    return False


# --- the store ---


def test_the_file_is_written_root_only_and_reads_back(tmp_path):
    store = DesiredStateStore(path=str(tmp_path / "agent/desired.json"))

    store.write({"hash": "h1", "modules": {}})

    mode = stat.S_IMODE(os.stat(tmp_path / "agent/desired.json").st_mode)
    assert mode == 0o600
    assert store.read() == {"hash": "h1", "modules": {}}


def test_a_missing_or_broken_file_reads_as_nothing(tmp_path):
    store = DesiredStateStore(path=str(tmp_path / "desired.json"))
    assert store.read() == {}

    (tmp_path / "desired.json").write_text("not json")
    assert store.read() == {}


def test_the_latest_state_is_the_one_last_taken(tmp_path):
    held, _engine = applier({}, tmp_path=tmp_path)
    assert held.latest() == {}

    held.take({"hash": "h2", "modules": {"vscode": {"want": "running"}}})

    assert held.latest() == {"hash": "h2", "modules": {"vscode": {"want": "running"}}}


# --- the order and the four wants ---


def test_every_module_gets_its_task_and_the_order_is_the_fixed_one(tmp_path):
    journal: list = []
    runners = {name: FakeRunner(journal=journal) for name in reversed(APPLY_ORDER)}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, state(**{name: "running" for name in APPLY_ORDER}))

    assert apply_order(engine.states[0], runners) == list(APPLY_ORDER)
    assert {entry[1] for entry in journal if entry[0] == "apply"} == {
        id(runner) for runner in runners.values()
    }
    assert engine.configured == set(APPLY_ORDER)
    assert held.applied_hash == "h1"


def test_installed_puts_the_software_there_and_nothing_else(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    run(held, state(samba="installed"))

    assert [name for name, _ in engine.installs] == ["samba"]
    assert runners["samba"].applied == []
    assert runners["samba"].stops == 0
    assert engine.configured == set()
    assert held.applied_hash == "h1"
    assert engine.results["samba"] == ("", {})


def test_running_installs_what_is_missing_configures_and_writes_the_mark(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    run(held, state(samba="running"))

    assert [name for name, _ in engine.installs] == ["samba"]
    assert runners["samba"].applied == [{"n": "samba"}]
    assert engine.configured == {"samba"}
    task, _state, _wait = engine.last("samba")
    assert [step["name"] for step in task["steps"]] == [
        "packages",
        "configure",
        "start",
    ]
    assert (task["index"], task["is_running"]) == (3, False)
    # The install task reads installing from its start to its end.
    assert set(engine.states_of("samba")[:-1]) == {"installing"}
    assert engine.states_of("samba")[-1] == ""


def test_running_on_software_that_is_there_installs_nothing(tmp_path):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="running"))

    assert engine.installs == []
    assert runners["samba"].applied == [{"n": "samba"}]
    # A configure task leaves the state the machine shows.
    assert set(engine.states_of("samba")) == {""}


def test_an_installed_module_of_another_version_is_switched_then_applied(tmp_path):
    runners = {"gitea": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)
    engine.switching.add("gitea")

    run(held, state(gitea="running"))

    assert engine.switches == ["gitea"]
    assert runners["gitea"].applied == [{"n": "gitea"}]
    assert "installing" in engine.states_of("gitea")


def test_a_switch_that_did_not_take_fails_the_module_and_applies_nothing(tmp_path):
    runners = {"gitea": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)
    engine.switching.add("gitea")
    engine.switch_refusal = {
        "code": "version_switch_failed",
        "params": {"version": "2", "detail": "no"},
    }

    run(held, state(gitea="running"))

    assert engine.results["gitea"][0] == "version_switch_failed"
    assert engine.failures["gitea"]["state"] == "failed"
    assert runners["gitea"].applied == []
    assert held.applied_hash == ""


def test_stopped_configures_then_stops_the_unit(tmp_path):
    journal: list = []
    runners = {"samba": FakeRunner(journal=journal)}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="stopped"))

    assert [entry[0] for entry in journal] == ["apply", "stop"]
    assert engine.configured == {"samba"}


def test_absent_uninstalls_what_is_there_and_touches_the_configuration_never(
    tmp_path,
):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)
    engine.configured.add("samba")

    run(held, state(samba="absent"))

    assert engine.uninstalls == ["samba"]
    assert runners["samba"].applied == []
    assert engine.configured == set()
    assert "uninstalling" in engine.states_of("samba")


def test_absent_on_software_that_is_not_there_only_clears_the_mark(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)
    engine.configured.add("samba")

    run(held, state(samba="absent"))

    assert engine.uninstalls == []
    assert engine.configured == set()
    assert held.applied_hash == "h1"


def test_a_module_the_state_does_not_mention_is_untouched(tmp_path):
    runners = {"samba": FakeRunner(), "gitea": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="running"))

    assert runners["gitea"].applied == []
    assert "gitea" not in engine.published


def test_a_want_outside_the_four_is_left_alone(tmp_path):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="whatever"))

    assert runners["samba"].applied == []
    assert engine.uninstalls == []


def test_a_failed_apply_writes_no_mark(tmp_path):
    runners = {"samba": FakeRunner(failure=ModuleApplyError("share_name_taken"))}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="running"))

    assert engine.configured == set()
    assert engine.results["samba"] == ("share_name_taken", {})
    assert engine.failures["samba"]["state"] == "failed"


def test_the_engine_observes_against_the_state_before_any_task_runs(tmp_path):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="running"))

    assert list(engine.states[0]) == ["samba"]
    assert engine.source_sets == {}


def test_the_state_s_source_sets_reach_the_engine(tmp_path):
    held, engine = applier({}, tmp_path=tmp_path)
    document = state()
    document["source_sets"] = {"pypi": {"probe": "/x", "sources": [], "variables": []}}

    run(held, document)

    assert engine.source_sets == document["source_sets"]


# --- the log and the bytes ---


def test_a_task_s_lines_go_up_one_log_stream_with_a_line_per_step(tmp_path):
    socket = FakeSocket()
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path, open_stream=socket)

    run(held, state(samba="running"))

    assert socket.opened == [("log", {"module": "samba"})]
    (log,) = socket.channels
    assert lines_of(log) == [
        "step 1/3: packages",
        "samba: installing",
        "step 2/3: configure",
        "step 3/3: start",
    ]
    assert log.closed == {"code": "", "params": {"state": "installed"}}


def test_a_configure_task_opens_its_log_stream_too(tmp_path):
    socket = FakeSocket()
    runners = {"samba": FakeRunner()}
    held, _ = applier(runners, tmp_path=tmp_path, open_stream=socket)

    run(held, state(samba="stopped"))

    assert socket.opened == [("log", {"module": "samba"})]
    assert lines_of(socket.channels[0]) == ["step 1/2: configure", "step 2/2: stop"]


def test_a_task_with_no_step_opens_no_stream(tmp_path):
    socket = FakeSocket()
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path, open_stream=socket)

    run(held, state(samba="absent"))

    assert socket.opened == []


def test_a_failed_install_closes_the_log_install_failed_and_fails_the_state(
    tmp_path,
):
    socket = FakeSocket()
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(
        runners,
        absent=("samba",),
        install_refusal={"code": "install_failed", "params": {"detail": "E: x"}},
    )
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path, open_stream=socket)

    run(held, state(samba="running"))

    (log,) = socket.channels
    assert log.closed == {
        "code": "install_failed",
        "params": {"detail": "E: x", "state": "install_failed"},
    }
    assert "packages: install_failed detail=E: x" in lines_of(log)
    assert runners["samba"].applied == []
    assert held.state_error == {
        "code": "install_failed",
        "params": {"module": "samba", "detail": "E: x"},
    }
    # The kept failure names the step it failed at.
    assert engine.failures["samba"]["step"] == {
        "name": "packages",
        "params": {},
        "index": 1,
        "count": 3,
    }
    task, _state, _wait = engine.last("samba")
    assert (task["index"], task["is_running"]) == (1, False)


def test_an_uninstall_s_output_goes_up_a_log_stream_too(tmp_path):
    runners = {"samba": FakeRunner()}
    socket = FakeSocket()
    held, _ = applier(runners, tmp_path=tmp_path, open_stream=socket)

    run(held, state(samba="absent"))

    (log,) = socket.channels
    assert lines_of(log) == ["step 1/1: uninstall", "samba: uninstalling"]
    assert log.closed == {"code": "", "params": {"state": "absent"}}


def test_the_bytes_come_down_a_package_stream_the_applier_opens(tmp_path):
    runners = {"gitea": FakeRunner()}
    engine = FakeEngine(runners, absent=("gitea",))
    socket = FakeSocket()
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)
    channel = FakeChannel(stream_id=3)
    channel.feed(("data", b"gitea binary"))
    channel.feed(("close", "", {"sha256": hashlib.sha256(b"gitea binary").hexdigest()}))

    def open_stream(kind, **args):
        if kind == "package":
            socket.opened.append((kind, args))
            return channel
        return socket(kind, **args)

    held._open_stream = open_stream

    run(held, state(gitea="installed"))

    assert socket.opened == [
        ("log", {"module": "gitea"}),
        (
            "package",
            {"module": "gitea", "artifact": "gitea", "digest": ARTIFACT["digest"]},
        ),
    ]
    name, received = engine.installs[0]
    assert name == "gitea"
    assert received["path"].startswith(str(tmp_path / "packages"))
    assert held.applied_hash == "h1"


def test_without_a_socket_the_bytes_cannot_come_and_the_next_state_tries_again(
    tmp_path,
):
    """A dropped socket made nothing about the machine fail: the entry is
    not latched, so the hub's next push of the same hash runs it."""
    runners = {"gitea": FakeRunner()}
    engine = FakeEngine(runners, absent=("gitea",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    run(held, state(gitea="installed"))

    assert engine.installs == [("gitea", {"code": "hub_unreachable", "params": {}})]
    assert held.applied_hash == ""
    assert held.state_error["code"] == "hub_unreachable"
    assert held._tried == {}

    run(held, state(gitea="installed"))
    assert len(engine.installs) == 2


def test_a_socket_that_refuses_the_stream_is_the_same_as_none(tmp_path):
    def refuse(kind, **args):
        raise GatewayUnreachable("gone")

    runners = {"gitea": FakeRunner()}
    engine = FakeEngine(runners, absent=("gitea",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path, open_stream=refuse)

    run(held, state(gitea="installed"))

    assert engine.installs == [("gitea", {"code": "hub_unreachable", "params": {}})]
    assert held._tried == {}


# --- the applied hash, the error and the tried hash ---


def test_the_hash_moves_only_when_every_mentioned_module_s_task_took(tmp_path):
    runners = {
        "samba": FakeRunner(),
        "gitea": FakeRunner(failure=ModuleApplyError("gitea_refused")),
    }
    held, _ = applier(runners, tmp_path=tmp_path)

    run(held, state("h1", samba="running", gitea="running"))
    assert held.applied_hash == ""

    runners["gitea"].failure = None
    run(held, marked(state("h2", samba="running", gitea="running"), "gitea"))
    assert held.applied_hash == "h2"


def test_the_state_error_names_the_first_failure_in_the_order(tmp_path):
    runners = {
        "gitea": FakeRunner(failure=ModuleApplyError("gitea_refused")),
        "samba": FakeRunner(failure=ModuleApplyError("share_name_taken")),
    }
    held, _ = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="running", gitea="running"))

    assert held.state_error == {
        "code": "share_name_taken",
        "params": {"module": "samba"},
    }


def test_a_success_after_a_failure_clears_the_error(tmp_path):
    runners = {"samba": FakeRunner(failure=ModuleApplyError("share_name_taken"))}
    held, engine = applier(runners, tmp_path=tmp_path)
    run(held, state(samba="running"))

    runners["samba"].failure = None
    run(held, marked(state(samba="running"), "samba"))

    assert held.state_error is None
    assert engine.results["samba"] == ("", {})


def test_take_keeps_the_state_and_the_worker_makes_its_tasks(tmp_path):
    runners = {"samba": FakeRunner()}
    held, _ = applier(runners, tmp_path=tmp_path)

    held.take(state(samba="running"))

    assert held.settle("", SETTLE_S)
    assert runners["samba"].applied == [{"n": "samba"}]
    assert held.latest()["hash"] == "h1"


def test_a_state_already_tried_is_not_tried_twice(tmp_path):
    runners = {"samba": FakeRunner()}
    held, _ = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="running"))
    run(held, state("h2", samba="running"))

    assert len(runners["samba"].applied) == 1


def test_a_failed_state_keeps_the_old_hash_and_is_not_tried_again_under_it(
    tmp_path,
):
    runners = {"samba": FakeRunner(failure=ModuleApplyError("share_name_taken"))}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="running"))
    run(held, state("h2", samba="running"))

    assert engine.results["samba"] == ("share_name_taken", {})
    assert held.applied_hash == ""
    assert "samba" in held._store.read_tried()


def test_a_failed_install_keeps_its_hash_and_installs_again_on_a_retry_mark(
    tmp_path,
):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(
        runners,
        absent=("samba",),
        install_refusal={"code": "install_failed", "params": {}},
    )
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)
    run(held, state(samba="running"))
    run(held, state(samba="running"))
    assert len(engine.installs) == 1

    engine.install_refusal = None
    run(held, marked(state(samba="running"), "samba"))

    assert len(engine.installs) == 2
    assert engine.results["samba"] == ("", {})


def test_a_failed_install_that_left_the_software_installs_again(tmp_path):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)
    engine.failures["samba"] = {"state": "install_failed", "code": "x", "params": {}}

    run(held, state(samba="installed"))

    assert [name for name, _ in engine.installs] == ["samba"]


def test_an_uninstall_of_a_failed_install_runs_whatever_the_check_finds(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)
    engine.failures["samba"] = {"state": "install_failed", "code": "x", "params": {}}

    run(held, state(samba="absent"))

    assert engine.uninstalls == ["samba"]


def test_a_changed_entry_is_tried_after_a_failure(tmp_path):
    runners = {"samba": FakeRunner(failure=ModuleApplyError("share_name_taken"))}
    held, _ = applier(runners, tmp_path=tmp_path)
    run(held, state(samba="running"))

    runners["samba"].failure = None
    changed = state(samba="running")
    changed["modules"]["samba"]["config"] = {"n": "other"}
    run(held, changed)

    assert runners["samba"].applied == [{"n": "other"}]


def test_a_retry_mark_on_one_module_never_runs_another_failed_module_again(
    tmp_path,
):
    runners = {
        "samba": FakeRunner(failure=ModuleApplyError("share_name_taken")),
        "gitea": FakeRunner(failure=ModuleApplyError("gitea_refused")),
    }
    held, _ = applier(runners, tmp_path=tmp_path)
    run(held, state(samba="running", gitea="running"))
    runners["gitea"].failure = None
    runners["samba"].failure = None

    run(held, marked(state(samba="running", gitea="running"), "gitea"))

    assert runners["gitea"].applied == [{"n": "gitea"}]
    assert runners["samba"].applied == []


def test_a_new_seat_password_runs_the_remote_desktop_module_again(tmp_path):
    runners = {"remote_desktop": FakeRunner()}
    held, _ = applier(runners, tmp_path=tmp_path, rdp=FakeShareHost())
    run(held, state(remote_desktop="running"))

    changed = state(remote_desktop="running")
    changed["desktop"] = {"seat_password": "new"}  # scan: allow
    run(held, changed)

    assert len(runners["remote_desktop"].applied) == 2


def test_a_refusal_s_log_line_carries_its_reason(tmp_path):
    """The agent's log says why, not only the code."""
    runners = {
        "samba": FakeRunner(
            failure=ModuleApplyError(
                "user_record_unusable",
                {"user": "t3user3", "detail": "DS Error: -14120 (eDSPermissionError)"},
            )
        )
    }
    lines: list = []
    held, _ = applier(runners, tmp_path=tmp_path)
    held._log = lines.append

    run(held, state(samba="running"))

    assert (
        "samba: user_record_unusable user=t3user3 "
        "detail=DS Error: -14120 (eDSPermissionError)"
    ) in lines


# --- a step that waits for something outside the agent ---


def test_a_failed_step_of_a_first_start_reads_install_failed(tmp_path):
    runners = {"samba": FakeRunner(failure=ModuleSetupError("ayakaleaf_setup_failed"))}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, state(samba="running"))

    assert engine.failures["samba"]["state"] == "install_failed"
    assert engine.results["samba"] == ("ayakaleaf_setup_failed", {})


def test_a_waiting_step_runs_again_every_recheck_and_holds_no_lock_between(
    tmp_path,
):
    """The step runs again at each check, the task names the wait, and no
    step lock is held while it waits."""
    locks = StepLocks()
    tries: list = []
    seen: list = []

    class FirstStartRunner(FakeRunner):
        def start(self):
            tries.append(1)
            if len(tries) < 3:
                raise ModuleInstallPending("first start")

    runners = {"samba": FirstStartRunner()}
    engine = FakeEngine(runners)

    def configure_steps(name, entry, want):
        steps = FakeEngine.configure_steps(engine, name, entry, want)
        return [
            ModuleStep(name=step.name, run=step.run, locks=PACKAGE_LOCKS)
            for step in steps
        ]

    engine.configure_steps = configure_steps
    held, _ = applier(
        runners, engine=engine, tmp_path=tmp_path, locks=locks, recheck_s=0.2
    )

    held.apply(state(samba="running"))
    assert wait_until(lambda: len(tries) >= 1)
    assert wait_until(lambda: engine.last("samba")[0].get("wait"))
    seen.append(locks.holders("package_manager"))
    seen.append((held.applied_hash, held.state_error))
    assert held.settle("", SETTLE_S)

    assert len(tries) == 3
    assert seen == [[], ("", None)]
    waits = [wait for _task, _state, wait in engine.published["samba"]]
    assert {"code": "waiting_for_check", "params": {"seconds": 0}} in waits
    assert held.applied_hash == "h1"
    assert engine.results["samba"] == ("", {})


def test_a_waiting_step_names_the_runner_s_own_wait(tmp_path):
    tries: list = []

    class RebootRunner(FakeRunner):
        def apply(self, config):
            tries.append(1)
            if len(tries) < 2:
                raise ModuleInstallPending("reboot_required")

    runners = {"samba": RebootRunner(wait={"code": "reboot_required"})}
    held, engine = applier(runners, tmp_path=tmp_path, recheck_s=0.05)

    run(held, state(samba="running"))

    waits = [wait for _task, _state, wait in engine.published["samba"]]
    assert {"code": "reboot_required", "params": {}} in waits


def test_a_newer_entry_is_taken_at_a_waiting_step_s_check(tmp_path):
    class NeverRunner(FakeRunner):
        def start(self):
            raise ModuleInstallPending("first start")

    runners = {"samba": NeverRunner()}
    held, engine = applier(runners, tmp_path=tmp_path, recheck_s=0.05)
    held.apply(state(samba="running"))
    assert wait_until(lambda: engine.last("samba")[0].get("wait"))

    run(held, state("h2", samba="absent"))

    assert engine.uninstalls == ["samba"]
    assert held.applied_hash == "h2"


# --- tasks of two modules at once, and the step locks ---


def test_two_modules_tasks_run_at_once(tmp_path):
    gate = threading.Event()
    runners = {"samba": FakeRunner(), "gitea": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    engine.install_gates["samba"] = gate
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(samba="running", gitea="running"))

    # Gitea's configure task ends while the file share's install waits.
    assert held.settle("gitea", SETTLE_S)
    assert runners["gitea"].applied == [{"n": "gitea"}]
    assert runners["samba"].applied == []
    assert not held.settle("samba", 0.05)
    gate.set()
    assert held.settle("", SETTLE_S)
    assert runners["samba"].applied == [{"n": "samba"}]


def test_a_first_step_waiting_for_a_lock_reads_queued_naming_its_holder(tmp_path):
    gate = threading.Event()
    runners = {"samba": FakeRunner(), "gitea": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba", "gitea"))
    engine.install_gates["samba"] = gate
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(samba="running"))
    assert wait_until(lambda: engine.last("samba")[0].get("index") == 1)
    held.apply(state("h2", samba="running", gitea="running"))

    assert wait_until(lambda: engine.last("gitea")[1] == "queued")
    assert engine.last("gitea")[2] == {
        "code": "waiting_for_lock",
        "params": {"lock": "package_manager", "module": "samba"},
    }
    gate.set()
    assert held.settle("", SETTLE_S)
    assert [name for name, _ in engine.installs] == ["samba", "gitea"]
    assert engine.states_of("gitea")[-1] == ""


def test_a_newer_entry_replaces_the_plan_at_the_next_step_boundary(tmp_path):
    """An Uninstall arriving during an install's long step takes effect once
    that step ends; the install's start never runs."""
    gate = threading.Event()
    journal: list = []
    runners = {"samba": FakeRunner(journal=journal)}
    engine = FakeEngine(runners, absent=("samba",))
    engine.install_gates["samba"] = gate
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(samba="running"))
    assert wait_until(lambda: engine.last("samba")[0].get("index") == 1)
    held.apply(state("h2", samba="absent"))
    gate.set()
    assert held.settle("", SETTLE_S)

    assert [name for name, _ in engine.installs] == ["samba"]
    assert engine.uninstalls == ["samba"]
    assert journal == []
    assert held.applied_hash == "h2"
    # The tried hash is the newer entry's, the one the task last planned from.
    assert held._store.read_tried()["samba"] == held._tried["samba"]
    task, _state, _wait = engine.last("samba")
    assert [step["name"] for step in task["steps"]] == ["uninstall"]


def test_a_new_plan_toward_absent_uninstalls_what_the_task_began(tmp_path):
    """A partial install is the task's own leftover, uninstalled whatever the
    check finds."""
    gate = threading.Event()
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(
        runners,
        absent=("samba",),
        install_refusal={"code": "download_failed", "params": {}},
    )
    engine.install_gates["samba"] = gate
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(samba="running"))
    assert wait_until(lambda: engine.last("samba")[0].get("index") == 1)
    held.apply(state("h2", samba="absent"))
    gate.set()
    assert held.settle("", SETTLE_S)

    assert engine.uninstalls == ["samba"]


def test_settle_waits_for_one_module_s_task_alone(tmp_path):
    gate = threading.Event()
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    engine.install_gates["samba"] = gate
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(samba="running"))

    assert held.settle("gitea", 0.05)
    assert not held.settle("samba", 0.05)
    gate.set()
    assert held.settle("samba", SETTLE_S)


# --- a restart ---


def _agent(runners, tmp_path, build=desired_state_module.AGENT_BUILD, engine=None):
    """A fresh agent's applier over the state files under ``tmp_path``."""
    return DesiredStateApplier(
        engine=engine if engine is not None else FakeEngine(runners),
        runners=runners,
        store=DesiredStateStore(path=str(tmp_path / "desired.json"), build=build),
        log=lambda message: None,
    )


class _CountingRunner(FakeRunner):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tries = 0

    def apply(self, config):
        self.tries += 1
        super().apply(config)


def test_the_tried_hash_outlives_a_restart_and_the_same_state_is_not_tried_again(
    tmp_path,
):
    runner = _CountingRunner(failure=ModuleApplyError("cloudcli_install_out_of_memory"))
    runners = {"cloudcli": runner}
    first = _agent(runners, tmp_path)
    run(first, state(cloudcli="running"))
    assert sorted(first._store.read_tried()) == ["cloudcli"]

    again = _agent(runners, tmp_path)
    again.take(state(cloudcli="running"))
    assert again.settle("", SETTLE_S)

    assert runner.tries == 1
    assert oct(os.stat(str(tmp_path / "desired.json.tried")).st_mode & 0o777) == "0o600"


def test_a_restart_mid_task_plans_the_module_again_from_what_the_machine_shows(
    tmp_path,
):
    """The process died during the install's long step: no tried hash was
    written, and the next agent plans from the machine, where the software
    now is, so it configures and starts with no install."""
    gate = threading.Event()
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    engine.install_gates["samba"] = gate
    dying = _agent(runners, tmp_path, engine=engine)
    dying.apply(state(samba="running"))
    assert wait_until(lambda: engine.last("samba")[0].get("index") == 1)
    assert "samba" not in dying._store.read_tried()

    machine = FakeEngine(runners)
    again = _agent(runners, tmp_path, engine=machine)
    again.take(state(samba="running"))
    assert again.settle("", SETTLE_S)
    gate.set()

    assert machine.installs == []
    assert runners["samba"].applied == [{"n": "samba"}]
    assert again.applied_hash == "h1"


def test_a_removal_lets_the_next_agent_apply_the_same_state_again(tmp_path):
    runner = _CountingRunner()
    runners = {"remote_desktop": runner}
    run(_agent(runners, tmp_path), state(remote_desktop="running"))

    DesiredStateStore(path=str(tmp_path / "desired.json")).clear_tried()
    again = _agent(runners, tmp_path)
    again.take(state(remote_desktop="running"))
    assert again.settle("", SETTLE_S)

    assert runner.tries == 2
    assert again.applied_hash == "h1"


def test_a_restart_of_the_same_build_applies_nothing_again(tmp_path):
    runner = _CountingRunner()
    runners = {"samba": runner}
    run(
        _agent(runners, tmp_path, build="0.6.0 2026-10-24T10:00:00Z"),
        state(samba="running"),
    )

    restarted = _agent(runners, tmp_path, build="0.6.0 2026-10-24T10:00:00Z")
    restarted.take(state(samba="running"))
    assert restarted.settle("", SETTLE_S)

    assert runner.tries == 1


def test_an_agent_of_another_build_applies_every_module_once_again(tmp_path):
    samba = _CountingRunner()
    cloudcli = _CountingRunner(failure=ModuleApplyError("cloudcli_install_failed"))
    runners = {"samba": samba, "cloudcli": cloudcli}
    run(
        _agent(runners, tmp_path, build="0.6.0 2026-10-24T10:00:00Z"),
        state(samba="running", cloudcli="running"),
    )

    upgraded = _agent(runners, tmp_path, build="0.6.0 2026-10-24T15:00:00Z")
    assert upgraded._tried == {}
    run(upgraded, state(samba="running", cloudcli="running"))

    assert (samba.tries, cloudcli.tries) == (2, 2)


def test_the_tried_file_names_the_build_that_kept_it(tmp_path):
    store = DesiredStateStore(path=str(tmp_path / "desired.json"), build="0.6.1 t1")
    store.write_tried({"samba": "a1"})

    kept = json.loads((tmp_path / "desired.json.tried").read_text())

    assert kept == {"build": "0.6.1 t1", "hashes": {"samba": "a1"}}
    assert store.read_tried() == {"samba": "a1"}
    other = DesiredStateStore(path=str(tmp_path / "desired.json"), build="0.6.1 t2")
    assert other.read_tried() == {}


def test_a_tried_file_of_an_older_shape_reads_as_nothing_tried(tmp_path):
    (tmp_path / "desired.json.tried").write_text(json.dumps({"samba": "a1"}))

    assert DesiredStateStore(path=str(tmp_path / "desired.json")).read_tried() == {}


def test_forgetting_the_mark_applies_a_state_already_held(tmp_path):
    runner = _CountingRunner()
    runners = {"samba": runner}
    held = _agent(runners, tmp_path)
    run(held, state(samba="running"))

    held.forget_tried()
    run(held, state(samba="running"))

    assert runner.tries == 2


def test_a_mark_another_process_deleted_is_read_again(tmp_path):
    runner = _CountingRunner()
    runners = {"samba": runner}
    held = _agent(runners, tmp_path)
    run(held, state(samba="running"))

    DesiredStateStore(path=str(tmp_path / "desired.json")).clear_tried()
    held.reload_tried()
    run(held, state(samba="running"))

    assert runner.tries == 2


def test_clearing_a_mark_that_is_not_there_is_no_error(tmp_path):
    DesiredStateStore(path=str(tmp_path / "desired.json")).clear_tried()


# --- the desktop and the AI tools ---


def test_the_seat_password_reaches_the_desktop_host(tmp_path):
    host = FakeShareHost()
    held, _ = applier({}, tmp_path=tmp_path, rdp=host)
    document = state()
    document["desktop"] = {"seat_password": "s3cret"}  # scan: allow

    run(held, document)

    assert host.passwords == ["s3cret"]  # scan: allow


def test_a_state_with_no_desktop_section_hands_the_host_nothing(tmp_path):
    host = FakeShareHost()
    held, _ = applier({}, tmp_path=tmp_path, rdp=host)
    document = state()
    del document["desktop"]

    run(held, document)

    assert host.passwords == []


class RecordedAiTools:
    """The machine's AI tools, whose one step records each section it runs."""

    def __init__(self):
        self.ran: list = []
        self.receive = None

    def steps(self, section, receive=None):
        self.receive = receive
        return [
            ModuleStep(
                name="tools",
                params={"account": "ann"},
                run=functools.partial(self._run, section),
            )
        ]

    def _run(self, section, context):
        self.ran.append(section)


def test_the_ai_tools_section_is_a_task_of_its_own_tried_once(tmp_path):
    tools = RecordedAiTools()
    held, engine = applier({}, tmp_path=tmp_path, ai_tools=tools)
    document = state()
    document["ai_tools"] = {"is_enabled": True, "accounts": [{"account": "ann"}]}

    run(held, document)
    run(held, dict(document, hash="h2"))

    assert tools.ran == [document["ai_tools"]]
    assert "ai_tools" in held._store.read_tried()
    assert "ai_tools" not in engine.published
    assert tools.receive == held.receive


def test_the_ai_tools_section_runs_again_when_it_changes(tmp_path):
    tools = RecordedAiTools()
    held, _ = applier({}, tmp_path=tmp_path, ai_tools=tools)
    document = state()
    document["ai_tools"] = {"is_enabled": False}

    run(held, document)
    run(held, dict(document, ai_tools={"is_enabled": True}))

    assert tools.ran == [{"is_enabled": False}, {"is_enabled": True}]


# --- a container module and Containers ---


def container_state(state_hash="h1", podman="running", **wants) -> dict:
    """A state naming Containers and container modules."""
    document = state(state_hash, podman=podman)
    for name, want in wants.items():
        document["modules"][name] = {
            "want": want,
            "config": {"n": name},
            "install": dict(CONTAINER_INSTALL),
        }
    return document


def test_a_container_module_the_order_does_not_name_comes_right_after_containers():
    modules = {
        name: {"install": {"method": "container"}}
        for name in ("zeta", "podman", "samba", "vscode")
    }
    runners = {name: object() for name in modules}

    assert apply_order(modules, runners) == ["samba", "podman", "zeta", "vscode"]


def test_a_container_module_waits_for_containers_and_asks_it_to_render(tmp_path):
    gate = threading.Event()
    journal: list = []
    runners = {"podman": FakeRunner(journal=journal), "demo": FakeRunner()}
    engine = FakeEngine(runners, absent=("podman", "demo"))
    engine.install_gates["podman"] = gate
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(container_state(demo="running"))
    assert wait_until(
        lambda: engine.last("demo")[2]
        == {"code": "waiting_for_module", "params": {"module": "podman"}}
    )
    # It waits for Containers in its first step, reading installing.
    assert engine.last("demo")[1] == "installing"
    assert engine.installs == []
    gate.set()
    assert held.settle("", SETTLE_S)

    # Containers applied in its own task, then once more for the render.
    assert [entry[0] for entry in journal] == ["apply", "start", "apply", "start"]
    assert [name for name, _ in engine.installs] == ["podman", "demo"]
    assert engine.results["demo"] == ("", {})


def test_a_container_module_fails_module_needed_while_containers_is_not_to_run(
    tmp_path,
):
    runners = {"podman": FakeRunner(), "demo": FakeRunner()}
    engine = FakeEngine(runners, absent=("demo",))
    engine.containers_state = "stopped"
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    run(held, container_state(podman="stopped", demo="running"))

    assert engine.results["demo"] == (
        "module_needed",
        {"module": "podman", "state": "stopped"},
    )
    assert engine.failures["demo"]["state"] == "install_failed"


def test_a_container_module_fails_when_containers_task_ends_not_running(tmp_path):
    runners = {
        "podman": FakeRunner(failure=ModuleApplyError("machine_unreachable")),
        "demo": FakeRunner(),
    }
    engine = FakeEngine(runners, absent=("demo",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    run(held, container_state(demo="running"))

    assert engine.results["demo"] == (
        "module_needed",
        {"module": "podman", "state": "failed"},
    )


def test_an_installed_container_module_ends_quietly_while_containers_is_stopped(
    tmp_path,
):
    """Containers' Stop stops every hub container; the module's task runs
    no step, keeps no failure and no tried hash, and the state that starts
    Containers again starts the module."""
    runners = {"podman": FakeRunner(), "demo": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    run(held, container_state(podman="stopped", demo="running"))

    assert runners["demo"].applied == []
    assert engine.results["demo"] == ("", {})
    assert "demo" not in held._store.read_tried()
    run(held, container_state("h2", podman="running", demo="running"))
    assert runners["demo"].applied == [{"n": "demo"}]


def test_render_asks_during_one_containers_task_make_one_more_configure(tmp_path):
    """Three container modules pulled at once each ask Containers to render:
    the first ask makes a configure task, and the two asks made while it
    runs are one more configure after it."""
    gate = threading.Event()
    applies: list = []
    names = ("one", "two", "three")
    runners = {"podman": FakeRunner(), **{name: FakeRunner() for name in names}}
    engine = FakeEngine(runners, absent=names)
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)
    run(held, container_state())

    def configure(context):
        applies.append(1)
        if len(applies) == 1:
            gate.wait(SETTLE_S)

    def podman_configure(name, entry, want):
        steps = FakeEngine.configure_steps(engine, name, entry, want)
        if name == "podman":
            steps[0] = ModuleStep(name="configure", run=configure)
        return steps

    engine.configure_steps = podman_configure
    first, others = threading.Event(), threading.Event()
    engine.install_gates = {"one": first, "two": others, "three": others}
    held.apply(container_state("h2", **{name: "installed" for name in names}))
    assert wait_until(
        lambda: all(engine.last(name)[0].get("index") == 2 for name in names)
    )
    first.set()
    # The first ask's configure task runs; the other two ask meanwhile.
    assert wait_until(lambda: len(applies) == 1)
    others.set()
    assert wait_until(
        lambda: all(
            engine.last(name)[0].get("index") == 3
            and engine.last(name)[2].get("code") == "waiting_for_module"
            for name in names
        )
    )
    gate.set()
    assert held.settle("", SETTLE_S)

    assert len(applies) == 2
    assert all(engine.results[name] == ("", {}) for name in names)


def test_nothing_here_applies_a_whole_state_again():
    """A waiting step checks itself; no pass over the whole state remains."""
    assert not hasattr(DesiredStateApplier, "apply_again")
    assert not hasattr(DesiredStateApplier, "_rechecked")


def test_a_module_s_own_ask_makes_a_configure_task_whatever_was_tried(tmp_path):
    """A forwarder that changed an instance's record asks for a configure
    task of its module; the entry's hash was tried long ago."""
    runners = {"cloudcli": FakeRunner()}
    held, _ = applier(runners, tmp_path=tmp_path)
    run(held, state(cloudcli="running"))

    task = held.ask_configure("cloudcli")
    assert held.settle("", SETTLE_S)

    assert task is not None and task.ended.is_set()
    assert runners["cloudcli"].applied == [{"n": "cloudcli"}] * 2
    assert held.ask_configure("gitea") is None


def test_an_ask_while_the_module_s_task_runs_is_one_more_plan_after_it(tmp_path):
    gate = threading.Event()
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    engine.install_gates["samba"] = gate
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)
    held.apply(state(samba="running"))
    assert wait_until(lambda: engine.last("samba")[0].get("index") == 1)

    held.ask_configure("samba")
    held.ask_configure("samba")
    gate.set()
    assert held.settle("", SETTLE_S)

    # Both asks are one more plan from the next boundary, which configures
    # after them; the old plan's configure does not run as well.
    assert runners["samba"].applied == [{"n": "samba"}]
    plans = [
        [step["name"] for step in task["steps"]]
        for task, _state, _wait in engine.published["samba"]
    ]
    assert ["configure", "start"] in plans
