"""Reporting what each module is, and carrying out the hub's orders.

The hub's state names, per module, what is wanted and the install recipe
resolved for this platform. :class:`ModuleEngine` observes every module it
has a runner for, named by the state or not, and derives one typed state
from three facts: whether the software is there, whether its unit is
active, and whether the hub has configured it. :class:`ReconcileWorker` is
the shared pattern: a thread woken by news, a signature that skips
unchanged inputs, an idle re-check so drift is still noticed, and per-name
typed statuses.

The engine keeps **no retry policy and no memory of past failures**: a
step that failed is reported failed with its code and never repeated,
because deciding to try again is the hub's. The recipes it works from are
already resolved for this platform, so nothing here reads a manifest or
searches a platform table either.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import tempfile
import threading
import time

from neutrino_agent.constants import (
    AGENT_MODULE_DETAILS_TTL_S,
    AGENT_MODULE_OUTPUT_LIMIT_BYTES,
    AGENT_MODULE_STATE_ABSENT,
    AGENT_MODULE_STATE_FAILED,
    AGENT_MODULE_STATE_INSTALLED,
    AGENT_MODULE_STATE_INSTALLING,
    AGENT_MODULE_STATE_RUNNING,
    AGENT_MODULE_STATE_STOPPED,
    AGENT_MODULE_STATE_UNINSTALLING,
    AGENT_MODULE_STATE_UNSUPPORTED,
    AGENT_RUSTDESK_BINARY_PATH,
    AGENT_WANT_RUNNING,
    AGENT_WANT_STOPPED,
)
from neutrino_agent.exceptions import InstallError, PlatformUnsupportedError
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

# What the hub can order. Only an `install` with an artifact needs bytes.
ORDER_INSTALL = "install"
ORDER_UNINSTALL = "uninstall"

# What each action shows while it runs, per the module state table.
ORDER_TRANSIENTS = {
    ORDER_INSTALL: AGENT_MODULE_STATE_INSTALLING,
    ORDER_UNINSTALL: AGENT_MODULE_STATE_UNINSTALLING,
}

# The kinds whose install runs by name with the platform's own tooling; the
# rest install from the artifact an order hands down.
BY_NAME_KINDS = ("system_package",)

ORDER_DONE = "done"
ORDER_FAILED = "failed"

# The wants under which the hub has configured a module: the panel writes
# them from Configure, Start and Stop. Until the configured mark lands on
# disk, a module the state wants this way counts as configured.
CONFIGURED_WANTS = (AGENT_WANT_RUNNING, AGENT_WANT_STOPPED)

# The states in which the software is there and its live details are read.
PRESENT_STATES = (
    AGENT_MODULE_STATE_INSTALLED,
    AGENT_MODULE_STATE_STOPPED,
    AGENT_MODULE_STATE_RUNNING,
)

# The recipe fields that are not part of the platform entry today's runners
# read: the kind names the runner, the verify command decides presence, and
# the package name is the entry's own.
RECIPE_HEADER_FIELDS = ("kind", "verify", "package")

# The module the agent carries itself. Its row reads installed while the
# agent's own build is on disk, and no order moves it.
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
    """Observes every module this machine has a runner for, and runs orders."""

    def __init__(self, *, platform, log=print, on_change=None, fetch_artifact=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            on_change: Called whenever a module's state changes.
            fetch_artifact: Called with ``(artifact_key, destination)`` to
                have the hub hand down the bytes an order names; None where
                there is no hub to ask.
        """
        # The state's modules section as the hub last sent it, by name:
        # ``{"want", "config", "install", "uninstall"}`` each.
        self._wanted: dict = {}
        self._fetch_artifact = fetch_artifact
        self._platform_tuple = platform_tuple()
        self._output: list = []
        self._on_line = None
        self._order_lock = threading.Lock()
        self._apply_results: dict = {}
        self._details_at = 0.0
        self._package = PackageModuleRunner(
            platform=platform, log=self._collect, publish=self._publish
        )
        self._system = SystemPackageModuleRunner(
            platform=platform, log=self._collect, publish=self._publish
        )
        # The modules this agent applies the hub's configuration to, by
        # name; each also carries out its own orders.
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
        """The per-module statuses, their details read again when stale.

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
        with self._lock:
            wanted = self._wanted.get(name)
        try:
            return self._verify(runner, _recipe_of(wanted))
        except Exception:  # noqa: BLE001 - an unreadable module is not installed
            return False

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

    def run_order(self, order: dict, on_line=None) -> dict:
        """Run one order now, in the caller's thread, and say how it went.

        Orders run one at a time: a second caller waits for the first.

        Args:
            order: ``{"id", "module", "action", "artifact_key", "digest",
                "package_kind"}``; the module's recipe is the one the
                state names.
            on_line: Called with each output line as the order produces it.

        Returns:
            ``{"state", "code", "params", "output"}``.
        """
        with self._order_lock:
            self._on_line = on_line
            try:
                result = self._run_order(order)
            finally:
                self._on_line = None
            self._refresh(is_forced=True)
        return result

    def _collect(self, message: str) -> None:
        """Log a line, keeping it for the order's report as well."""
        self._output.append(str(message))
        on_line = self._on_line
        if on_line is not None:
            on_line(str(message))
        self._log(message)

    def _reconcile(self) -> None:
        self._refresh(is_forced=False)

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

    def _row_of(self, name: str) -> dict:
        """One module's recipe as the row today's runners read."""
        with self._lock:
            wanted = self._wanted.get(name)
        return _row(_recipe_of(wanted))

    def _refresh(self, *, is_forced: bool) -> None:
        """Report what every observed module actually is."""
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
        if not is_stale and not is_forced:
            self._refresh_details()
            return
        for name, wanted in observed.items():
            self._publish(name, self._read_one(name, wanted))
        self._details_at = time.monotonic()
        # A module no runner and no state names stops being reported.
        self._keep_only(observed)

    def _refresh_details(self) -> None:
        """Read the live details of every present module again."""
        if time.monotonic() - self._details_at <= AGENT_MODULE_DETAILS_TTL_S:
            return
        self._details_at = time.monotonic()
        for name, runner in self._module_runners.items():
            with self._lock:
                status = dict(self._statuses.get(name) or {})
            if status.get("state") not in PRESENT_STATES:
                continue
            try:
                status["details"] = runner.details(self._row_of(name))
            except Exception as error:  # noqa: BLE001 - a read never fails a row
                self._log(f"{name}: details unreadable: {error}")
                continue
            self._publish(name, status)

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
            if not self._verify(runner, recipe):
                return _typed(AGENT_MODULE_STATE_ABSENT)
            is_active = bool(runner.is_active())
            is_configured = (wanted or {}).get("want") in CONFIGURED_WANTS
            status = _typed(
                _steady_state(is_active=is_active, is_configured=is_configured),
                is_active=is_active,
            )
            status["details"] = runner.details(_row(recipe))
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
    def _verify(runner, recipe: dict) -> bool:
        """Whether the software is there: the recipe's word, else the runner's."""
        command = str(recipe.get("verify", "") or "")
        if command:
            return verify_passes(command)
        return bool(runner.verify(_row(recipe)))

    def _run_order(self, order: dict) -> dict:
        """Do what one order says, and say how it went.

        Args:
            order: ``{"id", "module", "action", "artifact_key", "digest"}``.

        Returns:
            ``{"state", "code", "params", "output"}``.
        """
        name = str(order.get("module", ""))
        action = str(order.get("action", ""))
        self._output = []
        if name in BUILTIN_MODULES:
            return self._result(ORDER_FAILED, "module_not_orderable", {"module": name})
        with self._lock:
            wanted = self._wanted.get(name)
        if wanted is None:
            return self._result(ORDER_FAILED, "unknown_module", {"module": name})
        resolved = _row(_recipe_of(wanted))
        transient = ORDER_TRANSIENTS.get(action)
        if transient is None:
            return self._result(ORDER_FAILED, "unknown_action", {"action": action})
        self._publish(name, _typed(transient))
        self._collect(f"{name}: {action}")
        try:
            refusal = self._carry_out(action, name, resolved, order)
        except PlatformUnsupportedError:
            return self._result(ORDER_FAILED, "unsupported_platform", {})
        except InstallError as error:
            self._collect(str(error))
            return self._result(ORDER_FAILED, "install_failed", {})
        except Exception as error:  # noqa: BLE001 - reported, never raised
            self._collect(str(error))
            return self._result(
                ORDER_FAILED, "order_failed", {"detail": str(error)[:200]}
            )
        if refusal:
            return self._result(
                ORDER_FAILED,
                str(refusal.get("code", "order_failed")),
                dict(refusal.get("params") or {}),
            )
        return self._result(ORDER_DONE, "", {})

    def _carry_out(self, action: str, name: str, resolved: dict, order: dict) -> dict:
        """Run one action and check it took.

        Args:
            action: What the order says to do.
            name: The module name.
            resolved: The module's recipe as the row the runners read.
            order: The order itself, for the artifact it names.

        Returns:
            Empty when it took, ``{"code", "params"}`` when it did not.
        """
        kind = str(resolved.get("kind", ""))
        runner = self._runner_for(kind, name)
        if runner is None:
            return {"code": "unknown_kind", "params": {"kind": kind}}
        if action == ORDER_INSTALL:
            if kind in BY_NAME_KINDS:
                runner.install(resolved)
            else:
                refusal = self._install(name, resolved, order)
                if refusal:
                    return refusal
            # Verify is the whole point of the step: a package manager that
            # exits zero and installs nothing is a thing that happens.
            return {} if runner.verify(resolved) else {"code": "install_unconfirmed"}
        runner.uninstall(resolved)
        return {} if not runner.verify(resolved) else {"code": "uninstall_unconfirmed"}

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

    def _install(self, name: str, resolved: dict, order: dict) -> dict:
        """Get the bytes the hub holds and install them.

        Args:
            name: The module name.
            resolved: The module's recipe as the row the runners read.
            order: The order, which names the artifact and its digest.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        if self._fetch_artifact is None:
            return {"code": "hub_unreachable", "params": {}}
        artifact_key = str(order.get("artifact_key", ""))
        if not artifact_key:
            return {"code": "no_download_named", "params": {}}
        package_kind = str(order.get("package_kind", "")) or "pkg"
        with tempfile.TemporaryDirectory() as workdir:
            package = os.path.join(workdir, f"package.{package_kind}")
            self._collect(f"{name}: receiving {artifact_key}")
            refusal = self._fetch_artifact(artifact_key, package)
            if refusal:
                return refusal
            self._collect(f"{name}: installing")
            self._runner_for(str(resolved.get("kind", "")), name).install(
                resolved, package
            )
        return {}

    def _result(self, state: str, code: str, params: dict) -> dict:
        """How one order went, with the output it produced."""
        output = "\n".join(self._output)[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]
        self._output = []
        return {"state": state, "code": code, "params": dict(params), "output": output}


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
