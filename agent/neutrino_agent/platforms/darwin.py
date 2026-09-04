"""The macOS platform: the capabilities that exist, the rest refused.

Remote login rides ``systemsetup``. Stepping down to an account is ``su``,
macOS's own step-down, for the same reason Linux uses ``runuser`` and never
``sudo``. Metrics, power, share attach and service control answer
``unsupported_platform`` until the platform is filled in.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import shlex
import subprocess

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_agent import installers
from neutrino_agent.constants import (
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_STEP_DOWN_TIMEOUT_S,
)
from neutrino_agent.platforms.base import AgentPlatform

# Accounts below this uid are the system's, not people's.
DARWIN_HUMAN_UID_FLOOR = 501
DARWIN_NO_LOGIN_SHELLS = ("nologin", "false")


class DarwinPlatform(AgentPlatform):
    """macOS behind the platform contract."""

    os_name = "darwin"
    capabilities = frozenset(
        {"accounts", "account_files", "run_as", "packages", "openssh"}
    )

    def human_accounts(self) -> list:
        """The accounts that are people: uid at the floor or above, a shell
        someone can log in with, and a home directory that exists.

        Returns:
            Account names, sorted.
        """
        if pwd is None:
            return []
        accounts = []
        for entry in pwd.getpwall():
            if entry.pw_uid < DARWIN_HUMAN_UID_FLOOR:
                continue
            shell = entry.pw_shell or ""
            if not shell or os.path.basename(shell) in DARWIN_NO_LOGIN_SHELLS:
                continue
            if not entry.pw_dir or not os.path.isdir(entry.pw_dir):
                continue
            accounts.append(entry.pw_name)
        return sorted(accounts)

    def account_home(self, account: str) -> str:
        """One account's home directory, from the account database.

        Args:
            account: The account.

        Returns:
            The absolute home path.

        Raises:
            KeyError: When the account database has no such account.
        """
        if pwd is None:
            raise KeyError(account)
        return pwd.getpwnam(account).pw_dir

    def run_as_account(
        self,
        account: str,
        argv: list,
        *,
        stdin: str = "",
        timeout_s: int = AGENT_STEP_DOWN_TIMEOUT_S,
    ) -> "subprocess.CompletedProcess":
        """Run a process as an account, through ``su`` when root.

        The login shell (``su -``) gives the child the account's own
        environment, home included.

        Args:
            account: The account; empty runs as the agent itself.
            argv: Argument vector.
            stdin: Sent to the process's standard input.
            timeout_s: How long to wait.

        Returns:
            The completed process, with text output captured.
        """
        command = list(argv)
        if account and os.geteuid() == 0:
            command = ["su", "-", account, "-c", shlex.join(argv)]
        return subprocess.run(
            command, input=stdin, capture_output=True, text=True, timeout=timeout_s
        )

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

    def enable_openssh(self, entry: dict) -> None:
        """Switch remote login on.

        Args:
            entry: The manifest's platform entry.

        Raises:
            InstallError: If ``systemsetup`` refuses.
        """
        installers.run_checked(["systemsetup", "-setremotelogin", "on"])

    def read_openssh_status(self, entry: dict) -> bool:
        """Whether remote login is on.

        Args:
            entry: The manifest's platform entry.

        Returns:
            True when ``systemsetup`` reports it on.
        """
        try:
            result = subprocess.run(
                ["systemsetup", "-getremotelogin"],
                capture_output=True,
                text=True,
                timeout=AGENT_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return "On" in result.stdout
