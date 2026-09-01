"""Reconciling the machine toward the gateway's desired feature set.

The gateway does not send actions; it sends what should be true — which
features are on — plus the manifest catalog saying how each is obtained on
each platform. Every heartbeat hands that in here, a worker thread closes any
gap it finds, and the next heartbeat reports where things stand. Idempotence
falls out: a feature already in its desired state is only ever checked.

Installed software is not removed when a feature is switched off — deleting
someone's remote desktop because a toggle changed is the kind of surprise an
agent must not spring. The exception is ``ai_config``, which is pure
configuration pointing at the gateway: switched off, it is taken back out so
no tool keeps calling an endpoint that may have revoked its key.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time

from neutrino_agent.downloader import (
    DownloadError,
    download,
    resolve_github_asset,
    verify_package,
)
from neutrino_agent.installers import (
    InstallError,
    enable_openssh,
    install_package,
    openssh_status,
    uninstall_package,
)
from neutrino_agent import switcher
from neutrino_agent.platform_info import platform_keys, platform_tuple

INSTALL_TIMEOUT_S = 900
VERIFY_TIMEOUT_S = 30

# How often to re-check a catalog that has not changed. Every heartbeat wakes
# the worker, and running each feature's verify command that often would keep
# a Raspberry Pi busy doing nothing.
IDLE_RECHECK_INTERVAL_S = 60


class FeatureManager:
    """Keeps the machine converged on the gateway's desired features."""

    def __init__(self, *, log=print, on_change=None):
        """
        Args:
            log: Callable used for progress messages; defaults to printing,
                which systemd captures into the journal.
            on_change: Called whenever a feature's state changes. The agent
                uses it to beat straight away: an install that takes three
                seconds would otherwise begin and end between two heartbeats,
                and nobody watching would ever see it running.
        """
        self._log = log
        self._on_change = on_change
        self._lock = threading.Lock()
        self._catalog: dict = {}
        self._catalog_hash = ""
        self._desired: dict = {}
        self._statuses: dict = {}
        # Features whose install ran and whose verify did not confirm it.
        # Without this the idle re-check finds them absent a minute later and
        # installs them again, for ever: a package whose verify command names
        # the wrong path is re-downloaded every minute until somebody notices
        # the traffic.
        self._unconfirmed: set = set()
        self._platform = platform_tuple()
        self._signature = ""
        self._checked_at = 0.0
        self._wakeup = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    @property
    def catalog_hash(self) -> str:
        """The hash of the catalog this machine currently holds."""
        with self._lock:
            return self._catalog_hash

    def catalog(self) -> dict:
        """The manifest catalog this machine currently holds.

        Returns:
            Feature name to manifest, as the gateway last sent it.
        """
        with self._lock:
            return dict(self._catalog)

    @property
    def platform(self) -> dict:
        """This machine's platform tuple, for the heartbeat."""
        return self._platform

    def update(self, *, desired: dict, catalog: "dict | None", catalog_hash: str):
        """Take the gateway's word for what should be true.

        Args:
            desired: Feature name to ``{"is_enabled", "config"}``.
            catalog: The manifest catalog, sent only when this machine's copy
                is stale; None keeps the current one.
            catalog_hash: The hash of the catalog the gateway is serving.
        """
        with self._lock:
            if catalog is not None:
                self._catalog = catalog
                self._catalog_hash = catalog_hash
            self._desired = desired
        self._wakeup.set()

    def report(self) -> dict:
        """The per-feature states for the next heartbeat.

        Returns:
            Feature name to ``{"state", "message"}``.
        """
        with self._lock:
            return {name: dict(value) for name, value in self._statuses.items()}

    def _run(self) -> None:
        while True:
            self._wakeup.wait()
            self._wakeup.clear()
            try:
                self._reconcile()
            except Exception as error:  # noqa: BLE001 - the loop must survive
                self._log(f"feature reconcile crashed: {error}")

    def _reconcile(self) -> None:
        with self._lock:
            desired = dict(self._desired)
            catalog = dict(self._catalog)
            signature = json.dumps(
                [sorted(catalog), desired], sort_keys=True, default=str
            )
            is_stale = (
                signature != self._signature
                or time.monotonic() - self._checked_at > IDLE_RECHECK_INTERVAL_S
            )
            self._signature = signature
            if is_stale:
                self._checked_at = time.monotonic()
        if not is_stale:
            return
        for name, manifest in catalog.items():
            # A feature the owner has never decided about is reported, never
            # acted on: "not switched on" is not the same as "take it off
            # this machine", and software that was here before the agent was
            # must survive the agent arriving.
            self._publish(name, self._reconcile_one(name, manifest, desired.get(name)))
        # A feature the gateway no longer serves stops being reported.
        with self._lock:
            self._statuses = {
                name: value for name, value in self._statuses.items() if name in catalog
            }

    def _publish(self, name: str, status: dict) -> None:
        """Record one feature's state, and say so if it is news."""
        with self._lock:
            is_news = self._statuses.get(name) != status
            self._statuses[name] = status
        if is_news and self._on_change is not None:
            self._on_change()

    def _reconcile_one(self, name: str, manifest: dict, wanted: "dict | None") -> dict:
        """Bring one feature to its desired state, or just report it.

        Args:
            name: The feature name.
            manifest: Its manifest.
            wanted: What the owner asked for — ``is_enabled`` and, for the
                features that have one, ``is_activated``, plus whatever
                ``config`` the hub resolved. None when nothing has been asked,
                in which case the feature is inspected and never touched.

        Returns:
            ``{"state", "message", "is_active"}`` for the heartbeat and both
            pages.
        """
        entry = self._platform_entry(manifest)
        if entry is None:
            return {
                "state": "unsupported",
                "message": "no build for this platform",
                "is_active": False,
            }
        is_enabled = None if wanted is None else bool(wanted.get("is_enabled"))
        config = (wanted or {}).get("config", {})
        kind = manifest.get("kind", "")
        try:
            if kind == "ai_tools":
                return self._reconcile_ai_tools(name, entry, wanted, config)
            if kind == "openssh":
                return self._reconcile_openssh(entry, is_enabled)
            if kind == "package":
                return self._reconcile_package(name, manifest, entry, is_enabled)
        except (InstallError, DownloadError) as error:
            return {"state": "failed", "message": str(error)[:200], "is_active": False}
        except Exception as error:  # noqa: BLE001 - reported, not raised
            return {"state": "failed", "message": str(error)[:200], "is_active": False}
        return {
            "state": "unknown",
            "message": f"unknown kind {kind!r}",
            "is_active": False,
        }

    def _platform_entry(self, manifest: dict) -> "dict | None":
        platforms = manifest.get("platforms", {})
        for key in platform_keys(self._platform):
            if key in platforms:
                return platforms[key]
        return None

    def _reconcile_ai_tools(
        self, name: str, entry: dict, wanted: "dict | None", config: dict
    ) -> dict:
        """Have cc-switch on the machine, and have it point at the hub.

        Two independent wishes. Installing puts the switcher there and leaves
        it pointing wherever it already pointed; activating registers the hub
        in it and switches to it. Deactivating removes only the hub's entry,
        so the other providers someone keeps stay untouched.

        Args:
            name: The feature name, for the transient states.
            entry: The manifest's platform entry, naming where the CLI comes
                from.
            wanted: ``is_enabled`` and ``is_activated``, or None when nothing
                has been asked and this only reports.
            config: The endpoint, key and account, resolved by the hub.

        Returns:
            ``{"state", "message", "is_active"}``.
        """
        switcher_entry = entry.get("switcher", {})
        run_as = config.get("target_user", "")
        base_url = config.get("base_url", "")
        is_present = switcher.is_installed()
        is_active = (
            is_present
            and bool(run_as)
            and switcher.is_active(
                run_as=run_as,
                base_url=base_url,
                api_key=config.get("api_key", ""),
                model=config.get("model", ""),
            )
        )

        if wanted is None:
            return _ai_status(is_present, is_active)

        is_enabled = bool(wanted.get("is_enabled"))
        is_activated = bool(wanted.get("is_activated"))

        if not is_enabled:
            if not is_present:
                return _ai_status(False, False)
            self._publish(
                name, {"state": "removing", "message": "", "is_active": False}
            )
            self._log(f"{name}: removing the cc-switch command line")
            if is_active:
                switcher.deactivate(run_as=run_as, base_url=base_url)
            switcher.uninstall_cli()
            still_there = switcher.is_installed()
            return {
                "state": "installed" if still_there else "absent",
                "message": (
                    "the desktop app is still installed" if still_there else ""
                ),
                "is_active": False,
            }

        if not is_present:
            self._publish(
                name, {"state": "installing", "message": "", "is_active": False}
            )
            self._log(f"{name}: installing the cc-switch command line")
            switcher.install_cli(switcher_entry)
            is_present = True

        if is_activated and not is_active:
            if not base_url or not config.get("api_key"):
                return {
                    "state": "installed",
                    "message": "the hub sent no endpoint to point at",
                    "is_active": False,
                }
            self._publish(
                name, {"state": "activating", "message": "", "is_active": False}
            )
            if switcher.find_cli() is None:
                # Only the desktop app is here; the command line is what can
                # be driven, and both share one store.
                self._log(f"{name}: installing the cc-switch command line")
                switcher.install_cli(switcher_entry)
            self._log(f"{name}: pointing cc-switch at the hub")
            message = switcher.activate(
                base_url=base_url,
                api_key=config["api_key"],
                run_as=run_as,
                model=config.get("model", ""),
            )
            return {"state": "installed", "message": message, "is_active": True}

        if not is_activated and is_active:
            self._publish(
                name, {"state": "deactivating", "message": "", "is_active": True}
            )
            self._log(f"{name}: pointing cc-switch away from the hub")
            message = switcher.deactivate(run_as=run_as, base_url=base_url)
            return {"state": "installed", "message": message, "is_active": False}

        return _ai_status(is_present, is_active)

    def _reconcile_openssh(self, entry: dict, is_enabled: "bool | None") -> dict:
        os_name = self._platform.get("os", "")
        is_running = openssh_status(os_name, entry)
        if not is_enabled:
            # Never switched off from here: taking SSH off a machine the
            # gateway reaches over SSH is a door locked from the inside.
            return {
                "state": "installed" if is_running else "absent",
                "message": "",
                "is_active": False,
            }
        if is_running:
            return {"state": "installed", "message": "", "is_active": False}
        self._log("enabling the SSH server")
        message = enable_openssh(os_name, entry)
        return {"state": "installed", "message": message, "is_active": False}

    def _reconcile_package(
        self, name: str, manifest: dict, entry: dict, is_enabled: "bool | None"
    ) -> dict:
        is_installed = self._verify(manifest)
        if is_enabled is None:
            return {
                "state": "installed" if is_installed else "absent",
                "message": "",
                "is_active": False,
            }
        if not is_enabled:
            # Asking for it to go clears the note that installing it did not
            # confirm, so asking for it again is a fresh attempt rather than
            # the remembered answer.
            self._unconfirmed.discard(name)
            if not is_installed:
                return {"state": "absent", "message": "", "is_active": False}
            removal = entry.get("uninstall", "")
            if not removal:
                # Nothing was ever asked of it, or it cannot be removed
                # safely; either way it stays and says so.
                return {"state": "installed", "message": "", "is_active": False}
            self._publish(
                name, {"state": "removing", "message": "", "is_active": False}
            )
            self._log(f"{name}: removing")
            uninstall_package(removal)
            if self._verify(manifest):
                return {
                    "state": "installed",
                    "message": "removal did not take",
                    "is_active": False,
                }
            return {"state": "absent", "message": "", "is_active": False}
        if is_installed:
            self._unconfirmed.discard(name)
            return {"state": "installed", "message": "", "is_active": False}
        if name in self._unconfirmed:
            # Installed once already, and the verify still says otherwise.
            # Repeating it would fetch the same package on every re-check.
            return {
                "state": "installed",
                "message": "installed; verify did not confirm",
                "is_active": False,
            }

        self._publish(name, {"state": "installing", "message": "", "is_active": False})
        url = entry.get("url", "")
        if not url and entry.get("github_repo"):
            url = resolve_github_asset(
                entry["github_repo"], entry.get("asset_pattern", "")
            )
        if not url:
            return {
                "state": "failed",
                "message": "manifest names no download",
                "is_active": False,
            }

        package_kind = entry.get("package_kind", "deb")
        is_impersonated = bool(manifest.get("download", {}).get("impersonate"))
        with tempfile.TemporaryDirectory() as workdir:
            package = os.path.join(workdir, "package." + package_kind)
            self._log(f"{name}: downloading from {url}")
            download(url, package, is_impersonated=is_impersonated)
            # A CDN that blocks a fetcher answers with a page, not an error, so
            # what arrived is checked before anything is handed to an installer.
            verify_package(package, package_kind)
            self._log(f"{name}: installing")
            install_package(package, package_kind=package_kind, entry=entry)
        if self._verify(manifest):
            self._unconfirmed.discard(name)
            return {"state": "installed", "message": "", "is_active": False}
        self._unconfirmed.add(name)
        return {
            "state": "installed",
            "message": "installed; verify did not confirm",
            "is_active": False,
        }

    def _verify(self, manifest: dict) -> bool:
        """Whether a feature's own check says it is already installed."""
        verify = manifest.get("verify", {})
        command = verify.get(self._platform.get("os", ""), "")
        if not command:
            return False
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, timeout=VERIFY_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0


def _ai_status(is_present: bool, is_active: bool) -> dict:
    """The steady-state report for the AI tools feature."""
    return {
        "state": "installed" if is_present else "absent",
        "message": "pointing at the hub" if is_active else "",
        "is_active": is_active,
    }
