"""Reporting what each module is, and putting software on and off the machine.

The hub's state names, per module, what is wanted and the recipe resolved
for this platform, ``{runner, method, params}``. The recipe's ``runner``
chooses the runner, and an agent with no runner of that name reports the
module unsupported. :class:`ModuleEngine` observes every module it has a
runner for, named by the state or not, and derives one typed state from
three facts: whether the software is there, by the method's one presence
check, whether its unit is active, and whether the hub has configured it,
which is a root-only mark on disk. It also builds the steps a module's task
runs: the install by the recipe's method, the version switch, the
configure path and the uninstall, each step naming the step locks it takes.
A row of a module whose task runs carries the task, and reads ``queued``,
``installing`` or ``uninstalling`` while the task's plan asks for it.
:class:`ReconcileWorker` is the shared pattern: a thread woken by news, a signature that skips unchanged
inputs, an idle re-check so drift is still noticed, and per-name typed
statuses.

The engine keeps **no retry policy**: a step that failed is reported with
its code and never repeated, because deciding to try again is the hub's.
Each module's last failed step is kept on disk, one root-only file per
module beside the configured marks, so an agent that starts again reports
it as it was: ``install_failed`` for an install, ``failed`` for any other
step. The recipes it works from are already resolved for this platform, so
nothing here reads a manifest or searches a platform table either.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import dataclasses
import functools
import json
import os
import tempfile
import threading
import time

from neutrino_agent.constants import (
    AGENT_ARTIFACT_KEPT_SUFFIXES,
    AGENT_ARTIFACT_KIND_BINARY,
    AGENT_ARTIFACT_KIND_MSI,
    AGENT_ARTIFACT_KIND_PKG,
    AGENT_CONFIGURED_DIR,
    AGENT_CONTAINER_RUNNER,
    AGENT_CONTAINERS_MODULE,
    AGENT_METHOD_AGENT,
    AGENT_METHOD_BUILTIN,
    AGENT_METHOD_CONTAINER,
    AGENT_METHOD_HUB,
    AGENT_METHOD_SYSTEM,
    AGENT_FAILURES_DIR_NAME,
    AGENT_LOCK_ALONE,
    AGENT_LOCK_CONTAINERS,
    AGENT_LOCK_PACKAGE_MANAGER,
    AGENT_LOCK_SHARED,
    AGENT_MODULE_DETAILS_TTL_S,
    AGENT_MODULE_STATE_ABSENT,
    AGENT_MODULE_STATE_FAILED,
    AGENT_MODULE_STATE_INSTALL_FAILED,
    AGENT_MODULE_STATE_INSTALLED,
    AGENT_MODULE_STATE_INSTALLING,
    AGENT_MODULE_STATE_RUNNING,
    AGENT_MODULE_STATE_STOPPED,
    AGENT_MODULE_STATE_UNSUPPORTED,
    AGENT_STEP_ARTIFACT,
    AGENT_STEP_CONFIGURE,
    AGENT_STEP_PACKAGES,
    AGENT_STEP_PULL,
    AGENT_STEP_RENDER,
    AGENT_STEP_START,
    AGENT_STEP_STOP,
    AGENT_STEP_SWITCH,
    AGENT_STEP_UNINSTALL,
    AGENT_STEP_VERIFY,
    AGENT_STEP_WAIT_CONTAINERS,
    AGENT_VERSIONS_DIR_NAME,
    AGENT_WANT_RUNNING,
    AGENT_WANT_STOPPED,
)
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.ayakaleaf.constants import AYAKALEAF_NAME
from neutrino_agent.modules.ayakaleaf.hooks import AyakaleafHooks
from neutrino_agent.modules.cloudcli.hooks import CloudcliHooks
from neutrino_agent.modules.code_server.hooks import CodeServerHooks
from neutrino_agent.modules.codeg.hooks import CodegHooks
from neutrino_agent.modules.gitea.runner import GiteaModuleRunner
from neutrino_agent.modules.hermes_webui.constants import HERMES_WEBUI_NAME
from neutrino_agent.modules.hermes_webui.hooks import HermesWebuiHooks
from neutrino_agent.modules.podman.container_runner import (
    CONTAINER_MODULE_HOOKS,
    ContainerModuleRunner,
)
from neutrino_agent.modules.podman.machine_runner import PodmanMachineModuleRunner
from neutrino_agent.modules.podman.runner import PodmanModuleRunner
from neutrino_agent.modules.remote_desktop.runner import RemoteDesktopModuleRunner
from neutrino_agent.modules.samba.runner import (
    SambaModuleRunner,
    SambaNativeServerRunner,
)
from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared.base import ModuleStep
from neutrino_agent.modules.shared.instances import InstancesModuleRunner
from neutrino_agent.modules.podman.container_runner import recipe_images
from neutrino_agent.modules.shared.package import (
    check_received,
    drop_replaced,
    is_archive_kind,
    joiner,
    params_of,
    received_artifacts,
    remove_received,
    remove_staged,
    stage_artifact,
    swap_back,
    swap_in,
    verify_detail,
    verify_passes,
)
from neutrino_agent.modules.shared.step_locks import ordered
from neutrino_agent.modules.siyuan.hooks import SiyuanHooks
from neutrino_agent.modules.ssh_server.hooks import SshServerHooks
from neutrino_agent.modules.terminal.runner import TerminalModuleRunner
from neutrino_agent.modules.vscode.hooks import VscodeHooks
from neutrino_agent.platforms.detect import platform_tuple

# How often to re-check inputs that have not changed. Every heartbeat wakes
# the worker, and running each module's verify command that often would keep
# a Raspberry Pi busy doing nothing.
IDLE_RECHECK_INTERVAL_S = 60

# The methods whose presence check is the recipe's ``verify`` command.
VERIFIED_METHODS = (AGENT_METHOD_SYSTEM, AGENT_METHOD_HUB)
# The methods an install runs by; ``agent`` takes no operation.
INSTALLED_METHODS = (
    AGENT_METHOD_BUILTIN,
    AGENT_METHOD_SYSTEM,
    AGENT_METHOD_HUB,
    AGENT_METHOD_CONTAINER,
)

# The programs run as a person's account, each the shared runner with the
# module's own hooks.
VscodeModuleRunner = functools.partial(InstancesModuleRunner, hooks_class=VscodeHooks)
CodeServerModuleRunner = functools.partial(
    InstancesModuleRunner, hooks_class=CodeServerHooks
)
CloudcliModuleRunner = functools.partial(
    InstancesModuleRunner, hooks_class=CloudcliHooks
)
CodegModuleRunner = functools.partial(InstancesModuleRunner, hooks_class=CodegHooks)
SiyuanModuleRunner = functools.partial(InstancesModuleRunner, hooks_class=SiyuanHooks)
SshServerModuleRunner = functools.partial(
    InstancesModuleRunner, hooks_class=SshServerHooks
)
# The container modules with hooks of their own, which the container runner
# reads by module name.
CONTAINER_MODULE_HOOKS[HERMES_WEBUI_NAME] = HermesWebuiHooks
CONTAINER_MODULE_HOOKS[AYAKALEAF_NAME] = AyakaleafHooks

# The states a kept failure reads as: an install's, and every other step's.
FAILURE_STATES = (AGENT_MODULE_STATE_INSTALL_FAILED, AGENT_MODULE_STATE_FAILED)
# The suffix of the file one module's failure is kept in.
FAILURE_SUFFIX = ".json"
# The artifacts the system's own installer puts on the machine: another
# version replaces them by an uninstall and an install.
SYSTEM_INSTALLED_KINDS = (AGENT_ARTIFACT_KIND_MSI, AGENT_ARTIFACT_KIND_PKG)
# The locks of a step that runs the system's installer.
PACKAGE_MANAGER_LOCKS = ((AGENT_LOCK_PACKAGE_MANAGER, AGENT_LOCK_ALONE),)
# The locks of a container module's step on Containers' engine.
CONTAINERS_SHARED_LOCKS = ((AGENT_LOCK_CONTAINERS, AGENT_LOCK_SHARED),)
# The locks of a container module's uninstall. It drops its hub containers.
CONTAINERS_ALONE_LOCKS = ((AGENT_LOCK_CONTAINERS, AGENT_LOCK_ALONE),)


class ReconcileWorker:
    """A background reconcile loop that skips inputs it has already seen."""

    def __init__(self, *, log=print, on_change=None):
        """
        Args:
            log: Callable used for progress messages; defaults to printing,
                which systemd captures into the journal.
            on_change: Called whenever a name's status changes. The agent
                uses it to beat straight away: a step that takes three
                seconds would otherwise begin and end between two
                heartbeats, and nobody watching would ever see it running.
        """
        self._log = log
        self._on_change = on_change
        self._lock = threading.Lock()
        self._statuses: dict = {}
        self._signature = ""
        self._checked_at = 0.0
        self._wakeup = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def report(self) -> dict:
        """The per-name statuses, each ``{"state", "code", "params", ...}``."""
        with self._lock:
            return {name: dict(value) for name, value in self._statuses.items()}

    def _run(self) -> None:
        while True:
            self._wakeup.wait()
            self._wakeup.clear()
            try:
                self._reconcile()
            except Exception as error:  # noqa: BLE001 - the loop must survive
                self._log(f"reconcile crashed: {error}")

    def _reconcile(self) -> None:
        raise NotImplementedError

    def _is_stale(self, signature: str) -> bool:
        """Whether these inputs need work: changed, or idle long enough.

        Call under the worker's own lock.

        Args:
            signature: A stable serialization of the current inputs.

        Returns:
            True when a pass should run.
        """
        is_stale = (
            signature != self._signature
            or time.monotonic() - self._checked_at > IDLE_RECHECK_INTERVAL_S
        )
        self._signature = signature
        if is_stale:
            self._checked_at = time.monotonic()
        return is_stale

    def _publish(self, name: str, status: dict) -> None:
        """Record one name's status, and say so if it is news."""
        with self._lock:
            is_news = self._statuses.get(name) != status
            self._statuses[name] = status
        if is_news and self._on_change is not None:
            self._on_change()

    def _keep_only(self, names) -> None:
        """Drop statuses for names no longer in play."""
        with self._lock:
            self._statuses = {
                name: value for name, value in self._statuses.items() if name in names
            }


class ModuleEngine(ReconcileWorker):
    """Observes every module this machine has a runner for, and moves software."""

    def __init__(
        self,
        *,
        platform,
        log=print,
        on_change=None,
        configured_dir="",
        failures_dir="",
        versions_dir="",
    ):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            on_change: Called whenever a module's state changes.
            configured_dir: Where the configured marks live; empty is the
                machine's own directory.
            failures_dir: Where each module's last failed step is kept;
                empty is beside the configured marks.
            versions_dir: Where each ``hub`` module's installed version is
                kept; empty is beside the configured marks.
        """
        # The state's modules section as the hub last sent it, by name:
        # ``{"want", "config", "install"}`` each.
        self._wanted: dict = {}
        self._configured_dir = configured_dir or AGENT_CONFIGURED_DIR
        self._failures_dir = failures_dir or os.path.join(
            os.path.dirname(self._configured_dir), AGENT_FAILURES_DIR_NAME
        )
        self._versions_dir = versions_dir or os.path.join(
            os.path.dirname(self._configured_dir), AGENT_VERSIONS_DIR_NAME
        )
        self._platform_tuple = platform_tuple()
        # The line sink of the task running on each thread.
        self._lines = threading.local()
        # A runner logs while it is made (the file share's fence that did not
        # load), so the log is set before the runners are.
        self._log = log
        # Module name to its task's overlay on the row, ``{"task", "state",
        # "wait"}``; ``state`` empty while the row reads what the machine shows.
        self._task_rows: dict = {}
        # Module name to its last failed step, ``{"state", "code",
        # "params"}``, as kept on disk.
        self._failures: dict = {}
        # Module name to the detail of the read that last failed, logged once.
        self._verify_failures: dict = {}
        self._details_at = 0.0
        # The modules this agent applies the hub's configuration to, by
        # name; each also answers its own verbs. A platform that installs no
        # package has a runner only for what the system itself carries and
        # what the hub's cache sends: every other module the state names
        # reads as unsupported there.
        kinds = []
        if "packages" in platform.capabilities:
            kinds = [
                SambaModuleRunner,
                GiteaModuleRunner,
                PodmanModuleRunner,
                VscodeModuleRunner,
                CodeServerModuleRunner,
                CloudcliModuleRunner,
                CodegModuleRunner,
                SiyuanModuleRunner,
            ]
        else:
            if "smb_server" in platform.capabilities:
                kinds.append(SambaNativeServerRunner)
            if "hub_packages" in platform.capabilities:
                kinds.append(GiteaModuleRunner)
                kinds.append(VscodeModuleRunner)
                if platform.os_name == "darwin":
                    kinds.append(CodeServerModuleRunner)
                kinds.append(CloudcliModuleRunner)
                kinds.append(CodegModuleRunner)
                kinds.append(SiyuanModuleRunner)
                if platform.os_name in ("windows", "darwin"):
                    kinds.append(PodmanMachineModuleRunner)
        kinds.append(TerminalModuleRunner)
        kinds.append(RemoteDesktopModuleRunner)
        kinds.append(SshServerModuleRunner)
        self._module_runners = {}
        self._runners_by_name = {}
        for kind in kinds:
            runner = kind(platform=platform, log=self._collect, publish=self._publish)
            self._module_runners[runner.name] = runner
            self._runners_by_name[runner.runner] = runner
        self._platform = platform
        # One runner per container module the state has named, by module
        # name, each reaching Podman through the Containers runner.
        self._container_runners: dict = {}
        # Asks for a configure task of a module, by name; None asks nobody.
        self._configure_asker = None
        self._failures = self._read_failures()
        super().__init__(log=log, on_change=on_change)

    @property
    def module_runners(self) -> dict:
        """The runners that apply configuration, by module name, container modules' among them."""
        with self._lock:
            return {**self._module_runners, **self._container_runners}

    def runner_of(self, name: str):
        """The runner of one module as the engine holds it now.

        A container module's runner is made when a state first names the
        module, so a caller looks it up each time it needs it.

        Args:
            name: The module name.

        Returns:
            The runner, or None for a module this agent runs none of.
        """
        return self.module_runners.get(name)

    def container_runners(self) -> dict:
        """The runners of the container modules the state has named, by module name.

        Returns:
            A copy of the map.
        """
        with self._lock:
            return dict(self._container_runners)

    @property
    def platform_tuple(self) -> dict:
        """This machine's platform tuple, for the report."""
        return self._platform_tuple

    def report(self) -> dict:
        """The per-module statuses, read again when stale.

        Returns:
            ``{name: {"state", "is_active", "code", "params", "details"}}``.
        """
        if time.monotonic() - self._details_at > AGENT_MODULE_DETAILS_TTL_S:
            self._wakeup.set()
        return super().report()

    def take_state(self, modules: dict, source_sets: "dict | None" = None) -> None:
        """Take the modules section of the hub's state, and observe against it.

        Each module's runner is handed its recipe and its configuration, a
        container module getting its runner the first time the state names
        it, and every runner the state's source sets. The failure kept for a
        module the state no longer names is deleted.

        Args:
            modules: ``{name: {"want", "config", "install"}}``; empty when
                the machine belongs to no hub.
            source_sets: The state's ``source_sets`` section; None is none.
        """
        with self._lock:
            self._wanted = {
                name: dict(entry)
                for name, entry in modules.items()
                if isinstance(entry, dict)
            }
            wanted = dict(self._wanted)
            dropped = [name for name in self._failures if name not in self._wanted]
            for name, entry in wanted.items():
                self._add_container_runner(name, _recipe_of(entry))
            runners = {**self._module_runners, **self._container_runners}
        sets = dict(source_sets) if isinstance(source_sets, dict) else {}
        for runner in runners.values():
            runner.take_source_sets(sets)
        for name, entry in wanted.items():
            recipe = _recipe_of(entry)
            runner = self._runner_for(name, recipe)
            if runner is not None:
                runner.take_recipe(recipe)
                config = entry.get("config")
                runner.take_config(dict(config) if isinstance(config, dict) else {})
        for name in dropped:
            self.record_failure(name, None)
        self._wakeup.set()

    def is_installed(self, name: str, entry: "dict | None" = None) -> bool:
        """Whether one module's software is on this machine, checked now.

        Args:
            name: The module name.
            entry: The state's entry whose recipe is checked; None takes the
                latest state's.

        Returns:
            True when the method's presence check passes; False for a module
            this agent has no runner for or cannot read.
        """
        recipe = _recipe_of(entry if entry is not None else self._wanted_of(name))
        runner = self._runner_for(name, recipe)
        if runner is None:
            return False
        try:
            return self._is_present(runner, recipe)
        except Exception:  # noqa: BLE001 - an unreadable module is not installed
            return False

    def is_configured(self, name: str) -> bool:
        """Whether the hub's configuration was ever applied to one module.

        Args:
            name: The module name.

        Returns:
            True while the module's mark stands.
        """
        return os.path.isfile(os.path.join(self._configured_dir, name))

    def mark_configured(self, name: str) -> None:
        """Record that the hub's configuration applied to one module.

        Args:
            name: The module name.

        Raises:
            OSError: When the mark cannot be written.
        """
        os.makedirs(self._configured_dir, mode=0o700, exist_ok=True)
        path = os.path.join(self._configured_dir, name)
        with open(path, "a", encoding="utf-8"):
            pass
        os.chmod(path, 0o600)

    def clear_configured(self, name: str) -> None:
        """Forget that the hub ever configured one module.

        Args:
            name: The module name.
        """
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(self._configured_dir, name))

    def record_failure(self, name: str, failure: "dict | None") -> None:
        """Keep how one module's last step failed, on disk, or delete it.

        A name that is not one plain file name keeps nothing.

        Args:
            name: The module name.
            failure: ``{"state", "code", "params"}``, ``state`` being
                ``install_failed`` or ``failed``; None when the step took.
        """
        if not _is_plain(name):
            return
        kept = _failure(failure) if failure else None
        with self._lock:
            if self._failures.get(name) == kept:
                return
            if kept is None:
                self._failures.pop(name, None)
            else:
                self._failures[name] = kept
        self._write_failure(name, kept)

    def is_install_failed(self, name: str) -> bool:
        """Whether one module's last install failed and nothing replaced it.

        Args:
            name: The module name.

        Returns:
            True while its kept failure reads ``install_failed``.
        """
        with self._lock:
            failure = self._failures.get(name) or {}
        return failure.get("state") == AGENT_MODULE_STATE_INSTALL_FAILED

    def publish_task(self, name: str, task: dict, state: str, wait: dict) -> None:
        """Put one module's task on its row.

        A kept failure stays off the row while the task runs, so a module
        with one is read again when its task starts.

        Args:
            name: The module name.
            task: The task's row, ``{steps, index, wait, is_running}``.
            state: ``queued``, ``installing`` or ``uninstalling`` while the
                task's plan has the row read it; empty keeps the state the
                machine shows.
            wait: The wait a ``queued`` or ``installing`` row carries as its
                code, ``{code, params}``; empty for none.
        """
        with self._lock:
            was_transient = bool((self._task_rows.get(name) or {}).get("state"))
            was_running = self._is_task_running(name)
            self._task_rows[name] = {
                "task": dict(task),
                "state": state,
                "wait": dict(wait),
            }
            status = self._statuses.get(name)
            is_failure_hidden = (
                self._is_task_running(name)
                and not was_running
                and name in self._failures
            )
        if state:
            self._publish_observed(name, _typed(state))
        elif was_transient or is_failure_hidden:
            self.refresh_one(name)
        elif status is not None:
            self._publish_observed(name, dict(status))

    def set_configure_asker(self, asker) -> None:
        """Let every runner ask for a configure task of its own module.

        Args:
            asker: Called with a module's name; asks for a configure task
                of it. A container module's runner made later takes it too.
        """
        with self._lock:
            self._configure_asker = asker
            runners = {**self._module_runners, **self._container_runners}
        for name, runner in runners.items():
            runner.bind_configure_asker(functools.partial(asker, name))

    def set_line_sink(self, on_line) -> None:
        """Hand the lines the runners log on this thread to a task's stream.

        Args:
            on_line: Called with each line; None hands them to nobody.
        """
        self._lines.on_line = on_line

    def refresh_now(self) -> None:
        """Report every module again from what is true right now."""
        self._refresh(is_forced=True)

    def refresh_one(self, name: str) -> None:
        """Report one module again from what is true right now.

        Args:
            name: The module name.
        """
        with self._lock:
            observed = self._observed()
        if name in observed:
            self._publish_observed(name, self._read_one(name, observed[name]))

    def install_steps(self, name: str, entry: dict) -> list:
        """The steps that put one module's software on the machine, by its recipe's method.

        Args:
            name: The module name.
            entry: The state's entry the task plans from.

        Returns:
            :class:`ModuleStep` each, with the runner's own changes:
            ``packages`` for a ``system`` recipe and a ``hub`` recipe that
            names system packages, ``artifact {name}`` per artifact a
            ``hub`` recipe receives, then ``verify``; a ``container``
            recipe's ``wait_containers``, ``pull {image}`` per image,
            ``verify`` and ``render``.
        """
        recipe = _recipe_of(entry)
        runner = self._runner_for(name, recipe)
        method = str(recipe.get("method", "") or "")
        if runner is None or method not in INSTALLED_METHODS:
            return [self._refused_step(name, recipe, runner)]
        if method == AGENT_METHOD_CONTAINER:
            steps = [self._wait_containers_step(AGENT_MODULE_STATE_INSTALL_FAILED)]
            steps += [
                ModuleStep(
                    name=AGENT_STEP_PULL,
                    params={"image": image["name"]},
                    run=functools.partial(self._run_pull, runner, image),
                    locks=CONTAINERS_SHARED_LOCKS,
                    failed_state=AGENT_MODULE_STATE_INSTALL_FAILED,
                    error_code="install_failed",
                )
                for image in recipe_images(recipe)
            ]
            steps.append(
                self._verify_step(name, runner, recipe, CONTAINERS_SHARED_LOCKS)
            )
            steps.append(
                ModuleStep(
                    name=AGENT_STEP_RENDER,
                    run=_render_containers,
                    failed_state=AGENT_MODULE_STATE_INSTALL_FAILED,
                    error_code="install_failed",
                )
            )
        else:
            params = params_of(recipe)
            steps = []
            if (
                method == AGENT_METHOD_SYSTEM
                or params.get("packages")
                or params.get("pre_install")
            ):
                steps.append(
                    ModuleStep(
                        name=AGENT_STEP_PACKAGES,
                        run=functools.partial(self._run_packages, runner, recipe),
                        locks=PACKAGE_MANAGER_LOCKS,
                        failed_state=AGENT_MODULE_STATE_INSTALL_FAILED,
                        error_code="install_failed",
                    )
                )
            if method == AGENT_METHOD_HUB:
                steps += [
                    ModuleStep(
                        name=AGENT_STEP_ARTIFACT,
                        params={"name": str(artifact.get("name", "") or "")},
                        run=functools.partial(
                            self._run_artifact, runner, recipe, dict(artifact)
                        ),
                        locks=_installer_locks([artifact]),
                        failed_state=AGENT_MODULE_STATE_INSTALL_FAILED,
                        error_code="install_failed",
                    )
                    for artifact in received_artifacts(recipe)
                ]
            steps.append(self._verify_step(name, runner, recipe, ()))
        return self._with_runner_locks(runner, runner.install_steps(recipe, steps))

    def switch_steps(self, name: str, entry: dict) -> list:
        """The one ``switch {version}`` step that puts the recipe's version in place of the one installed.

        Args:
            name: The module name.
            entry: The state's entry the task plans from.

        Returns:
            The step, under ``package_manager`` when an artifact is an msi
            or a pkg.
        """
        recipe = _recipe_of(entry)
        runner = self._runner_for(name, recipe)
        step = ModuleStep(
            name=AGENT_STEP_SWITCH,
            params={"version": str(params_of(recipe).get("version", "") or "")},
            run=functools.partial(self._run_switch, name, dict(entry)),
            locks=_installer_locks(received_artifacts(recipe)),
            error_code="version_switch_failed",
        )
        return self._with_runner_locks(runner, [step])

    def configure_steps(self, name: str, entry: dict, want: str) -> list:
        """The steps that apply one module's configuration and settle its unit.

        Args:
            name: The module name.
            entry: The state's entry the task plans from.
            want: ``running`` or ``stopped``.

        Returns:
            ``configure``, then ``start`` under ``running`` and ``stop``
            under ``stopped``, with the runner's own changes; a container
            module's begin with ``wait_containers``, and its ``start`` and
            ``stop`` take ``containers`` shared.
        """
        recipe = _recipe_of(entry)
        runner = self._runner_for(name, recipe)
        config = entry.get("config")
        config = dict(config) if isinstance(config, dict) else {}
        is_container = str(recipe.get("method", "") or "") == AGENT_METHOD_CONTAINER
        unit_locks = CONTAINERS_SHARED_LOCKS if is_container else ()
        steps = (
            [self._wait_containers_step(AGENT_MODULE_STATE_FAILED)]
            if is_container
            else []
        )
        steps.append(
            ModuleStep(
                name=AGENT_STEP_CONFIGURE,
                run=functools.partial(_run_apply, runner, config),
            )
        )
        if want == AGENT_WANT_RUNNING:
            steps.append(
                ModuleStep(
                    name=AGENT_STEP_START,
                    run=functools.partial(_run_start, runner),
                    locks=unit_locks,
                )
            )
        elif want == AGENT_WANT_STOPPED:
            steps.append(
                ModuleStep(
                    name=AGENT_STEP_STOP,
                    run=functools.partial(_run_stop, runner),
                    locks=unit_locks,
                )
            )
        return self._with_runner_locks(
            runner, runner.configure_steps(config, want, steps)
        )

    def uninstall_steps(self, name: str, entry: dict) -> list:
        """The one ``uninstall`` step that takes one module's software off the machine.

        The configuration the hub wrote and the configured mark go with it;
        the module's data stays where the recipe says so. On software the
        recipe's check does not find, what an earlier install left, a part
        that fails is logged and the check afterwards is the outcome.

        Args:
            name: The module name.
            entry: The state's entry the task plans from.

        Returns:
            The step, under ``package_manager`` for a recipe that removes
            system packages, an msi or a pkg, and ``containers`` alone for
            a container module, with the runner's own changes.
        """
        recipe = _recipe_of(entry)
        runner = self._runner_for(name, recipe)
        method = str(recipe.get("method", "") or "")
        if method == AGENT_METHOD_CONTAINER:
            locks = CONTAINERS_ALONE_LOCKS
        elif method == AGENT_METHOD_SYSTEM:
            locks = PACKAGE_MANAGER_LOCKS
        else:
            locks = _installer_locks(received_artifacts(recipe))
        step = ModuleStep(
            name=AGENT_STEP_UNINSTALL,
            run=functools.partial(self._run_uninstall, name, dict(entry)),
            locks=locks,
            error_code="uninstall_failed",
        )
        if runner is None:
            return [step]
        return self._with_runner_locks(runner, runner.uninstall_steps(recipe, [step]))

    def installed_version(self, name: str) -> dict:
        """The version of one ``hub`` module the agent installed, as it keeps it.

        Args:
            name: The module name.

        Returns:
            ``{"version", "digests"}``, ``digests`` each installed
            artifact's digest by name; empty when none is kept.
        """
        try:
            with open(self._version_path(name), "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        if not isinstance(held, dict) or not isinstance(held.get("version"), str):
            return {}
        digests = held.get("digests")
        return {
            "version": held["version"],
            "digests": dict(digests) if isinstance(digests, dict) else {},
        }

    def take_version_switch(self, name: str, entry: dict) -> bool:
        """Whether an installed ``hub`` module is to be switched to the version its recipe names.

        A module installed before the agent kept its version takes the
        recipe's as its own here, and is not switched.

        Args:
            name: The module name.
            entry: The state's entry the task plans from.

        Returns:
            True when the kept version differs from the recipe's.
        """
        recipe = _recipe_of(entry)
        if str(recipe.get("method", "") or "") != AGENT_METHOD_HUB:
            return False
        if self._runner_for(name, recipe) is None:
            return False
        wanted = str(params_of(recipe).get("version", "") or "")
        held = self.installed_version(name)
        if not held:
            self._keep_version(name, recipe)
            return False
        return bool(wanted) and held["version"] != wanted

    def _verify_step(self, name: str, runner, recipe: dict, locks: tuple) -> ModuleStep:
        """The ``verify`` step: the method's presence check, a ``hub`` module's version kept."""
        return ModuleStep(
            name=AGENT_STEP_VERIFY,
            run=functools.partial(self._run_verify, name, runner, dict(recipe)),
            locks=locks,
            failed_state=AGENT_MODULE_STATE_INSTALL_FAILED,
            error_code="install_failed",
        )

    def _wait_containers_step(self, failed_state: str) -> ModuleStep:
        """The ``wait_containers`` step, holding no lock."""
        return ModuleStep(
            name=AGENT_STEP_WAIT_CONTAINERS,
            run=_wait_for_containers,
            failed_state=failed_state,
            error_code="install_failed",
        )

    def _refused_step(self, name: str, recipe: dict, runner) -> ModuleStep:
        """A ``verify`` step that fails at once: no runner, a module the agent carries, or a method this agent does not install by."""
        if recipe.get("method") == AGENT_METHOD_AGENT:
            refusal = ModuleApplyError("module_not_orderable", {"module": name})
        elif runner is None:
            refusal = ModuleApplyError(
                "runner_unknown", {"runner": str(recipe.get("runner", "") or "")}
            )
        else:
            refusal = ModuleApplyError(
                "method_unknown", {"method": str(recipe.get("method", "") or "")}
            )
        return ModuleStep(
            name=AGENT_STEP_VERIFY,
            run=functools.partial(_raise, refusal),
            failed_state=AGENT_MODULE_STATE_INSTALL_FAILED,
        )

    def _with_runner_locks(self, runner, steps: list) -> list:
        """Each step with the locks its runner adds, in the order they are taken."""
        return [
            dataclasses.replace(
                step, locks=ordered((*step.locks, *runner.step_locks(step.name)))
            )
            for step in steps
        ]

    def _run_packages(self, runner, recipe: dict, context) -> None:
        """Install the recipe's system packages by name, its ``pre_install`` first."""
        runner.install(recipe)

    def _run_artifact(self, runner, recipe: dict, artifact: dict, context) -> None:
        """Receive one artifact, check its digest against the recipe, install it.

        Raises:
            ModuleApplyError: The stream's own ``{code, params}`` when the
                hub could not hand it down; ``package_digest_mismatch`` when
                its bytes are not the recipe's.
        """
        received = context.receive(artifact)
        if "path" not in received:
            raise ModuleApplyError(
                str(received.get("code", "") or "hub_unreachable"),
                dict(received.get("params") or {}),
            )
        try:
            refusal = check_received(artifact, received)
            if refusal:
                raise ModuleApplyError(refusal["code"], dict(refusal["params"]))
            runner.install_artifact(recipe, dict(artifact), received["path"])
        finally:
            remove_received(received["path"])

    def _run_verify(self, name: str, runner, recipe: dict, context) -> None:
        """Check the software is there by the method's check, and keep a ``hub`` module's version.

        Raises:
            ModuleApplyError: ``install_unconfirmed`` when the check fails;
                a package manager that exits zero and installs nothing is a
                thing that happens.
        """
        if not self._is_present(runner, recipe):
            raise ModuleApplyError("install_unconfirmed", {})
        if str(recipe.get("method", "") or "") == AGENT_METHOD_HUB:
            self._keep_version(name, recipe)

    def _run_pull(self, runner, image: dict, context) -> None:
        """Have Containers' Podman pull one image of a container module."""
        runner.pull_image(image)

    def _run_switch(self, name: str, entry: dict, context) -> None:
        """Run the version switch.

        Raises:
            ModuleApplyError: The switch's own ``{code, params}``.
        """
        refusal = self._switch(name, entry, context.receive)
        if refusal:
            raise ModuleApplyError(refusal["code"], dict(refusal["params"]))

    def _run_uninstall(self, name: str, entry: dict, context) -> None:
        """Run the uninstall.

        Raises:
            ModuleApplyError: ``module_not_orderable`` for a module the
                agent carries; the uninstall's own ``{code, params}``.
        """
        if _recipe_of(entry).get("method") == AGENT_METHOD_AGENT:
            raise ModuleApplyError("module_not_orderable", {"module": name})
        refusal = self._uninstall(name, entry)
        if refusal:
            raise ModuleApplyError(refusal["code"], dict(refusal["params"]))

    def _switch(self, name: str, wanted: dict, receive) -> dict:
        """Stage, swap in and verify another version, or put the old one back."""
        recipe = _recipe_of(wanted)
        runner = self._runner_for(name, recipe)
        if runner is None:
            return {
                "code": "runner_unknown",
                "params": {"runner": str(recipe.get("runner", "") or "")},
            }
        version = str(params_of(recipe).get("version", "") or "")
        digests = self.installed_version(name).get("digests") or {}
        changed = [
            artifact
            for artifact in received_artifacts(recipe)
            if digests.get(str(artifact.get("name", "") or ""))
            != artifact.get("digest")
        ]
        self._collect(f"{name}: switching to {version}")
        staged: list = []
        installed_by_kind: list = []
        try:
            for artifact in changed:
                received = receive(artifact)
                if "path" not in received:
                    remove_staged(staged)
                    for _artifact, path in installed_by_kind:
                        remove_received(path)
                    return dict(received)
                refusal = check_received(artifact, received)
                if refusal:
                    remove_received(received["path"])
                    remove_staged(staged)
                    return refusal
                kind = str(artifact.get("kind", "") or "")
                if kind in AGENT_ARTIFACT_KEPT_SUFFIXES:
                    installed_by_kind.append((artifact, received["path"]))
                    continue
                try:
                    staged += stage_artifact(
                        artifact,
                        received["path"],
                        module_dir=runner.module_dir,
                        join=joiner(self._platform.os_name),
                        binary_target=(
                            runner.binary_path(recipe, artifact)
                            if kind == AGENT_ARTIFACT_KIND_BINARY
                            else ""
                        ),
                    )
                finally:
                    remove_received(received["path"])
        except (ModuleApplyError, OSError) as error:
            remove_staged(staged)
            for _artifact, path in installed_by_kind:
                remove_received(path)
            if isinstance(error, ModuleApplyError):
                return {"code": error.code, "params": dict(error.params)}
            return _switch_failed(version, str(error))
        with contextlib.suppress(Exception):
            runner.stop()
        swapped: list = []
        try:
            swapped = swap_in(staged)
            for artifact, path in installed_by_kind:
                try:
                    if artifact.get("kind") in SYSTEM_INSTALLED_KINDS:
                        runner.uninstall_package(recipe, dict(artifact))
                    runner.install_artifact(recipe, dict(artifact), path)
                finally:
                    remove_received(path)
            detail = verify_detail(str(params_of(recipe).get("verify", "") or ""))
        except Exception as error:  # noqa: BLE001 - every failure puts the old back
            swapped = getattr(error, "swapped", swapped)
            detail = str(error) or type(error).__name__
            if isinstance(error, ModuleApplyError):
                detail = " ".join(
                    [error.code]
                    + [f"{key}={value}" for key, value in error.params.items()]
                )
        if detail:
            swap_back(swapped)
            remove_staged(staged)
            self._collect(f"{name}: {version} did not take; the old version runs")
            self._start_again(name, runner, wanted)
            return _switch_failed(version, detail)
        drop_replaced(staged)
        if any(is_archive_kind(str(a.get("kind", "") or "")) for a in changed):
            for target, _staged in swapped:
                if os.path.isdir(target):
                    self._platform.label_programs(target)
            self._platform.open_to_accounts(runner.module_dir)
        self._keep_version(name, recipe)
        self._collect(f"{name}: {version} is in place")
        return {}

    def _start_again(self, name: str, runner, wanted: dict) -> None:
        """Run the old version again after a switch that did not take, as its ``want`` says."""
        if str(wanted.get("want", "") or "") != AGENT_WANT_RUNNING:
            return
        config = wanted.get("config")
        try:
            runner.apply(dict(config) if isinstance(config, dict) else {})
            runner.start()
        except Exception as error:  # noqa: BLE001 - logged; the failure is reported
            self._collect(f"{name}: the old version did not start: {error}")

    def _keep_version(self, name: str, recipe: dict) -> None:
        """Keep the version a recipe names as one module's installed one, with its digests."""
        if not _is_plain(name):
            return
        held = {
            "version": str(params_of(recipe).get("version", "") or ""),
            "digests": {
                str(artifact.get("name", "") or ""): str(
                    artifact.get("digest", "") or ""
                )
                for artifact in received_artifacts(recipe)
            },
        }
        try:
            os.makedirs(self._versions_dir, mode=0o700, exist_ok=True)
            handle, temporary = tempfile.mkstemp(
                dir=self._versions_dir, prefix=".version_"
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(held, stream)
                os.chmod(temporary, 0o600)
                os.replace(temporary, self._version_path(name))
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)
                raise
        except OSError as error:
            self._log(f"{name}: could not keep its version: {error}")

    def _forget_version(self, name: str) -> None:
        """Delete one module's kept version."""
        if _is_plain(name):
            with contextlib.suppress(OSError):
                os.unlink(self._version_path(name))

    def _version_path(self, name: str) -> str:
        return os.path.join(self._versions_dir, name + FAILURE_SUFFIX)

    def _uninstall(self, name: str, wanted: dict) -> dict:
        """Uninstall by the recipe, drop the hub's configuration and the mark."""
        recipe = _recipe_of(wanted)
        removal = params_of(recipe).get("uninstall")
        removal = dict(removal) if isinstance(removal, dict) else {}
        runner = self._runner_for(name, recipe)
        if runner is None:
            return {
                "code": "runner_unknown",
                "params": {"runner": str(recipe.get("runner", "") or "")},
            }
        try:
            is_leftover = not self._is_present(runner, recipe)
        except Exception:  # noqa: BLE001 - an unreadable module is not installed
            is_leftover = True
        try:
            self._remove(name, runner, recipe, removal)
        except Exception as error:  # noqa: BLE001 - logged; the check is the outcome
            if not is_leftover:
                raise
            said = str(error)
            if isinstance(error, ModuleApplyError):
                said = " ".join(
                    [error.code]
                    + [f"{key}={value}" for key, value in error.params.items()]
                )
            self._collect(f"{name}: {said}"[:500])
        self.clear_configured(name)
        if self._is_present(runner, recipe):
            return {"code": "uninstall_unconfirmed", "params": {}}
        self._forget_version(name)
        return {}

    def _remove(self, name: str, runner, recipe: dict, removal: dict) -> None:
        """The uninstall's steps: the hub's configuration, the software, the
        recipe's own steps after it, and the data where the recipe says so."""
        if self.is_configured(name):
            with contextlib.suppress(Exception):
                runner.stop()
            runner.remove_configuration()
        runner.uninstall(recipe)
        for step in removal.get("post_uninstall") or []:
            self._collect(str(step))
            output = installers.run_shell(str(step))
            if output.strip():
                self._collect(output.strip())
        if not bool(removal.get("is_data_kept", True)):
            self._collect(f"{name}: removing its data")
            runner.remove_data()

    def _collect(self, message: str) -> None:
        """Log a line, handing it to the stream of the task this thread runs as well."""
        on_line = getattr(self._lines, "on_line", None)
        if on_line is not None:
            on_line(str(message))
        self._log(message)

    def _reconcile(self) -> None:
        self._refresh(is_forced=False)

    def _wanted_of(self, name: str) -> "dict | None":
        with self._lock:
            wanted = self._wanted.get(name)
        return dict(wanted) if wanted is not None else None

    def _observed(self) -> dict:
        """Every module observed, to what the state says of it. Call under the lock.

        Returns:
            The state's modules in the hub's order, then the runners the
            state does not name; an unnamed module maps to None.
        """
        observed = {name: dict(entry) for name, entry in self._wanted.items()}
        for name in [*self._module_runners, *self._container_runners]:
            observed.setdefault(name, None)
        return observed

    def _refresh(self, *, is_forced: bool) -> None:
        """Report what every observed module actually is.

        A pass runs when the state changed, when it is forced, or when the
        last read is older than the details' lifetime. A module mid-operation
        keeps its transient row.
        """
        with self._lock:
            observed = self._observed()
            signature = json.dumps(
                {
                    name: (entry or {}).get("want", "")
                    for name, entry in observed.items()
                },
                sort_keys=True,
                default=str,
            )
            is_stale = self._is_stale(signature)
        is_due = time.monotonic() - self._details_at > AGENT_MODULE_DETAILS_TTL_S
        if not (is_stale or is_forced or is_due):
            return
        self._details_at = time.monotonic()
        for name, wanted in observed.items():
            with self._lock:
                overlay = self._task_rows.get(name) or {}
                # Containers keeps its row while a container module pulls on
                # its Podman, which a read then finds busy.
                is_pulled_on = name == AGENT_CONTAINERS_MODULE and self._is_pulling()
            if is_pulled_on:
                continue
            if overlay.get("state"):
                self._publish_observed(name, _typed(overlay["state"]))
                continue
            self._publish_observed(name, self._read_one(name, wanted))
        # A module no runner and no state names stops being reported.
        self._keep_only(observed)

    def _publish_observed(self, name: str, status: dict) -> None:
        """Record one module's status as read, with its task on the row.

        A module whose task's plan has the row read ``queued``,
        ``installing`` or ``uninstalling`` keeps that row, with the step's
        wait as its code, as it stands when the row is written: a read of
        every module takes seconds, and a task can begin meanwhile.

        Args:
            name: The module name.
            status: What a read found.
        """
        with self._lock:
            status = _with_task(status, self._task_rows.get(name))
            is_news = self._statuses.get(name) != status
            self._statuses[name] = status
        if is_news and self._on_change is not None:
            self._on_change()

    def _is_task_running(self, name: str) -> bool:
        """Whether one module's task runs. Call under the lock."""
        task = (self._task_rows.get(name) or {}).get("task") or {}
        return bool(task.get("is_running"))

    def _kept_failure(self, name: str) -> "dict | None":
        """One module's kept failure as its row reads it: none while its task runs. Call under the lock."""
        if self._is_task_running(name):
            return None
        return self._failures.get(name)

    def _is_pulling(self) -> bool:
        """Whether a container module's task runs a ``pull``. Call under the lock."""
        for name in self._container_runners:
            task = (self._task_rows.get(name) or {}).get("task") or {}
            steps = task.get("steps") or []
            index = int(task.get("index", 0) or 0)
            if (
                task.get("is_running")
                and 0 < index <= len(steps)
                and steps[index - 1].get("name") == AGENT_STEP_PULL
            ):
                return True
        return False

    def _read_one(self, name: str, wanted: "dict | None") -> dict:
        """What one module actually is on this machine, acting on nothing.

        Args:
            name: The module name.
            wanted: The state's entry for it, None when the state names
                it not.

        Returns:
            ``{"state", "is_active", "code", "params", "details"}``; an
            ``installing`` row carries the runner's install wait as its
            code and params, and a module whose last install failed reads
            ``install_failed`` with that install's code and params,
            whatever is on the machine, except while its task runs.
        """
        recipe = _recipe_of(wanted)
        runner = self._runner_for(name, recipe)
        if runner is None:
            return _typed(AGENT_MODULE_STATE_UNSUPPORTED)
        with self._lock:
            failure = self._kept_failure(name)
        if (
            failure is not None
            and failure["state"] == AGENT_MODULE_STATE_INSTALL_FAILED
        ):
            status = _typed(AGENT_MODULE_STATE_INSTALL_FAILED, failure["code"])
            status["params"] = dict(failure["params"])
            return status
        try:
            if not self._is_present(runner, recipe):
                with self._lock:
                    self._verify_failures.pop(name, None)
                return self._with_failure(
                    name, _typed(AGENT_MODULE_STATE_ABSENT), is_present=False
                )
            is_active = bool(runner.is_active())
            status = _typed(
                _steady_state(
                    is_active=is_active, is_configured=self.is_configured(name)
                ),
                is_active=is_active,
            )
            if runner.is_installing():
                status["state"] = AGENT_MODULE_STATE_INSTALLING
                wait = runner.install_wait()
                status["code"] = str(wait.get("code", "") or "")
                status["params"] = dict(wait.get("params") or {})
            else:
                status = _with_notice(runner, status)
            details = runner.details(recipe)
            status["details"] = dict(details) if isinstance(details, dict) else {}
        except PlatformUnsupportedError:
            return _typed(AGENT_MODULE_STATE_FAILED, "unsupported_platform")
        except Exception as error:  # noqa: BLE001 - reported, never raised
            detail = str(error)[:200]
            with self._lock:
                is_new = self._verify_failures.get(name) != detail
                self._verify_failures[name] = detail
            if is_new:
                self._log(f"{name}: verify_failed: {detail}")
            return _typed(AGENT_MODULE_STATE_FAILED, "verify_failed", detail=detail)
        with self._lock:
            self._verify_failures.pop(name, None)
        return self._with_failure(name, status)

    def _with_failure(
        self, name: str, status: dict, *, is_present: bool = True
    ) -> dict:
        """One row with the last failed step's code, failed when the software
        is there."""
        with self._lock:
            failure = self._kept_failure(name)
        if failure is not None:
            if is_present:
                status["state"] = AGENT_MODULE_STATE_FAILED
            status["code"] = failure["code"]
            status["params"] = dict(failure["params"])
        return status

    def _failure_path(self, name: str) -> str:
        return os.path.join(self._failures_dir, name + FAILURE_SUFFIX)

    def _read_failures(self) -> dict:
        """The failures kept on disk.

        Returns:
            Module name to ``{"state", "code", "params"}``; a file that
            cannot be read or holds another shape is left out.
        """
        try:
            names = os.listdir(self._failures_dir)
        except OSError:
            return {}
        kept = {}
        for file_name in sorted(names):
            name = file_name[: -len(FAILURE_SUFFIX)]
            if not file_name.endswith(FAILURE_SUFFIX) or not _is_plain(name):
                continue
            try:
                with open(self._failure_path(name), "r", encoding="utf-8") as stream:
                    failure = _failure(json.load(stream))
            except (OSError, ValueError):
                continue
            if failure is not None:
                kept[name] = failure
        return kept

    def _write_failure(self, name: str, failure: "dict | None") -> None:
        """Keep one module's failure root-only, whole or not at all, or delete it.

        A file that cannot be written is a line in the log, and the row
        reads the failure all the same until the agent starts again.
        """
        path = self._failure_path(name)
        try:
            if failure is None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(path)
                return
            os.makedirs(self._failures_dir, mode=0o700, exist_ok=True)
            handle, temporary = tempfile.mkstemp(
                dir=self._failures_dir, prefix=".failure_"
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(failure, stream, sort_keys=True)
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)
                raise
        except OSError as error:
            self._log(f"{name}: could not keep its failure: {error}")

    @staticmethod
    def _is_present(runner, recipe: dict) -> bool:
        """Whether the software is there, by the method's one presence check.

        A module the agent carries is always there; a ``system`` or a
        ``hub`` recipe is there while its ``verify`` exits 0; a
        ``container`` recipe while every image it pins is in Containers'
        Podman, as its runner reads it. A ``builtin`` recipe, and a module
        the state does not name, which comes with no recipe, are judged by
        the runner's own check.
        """
        method = str(recipe.get("method", "") or "")
        if method == AGENT_METHOD_AGENT:
            return True
        if method in VERIFIED_METHODS:
            return verify_passes(str(params_of(recipe).get("verify", "") or ""))
        return bool(runner.verify(recipe))

    def _runner_for(self, name: str, recipe: dict):
        """The runner for one module: the one its recipe names, else its own by name.

        Args:
            name: The module name.
            recipe: The module's recipe; empty for a module the state does
                not name.

        Returns:
            The runner, or None for a module whose recipe names a runner
            this agent does not have.
        """
        runner_name = str(recipe.get("runner", "") or "")
        if not runner_name:
            return self._module_runners.get(name) or self._container_runners.get(name)
        if runner_name == AGENT_CONTAINER_RUNNER:
            return self._container_runners.get(name)
        return self._runners_by_name.get(runner_name)

    def _add_container_runner(self, name: str, recipe: dict) -> None:
        """Make the runner of a container module the state names, once. Call under the lock.

        A machine with no Containers runner gets none, and the module reads
        unsupported there.
        """
        if str(recipe.get("runner", "") or "") != AGENT_CONTAINER_RUNNER:
            return
        containers = self._module_runners.get(AGENT_CONTAINERS_MODULE)
        if name in self._container_runners or containers is None:
            return
        if name in self._module_runners or not _is_plain(name):
            return
        runner = ContainerModuleRunner(
            platform=self._platform,
            name=name,
            containers=containers,
            log=self._collect,
            publish=self._publish,
        )
        if self._configure_asker is not None:
            runner.bind_configure_asker(functools.partial(self._configure_asker, name))
        self._container_runners[name] = runner


def _switch_failed(version: str, detail: str) -> dict:
    """The refusal of a version switch that did not take.

    Args:
        version: The version it switched to.
        detail: The failed step's output.

    Returns:
        ``version_switch_failed {version, detail}``.
    """
    return {
        "code": "version_switch_failed",
        "params": {"version": version, "detail": detail[-500:]},
    }


def _installer_locks(artifacts) -> tuple:
    """``package_manager`` when an artifact is an msi or a pkg, else no lock."""
    kinds = {str(artifact.get("kind", "") or "") for artifact in artifacts}
    return PACKAGE_MANAGER_LOCKS if kinds & set(SYSTEM_INSTALLED_KINDS) else ()


def _run_apply(runner, config: dict, context) -> None:
    """The ``configure`` step: the runner's apply of the configuration."""
    runner.apply(dict(config))


def _run_start(runner, context) -> None:
    """The ``start`` step: the runner's start."""
    runner.start()


def _run_stop(runner, context) -> None:
    """The ``stop`` step: the runner's stop."""
    runner.stop()


def _wait_for_containers(context) -> None:
    """The ``wait_containers`` step: the task waits until Containers runs and has no task."""
    context.wait_for_containers()


def _render_containers(context) -> None:
    """The ``render`` step: a configure task of Containers, asked for and waited for."""
    context.render_containers()


def _raise(error: Exception, context) -> None:
    """A step that fails at once with the error it was made with."""
    raise error


def _with_task(status: dict, overlay: "dict | None") -> dict:
    """One row with its module's task, transient while the task's plan reads so.

    Args:
        status: The row as read.
        overlay: The module's ``{task, state, wait}``; None for a module
            that has had no task.

    Returns:
        The row with ``task``; a ``queued``, ``installing`` or
        ``uninstalling`` row carries the wait's code and params.
    """
    if not overlay:
        return {**status, "task": None}
    if not overlay.get("state"):
        return {**status, "task": dict(overlay["task"])}
    wait = overlay.get("wait") or {}
    return {
        "state": overlay["state"],
        "is_active": False,
        "code": str(wait.get("code", "") or ""),
        "params": dict(wait.get("params") or {}),
        "details": {},
        "task": dict(overlay["task"]),
    }


def _is_plain(name: str) -> bool:
    """Whether a module name is one plain file name, safe to keep a file under."""
    return (
        bool(name)
        and not name.startswith(".")
        and not any(separator in name for separator in ("/", "\\"))
    )


def _failure(held) -> "dict | None":
    """One kept failure in its one shape, or None for anything else.

    Args:
        held: ``{"state", "code", "params"}`` as recorded or read back.

    Returns:
        The failure, ``state`` one of the two failure states and a code
        beside it; None when it is not one.
    """
    if not isinstance(held, dict):
        return None
    state = str(held.get("state", "") or "")
    code = str(held.get("code", "") or "")
    params = held.get("params")
    if state not in FAILURE_STATES or not code:
        return None
    return {
        "state": state,
        "code": code,
        "params": dict(params) if isinstance(params, dict) else {},
    }


def _recipe_of(wanted: "dict | None") -> dict:
    """The install recipe one state entry carries, empty when it carries none."""
    recipe = (wanted or {}).get("install")
    return dict(recipe) if isinstance(recipe, dict) else {}


def _steady_state(*, is_active: bool, is_configured: bool) -> str:
    """The state of software that is there, from the unit and the mark."""
    if not is_configured:
        return AGENT_MODULE_STATE_INSTALLED
    return AGENT_MODULE_STATE_RUNNING if is_active else AGENT_MODULE_STATE_STOPPED


def _with_notice(runner, status: dict) -> dict:
    """A steady row with the runner's notice as its code, where it has one.

    Args:
        runner: The module's runner.
        status: The row, with no code of its own.

    Returns:
        The row, carrying the notice's ``code`` and ``params`` when the
        runner names one; a failure recorded for the module is put on
        afterwards and wins.
    """
    notice = runner.notice()
    code = str((notice or {}).get("code", "") or "")
    if not code:
        return status
    status["code"] = code
    status["params"] = dict(notice.get("params") or {})
    return status


def _typed(state: str, code: str = "", *, is_active: bool = False, **params) -> dict:
    """One typed status, the shape every surface words for itself.

    ``details`` carries facts a surface prints as they are, beside the code
    every surface words for itself.
    """
    return {
        "state": state,
        "is_active": is_active,
        "code": code,
        "params": params,
        "details": {},
    }
