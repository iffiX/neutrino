"""Reconciling a downloaded-package function.

Installed software is not removed just because a function was never switched
on — "not switched on" is not "take it off this machine", and software that
was here before the agent was must survive the agent arriving. Removal
happens only when the hub says off and the manifest names a removal command.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import subprocess
import tempfile

from neutrino_agent.downloader import download, resolve_github_asset, verify_package
from neutrino_agent.functions.base import FunctionReconciler, clean_status

VERIFY_TIMEOUT_S = 30


class PackageFunctionReconciler(FunctionReconciler):
    """Installs, verifies and removes one downloadable package."""

    kind = "package"

    def __init__(self, *, platform, log=print, publish=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        # Functions whose install ran and whose verify did not confirm it.
        # Without this the idle re-check finds them absent a minute later and
        # installs them again, for ever: a package whose verify command names
        # the wrong path is re-downloaded every minute until somebody notices
        # the traffic.
        self._unconfirmed: set = set()

    def reconcile(
        self, *, name: str, manifest: dict, entry: dict, wanted: "dict | None"
    ) -> dict:
        """Bring one package function to its desired state, or just report it.

        Args:
            name: The function name.
            manifest: Its manifest.
            entry: The manifest's entry for this platform.
            wanted: The hub's decision, or None to only inspect.

        Returns:
            ``{"state", "code", "params", "is_active"}``.
        """
        is_enabled = None if wanted is None else bool(wanted.get("is_enabled"))
        is_installed = self._verify(manifest)
        if is_enabled is None:
            return clean_status("installed" if is_installed else "absent")
        if not is_enabled:
            return self._remove(name, manifest, entry, is_installed)
        if is_installed:
            self._unconfirmed.discard(name)
            return clean_status("installed")
        if name in self._unconfirmed:
            # Installed once already, and the verify still says otherwise.
            # Repeating it would fetch the same package on every re-check.
            return self._unconfirmed_status()
        return self._install(name, manifest, entry)

    def _remove(
        self, name: str, manifest: dict, entry: dict, is_installed: bool
    ) -> dict:
        # Asking for it to go clears the note that installing it did not
        # confirm, so asking for it again is a fresh attempt rather than
        # the remembered answer.
        self._unconfirmed.discard(name)
        if not is_installed:
            return clean_status("absent")
        removal = entry.get("uninstall", "")
        if not removal:
            # Nothing was ever asked of it, or it cannot be removed
            # safely; either way it stays and says so.
            return clean_status("installed")
        self._publish(name, clean_status("removing"))
        self._log(f"{name}: removing")
        self._platform.uninstall_package(removal)
        if self._verify(manifest):
            return {
                "state": "installed",
                "code": "remove_unconfirmed",
                "params": {},
                "is_active": False,
            }
        return clean_status("absent")

    def _install(self, name: str, manifest: dict, entry: dict) -> dict:
        self._publish(name, clean_status("installing"))
        url = entry.get("url", "")
        if not url and entry.get("github_repo"):
            url = resolve_github_asset(
                entry["github_repo"], entry.get("asset_pattern", "")
            )
        if not url:
            return {
                "state": "failed",
                "code": "no_download_named",
                "params": {},
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
            self._platform.install_package(
                package, package_kind=package_kind, entry=entry
            )
        if self._verify(manifest):
            self._unconfirmed.discard(name)
            return clean_status("installed")
        self._unconfirmed.add(name)
        return self._unconfirmed_status()

    def _unconfirmed_status(self) -> dict:
        return {
            "state": "installed",
            "code": "verify_unconfirmed",
            "params": {},
            "is_active": False,
        }

    def _verify(self, manifest: dict) -> bool:
        """Whether a function's own check says it is already installed."""
        verify = manifest.get("verify", {})
        command = verify.get(self._platform.os_name, "")
        if not command:
            return False
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, timeout=VERIFY_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0
