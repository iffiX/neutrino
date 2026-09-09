"""Carrying out the hub's orders, and reporting what is true.

The hub opens an order — install this, uninstall that — as a stream on the
socket, and this machine runs it in that stream's own thread, one at a
time, and says how it went. :class:`ReconcileWorker` is the shared pattern:
a thread woken by news, a signature that skips unchanged inputs, an idle
re-check so drift is still noticed, and per-name typed statuses.

:class:`ModuleEngine` is deliberately without judgment. It keeps **no retry
policy and no memory of past failures**: an order that failed is reported
failed and never repeated, because deciding to try again is the hub's, and
a machine that decided for itself would be a second opinion nobody asked
for. The catalog it works from is already resolved for this platform, so
nothing here reads a manifest or searches a platform table either.
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
    AGENT_RUSTDESK_BINARY_PATH,
)
from neutrino_agent.modules.gitea.runner import GiteaModuleRunner
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.modules.package import PackageModuleRunner
from neutrino_agent.modules.podman.runner import PodmanModuleRunner
from neutrino_agent.modules.rustdesk import RustdeskModuleRunner
from neutrino_agent.modules.samba.runner import SambaModuleRunner
from neutrino_agent.modules.system_package import SystemPackageModuleRunner
from neutrino_agent.modules.zfs.runner import ZfsModuleRunner
from neutrino_agent.platforms.base import PlatformUnsupportedError
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
    ORDER_INSTALL: "installing",
    ORDER_UNINSTALL: "uninstalling",
}

# The kinds whose install runs by name with the platform's own tooling; the
# rest install from the artifact an order hands down.
BY_NAME_KINDS = ("system_package",)

ORDER_DONE = "done"
ORDER_FAILED = "failed"

# The module the agent carries itself. Its row reads installed while the
# agent's own build is on disk, and no order moves it.
BUILTIN_RUSTDESK_NAME = "rustdesk"
BUILTIN_MODULES = {
    BUILTIN_RUSTDESK_NAME: {
        "title": "RustDesk",
        "description": "Remote desktop, direct connect on the LAN",
        "kind": "rustdesk",
        "installer": "agent",
        "source": "rustdesk/rustdesk",
        "version": "",
        "license": "AGPL-3.0",
        "corresponding_source": "https://github.com/rustdesk/rustdesk",
        "platform_key": "linux",
        "entry": {},
        "verify": "",
        "package": "rustdesk",
    }
}


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
    """Runs the hub's module orders and reports what this machine has."""

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
        self._catalog: dict = {}
        self._catalog_hash = ""
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
        self._rustdesk = RustdeskModuleRunner(
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
            for name, resolved in BUILTIN_MODULES.items():
                self._statuses[name] = self._read_one(name, resolved)

    @property
    def module_runners(self) -> dict:
        """The runners that apply configuration, by module name."""
        return dict(self._module_runners)

    @property
    def catalog_hash(self) -> str:
        """The hash of the catalog this machine currently holds."""
        with self._lock:
            return self._catalog_hash

    @property
    def platform_tuple(self) -> dict:
        """This machine's platform tuple, for the heartbeat."""
        return self._platform_tuple

    def catalog(self) -> dict:
        """The catalog this machine currently holds.

        Returns:
            ``{"modules"}``, as the hub last sent it, its modules already
            resolved for this platform, with the agent's own built-in rows
            added.
        """
        with self._lock:
            return {**self._catalog, "modules": self._modules()}

    def resolved(self, name: str) -> "dict | None":
        """One module as the hub resolved it for this platform.

        Args:
            name: The module name.

        Returns:
            The resolved module, or None when the catalog has no such row.
        """
        with self._lock:
            return self._modules().get(name)

    def report(self) -> dict:
        """The per-module statuses, their details read again when stale."""
        if time.monotonic() - self._details_at > AGENT_MODULE_DETAILS_TTL_S:
            self._wakeup.set()
        return super().report()

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

    def update(self, *, catalog: "dict | None", catalog_hash: str) -> None:
        """Take the hub's catalog when this copy is stale.

        Args:
            catalog: The catalog; None keeps the current one.
            catalog_hash: The hash of the catalog the hub is serving.
        """
        with self._lock:
            if catalog is not None:
                # A non-mapping catalog raises before the held one is replaced.
                self._catalog = dict(catalog)
                self._catalog_hash = catalog_hash
        self._wakeup.set()

    def run_order(self, order: dict, on_line=None) -> dict:
        """Run one order now, in the caller's thread, and say how it went.

        Orders run one at a time: a second caller waits for the first.

        Args:
            order: ``{"id", "module", "action", "artifact_key", "digest",
                "package_kind", "resolved"}``; ``resolved`` is the module
                as the hub resolved it for this platform, and is kept so
                the module is reported from then on.
            on_line: Called with each output line as the order produces it.

        Returns:
            ``{"state", "code", "params", "output"}``.
        """
        name = str(order.get("module", ""))
        resolved = order.get("resolved")
        with self._order_lock:
            if isinstance(resolved, dict) and name:
                with self._lock:
                    modules = dict(self._catalog.get("modules", {}))
                    modules[name] = dict(resolved)
                    self._catalog = {**self._catalog, "modules": modules}
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

    def _modules(self) -> dict:
        """The catalog's modules with the built-in rows. Call under the lock."""
        return {**self._catalog.get("modules", {}), **BUILTIN_MODULES}

    def _refresh(self, *, is_forced: bool) -> None:
        """Report what every module in the catalog actually is."""
        with self._lock:
            modules = self._modules()
            signature = json.dumps(sorted(modules), sort_keys=True, default=str)
            is_stale = self._is_stale(signature)
        if not is_stale and not is_forced:
            self._refresh_details(modules)
            return
        for name, resolved in modules.items():
            self._publish(name, self._read_one(name, resolved))
        self._details_at = time.monotonic()
        # A module the hub no longer serves stops being reported.
        self._keep_only(modules)

    def _refresh_details(self, modules: dict) -> None:
        """Read the live details of every installed module again."""
        if time.monotonic() - self._details_at <= AGENT_MODULE_DETAILS_TTL_S:
            return
        self._details_at = time.monotonic()
        for name, runner in self._module_runners.items():
            resolved = modules.get(name)
            with self._lock:
                status = dict(self._statuses.get(name) or {})
            if resolved is None or status.get("state") != "installed":
                continue
            try:
                status["details"] = runner.details(resolved)
            except Exception as error:  # noqa: BLE001 - a read never fails a row
                self._log(f"{name}: details unreadable: {error}")
                continue
            self._publish(name, status)

    def _read_one(self, name: str, resolved: dict) -> dict:
        """What one module actually is on this machine, acting on nothing.

        Args:
            name: The module name.
            resolved: The module as the hub resolved it for this platform.

        Returns:
            ``{"state", "code", "params", "details"}``.
        """
        if name in BUILTIN_MODULES:
            is_present = os.path.isfile(AGENT_RUSTDESK_BINARY_PATH)
            return _typed("installed" if is_present else "absent", "")
        if not isinstance(resolved, dict) or resolved.get("entry") is None:
            return _typed("unsupported", "no_platform_build")
        kind = resolved.get("kind", "")
        runner = self._runner_for(kind, name)
        if runner is None:
            return _typed("unsupported", "unknown_kind", kind=kind)
        try:
            # A module the platform carries natively is simply there.
            if kind == "system_package" and runner.is_native(resolved):
                return _typed("installed", "")
            is_present = runner.verify(resolved)
            status = _typed("installed" if is_present else "absent", "")
            if is_present:
                status["details"] = runner.details(resolved)
                with self._lock:
                    failure = self._apply_results.get(name)
                if failure is not None:
                    status["code"], status["params"] = failure[0], dict(failure[1])
            return status
        except PlatformUnsupportedError:
            return _typed("failed", "unsupported_platform")
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return _typed("failed", "verify_failed", detail=str(error)[:200])

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
            resolved = dict(self._catalog.get("modules", {})).get(name)
        if not isinstance(resolved, dict) or resolved.get("entry") is None:
            return self._result(ORDER_FAILED, "no_platform_build", {})
        transient = ORDER_TRANSIENTS.get(action)
        if transient is None:
            return self._result(ORDER_FAILED, "unknown_action", {"action": action})
        self._publish(name, _typed(transient, ""))
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
            resolved: The module as the hub resolved it.
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
            kind: The manifest kind.
            name: The module name.

        Returns:
            The runner, or None for a kind this agent does not know.
        """
        runner = self._module_runners.get(name)
        if runner is not None and (not kind or runner.kind == kind):
            return runner
        return {
            "package": self._package,
            "system_package": self._system,
            "rustdesk": self._rustdesk,
        }.get(kind)

    def _install(self, name: str, resolved: dict, order: dict) -> dict:
        """Get the bytes the hub holds and install them.

        Args:
            name: The module name.
            resolved: The module as the hub resolved it.
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


def _typed(state: str, code: str, **params) -> dict:
    """One typed status, the shape every surface words for itself.

    ``details`` carries facts a surface prints as they are — a remote
    desktop's id — beside the code every surface words for itself.
    """
    return {"state": state, "code": code, "params": params, "details": {}}
