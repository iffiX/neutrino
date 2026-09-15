"""Installing and uninstalling modules the machine's package manager carries.

A system-package module names distro packages, never a download: its
install asks the hub for no bytes and the platform installs the names with
its own tooling. An entry may name ``pre_install`` shell steps, run before the
packages, for a repository the distribution keeps the software in. With no
packages named, a module is present when its own binary is on the path, so
software somebody installed by hand is observed without a recipe.

Not pure: runs the package manager.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import shutil
import subprocess

from neutrino_agent.modules import installers
from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.modules.package import DEB_INSTALLED_STATUS, VERIFY_TIMEOUT_S


def _entry_packages(resolved: dict) -> list:
    """The package names this module's entry asks for."""
    entry = resolved.get("entry") or {}
    return [str(name) for name in entry.get("packages") or []]


def _entry_steps(resolved: dict) -> list:
    """The shell steps this module's entry runs before its packages."""
    entry = resolved.get("entry") or {}
    return [str(step) for step in entry.get("pre_install") or []]


class SystemPackageModuleRunner(ModuleRunner):
    """Installs named distro packages, removes them, and says which it is.

    Attributes:
        binary: The program that says the software is there when the entry
            names no package; empty for a runner with none of its own.
    """

    kind = "system_package"
    binary = ""

    def verify(self, resolved: dict) -> bool:
        """Whether every named package is actually installed.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when all the named packages are there; with none named,
            whether the runner's own binary is on the path.
        """
        packages = _entry_packages(resolved)
        if not packages:
            return bool(self.binary) and shutil.which(self.binary) is not None
        return all(self._is_installed(name) for name in packages)

    def install(self, resolved: dict) -> None:
        """Install the named packages with the machine's own tooling.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If a step or the package manager refuses.
            PlatformUnsupportedError: If this platform installs nothing.
        """
        for step in _entry_steps(resolved):
            self._log(step)
            output = installers.run_shell(step)
            if output.strip():
                self._log(output.strip())
        output = self._platform.install_system_packages(_entry_packages(resolved))
        if output.strip():
            self._log(output.strip())

    def uninstall(self, resolved: dict) -> None:
        """Take the named packages off this machine.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the uninstall refuses.
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
