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

The engine keeps **no retry policy and no memory of past failures**: a
step that failed is reported failed with its code and never repeated,
because deciding to try again is the hub's. The recipes it works from are
already resolved for this platform, so nothing here reads a manifest or
searches a platform table either.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import json
import os
import threading
import time

from neutrino_agent.constants import (
    AGENT_CONFIGURED_DIR,
    AGENT_MODULE_DETAILS_TTL_S,
    AGENT_MODULE_STATE_ABSENT,
    AGENT_MODULE_STATE_FAILED,
    AGENT_MODULE_STATE_INSTALLED,
    AGENT_MODULE_STATE_INSTALLING,
    AGENT_MODULE_STATE_RUNNING,
    AGENT_MODULE_STATE_STOPPED,
    AGENT_MODULE_STATE_UNINSTALLING,
    AGENT_MODULE_STATE_UNSUPPORTED,
    AGENT_RUSTDESK_BINARY_PATH,
)
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.modules import installers
from neutrino_agent.modules.gitea.runner import GiteaModuleRunner
from neutrino_agent.modules.package import PackageModuleRunner, verify_passes
from neutrino_agent.modules.podman.runner import PodmanModuleRunner
from neutrino_agent.modules.samba.runner import SambaModuleRunner
from neutrino_agent.modules.system_package import SystemPackageModuleRunner
from neutrino_agent.modules.zfs.runner import ZfsModuleRunner
from neutrino_agent.platforms.detect import platform_tuple

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

# The module the agent carries itself. Its row reads installed while the
# agent's own build is on disk, and no operation moves it.
BUILTIN_RUSTDESK_NAME = "rustdesk"
BUILTIN_MODULES = (BUILTIN_RUSTDESK_NAME,)


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

    def __init__(self, *, platform, log=print, on_change=None, configured_dir=""):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            on_change: Called whenever a module's state changes.
            configured_dir: Where the configured marks live; empty is the
                machine's own directory.
        """
        # The state's modules section as the hub last sent it, by name:
        # ``{"want", "config", "install", "uninstall"}`` each.
        self._wanted: dict = {}
        self._configured_dir = configured_dir or AGENT_CONFIGURED_DIR
        self._platform_tuple = platform_tuple()
        self._on_line = None
        self._operation_lock = threading.Lock()
        # The modules mid-operation, whose transient state a refresh keeps.
        self._in_transit: set = set()
        self._apply_results: dict = {}
        self._details_at = 0.0
        self._package = PackageModuleRunner(
            platform=platform, log=self._collect, publish=self._publish
        )
        self._system = SystemPackageModuleRunner(
            platform=platform, log=self._collect, publish=self._publish
        )
        # The modules this agent applies the hub's configuration to, by
        # name; each also answers its own verbs.
        self._module_runners = {
            runner.name: runner
            for runner in (
                SambaModuleRunner(
                    platform=platform, log=self._collect, publish=self._publish
                ),
                GiteaModuleRunner(
                    platform=platform, log=self._collect, publish=self._publish
                ),
                PodmanModuleRunner(
                    platform=platform, log=self._collect, publish=self._publish
                ),
                ZfsModuleRunner(
                    platform=platform, log=self._collect, publish=self._publish
                ),
            )
        }
        super().__init__(log=log, on_change=on_change)
        # The built-in rows are known from the start, so their first
        # refresh is not news that wakes a report.
        with self._lock:
            for name in BUILTIN_MODULES:
                self._statuses[name] = self._read_one(name, None)

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

    def record_apply(self, name: str, code: str, params: dict) -> None:
        """Keep how the last apply of one module went, for its row.

        Args:
            name: The module name.
            code: Why it failed; empty when it took.
            params: What the wording names.
        """
        with self._lock:
            if code:
                self._apply_results[name] = (code, dict(params))
            else:
                self._apply_results.pop(name, None)

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
                from bytes; returns ``{"path"}`` naming the package on
                disk, or ``{"code", "params"}``. The file is deleted once
                the install ran.
            on_line: Called with each output line as the install produces
                it.

        Returns:
            Empty when the software is there afterwards, ``{"code",
            "params"}`` when it is not.
        """
        return self._operate(
            name,
            AGENT_MODULE_STATE_INSTALLING,
            "install_failed",
            on_line,
            self._install,
            receive,
        )

    def uninstall(self, name: str, *, on_line=None) -> dict:
        """Take one module's software off the machine, in the caller's thread.

        The configuration the hub wrote and the configured mark go with
        it; the module's data stays. The row reads ``uninstalling`` while
        it runs.

        Args:
            name: The module name; its recipes are the ones the state names.
            on_line: Called with each output line as the uninstall
                produces it.

        Returns:
            Empty when the software is gone afterwards, ``{"code",
            "params"}`` when it is not.
        """
        return self._operate(
            name,
            AGENT_MODULE_STATE_UNINSTALLING,
            "uninstall_failed",
            on_line,
            self._uninstall,
        )

    def _operate(
        self, name: str, transient: str, failure: str, on_line, step, *extra
    ) -> dict:
        """Run one package operation under the machine's one lock.

        Args:
            name: The module name.
            transient: The state the row shows while the operation runs.
            failure: The code a step that raised is reported under.
            on_line: Called with each output line.
            step: The operation itself, given the name, its state entry
                and ``extra``.
            *extra: What the step takes beside them.

        Returns:
            Empty when the operation took, ``{"code", "params"}`` when not.
        """
        if name in BUILTIN_MODULES:
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
            except Exception as error:  # noqa: BLE001 - reported, never raised
                self._collect(str(error))
                refusal = {"code": failure, "params": {"detail": str(error)[:200]}}
            finally:
                self._on_line = None
                with self._lock:
                    self._in_transit.discard(name)
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
        if kind in BY_NAME_KINDS:
            runner.install(resolved)
        else:
            received = receive(name)
            if "path" not in received:
                return dict(received)
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
        self._collect(f"{name}: uninstalling")
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
        self.clear_configured(name)
        if self._verify(runner, recipe, runner.observe(resolved)):
            return {"code": "uninstall_unconfirmed", "params": {}}
        return {}

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
            state does not name, then the built-in rows; an unnamed module
            maps to None.
        """
        observed = {name: dict(entry) for name, entry in self._wanted.items()}
        for name in list(self._module_runners) + list(BUILTIN_MODULES):
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
        is_due = time.monotonic() - self._details_at > AGENT_MODULE_DETAILS_TTL_S
        if not (is_stale or is_forced or is_due):
            return
        self._details_at = time.monotonic()
        for name, wanted in observed.items():
            if name in in_transit:
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
            ``{"state", "is_active", "code", "params", "details"}``.
        """
        if name in BUILTIN_MODULES:
            is_present = os.path.isfile(AGENT_RUSTDESK_BINARY_PATH)
            return _typed(
                AGENT_MODULE_STATE_INSTALLED
                if is_present
                else AGENT_MODULE_STATE_ABSENT
            )
        recipe = _recipe_of(wanted)
        runner = self._runner_for(str(recipe.get("kind", "")), name)
        if runner is None:
            return _typed(AGENT_MODULE_STATE_UNSUPPORTED)
        try:
            observed = runner.observe(_row(recipe))
            if not self._verify(runner, recipe, observed):
                return _typed(AGENT_MODULE_STATE_ABSENT)
            is_active = bool(observed.get("is_active", False))
            status = _typed(
                _steady_state(
                    is_active=is_active, is_configured=self.is_configured(name)
                ),
                is_active=is_active,
            )
            details = observed.get("details")
            status["details"] = dict(details) if isinstance(details, dict) else {}
        except PlatformUnsupportedError:
            return _typed(AGENT_MODULE_STATE_FAILED, "unsupported_platform")
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return _typed(
                AGENT_MODULE_STATE_FAILED, "verify_failed", detail=str(error)[:200]
            )
        with self._lock:
            failure = self._apply_results.get(name)
        if failure is not None:
            status["state"] = AGENT_MODULE_STATE_FAILED
            status["code"], status["params"] = failure[0], dict(failure[1])
        return status

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
            The runner, or None for a module this agent has no runner for.
        """
        runner = self._module_runners.get(name)
        if runner is not None and (not kind or runner.kind == kind):
            return runner
        return {"package": self._package, "system_package": self._system}.get(kind)


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
