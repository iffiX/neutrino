"""The Windows platform: the capabilities that exist, the rest refused.

The SSH server rides PowerShell's ``Add-WindowsCapability``. Windows has no
general way to become another user without their password, so account work
is file work: the agent writes into the account's profile, where inherited
ACLs make the files the account's own. Running a process as an account,
enumerating accounts, metrics, power, share attach and service control
answer ``unsupported_platform`` until the platform is filled in.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from neutrino_agent.modules import installers
from neutrino_agent.constants import AGENT_COMMAND_TIMEOUT_S
from neutrino_agent.platforms.base import AgentPlatform

WINDOWS_PROFILES_DIR = "C:\\Users"
WINDOWS_OPENSSH_CAPABILITY = "OpenSSH.Server~~~~0.0.1.0"


class WindowsPlatform(AgentPlatform):
    """Windows behind the platform contract."""

    os_name = "windows"
    capabilities = frozenset({"account_files", "packages", "openssh"})

    def account_home(self, account: str) -> str:
        """One account's profile directory.

        Args:
            account: The account.

        Returns:
            The absolute profile path.
        """
        return str(Path(WINDOWS_PROFILES_DIR) / account)

    def read_account_file(self, *, account: str, relative: str) -> str:
        """Read a file below an account's profile.

        Args:
            account: The account; empty reads below the agent's own home.
            relative: Path below the profile.

        Returns:
            The file's text, empty when it is absent or unreadable.
        """
        if not relative:
            return ""
        path = self._profile_file(account, relative)
        try:
            return path.read_text(encoding="utf-8") if path.is_file() else ""
        except OSError:
            return ""

    def read_account_file_mode(self, *, account: str, relative: str) -> str:
        """NTFS carries ACLs, not POSIX modes; there is nothing to report.

        Args:
            account: The account.
            relative: Path below the profile.

        Returns:
            Empty.
        """
        return ""

    def write_account_file(
        self, *, account: str, relative: str, text: str, mode: str = ""
    ) -> None:
        """Write a file below an account's profile, directly.

        The profile's inherited ACLs make the file the account's own.

        Args:
            account: The account; empty writes below the agent's own home.
            relative: Path below the profile.
            text: What to write.
            mode: Ignored; NTFS carries ACLs, not POSIX modes.
        """
        path = self._profile_file(account, relative)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            return

    def remove_account_file(self, *, account: str, relative: str) -> None:
        """Delete a file below an account's profile, absent being fine.

        Args:
            account: The account; empty removes below the agent's own home.
            relative: Path below the profile.
        """
        if not relative:
            return
        path = self._profile_file(account, relative)
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            return

    def install_package(self, path: str, *, package_kind: str, entry: dict) -> None:
        """Install one downloaded package.

        Args:
            path: The downloaded file.
            package_kind: The package kind.
            entry: The manifest's platform entry.

        Raises:
            InstallError: If the installer fails or the kind is unknown.
        """
        installers.install_package(path, package_kind=package_kind, entry=entry)

    def uninstall_package(self, command: str) -> None:
        """Remove a package the way its manifest says to.

        Args:
            command: The manifest's removal command.

        Raises:
            InstallError: If the removal fails.
        """
        installers.uninstall_package(command)

    def install_openssh(self, entry: dict) -> None:
        """Install the SSH server capability and start ``sshd``.

        Args:
            entry: The manifest's platform entry, naming the capability.

        Raises:
            InstallError: If PowerShell refuses.
        """
        capability = entry.get("capability", WINDOWS_OPENSSH_CAPABILITY)
        installers.run_checked(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Add-WindowsCapability -Online -Name {capability}; "
                "Set-Service -Name sshd -StartupType Automatic; "
                "Start-Service sshd",
            ],
            timeout_s=installers.INSTALL_TIMEOUT_S,
        )

    def uninstall_openssh(self, entry: dict) -> None:
        """Stop ``sshd`` and remove the SSH server capability.

        Args:
            entry: The manifest's platform entry, naming the capability.

        Raises:
            InstallError: If PowerShell refuses.
        """
        capability = entry.get("capability", WINDOWS_OPENSSH_CAPABILITY)
        installers.run_checked(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Stop-Service sshd -ErrorAction SilentlyContinue; "
                f"Remove-WindowsCapability -Online -Name {capability}",
            ],
            timeout_s=installers.INSTALL_TIMEOUT_S,
        )

    def read_openssh_status(self, entry: dict) -> bool:
        """Whether ``sshd`` is installed and running.

        Args:
            entry: The manifest's platform entry.

        Returns:
            True when the service reports Running.
        """
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-Service sshd -ErrorAction SilentlyContinue).Status",
                ],
                capture_output=True,
                text=True,
                timeout=AGENT_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return "Running" in result.stdout

    def _profile_file(self, account: str, relative: str) -> Path:
        """The path one profile file lives at.

        Args:
            account: The account; empty means the agent's own home.
            relative: Path below the profile.

        Returns:
            The absolute path.
        """
        if not account:
            return Path(os.path.expanduser("~")) / relative
        return Path(self.account_home(account)) / relative
