"""Reporting what each module is, and putting software on and off the machine.

The hub's state names, per module, what is wanted and the recipe resolved
for this platform, ``{runner, method, params}``. The recipe's ``runner``
chooses the runner, and an agent with no runner of that name reports the
module unsupported. :class:`ModuleEngine` observes every module it has a
runner for, named by the state or not, and derives one typed state from
three facts: whether the software is there, by the method's one presence
check, whether its unit is active, and whether the hub has configured it,
which is a root-only mark on disk. It also carries out the two package
operations the reconcile asks for, one at a time, because one package
manager holds the machine-wide lock. :class:`ReconcileWorker` is the
shared pattern: a thread woken by news, a signature that skips unchanged
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
import functools
import json
import os
import tempfile
import threading
import time

from neutrino_agent.constants import (
    AGENT_CONFIGURED_DIR,
    AGENT_CONTAINER_RUNNER,
    AGENT_CONTAINERS_MODULE,
    AGENT_METHOD_AGENT,
    AGENT_METHOD_BUILTIN,
    AGENT_METHOD_CONTAINER,
    AGENT_METHOD_HUB,
    AGENT_METHOD_SYSTEM,
    AGENT_FAILURES_DIR_NAME,
    AGENT_MODULE_DETAILS_TTL_S,
    AGENT_MODULE_STATE_ABSENT,
    AGENT_MODULE_STATE_FAILED,
    AGENT_MODULE_STATE_INSTALL_FAILED,
    AGENT_MODULE_STATE_INSTALLED,
    AGENT_MODULE_STATE_INSTALLING,
    AGENT_MODULE_STATE_QUEUED,
    AGENT_MODULE_STATE_RUNNING,
    AGENT_MODULE_STATE_STOPPED,
    AGENT_MODULE_STATE_UNINSTALLING,
    AGENT_MODULE_STATE_UNSUPPORTED,
    AGENT_PRESENT_WANTS,
)
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
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
from neutrino_agent.modules.shared.instances import InstancesModuleRunner
from neutrino_agent.modules.shared.package import (
    check_received,
    params_of,
    received_artifacts,
    remove_received,
    verify_passes,
)
from neutrino_agent.modules.ssh_server.hooks import SshServerHooks
from neutrino_agent.modules.terminal.runner import TerminalModuleRunner
from neutrino_agent.modules.vscode.hooks import VscodeHooks
from neutrino_agent.modules.zfs.runner import ZfsModuleRunner
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
SshServerModuleRunner = functools.partial(
    InstancesModuleRunner, hooks_class=SshServerHooks
)
# The container modules with hooks of their own, which the container runner
# reads by module name.
CONTAINER_MODULE_HOOKS[HERMES_WEBUI_NAME] = HermesWebuiHooks

# The states a kept failure reads as: an install's, and every other step's.
FAILURE_STATES = (AGENT_MODULE_STATE_INSTALL_FAILED, AGENT_MODULE_STATE_FAILED)
# The suffix of the file one module's failure is kept in.
FAILURE_SUFFIX = ".json"
# The states that end a container module's hold on installing, beside its
# want.
HOLD_ENDING_STATES = (
    AGENT_MODULE_STATE_INSTALL_FAILED,
    AGENT_MODULE_STATE_FAILED,
    AGENT_MODULE_STATE_UNSUPPORTED,
)


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
        """
        # The state's modules section as the hub last sent it, by name:
        # ``{"want", "config", "install"}`` each.
        self._wanted: dict = {}
        self._configured_dir = configured_dir or AGENT_CONFIGURED_DIR
        self._failures_dir = failures_dir or os.path.join(
            os.path.dirname(self._configured_dir), AGENT_FAILURES_DIR_NAME
        )
        self._platform_tuple = platform_tuple()
        self._on_line = None
        # A runner logs while it is made (the file share's fence that did not
        # load), so the log is set before the runners are.
        self._log = log
        self._operation_lock = threading.Lock()
        # The modules mid-operation, whose transient state a refresh keeps.
        self._in_transit: set = set()
        # The modules waiting behind the one the applier is on.
        self._queued: set = set()
        # The container modules that read installing until they read their
        # want or a step fails.
        self._held_installing: set = set()
        # Module name to its last failed step, ``{"state", "code",
        # "params"}``, as kept on disk.
        self._failures: dict = {}
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
                ZfsModuleRunner,
                VscodeModuleRunner,
                CodeServerModuleRunner,
                CloudcliModuleRunner,
                CodegModuleRunner,
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
            self._held_installing &= set(self._wanted)
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

    def is_installed(self, name: str) -> bool:
        """Whether one module's software is on this machine, checked now.

        Args:
            name: The module name.

        Returns:
            True when the method's presence check passes; False for a module
            this agent has no runner for or cannot read.
        """
        recipe = _recipe_of(self._wanted_of(name))
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

    def set_queued(self, names) -> None:
        """Report the modules waiting behind the one being applied as ``queued``.

        A module that leaves the set is read again at once.

        Args:
            names: The waiting modules; empty when none waits.
        """
        with self._lock:
            queued = set(names)
            left = self._queued - queued
            self._queued = queued
            observed = self._observed()
        for name in sorted(queued):
            self._publish_observed(name, _typed(AGENT_MODULE_STATE_QUEUED))
        for name in sorted(left):
            if name in observed:
                self._publish_observed(name, self._read_one(name, observed[name]))

    def hold_installing(self, names) -> None:
        """Read these container modules ``installing`` until each reads its ``want`` or fails.

        A container module's install is its pull, after which Containers is
        applied again for it and its first start runs; its row reads
        ``installing`` through all of it.

        Args:
            names: The container modules a state asks to be present that
                are not installed.
        """
        names = list(names)
        with self._lock:
            self._held_installing |= set(names)
        for name in names:
            self._publish_observed(name, _typed(AGENT_MODULE_STATE_INSTALLING))

    def refresh_now(self) -> None:
        """Report every module again from what is true right now."""
        self._refresh(is_forced=True)

    def install(self, name: str, *, receive, on_line=None) -> dict:
        """Put one module's software on the machine, in the caller's thread.

        Package operations run one at a time: a second caller waits for
        the first. The row reads ``installing`` while it runs.

        Args:
            name: The module name; its recipe is the one the state names.
            receive: Called with the module name and each artifact a
                ``hub`` recipe receives; returns ``{"path", "sha256"}``
                naming the file on disk and its digest, or ``{"code",
                "params"}``. The file is deleted once the install ran.
            on_line: Called with each output line as the install produces
                it.

        Returns:
            Empty when the software is there afterwards, ``{"code",
            "params"}`` when it is not; the module then reads
            ``install_failed``.
        """
        return self._operate(
            name,
            (AGENT_MODULE_STATE_INSTALLING, AGENT_MODULE_STATE_INSTALL_FAILED),
            "install_failed",
            on_line,
            self._install,
            receive,
        )

    def uninstall(self, name: str, *, on_line=None) -> dict:
        """Take one module's software off the machine, in the caller's thread.

        The configuration the hub wrote and the configured mark go with
        it; the module's data stays. The row reads ``uninstalling`` while
        it runs. On software the recipe's check does not find, what an
        earlier install left, a step that fails is logged and the check
        afterwards is the outcome.

        Args:
            name: The module name; its recipes are the ones the state names.
            on_line: Called with each output line as the uninstall
                produces it.

        Returns:
            Empty when the software is gone afterwards, ``{"code",
            "params"}`` when it is not; the module then reads ``failed``.
        """
        return self._operate(
            name,
            (AGENT_MODULE_STATE_UNINSTALLING, AGENT_MODULE_STATE_FAILED),
            "uninstall_failed",
            on_line,
            self._uninstall,
        )

    def _operate(
        self, name: str, states: tuple, failure: str, on_line, step, *extra
    ) -> dict:
        """Run one package operation under the machine's one lock.

        Its outcome replaces the module's kept failure before the row is
        read again.

        Args:
            name: The module name.
            states: The state the row shows while the operation runs, and
                the state a failure of it is kept under.
            failure: The code a step that raised is reported under.
            on_line: Called with each output line.
            step: The operation itself, given the name, its state entry
                and ``extra``.
            *extra: What the step takes beside them.

        Returns:
            Empty when the operation took, ``{"code", "params"}`` when not.
        """
        transient, failed_state = states
        wanted = self._wanted_of(name)
        if wanted is None:
            return {"code": "unknown_module", "params": {"module": name}}
        if _recipe_of(wanted).get("method") == AGENT_METHOD_AGENT:
            return {"code": "module_not_orderable", "params": {"module": name}}
        with self._operation_lock:
            with self._lock:
                self._in_transit.add(name)
            self._on_line = on_line
            self._publish(name, _typed(transient))
            try:
                refusal = step(name, wanted, *extra)
            except PlatformUnsupportedError:
                refusal = {"code": "unsupported_platform", "params": {}}
            except ModuleApplyError as error:
                self._collect(error.code)
                refusal = {"code": error.code, "params": dict(error.params)}
            except Exception as error:  # noqa: BLE001 - reported, never raised
                self._collect(str(error))
                refusal = {"code": failure, "params": {"detail": str(error)[:200]}}
            finally:
                self._on_line = None
                with self._lock:
                    self._in_transit.discard(name)
            self.record_failure(
                name, {"state": failed_state, **refusal} if refusal else None
            )
            self._refresh(is_forced=True)
        return refusal

    def _install(self, name: str, wanted: dict, receive) -> dict:
        """Install by the recipe's method and check it took."""
        recipe = _recipe_of(wanted)
        method = str(recipe.get("method", "") or "")
        runner = self._runner_for(name, recipe)
        if runner is None:
            return {
                "code": "runner_unknown",
                "params": {"runner": str(recipe.get("runner", "") or "")},
            }
        if method not in INSTALLED_METHODS:
            return {"code": "method_unknown", "params": {"method": method}}
        self._collect(f"{name}: installing")
        runner.install(recipe)
        if method == AGENT_METHOD_HUB:
            for artifact in received_artifacts(recipe):
                refusal = self._install_artifact(
                    runner, recipe, artifact, name, receive
                )
                if refusal:
                    return refusal
        # The check is the whole point of the step: a package manager that
        # exits zero and installs nothing is a thing that happens.
        if not self._is_present(runner, recipe):
            return {"code": "install_unconfirmed", "params": {}}
        return {}

    def _install_artifact(
        self, runner, recipe: dict, artifact: dict, name: str, receive
    ) -> dict:
        """Receive one artifact, check its digest against the recipe, install it.

        Returns:
            Empty when it landed; the stream's own ``{"code", "params"}``
            when the hub could not hand it down, ``package_digest_mismatch``
            when its bytes are not the recipe's.
        """
        received = receive(name, artifact)
        if "path" not in received:
            return dict(received)
        try:
            refusal = check_received(artifact, received)
            if refusal:
                return refusal
            runner.install_artifact(recipe, dict(artifact), received["path"])
        finally:
            remove_received(received["path"])
        return {}

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
        is_leftover = not self.is_installed(name)
        self._collect(f"{name}: uninstalling")
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
        """Log a line, handing it to the operation's stream as well."""
        on_line = self._on_line
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
                is_held = name in self._in_transit or name in self._queued
                # Containers keeps its row while a container module pulls on
                # its Podman, which a read then finds busy.
                is_pulled_on = name == AGENT_CONTAINERS_MODULE and self._is_pulling()
            if is_pulled_on:
                continue
            if is_held:
                self._publish_observed(name, _typed(AGENT_MODULE_STATE_QUEUED))
                continue
            self._publish_observed(name, self._read_one(name, wanted))
        # A module no runner and no state names stops being reported.
        self._keep_only(observed)

    def _publish_observed(self, name: str, status: dict) -> None:
        """Record one module's status as read, unless an operation or the queue holds its row.

        A module mid-operation keeps its transient row, and a queued one
        reads ``queued``, as they stand when the row is written: a read of
        every module takes seconds, and an install can begin meanwhile.

        Args:
            name: The module name.
            status: What a read found.
        """
        with self._lock:
            if name in self._in_transit:
                return
            if name in self._queued:
                status = _typed(AGENT_MODULE_STATE_QUEUED)
            status = self._held_status(name, status)
            is_news = self._statuses.get(name) != status
            self._statuses[name] = status
        if is_news and self._on_change is not None:
            self._on_change()

    def _held_status(self, name: str, status: dict) -> dict:
        """The row of a module held ``installing``, which ends the hold once
        it reads its ``want`` or fails. Call under the lock."""
        if name not in self._held_installing:
            return status
        want = str((self._wanted.get(name) or {}).get("want", "") or "")
        if want not in AGENT_PRESENT_WANTS or status["state"] in (
            want,
            *HOLD_ENDING_STATES,
        ):
            self._held_installing.discard(name)
            return status
        if status["state"] == AGENT_MODULE_STATE_INSTALLING:
            return status
        return {
            **status,
            "state": AGENT_MODULE_STATE_INSTALLING,
            "code": "",
            "params": {},
        }

    def _is_pulling(self) -> bool:
        """Whether a container module's install runs. Call under the lock."""
        return any(
            name in self._in_transit
            and (self._statuses.get(name) or {}).get("state")
            == AGENT_MODULE_STATE_INSTALLING
            for name in self._container_runners
        )

    def _read_one(self, name: str, wanted: "dict | None") -> dict:
        """What one module actually is on this machine, acting on nothing.

        Args:
            name: The module name.
            wanted: The state's entry for it, None when the state names
                it not.

        Returns:
            ``{"state", "is_active", "code", "params", "details"}``; an
            ``installing`` row carries the runner's install wait as its
            code and params, an ``absent`` row the part the runner names
            missing, and a module whose last install failed reads
            ``install_failed`` with that install's code and params,
            whatever is on the machine.
        """
        recipe = _recipe_of(wanted)
        runner = self._runner_for(name, recipe)
        if runner is None:
            return _typed(AGENT_MODULE_STATE_UNSUPPORTED)
        with self._lock:
            failure = self._failures.get(name)
        if (
            failure is not None
            and failure["state"] == AGENT_MODULE_STATE_INSTALL_FAILED
        ):
            status = _typed(AGENT_MODULE_STATE_INSTALL_FAILED, failure["code"])
            status["params"] = dict(failure["params"])
            return status
        try:
            if not self._is_present(runner, recipe):
                reason = runner.absent_reason(recipe)
                status = _typed(
                    AGENT_MODULE_STATE_ABSENT, str(reason.get("code", "") or "")
                )
                status["params"] = dict(reason.get("params") or {})
                return self._with_failure(name, status, is_present=False)
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
            details = runner.details(recipe)
            status["details"] = dict(details) if isinstance(details, dict) else {}
        except PlatformUnsupportedError:
            return _typed(AGENT_MODULE_STATE_FAILED, "unsupported_platform")
        except Exception as error:  # noqa: BLE001 - reported, never raised
            self._log(f"{name}: verify_failed: {str(error)[:200]}")
            return _typed(
                AGENT_MODULE_STATE_FAILED, "verify_failed", detail=str(error)[:200]
            )
        return self._with_failure(name, status)

    def _with_failure(
        self, name: str, status: dict, *, is_present: bool = True
    ) -> dict:
        """One row with the last failed step's code, failed when the software
        is there."""
        with self._lock:
            failure = self._failures.get(name)
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
        self._container_runners[name] = ContainerModuleRunner(
            platform=self._platform,
            name=name,
            containers=containers,
            log=self._collect,
            publish=self._publish,
        )


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
