"""Carrying out the hub's orders, and reporting what is true.

The hub sends orders — install this, uninstall that — and this machine runs
them one at a time and says how each went. :class:`ReconcileWorker` is the
shared pattern: a thread woken by news, a signature that skips unchanged
inputs, an idle re-check so drift is still noticed, and per-name typed
statuses. The AI service reconciler builds on it too.

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

from neutrino_agent.constants import AGENT_MODULE_OUTPUT_LIMIT_BYTES
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.modules.package import PackageModuleRunner
from neutrino_agent.modules.rustdesk import RustdeskModuleRunner
from neutrino_agent.modules.system_package import SystemPackageModuleRunner
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
        self._queued: list = []
        self._ran: set = set()
        self._results: dict = {}
        self._output: list = []
        self._package = PackageModuleRunner(
            platform=platform, log=self._collect, publish=self._publish
        )
        self._system = SystemPackageModuleRunner(
            platform=platform, log=self._collect, publish=self._publish
        )
        self._rustdesk = RustdeskModuleRunner(
            platform=platform, log=self._collect, publish=self._publish
        )
        super().__init__(log=log, on_change=on_change)

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
            ``{"modules", "services"}``, as the hub last sent it, its
            modules already resolved for this platform.
        """
        with self._lock:
            return dict(self._catalog)

    def results(self) -> list:
        """How the orders this machine has finished went.

        Returns:
            One ``{"id", "module", "state", "code", "params", "output"}``
            each, repeated on every beat until the hub's reply shows it
            stopped asking — a result lost in the wire is an order the hub
            would wait on for ever.
        """
        with self._lock:
            return [dict(result) for result in self._results.values()]

    def update(self, *, catalog: "dict | None", catalog_hash: str, orders) -> None:
        """Take the hub's orders, and its catalog when this copy is stale.

        Args:
            catalog: The catalog, sent only when this machine's copy is
                stale; None keeps the current one.
            catalog_hash: The hash of the catalog the hub is serving.
            orders: The orders standing for this machine.

        Raises:
            TypeError: If the orders are not a list. A reply shape this
                build cannot read becomes a typed error one level up, never
                a beat that quietly did nothing.
        """
        if orders is not None and not isinstance(orders, list):
            raise TypeError(f"module_orders is {type(orders).__name__}, not a list")
        with self._lock:
            if catalog is not None:
                # A non-mapping catalog raises before the held one is replaced.
                self._catalog = dict(catalog)
                self._catalog_hash = catalog_hash
            standing = set()
            for order in orders or []:
                if not isinstance(order, dict):
                    continue
                order_id = str(order.get("id", ""))
                if not order_id:
                    continue
                standing.add(order_id)
                if order_id not in self._ran and not any(
                    queued.get("id") == order_id for queued in self._queued
                ):
                    self._queued.append(dict(order))
            # The hub has stopped asking about these, so it has the result.
            for order_id in list(self._results):
                if order_id not in standing:
                    self._results.pop(order_id, None)
                    self._ran.discard(order_id)
        self._wakeup.set()

    def _collect(self, message: str) -> None:
        """Log a line, keeping it for the order's report as well."""
        self._output.append(str(message))
        self._log(message)

    def _reconcile(self) -> None:
        order = self._take_order()
        if order is not None:
            self._run_order(order)
            self._refresh(is_forced=True)
            return
        self._refresh(is_forced=False)

    def _take_order(self) -> "dict | None":
        """The next order to run, if the hub has one standing."""
        with self._lock:
            if not self._queued:
                return None
            order = self._queued.pop(0)
            self._ran.add(str(order.get("id", "")))
            return order

    def _refresh(self, *, is_forced: bool) -> None:
        """Report what every module in the catalog actually is."""
        with self._lock:
            modules = dict(self._catalog.get("modules", {}))
            signature = json.dumps(sorted(modules), sort_keys=True, default=str)
            is_stale = self._is_stale(signature)
        if not is_stale and not is_forced:
            return
        for name, resolved in modules.items():
            self._publish(name, self._read_one(name, resolved))
        # A module the hub no longer serves stops being reported.
        self._keep_only(modules)

    def _read_one(self, name: str, resolved: dict) -> dict:
        """What one module actually is on this machine, acting on nothing.

        Args:
            name: The module name.
            resolved: The module as the hub resolved it for this platform.

        Returns:
            ``{"state", "code", "params", "details"}``.
        """
        if not isinstance(resolved, dict) or resolved.get("entry") is None:
            return _typed("unsupported", "no_platform_build")
        kind = resolved.get("kind", "")
        runner = self._runner_for(kind)
        if runner is None:
            return _typed("unsupported", "unknown_kind", kind=kind)
        try:
            # A module the platform carries natively is simply there.
            if kind == "system_package" and self._system.is_native(resolved):
                return _typed("installed", "")
            is_present = runner.verify(resolved)
            status = _typed("installed" if is_present else "absent", "")
            if is_present:
                status["details"] = runner.details(resolved)
            return status
        except PlatformUnsupportedError:
            return _typed("failed", "unsupported_platform")
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return _typed("failed", "verify_failed", detail=str(error)[:200])

    def _run_order(self, order: dict) -> None:
        """Do what one order says, and record how it went.

        Args:
            order: ``{"id", "module", "action", "artifact_key", "digest"}``.
        """
        order_id = str(order.get("id", ""))
        name = str(order.get("module", ""))
        action = str(order.get("action", ""))
        self._output = []
        with self._lock:
            resolved = dict(self._catalog.get("modules", {})).get(name)
        if not isinstance(resolved, dict) or resolved.get("entry") is None:
            self._record(order_id, name, ORDER_FAILED, "no_platform_build", {})
            return
        transient = ORDER_TRANSIENTS.get(action)
        if transient is None:
            self._record(
                order_id, name, ORDER_FAILED, "unknown_action", {"action": action}
            )
            return
        self._publish(name, _typed(transient, ""))
        self._collect(f"{name}: {action}")
        try:
            refusal = self._carry_out(action, name, resolved, order)
        except PlatformUnsupportedError:
            self._record(order_id, name, ORDER_FAILED, "unsupported_platform", {})
            return
        except InstallError as error:
            self._collect(str(error))
            self._record(order_id, name, ORDER_FAILED, "install_failed", {})
            return
        except Exception as error:  # noqa: BLE001 - reported, never raised
            self._collect(str(error))
            self._record(
                order_id,
                name,
                ORDER_FAILED,
                "order_failed",
                {"detail": str(error)[:200]},
            )
            return
        if refusal:
            self._record(
                order_id,
                name,
                ORDER_FAILED,
                str(refusal.get("code", "order_failed")),
                dict(refusal.get("params") or {}),
            )
            return
        self._record(order_id, name, ORDER_DONE, "", {})

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
        runner = self._runner_for(kind)
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

    def _runner_for(self, kind: str):
        """The runner that owns one manifest kind, or None for a kind this
        agent does not know."""
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
            self._runner_for(str(resolved.get("kind", ""))).install(resolved, package)
        return {}

    def _record(
        self, order_id: str, module: str, state: str, code: str, params: dict
    ) -> None:
        """Keep how one order went, for the next beat to carry up."""
        output = "\n".join(self._output)[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]
        self._output = []
        with self._lock:
            self._results[order_id] = {
                "id": order_id,
                "module": module,
                "state": state,
                "code": code,
                "params": dict(params),
                # Every order carries its output, success included: a result
                # rides once and stops when the hub acknowledges it, so this
                # is one message per operation rather than a per-beat cost,
                # and a person watching an install wants to see it work.
                "output": output,
            }
        if self._on_change is not None:
            self._on_change()


def _typed(state: str, code: str, **params) -> dict:
    """One typed status, the shape every surface words for itself.

    ``details`` carries facts a surface prints as they are — a remote
    desktop's id — beside the code every surface words for itself.
    """
    return {"state": state, "code": code, "params": params, "details": {}}
