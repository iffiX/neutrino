"""The hub's state for this machine, kept and made true by one task per module.

The hub sends one state per device: ``{hash, modules, desktop}``, with one
entry per module it has a say about, ``{want, config, install}``, the
recipe ``install`` being ``{runner, method, params}``, and the seat password
this machine's desktop answers with. A copy lands here on every ``state``
frame, root-only on disk, and each mentioned module whose entry is news
gets a task, :class:`ModuleTask`, that makes its actual state equal its
``want``:

| ``want`` | The task ensures |
| --- | --- |
| ``absent`` | the software is uninstalled by its recipe, the configuration the hub wrote and the configured mark are gone; the data stays |
| ``installed`` | the software is there; nothing is configured, nothing started |
| ``stopped`` | the software is there, the configuration applied, the unit stopped |
| ``running`` | the software is there, the configuration applied, the unit up |

A module the state does not mention is left as it is. The tasks of two
modules run at once, each step under the step locks it names, and a newer
entry for a module whose task runs replaces the plan at the next step
boundary. Each artifact an install receives comes down a ``package
{module, artifact, digest}`` stream, and a task's lines go up one ``log
{module}`` stream.

The applied hash is what the hub compares against: it moves to the state's
hash once every mentioned module's task has ended with no failure. Each
module's entry, and the ``ai_tools`` section, is tried once: the hash of the
entry a task last planned from is kept per section beside the state on
disk, under the build of the agent that tried it, so a change to one entry,
or a retry mark on it, runs that module's task alone, an agent that starts
again tries nothing again, and an agent of another build tries every entry
once again. A failure the socket caused keeps no hash, so the next state
with that entry tries it again. Each task's outcome replaces the module's
kept failure. The marks hold for one install, one build and one binding:
the agent's removal, a join and a leave delete them, and another build
reads none of them.

Not pure: writes the state file, starts the tasks and opens streams.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import functools
import hashlib
import json
import os
import tempfile
import threading

from neutrino_agent import AGENT_BUILT_AT, AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_CONTAINERS_MODULE,
    AGENT_DESIRED_STATE_PATH,
    AGENT_METHOD_CONTAINER,
    AGENT_MODULE_INSTALL_RECHECK_S,
    AGENT_PRESENT_WANTS,
    AGENT_WAIT_CHECK,
    AGENT_WANT_ABSENT,
    AGENT_WANT_RUNNING,
    AGENT_WANT_STOPPED,
)
from neutrino_agent.core.tasks import (
    PLAN_CONFIGURE,
    PLAN_INSTALL,
    PLAN_SWITCH,
    PLAN_UNINSTALL,
    ModuleTask,
    module_wait,
)
from neutrino_agent.exceptions import GatewayUnreachable, ModuleApplyError
from neutrino_agent.modules.remote_desktop.constants import REMOTE_DESKTOP_NAME
from neutrino_agent.modules.shared import system_package
from neutrino_agent.modules.shared.step_locks import StepLocks
from neutrino_agent.streams import STREAM_KIND_LOG, STREAM_KIND_PACKAGE
from neutrino_agent.streams.log import LogStream
from neutrino_agent.streams.package import PackageStream

# The order modules apply in. A container module the list does not name
# applies right after Containers, whose Podman runs it.
APPLY_ORDER = (
    "samba",
    "terminal",
    "ssh_server",
    "gitea",
    "podman",
    "hermes_webui",
    "ayakaleaf",
    "vscode",
    "code_server",
    "cloudcli",
    "codeg",
    "siyuan",
    "remote_desktop",
)

# The wants that apply the hub's configuration.
CONFIGURING_WANTS = (AGENT_WANT_RUNNING, AGENT_WANT_STOPPED)

# The one failure the next state frame tries again: the socket went away
# under the operation, and nothing about the machine made it fail.
RETRIED_CODE = "hub_unreachable"
# A container module's failure while Containers does not run.
CODE_MODULE_NEEDED = "module_needed"
# The file beside the state that keeps the hash last tried, per section.
TRIED_SUFFIX = ".tried"
# This agent's build, which the hashes last tried are kept under: its
# version and the time its package was built.
AGENT_BUILD = f"{AGENT_VERSION} {AGENT_BUILT_AT}".strip()
# The state's section for the machine's AI tools, tried like a module.
AI_TOOLS_SECTION = "ai_tools"
# The state's section of the source sets its recipes name.
SOURCE_SETS_SECTION = "source_sets"
# The module whose Podman runs every container module.
CONTAINERS_MODULE = AGENT_CONTAINERS_MODULE


def apply_order(modules: dict, runners: dict) -> list:
    """The modules of one state that have a runner, in the order they apply.

    Args:
        modules: The state's modules section.
        runners: Module name to its runner.

    Returns:
        The names in ``APPLY_ORDER``; a container module the order does not
        name comes right after Containers, by name.
    """
    named = [name for name in APPLY_ORDER if name in modules and name in runners]
    extra = sorted(
        name
        for name in modules
        if name in runners
        and name not in APPLY_ORDER
        and _method_of(modules[name]) == AGENT_METHOD_CONTAINER
    )
    slot = APPLY_ORDER.index(CONTAINERS_MODULE) + 1
    at = len([name for name in named if APPLY_ORDER.index(name) < slot])
    return named[:at] + extra + named[at:]


def _method_of(entry: dict) -> str:
    """The install method a state entry's recipe names, empty for none."""
    recipe = entry.get("install") if isinstance(entry, dict) else None
    return (
        str((recipe or {}).get("method", "") or "") if isinstance(recipe, dict) else ""
    )


def _section_hash(section) -> str:
    """The SHA-256 of one section's canonical JSON form."""
    serialized = json.dumps(section, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class DesiredStateStore:
    """The last state taken from the hub, on disk."""

    def __init__(
        self, *, path: str = AGENT_DESIRED_STATE_PATH, build: str = AGENT_BUILD
    ):
        """
        Args:
            path: Where the file lives.
            build: The agent's build the hashes last tried are kept under.
        """
        self._path = path
        self._build = build

    def read(self) -> dict:
        """The stored state.

        Returns:
            The document, ``{hash, modules, desktop}``; empty when nothing
            was ever taken or the file cannot be read.
        """
        try:
            with open(self._path, "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        return dict(held) if isinstance(held, dict) else {}

    def write(self, document: dict) -> None:
        """Keep one state, root-only, whole or not at all.

        Args:
            document: The state as the hub sent it.

        Raises:
            OSError: When the file cannot be written; the partial file is
                removed first.
        """
        directory = os.path.dirname(self._path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".desired_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(document, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise

    def read_tried(self) -> dict:
        """The hash of the entry last tried, per section, by this build.

        Returns:
            Module name, or ``ai_tools``, to the hash; empty when none is
            kept, the file cannot be read, it holds another shape, or
            another build of the agent kept it.
        """
        try:
            with open(self._path + TRIED_SUFFIX, "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        if not isinstance(held, dict) or held.get("build") != self._build:
            return {}
        hashes = held.get("hashes")
        if not isinstance(hashes, dict):
            return {}
        return {
            str(name): value
            for name, value in hashes.items()
            if isinstance(value, str) and value
        }

    def clear_tried(self) -> None:
        """Delete every hash last tried, so the next state is applied whatever
        its hashes.

        Raises:
            OSError: When the file is there and cannot be deleted.
        """
        try:
            os.unlink(self._path + TRIED_SUFFIX)
        except FileNotFoundError:
            pass

    def write_tried(self, tried: dict) -> None:
        """Keep the hash of the entry last tried, per section, root-only,
        under this build.

        Args:
            tried: Module name, or ``ai_tools``, to the hash.

        Raises:
            OSError: When the file cannot be written.
        """
        directory = os.path.dirname(self._path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".tried_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(
                    {"build": self._build, "hashes": dict(tried)},
                    stream,
                    sort_keys=True,
                )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path + TRIED_SUFFIX)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise


class DesiredStateApplier:
    """Takes states from the hub and makes the latest one true, one task per module."""

    def __init__(
        self,
        *,
        engine,
        runners: dict,
        store: DesiredStateStore,
        rdp=None,
        log=print,
        open_stream=None,
        package_dir: str = "",
        ai_tools=None,
        locks=None,
        recheck_s: float = AGENT_MODULE_INSTALL_RECHECK_S,
    ):
        """
        Args:
            engine: The :class:`ModuleEngine`, which observes each module
                against the state, reports it, and builds its steps.
            runners: Module name to its runner, for the modules this agent
                applies.
            store: Where the last taken state is kept.
            rdp: The :class:`RdpShareHost` the desktop section is handed
                to; None applies nothing of it.
            log: Callable used for progress messages.
            open_stream: Called with ``(kind, **args)`` to open a stream
                to the hub; returns its channel and raises
                :class:`GatewayUnreachable` with no socket. None opens
                nothing: an install that needs bytes then fails
                ``hub_unreachable``.
            package_dir: Where a package's bytes land until their digest
                is checked.
            ai_tools: The :class:`AiToolsApplier` whose steps make the
                state's ``ai_tools`` section true; None applies nothing of
                it.
            locks: The agent's :class:`StepLocks`; None makes a set of its
                own.
            recheck_s: How often a step that waits for something outside
                the agent runs again.
        """
        self._engine = engine
        self._runners = dict(runners)
        self._store = store
        self._rdp = rdp
        self._log = log
        self._open_stream = open_stream
        self._package_dir = package_dir
        self._ai_tools = ai_tools
        self._locks = locks if locks is not None else StepLocks()
        self._recheck_s = recheck_s
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._pending: "dict | None" = None
        self._is_dispatching = False
        # The latest state dispatched, its modules by name, and the names
        # with a runner in the order they apply.
        self._document: dict = {}
        self._modules: dict = {}
        self._order: list = []
        # The running task of each module, and of ``ai_tools``, by name.
        self._tasks: dict = {}
        self._applied_hash = ""
        self._tried = store.read_tried()
        # Module name to its last task's failure in this process, ``{"state",
        # "code", "params", "step"}``; None when it took.
        self._outcomes: dict = {}
        self._state_error: "dict | None" = None
        self._wakeup = threading.Event()
        self._worker = threading.Thread(
            target=self._run, name="desired_state", daemon=True
        )
        self._worker.start()

    @property
    def applied_hash(self) -> str:
        """The hash of the last state every mentioned module's task applied."""
        with self._lock:
            return self._applied_hash

    @property
    def state_error(self) -> "dict | None":
        """Why the last state did not fully apply, as ``{"code", "params"}``."""
        with self._lock:
            return dict(self._state_error) if self._state_error else None

    @property
    def locks(self):
        """The agent's step locks. The self-update and a verb take them too."""
        return self._locks

    def settle(self, module: str, timeout_s: float) -> bool:
        """Wait until no state is pending and one module's task has ended.

        A verb that acts on a module runs after that module's task, not
        beside it.

        Args:
            module: The module; empty waits for every task.
            timeout_s: How long to wait.

        Returns:
            True when nothing is pending and the task has ended; False when
            the wait ran out.
        """
        with self._idle:
            return self._idle.wait_for(
                functools.partial(self._is_settled, module), timeout_s
            )

    def forget_tried(self) -> None:
        """Forget every hash last tried, here and on disk: what each was tried
        against is gone."""
        with self._lock:
            self._tried = {}
        try:
            self._store.clear_tried()
        except OSError as error:
            self._log(f"could not forget the tried state: {error}")

    def reload_tried(self) -> None:
        """Read the hashes last tried from disk again, after another process
        changed the binding and, with it, the marks."""
        tried = self._store.read_tried()
        with self._lock:
            self._tried = tried

    def latest(self) -> dict:
        """The last state taken from the hub, as it was kept.

        Returns:
            The document, ``{hash, modules, desktop}``; empty when none was
            ever taken.
        """
        return self._store.read()

    def take(self, document: dict) -> None:
        """Keep one state from the hub and apply it when it is news.

        Args:
            document: The state, ``{hash, modules, desktop}``.
        """
        kept = dict(document)
        try:
            self._store.write(kept)
        except OSError as error:
            self._log(f"could not keep the desired state: {error}")
        with self._lock:
            self._pending = kept
        self._wakeup.set()

    def apply(self, document: dict) -> None:
        """Make one state's tasks in the caller's thread. Each task runs on a thread of its own.

        A module with a runner whose entry's hash is neither the one last
        tried nor the one its running task works from gets a task, or hands
        its running task the newer entry, in ``APPLY_ORDER``, a container
        module the order does not name right after Containers. The
        ``ai_tools`` section gets a task of its own the same way.

        Args:
            document: The state, ``{hash, modules, desktop, source_sets}``.
        """
        modules = document.get("modules")
        modules = {
            name: entry
            for name, entry in (modules if isinstance(modules, dict) else {}).items()
            if isinstance(entry, dict)
        }
        source_sets = document.get(SOURCE_SETS_SECTION)
        self._engine.take_state(
            modules, source_sets if isinstance(source_sets, dict) else {}
        )
        self._apply_desktop(document.get("desktop"))
        hashes = {
            name: _section_hash(
                [entry, document.get("desktop")]
                if name == REMOTE_DESKTOP_NAME
                else entry
            )
            for name, entry in modules.items()
        }
        runners = {**self._runners, **self._engine.container_runners()}
        order = apply_order(modules, runners)
        made = []
        with self._lock:
            self._document = dict(document)
            self._modules = modules
            self._order = order
            for name in order:
                made.append(self._offer(name, modules[name], hashes[name]))
            if self._ai_tools is not None:
                section = document.get(AI_TOOLS_SECTION)
                made.append(
                    self._offer(
                        AI_TOOLS_SECTION, {"section": section}, _section_hash(section)
                    )
                )
            self._settle_hash()
        for task in made:
            if task is not None:
                task.start()
        self._engine.refresh_now()

    # --- what a task asks of its owner ---

    def task_started(self, task) -> None:
        """Hand the lines the runners log on the task's thread to its log stream,
        and the waits of its package runs to its row.

        Args:
            task: The task, on its own thread.
        """
        self._engine.set_line_sink(task.log)
        system_package.set_wait_sink(task.set_wait)

    def plan_task(self, task, entry: dict, *, has_installed: bool) -> tuple:
        """Plan a task's steps from its entry and what the machine shows.

        ``absent`` plans the uninstall when the software is there, the last
        install failed, or this task already ran an install step; a present
        ``want`` plans the install when the software is missing or the last
        install failed, the version switch when a ``hub`` module's kept
        version differs from its recipe's, then the configure steps under
        ``stopped`` and ``running``.

        Args:
            task: The task.
            entry: The state's entry it plans from.
            has_installed: Whether this task already ran an install step.

        Returns:
            ``(kind, steps)``: ``install``, ``switch``, ``uninstall`` or
            ``configure``, and the :class:`ModuleStep` list.
        """
        name = task.name
        if name == AI_TOOLS_SECTION:
            return PLAN_CONFIGURE, self._ai_tools.steps(
                entry.get("section"), receive=self.receive
            )
        want = str(entry.get("want", "") or "")
        if want == AGENT_WANT_ABSENT:
            if (
                has_installed
                or self._engine.is_install_failed(name)
                or self._engine.is_installed(name, entry)
            ):
                return PLAN_UNINSTALL, self._engine.uninstall_steps(name, entry)
            self._engine.clear_configured(name)
            return PLAN_CONFIGURE, []
        if want not in AGENT_PRESENT_WANTS:
            self._log(f"{name}: want {want!r} is not one this agent knows")
            return PLAN_CONFIGURE, []
        kind = PLAN_CONFIGURE
        steps = []
        if self._engine.is_install_failed(name) or not self._engine.is_installed(
            name, entry
        ):
            kind = PLAN_INSTALL
            steps += self._engine.install_steps(name, entry)
        elif self._engine.take_version_switch(name, entry):
            kind = PLAN_SWITCH
            steps += self._engine.switch_steps(name, entry)
        if want in CONFIGURING_WANTS:
            steps += self._engine.configure_steps(name, entry, want)
        return kind, steps

    def is_task_cut(self, task) -> bool:
        """Whether a task ends at the next step boundary with no failure.

        An installed container module's configure task ends there while
        Containers' ``want`` is not ``running``.

        Args:
            task: The task.

        Returns:
            True when its next step is not to run.
        """
        if task.kind != PLAN_CONFIGURE:
            return False
        if _method_of(task.entry) != AGENT_METHOD_CONTAINER:
            return False
        return self._containers_want() != AGENT_WANT_RUNNING

    def end_task(self, task, outcome, *, is_cut: bool, is_forced: bool = False) -> bool:
        """End a task, unless a newer entry came: keep its outcome and its tried hash.

        Args:
            task: The task.
            outcome: Its failure, ``{"state", "code", "params", "step"}``;
                None when every step took.
            is_cut: Whether it ended at a step boundary with no failure,
                which keeps no tried hash.
            is_forced: Whether it ends whatever newer entry it holds.

        Returns:
            True when the task ended; False when it holds a newer entry and
            plans again.
        """
        name = task.name
        entry = task.entry
        with self._lock:
            if task.has_newer() and not is_forced:
                return False
            task.end()
            is_kept = not is_cut and (
                outcome is None or outcome.get("code") != RETRIED_CODE
            )
            if is_kept:
                self._tried[name] = task.planned_hash
            else:
                self._tried.pop(name, None)
            tried = dict(self._tried)
            if name != AI_TOOLS_SECTION:
                self._outcomes[name] = dict(outcome) if outcome else None
        try:
            self._write_tried(tried)
            if name != AI_TOOLS_SECTION:
                self._keep_outcome(task, entry, outcome, is_cut=is_cut)
        finally:
            with self._idle:
                if self._tasks.get(name) is task:
                    del self._tasks[name]
                self._settle_hash()
                self._idle.notify_all()
        return True

    def task_changed(self, task) -> None:
        """Put a module task's row on the module's report row.

        Args:
            task: The task.
        """
        if task.name != AI_TOOLS_SECTION:
            self._engine.publish_task(task.name, task.row(), task.state(), task.wait())

    def pending_wait(self, task) -> dict:
        """What a step waiting for something outside the agent names.

        Args:
            task: The task.

        Returns:
            The runner's own wait where it names one, ``reboot_required``
            among them; else ``waiting_for_check {seconds}``.
        """
        runner = self._runner_of(task.name)
        wait = {}
        if runner is not None:
            try:
                wait = dict(runner.install_wait() or {})
            except Exception:  # noqa: BLE001 - a wait that cannot be read names none
                wait = {}
        if str(wait.get("code", "") or ""):
            return {"code": wait["code"], "params": dict(wait.get("params") or {})}
        return {
            "code": AGENT_WAIT_CHECK,
            "params": {"seconds": int(self._recheck_s)},
        }

    def closing_state(self, task) -> tuple:
        """The state and the failure a task's log stream closes with.

        Args:
            task: The task, ended.

        Returns:
            ``(state, failure)``: the module's state as the report now
            reads it, and its last task's failure, None when it took.
        """
        state = str((self._engine.report().get(task.name) or {}).get("state", ""))
        with self._lock:
            return state, self._outcomes.get(task.name)

    def open_log(self, name: str) -> "LogStream | None":
        """A ``log {module}`` stream to the hub, or None with no socket.

        Args:
            name: The module name; ``ai_tools`` opens none.

        Returns:
            The stream.
        """
        if self._open_stream is None or name == AI_TOOLS_SECTION:
            return None
        try:
            return LogStream(self._open_stream(STREAM_KIND_LOG, module=name))
        except GatewayUnreachable:
            return None

    def receive(self, name: str, artifact: dict) -> dict:
        """One artifact's bytes, down a ``package {module, artifact, digest}`` stream.

        Args:
            name: The module the artifact belongs to, or ``cc_switch``.
            artifact: The recipe's artifact, ``{name, digest, ...}``.

        Returns:
            ``{"path", "sha256"}`` naming the file the close's digest
            checked and that digest, or ``{"code", "params"}``.
        """
        if self._open_stream is None:
            return {"code": RETRIED_CODE, "params": {}}
        try:
            channel = self._open_stream(
                STREAM_KIND_PACKAGE,
                module=name,
                artifact=str(artifact.get("name", "") or ""),
                digest=str(artifact.get("digest", "") or ""),
            )
        except GatewayUnreachable:
            return {"code": RETRIED_CODE, "params": {}}
        return PackageStream(channel, directory=self._package_dir).receive()

    def wait_for_containers(self, task) -> None:
        """Wait until Containers reads ``running`` and has no task.

        Args:
            task: The container module's task.

        Raises:
            ModuleApplyError: ``module_needed {module, state}`` when
                Containers' ``want`` is not ``running``, or when it has no
                task and does not read ``running``.
            StepSuperseded: When the task holds a newer entry meanwhile.
        """
        while True:
            with self._lock:
                want = self._containers_want()
                containers = self._tasks.get(CONTAINERS_MODULE)
            if want != AGENT_WANT_RUNNING:
                raise self._module_needed()
            if containers is None:
                if self._containers_state() == AGENT_WANT_RUNNING:
                    task.set_wait({})
                    return
                raise self._module_needed()
            task.set_wait(module_wait(CONTAINERS_MODULE))
            task.wait_for_task(containers)

    def render_containers(self, task) -> None:
        """Ask Containers for a configure task, and wait for it to end.

        Containers' running task takes the ask as a newer entry and
        configures once more after its plan; two asks while it runs make
        one more configure.

        Args:
            task: The container module's task.

        Raises:
            ModuleApplyError: ``module_needed {module, state}`` when
                Containers is not to run, or does not read ``running``
                afterwards.
            StepSuperseded: When the task holds a newer entry meanwhile.
        """
        made = None
        with self._lock:
            entry = self._modules.get(CONTAINERS_MODULE)
            if entry is None or self._containers_want() != AGENT_WANT_RUNNING:
                containers = None
            else:
                containers = self._tasks.get(CONTAINERS_MODULE)
                entry_hash = _section_hash(entry)
                if containers is not None and containers.is_running:
                    containers.offer(entry, entry_hash)
                else:
                    containers = made = self._new_task(
                        CONTAINERS_MODULE, entry, entry_hash
                    )
        if containers is None:
            raise self._module_needed()
        if made is not None:
            made.start()
        task.set_wait(module_wait(CONTAINERS_MODULE))
        task.wait_for_task(containers)
        task.set_wait({})
        if self._containers_state() != AGENT_WANT_RUNNING:
            raise self._module_needed()

    def _keep_outcome(self, task, entry: dict, outcome, *, is_cut: bool) -> None:
        """Mark a module configured once its task took, keep its failure, and read its row again."""
        name = task.name
        want = str(entry.get("want", "") or "")
        if outcome is None and not is_cut and want in CONFIGURING_WANTS:
            try:
                self._engine.mark_configured(name)
            except OSError as error:
                self._log(f"{name}: could not mark it configured: {error}")
        if outcome is not None:
            said = " ".join(
                f"{key}={value}" for key, value in outcome["params"].items()
            )
            self._log(f"{name}: {outcome['code']} {said}".rstrip()[:500])
        self._engine.record_failure(name, outcome)
        self._engine.publish_task(name, task.row(), "", {})
        if task.kind == PLAN_CONFIGURE:
            self._engine.refresh_one(name)

    def _is_settled(self, module: str) -> bool:
        """Whether no state is pending and the module's task has ended. Call under the lock."""
        if self._pending is not None or self._is_dispatching:
            return False
        if module:
            return module not in self._tasks
        return not self._tasks

    def _offer(self, name: str, entry: dict, entry_hash: str):
        """Hand one entry to the module's running task, or make a task for it. Call under the lock.

        Returns:
            The task made, for the caller to start; None when none was.
        """
        task = self._tasks.get(name)
        if task is not None and task.is_running:
            if task.entry_hash != entry_hash:
                task.offer(entry, entry_hash)
            return None
        if entry_hash == self._tried.get(name):
            return None
        return self._new_task(name, entry, entry_hash)

    def _new_task(self, name: str, entry: dict, entry_hash: str):
        """A task for one module, kept as its running one. Call under the lock."""
        task = ModuleTask(
            name=name,
            entry=entry,
            entry_hash=entry_hash,
            owner=self,
            locks=self._locks,
            log=self._log,
            recheck_s=self._recheck_s,
        )
        self._tasks[name] = task
        return task

    def _runner_of(self, name: str):
        """The runner of one module, a container module's made since the start among them."""
        return self._runners.get(name) or self._engine.runner_of(name)

    def _containers_want(self) -> str:
        """Containers' ``want`` in the latest state. Call under the lock."""
        entry = self._modules.get(CONTAINERS_MODULE) or {}
        return str(entry.get("want", "") or "")

    def _containers_state(self) -> str:
        """Containers' state as its row reads it now."""
        row = self._engine.report().get(CONTAINERS_MODULE) or {}
        return str(row.get("state", "") or "")

    def _module_needed(self) -> ModuleApplyError:
        """``module_needed {module, state}`` naming Containers and the state it reads."""
        return ModuleApplyError(
            CODE_MODULE_NEEDED,
            {"module": CONTAINERS_MODULE, "state": self._containers_state()},
        )

    def _apply_desktop(self, wanted) -> None:
        """Give the desktop host the seat password the hub holds.

        The Remote desktop module writes it into RustDesk's settings when it
        applies, and only when it is not the one written there.

        Args:
            wanted: The state's ``desktop`` section, or anything else when
                it carries none.
        """
        if self._rdp is None or not isinstance(wanted, dict):
            return
        self._rdp.take_seat_password(str(wanted.get("seat_password", "")))

    def _write_tried(self, tried: dict) -> None:
        """Keep the hashes last tried on disk. A failure is a line in the log."""
        try:
            self._store.write_tried(tried)
        except OSError as error:
            self._log(f"could not keep the tried state: {error}")

    def _settle_hash(self) -> None:
        """Move the applied hash and the state error by every mentioned module's task. Call under the lock."""
        first_failure = None
        for name in self._order:
            outcome = self._outcomes.get(name)
            if outcome is not None and first_failure is None:
                first_failure = {"module": name, **outcome}
        if first_failure is not None:
            self._state_error = {
                "code": first_failure["code"],
                "params": {
                    "module": first_failure["module"],
                    **first_failure["params"],
                },
            }
            return
        self._state_error = None
        is_busy = any(name in self._tasks for name in self._order) or (
            AI_TOOLS_SECTION in self._tasks
        )
        if not is_busy:
            self._applied_hash = str(self._document.get("hash", "") or "")

    def _run(self) -> None:
        while True:
            self._wakeup.wait()
            self._wakeup.clear()
            while True:
                with self._lock:
                    pending = self._pending
                    self._pending = None
                    self._is_dispatching = pending is not None
                if pending is None:
                    with self._idle:
                        self._idle.notify_all()
                    break
                try:
                    self.apply(pending)
                except Exception as error:  # noqa: BLE001 - the loop must survive
                    self._log(f"applying the desired state crashed: {error}")
                finally:
                    with self._idle:
                        self._is_dispatching = False
                        self._idle.notify_all()
