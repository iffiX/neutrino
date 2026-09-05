"""Installing and uninstalling modules the machine's package manager carries.

A system-package module names distro packages, never a download: its orders
skip the hub's cache and the platform installs the names with its own
tooling. An entry with no packages means the platform carries the capability
natively — nothing to install, and the row reads as built in.

Not pure: runs the package manager.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import shutil
import subprocess

from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.modules.package import DEB_INSTALLED_STATUS, VERIFY_TIMEOUT_S


def _entry_packages(resolved: dict) -> list:
    """The package names this module's entry asks for."""
    entry = resolved.get("entry") or {}
    return [str(name) for name in entry.get("packages") or []]


class SystemPackageModuleRunner(ModuleRunner):
    """Installs named distro packages, removes them, and says which it is."""

    kind = "system_package"

    def is_native(self, resolved: dict) -> bool:
        """Whether this platform carries the capability with no package.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when the entry names nothing to install.
        """
        return not _entry_packages(resolved)

    def verify(self, resolved: dict) -> bool:
        """Whether every named package is actually installed.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when all the packages are there, or none are named.
        """
        return all(self._is_installed(name) for name in _entry_packages(resolved))

    def install(self, resolved: dict) -> None:
        """Install the named packages with the machine's own tooling.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the package manager refuses.
            PlatformUnsupportedError: If this platform installs nothing.
        """
        output = self._platform.install_system_packages(_entry_packages(resolved))
        if output.strip():
            self._log(output.strip())

    def remove(self, resolved: dict) -> None:
        """Take the named packages off this machine.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the removal refuses.
            PlatformUnsupportedError: If this platform removes nothing.
        """
        output = self._platform.remove_system_packages(_entry_packages(resolved))
        if output.strip():
            self._log(output.strip())

    @staticmethod
    def _is_installed(name: str) -> bool:
        """Ask the machine's own package database about one name."""
        if shutil.which("dpkg-query"):
            command = ["dpkg-query", "-W", "-f=${Status}", name]
            expected = DEB_INSTALLED_STATUS
        elif shutil.which("rpm"):
            command = ["rpm", "-q", name]
            expected = ""
        else:
            return False
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=VERIFY_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode != 0:
            return False
        return not expected or result.stdout.strip() == expected
