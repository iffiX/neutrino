"""Reconciling the machine toward the hub's desired state.

The hub does not send actions; it sends what should be true, and a worker
thread closes any gap it finds. :class:`ReconcileWorker` is that pattern
once: a thread woken by news, a signature that skips unchanged inputs, an
idle re-check so drift is still caught, and per-name typed statuses.
:class:`ModuleEngine` builds the modules half of the catalog on it; the AI
service reconciler builds on it too.

The catalog is the hub's answer to "what exists for this machine", in two
halves under one hash: the module manifests, and the typed service list.
The engine reconciles the modules half; the services are visible and
decided only on the machine.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import threading
import time

from neutrino_agent.modules.downloader import DownloadError
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.modules.openssh import OpensshModuleReconciler
from neutrino_agent.modules.package import PackageModuleReconciler
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.detect import platform_keys, platform_tuple

# How often to re-check inputs that have not changed. Every heartbeat wakes
# the worker, and running each module's verify command that often would keep
# a Raspberry Pi busy doing nothing.
IDLE_RECHECK_INTERVAL_S = 60


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
    """Keeps the machine converged on the hub's desired modules."""

    def __init__(self, *, platform, log=print, on_change=None, fetch_gated=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            on_change: Called whenever a module's state changes.
            fetch_gated: Passed to the package reconciler, which uses it for
                the downloads a vendor serves only to a browser.
        """
        self._catalog: dict = {}
        self._catalog_hash = ""
        self._desired: dict = {}
        self._platform_tuple = platform_tuple()
        self._reconcilers = {
            reconciler.kind: reconciler
            for reconciler in (
                PackageModuleReconciler(
                    platform=platform,
                    log=log,
                    publish=self._publish,
                    fetch_gated=fetch_gated,
                ),
                OpensshModuleReconciler(
                    platform=platform, log=log, publish=self._publish
                ),
            )
        }
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
            ``{"modules", "services"}``, as the hub last sent it.
        """
        with self._lock:
            return dict(self._catalog)

    def update(self, *, desired: dict, catalog: "dict | None", catalog_hash: str):
        """Take the hub's word for what should be true.

        Args:
            desired: Module name to ``{"is_enabled", "config"}``.
            catalog: The catalog, sent only when this machine's copy is
                stale; None keeps the current one.
            catalog_hash: The hash of the catalog the hub is serving.
        """
        with self._lock:
            if catalog is not None:
                # A non-mapping catalog raises before the held one is replaced.
                self._catalog = dict(catalog)
                self._catalog_hash = catalog_hash
            self._desired = desired
        self._wakeup.set()

    def _reconcile(self) -> None:
        with self._lock:
            desired = dict(self._desired)
            modules = dict(self._catalog.get("modules", {}))
            signature = json.dumps(
                [sorted(modules), desired], sort_keys=True, default=str
            )
            is_stale = self._is_stale(signature)
        if not is_stale:
            return
        for name, manifest in modules.items():
            # A module the owner has never decided about is reported, never
            # acted on: "not switched on" is not the same as "take it off
            # this machine", and software that was here before the agent was
            # must survive the agent arriving.
            self._publish(name, self._reconcile_one(name, manifest, desired.get(name)))
        # A module the hub no longer serves stops being reported.
        self._keep_only(modules)

    def _reconcile_one(self, name: str, manifest: dict, wanted: "dict | None") -> dict:
        """Bring one module to its desired state, or just report it.

        Args:
            name: The module name.
            manifest: Its manifest.
            wanted: What the hub decided; None only inspects.

        Returns:
            ``{"state", "code", "params", "is_active"}`` for the heartbeat
            and both pages.
        """
        entry = self._platform_entry(manifest)
        if entry is None:
            return {
                "state": "unsupported",
                "code": "no_platform_build",
                "params": {},
                "is_active": False,
            }
        kind = manifest.get("kind", "")
        reconciler = self._reconcilers.get(kind)
        if reconciler is None:
            return {
                "state": "unknown",
                "code": "unknown_kind",
                "params": {"kind": kind},
                "is_active": False,
            }
        try:
            return reconciler.reconcile(
                name=name, manifest=manifest, entry=entry, wanted=wanted
            )
        except PlatformUnsupportedError:
            return {
                "state": "failed",
                "code": "unsupported_platform",
                "params": {},
                "is_active": False,
            }
        except DownloadError as error:
            return self._failure("download_failed", error)
        except InstallError as error:
            return self._failure("install_failed", error)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            return self._failure("reconcile_failed", error)

    def _platform_entry(self, manifest: dict) -> "dict | None":
        platforms = manifest.get("platforms", {})
        for key in platform_keys(self._platform_tuple):
            if key in platforms:
                return platforms[key]
        return None

    @staticmethod
    def _failure(code: str, error: Exception) -> dict:
        return {
            "state": "failed",
            "code": code,
            "params": {"detail": str(error)[:200]},
            "is_active": False,
        }
