"""Installing, removing and verifying one downloaded-package module.

Execution, and nothing else. This machine does not decide when to install,
does not fetch anything from the internet, and holds no memory of how the
last attempt went — the hub owns all three, and an outpost that kept its own
policy would be a second one to disagree with it.

What it is given is a resolved module: the hub already read the manifest and
picked the entry for this platform, so nothing here searches a platform
table. What it answers with is what is true on this machine now.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import subprocess

from neutrino_agent.modules.base import ModuleRunner

VERIFY_TIMEOUT_S = 30

DEB_INSTALLED_STATUS = "install ok installed"


class PackageModuleRunner(ModuleRunner):
    """Puts one package on this machine, takes it off, and says which it is."""

    kind = "package"

    def verify(self, resolved: dict) -> bool:
        """Whether the package is actually installed.

        A deb is judged by dpkg's own status database: only
        ``install ok installed`` counts, so the ``rc`` state a plain remove
        leaves behind reads as absent. Other kinds run the verify command
        the hub resolved for this platform.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when the package is installed.
        """
        entry = resolved.get("entry") or {}
        if entry.get("package_kind") == "deb":
            return self._verify_deb(str(resolved.get("package", "")))
        command = str(resolved.get("verify", ""))
        if not command:
            return False
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, timeout=VERIFY_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def install(self, resolved: dict, package_path: str) -> None:
        """Install the bytes the hub handed down.

        Args:
            resolved: The module as the hub resolved it.
            package_path: The package on local disk.

        Raises:
            InstallError: If the platform's installer refuses.
            PlatformUnsupportedError: If this platform installs nothing.
        """
        entry = resolved.get("entry") or {}
        self._platform.install_package(
            package_path,
            package_kind=str(entry.get("package_kind", "")),
            entry=entry,
        )

    def uninstall(self, resolved: dict) -> None:
        """Take the package off this machine.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the uninstall refuses.
            PlatformUnsupportedError: If this platform removes nothing.
        """
        command = self._uninstall_command(resolved)
        if not command:
            # The module names no way off this platform; saying so beats
            # guessing a command at something installed as root.
            return
        self._platform.uninstall_package(command)

    def _uninstall_command(self, resolved: dict) -> str:
        """The command that takes this package off the machine.

        A deb is purged by name: ``apt-get remove`` leaves the ``rc`` state
        behind, whose config-files remnant is what made an uninstall look like
        it never took. Other kinds keep the manifest's own command.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            The shell command, empty when the module names none.
        """
        entry = resolved.get("entry") or {}
        if entry.get("package_kind") == "deb":
            package = str(resolved.get("package", ""))
            if package:
                return f"apt-get purge -y {package}"
        return str(entry.get("uninstall", ""))

    @staticmethod
    def _verify_deb(package: str) -> bool:
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
