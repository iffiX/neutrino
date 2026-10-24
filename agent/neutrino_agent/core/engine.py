"""Reporting what each module is, and putting software on and off the machine.

The hub's state names, per module, what is wanted and the install and
uninstall recipes resolved for this platform. :class:`ModuleEngine`
observes every module it has a runner for, named by the state or not, and
derives one typed state from three facts: whether the software is there,
whether its unit is active, and whether the hub has configured it, which
is a root-only mark on disk. It also carries out the two package
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
)
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.cloudcli.hooks import CloudcliHooks
from neutrino_agent.modules.code_server.hooks import CodeServerHooks
from neutrino_agent.modules.codeg.hooks import CodegHooks
from neutrino_agent.modules.gitea.runner import GiteaModuleRunner
from neutrino_agent.modules.podman.machine_runner import PodmanMachineModuleRunner
from neutrino_agent.modules.podman.runner import PodmanModuleRunner
from neutrino_agent.modules.remote_desktop.runner import RemoteDesktopModuleRunner
from neutrino_agent.modules.samba.runner import (
    SambaModuleRunner,
    SambaNativeServerRunner,
)
from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared.instances import InstancesModuleRunner
from neutrino_agent.modules.shared.package import PackageModuleRunner, verify_passes
from neutrino_agent.modules.shared.system_package import SystemPackageModuleRunner
from neutrino_agent.modules.terminal.runner import TerminalModuleRunner
from neutrino_agent.modules.vscode.hooks import VscodeHooks
from neutrino_agent.modules.zfs.runner import ZfsModuleRunner
from neutrino_agent.platforms.detect import platform_tuple
from neutrino_agent.streams.package import CODE_DIGEST_MISMATCH, CODE_UNREACHABLE

# How often to re-check inputs that have not changed. Every heartbeat wakes
# the worker, and running each module's verify command that often would keep
# a Raspberry Pi busy doing nothing.
IDLE_RECHECK_INTERVAL_S = 60

# The kinds whose install runs by name with the platform's own tooling; the
# rest install from the bytes a package stream brings down.
BY_NAME_KINDS = ("system_package",)

# The recipe fields that are not part of the platform entry today's runners
# read: the kind names the runner, the verify command decides presence, and
# the package name is the entry's own.
RECIPE_HEADER_FIELDS = ("kind", "verify", "package")

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

# The modules the agent's own package carries: no operation moves them.
CARRIED_MODULES = (RemoteDesktopModuleRunner.name,)

# The states a kept failure reads as: an install's, and every other step's.
FAILURE_STATES = (AGENT_MODULE_STATE_INSTALL_FAILED, AGENT_MODULE_STATE_FAILED)
# The suffix of the file one module's failure is kept in.
FAILURE_SUFFIX = ".json"


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
        # ``{"want", "config", "install", "uninstall"}`` each.
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
        # Module name to its last failed step, ``{"state", "code",
        # "params"}``, as kept on disk.
        self._failures: dict = {}
        self._details_at = 0.0
        # A platform that installs no package has a runner only for what
        # the system itself carries: every other module the state names
        # reads as unsupported there.
        self._package = None
        self._system = None
        # The modules this agent applies the hub's configuration to, by
        # name; each also answers its own verbs.
        kinds = []
        if "packages" in platform.capabilities:
            self._package = PackageModuleRunner(
                platform=platform, log=self._collect, publish=self._publish
            )
            self._system = SystemPackageModuleRunner(
                platform=platform, log=self._collect, publish=self._publish
            )
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
        self._module_runners = {}
        for kind in kinds:
            runner = kind(platform=platform, log=self._collect, publish=self._publish)
            self._module_runners[runner.name] = runner
        self._failures = self._read_failures()
        super().__init__(log=log, on_change=on_change)

    @property
    def module_runners(self) -> dict:
        """The runners that apply configuration, by module name."""
        return dict(self._module_runners)

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

    def take_state(self, modules: dict) -> None:
        """Take the modules section of the hub's state, and observe against it.

        The failure kept for a module the state no longer names is deleted.

        Args:
            modules: ``{name: {"want", "config", "install", "uninstall"}}``;
                empty when the machine belongs to no hub.
        """
        with self._lock:
            self._wanted = {
                name: dict(entry)
                for name, entry in modules.items()
                if isinstance(entry, dict)
            }
            dropped = [name for name in self._failures if name not in self._wanted]
        for name in dropped:
            self.record_failure(name, None)
        self._wakeup.set()

    def is_installed(self, name: str) -> bool:
        """Whether one module's software is on this machine, checked now.

        Args:
            name: The module name.

        Returns:
            True when the recipe's verify command passes, or the runner's
            own check does where the state names no command; False for a
            module this agent has no runner for or cannot read.
        """
        runner = self._module_runners.get(name)
        if runner is None:
            return False
        recipe = _recipe_of(self._wanted_of(name))
        try:
            return self._verify(runner, recipe, runner.observe(_row(recipe)))
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
            in_transit = set(self._in_transit)
            observed = self._observed()
        for name in sorted(queued - in_transit):
            self._publish(name, _typed(AGENT_MODULE_STATE_QUEUED))
        for name in sorted(left - in_transit):
            if name in observed:
                self._publish(name, self._read_one(name, observed[name]))

    def refresh_now(self) -> None:
        """Report every module again from what is true right now."""
        self._refresh(is_forced=True)

    def install(self, name: str, *, receive, on_line=None) -> dict:
        """Put one module's software on the machine, in the caller's thread.

        Package operations run one at a time: a second caller waits for
        the first. The row reads ``installing`` while it runs.

        Args:
            name: The module name; its recipe is the one the state names.
            receive: Called with the module name when the recipe installs
                from bytes, and with the component's name as well for each
                component a recipe lists; returns ``{"path", "sha256"}``
                naming the package on disk and its digest, or ``{"code",
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
        if name in CARRIED_MODULES:
            return {"code": "module_not_orderable", "params": {"module": name}}
        wanted = self._wanted_of(name)
        if wanted is None:
            return {"code": "unknown_module", "params": {"module": name}}
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
        """Install by the recipe and check it took."""
        recipe = _recipe_of(wanted)
        resolved = _row(recipe)
        kind = resolved["kind"]
        runner = self._runner_for(kind, name)
        if runner is None:
            return {"code": "unknown_kind", "params": {"kind": kind}}
        self._collect(f"{name}: installing")
        components = [
            component
            for component in resolved["entry"].get("components") or []
            if isinstance(component, dict)
        ]
        if kind in BY_NAME_KINDS:
            runner.install(resolved)
        elif components:
            for component in components:
                refusal = self._install_component(
                    runner, resolved, component, name, receive
                )
                if refusal:
                    return refusal
        else:
            received = receive(name)
            if "path" not in received:
                return _download_refusal(runner, received)
            try:
                runner.install(resolved, received["path"])
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(received["path"])
        # Verify is the whole point of the step: a package manager that
        # exits zero and installs nothing is a thing that happens.
        if not self._verify(runner, recipe, runner.observe(resolved)):
            return {"code": "install_unconfirmed", "params": {}}
        return {}

    def _install_component(
        self, runner, resolved: dict, component: dict, name: str, receive
    ) -> dict:
        """Receive one component, check its digest against the recipe, unpack it.

        Returns:
            Empty when it landed, ``{"code", "params"}`` when it did not.
        """
        component_name = str(component.get("name", "") or "")
        received = receive(name, component_name)
        if "path" not in received:
            return _download_refusal(runner, received)
        try:
            expected = str(component.get("sha256", "") or "")
            if expected and received.get("sha256") != expected:
                return {
                    "code": CODE_DIGEST_MISMATCH,
                    "params": {"component": component_name},
                }
            runner.install_component(resolved, dict(component), received["path"])
        finally:
            with contextlib.suppress(OSError):
                os.unlink(received["path"])
        return {}

    def _uninstall(self, name: str, wanted: dict) -> dict:
        """Uninstall by the recipe, drop the hub's configuration and the mark."""
        recipe = _recipe_of(wanted)
        removal = wanted.get("uninstall")
        removal = dict(removal) if isinstance(removal, dict) else {}
        resolved = _row(dict(recipe, **removal))
        kind = resolved["kind"]
        runner = self._runner_for(kind, name)
        if runner is None:
            return {"code": "unknown_kind", "params": {"kind": kind}}
        is_leftover = not self.is_installed(name)
        self._collect(f"{name}: uninstalling")
        try:
            self._remove(name, runner, resolved, removal)
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
        if self._verify(runner, recipe, runner.observe(resolved)):
            return {"code": "uninstall_unconfirmed", "params": {}}
        return {}

    def _remove(self, name: str, runner, resolved: dict, removal: dict) -> None:
        """The uninstall's steps: the hub's configuration, the package, the
        recipe's own steps after it, and the data where the recipe says so."""
        if self.is_configured(name):
            with contextlib.suppress(Exception):
                runner.stop()
            runner.remove_configuration()
        runner.uninstall(resolved)
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
        for name in self._module_runners:
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
            in_transit = set(self._in_transit)
            queued = set(self._queued)
        is_due = time.monotonic() - self._details_at > AGENT_MODULE_DETAILS_TTL_S
        if not (is_stale or is_forced or is_due):
            return
        self._details_at = time.monotonic()
        for name, wanted in observed.items():
            if name in in_transit:
                continue
            if name in queued:
                self._publish(name, _typed(AGENT_MODULE_STATE_QUEUED))
                continue
            self._publish(name, self._read_one(name, wanted))
        # A module no runner and no state names stops being reported.
        self._keep_only(observed)

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
        runner = self._runner_for(str(recipe.get("kind", "")), name)
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
            observed = runner.observe(_row(recipe))
            if not self._verify(runner, recipe, observed):
                reason = runner.absent_reason(_row(recipe))
                status = _typed(
                    AGENT_MODULE_STATE_ABSENT, str(reason.get("code", "") or "")
                )
                status["params"] = dict(reason.get("params") or {})
                return self._with_failure(name, status, is_present=False)
            is_active = bool(observed.get("is_active", False))
            status = _typed(
                _steady_state(
                    is_active=is_active, is_configured=self.is_configured(name)
                ),
                is_active=is_active,
            )
            if observed.get("is_installing"):
                status["state"] = AGENT_MODULE_STATE_INSTALLING
                wait = runner.install_wait()
                status["code"] = str(wait.get("code", "") or "")
                status["params"] = dict(wait.get("params") or {})
            details = observed.get("details")
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
    def _verify(runner, recipe: dict, observed: dict) -> bool:
        """Whether the software is there.

        A module the hub named comes with ``install.verify``, and its exit
        is the answer. A module only observed, one the state never mentions,
        has no recipe, and the runner's own check answers for it.
        """
        command = str(recipe.get("verify", "") or "")
        if command:
            return verify_passes(command)
        return bool(observed.get("is_installed", False))

    def _runner_for(self, kind: str, name: str = ""):
        """The runner for one module: its own by name, else its kind's.

        Args:
            kind: The recipe's kind.
            name: The module name.

        Returns:
            The runner, or None for a module this agent has no runner for,
            which is every module on a platform that installs no package.
        """
        runner = self._module_runners.get(name)
        if runner is not None and (not kind or runner.kind == kind):
            return runner
        return {"package": self._package, "system_package": self._system}.get(kind)


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


def _download_refusal(runner, received: dict) -> dict:
    """Why an install got no package, in the runner's own code when it names one.

    Args:
        runner: The module's runner.
        received: The package stream's ``{"code", "params"}``.

    Returns:
        ``{"code", "params"}``: the runner's ``download_failure_code`` with
        the hub's code as ``detail``, or the stream's own when the runner
        names none or the socket went away, which the next state retries.
    """
    code = str(received.get("code", "") or "")
    if not runner.download_failure_code or code == CODE_UNREACHABLE:
        return dict(received)
    return {"code": runner.download_failure_code, "params": {"detail": code}}


def _recipe_of(wanted: "dict | None") -> dict:
    """The install recipe one state entry carries, empty when it carries none."""
    recipe = (wanted or {}).get("install")
    return dict(recipe) if isinstance(recipe, dict) else {}


def _row(recipe: dict) -> dict:
    """One recipe as the row today's runners read.

    Args:
        recipe: ``{"kind", "verify", "package", ...}``, the rest being the
            platform entry: packages, steps, package kind.

    Returns:
        ``{"kind", "entry", "verify", "package"}``.
    """
    return {
        "kind": str(recipe.get("kind", "") or ""),
        "entry": {
            key: value
            for key, value in recipe.items()
            if key not in RECIPE_HEADER_FIELDS
        },
        "verify": str(recipe.get("verify", "") or ""),
        "package": str(recipe.get("package", "") or ""),
    }


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
