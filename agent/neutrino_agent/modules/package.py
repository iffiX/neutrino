"""Reconciling a downloaded-package module.

Installed software is not removed just because a module was never switched
on — "not switched on" is not "take it off this machine", and software that
was here before the agent was must survive the agent arriving. Removal
happens only when the hub says off, and it purges on Debian so a half-kept
``rc`` state cannot read as still installed.

An attempt whose verify does not confirm it latches, in both directions: an
install that cannot be confirmed is not re-downloaded every idle re-check,
and a removal that did not take is not re-run every minute either. Asking
for the opposite clears the latch, so a person's next decision is a fresh
attempt.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import subprocess
import tempfile

from neutrino_agent.modules.base import ModuleReconciler, clean_status
from neutrino_agent.modules.downloader import (
    download,
    resolve_github_asset,
    verify_package,
)

VERIFY_TIMEOUT_S = 30

DEB_INSTALLED_STATUS = "install ok installed"


class PackageModuleReconciler(ModuleReconciler):
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
        # Modules whose install or removal ran and whose verify did not
        # confirm it. Without these the idle re-check repeats the same
        # attempt every minute for ever.
        self._install_unconfirmed: set = set()
        self._remove_unconfirmed: set = set()

    def reconcile(
        self, *, name: str, manifest: dict, entry: dict, wanted: "dict | None"
    ) -> dict:
        """Bring one package module to its desired state, or just report it.

        Args:
            name: The module name.
            manifest: Its manifest.
            entry: The manifest's entry for this platform.
            wanted: The hub's decision, or None to only inspect.

        Returns:
            ``{"state", "code", "params", "is_active"}``.
        """
        is_enabled = None if wanted is None else bool(wanted.get("is_enabled"))
        is_installed = self._verify(manifest, entry)
        if is_enabled is None:
            return clean_status("installed" if is_installed else "absent")
        if not is_enabled:
            return self._remove(name, manifest, entry, is_installed)
        self._remove_unconfirmed.discard(name)
        if is_installed:
            self._install_unconfirmed.discard(name)
            return clean_status("installed")
        if name in self._install_unconfirmed:
            return self._install_unconfirmed_status()
        return self._install(name, manifest, entry)

    def _remove(
        self, name: str, manifest: dict, entry: dict, is_installed: bool
    ) -> dict:
        self._install_unconfirmed.discard(name)
        if not is_installed:
            self._remove_unconfirmed.discard(name)
            return clean_status("absent")
        if name in self._remove_unconfirmed:
            return self._remove_unconfirmed_status()
        removal = self._removal_command(manifest, entry)
        if not removal:
            # Nothing was ever asked of it, or it cannot be removed
            # safely; either way it stays and says so.
            return clean_status("installed")
        self._publish(name, clean_status("removing"))
        self._log(f"{name}: removing")
        self._platform.uninstall_package(removal)
        if self._verify(manifest, entry):
            self._remove_unconfirmed.add(name)
            return self._remove_unconfirmed_status()
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
        if self._verify(manifest, entry):
            self._install_unconfirmed.discard(name)
            return clean_status("installed")
        self._install_unconfirmed.add(name)
        return self._install_unconfirmed_status()

    def _install_unconfirmed_status(self) -> dict:
        return {
            "state": "installed",
            "code": "verify_unconfirmed",
            "params": {},
            "is_active": False,
        }

    def _remove_unconfirmed_status(self) -> dict:
        return {
            "state": "installed",
            "code": "remove_unconfirmed",
            "params": {},
            "is_active": False,
        }

    def _removal_command(self, manifest: dict, entry: dict) -> str:
        """The command that takes this package off the machine.

        A deb is purged by name: ``apt-get remove`` leaves the ``rc`` state
        behind, whose config-files remnant is what made a removal look like
        it never took. Other kinds keep the manifest's own command.

        Args:
            manifest: The module's manifest.
            entry: The manifest's entry for this platform.

        Returns:
            The shell command, empty when the module names none.
        """
        if entry.get("package_kind") == "deb":
            package = self._package_name(manifest, entry)
            if package:
                return f"apt-get purge -y {package}"
        return entry.get("uninstall", "")

    def _verify(self, manifest: dict, entry: dict) -> bool:
        """Whether the package is actually installed.

        A deb is judged by dpkg's own status database: only
        ``install ok installed`` counts, so the ``rc`` state a plain remove
        leaves behind reads as absent. Other kinds run the manifest's own
        verify command.

        Args:
            manifest: The module's manifest.
            entry: The manifest's entry for this platform.

        Returns:
            True when the package is installed.
        """
        if entry.get("package_kind") == "deb":
            return self._verify_deb(self._package_name(manifest, entry))
        command = manifest.get("verify", {}).get(self._platform.os_name, "")
        if not command:
            return False
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, timeout=VERIFY_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def _verify_deb(self, package: str) -> bool:
        if not package:
            return False
        try:
            result = subprocess.run(
                ["dpkg-query", "-W", "-f=${Status}", package],
                capture_output=True,
                text=True,
                timeout=VERIFY_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and result.stdout.strip() == DEB_INSTALLED_STATUS

    @staticmethod
    def _package_name(manifest: dict, entry: dict) -> str:
        return str(entry.get("package", "") or manifest.get("name", ""))
