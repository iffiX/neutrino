"""The contract every platform implements.

The contract names intents, not mechanisms: enumerate human accounts;
resolve an account's home; run a process as an account; control the agent's
own service; power actions; read host metrics; install and remove a package
of a kind. A new platform is a new class, and nothing above this seam
changes.

Each platform advertises the capabilities it has in ``capabilities``.
Invoking one it does not have raises :class:`PlatformUnsupportedError`, whose
``code`` every surface reports as ``{"code": "unsupported_platform"}``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import subprocess

from neutrino_agent.constants import AGENT_DATA_DIR_POSIX, AGENT_STEP_DOWN_TIMEOUT_S
from neutrino_agent.exceptions import PlatformUnsupportedError


class AgentPlatform:
    """What the agent asks of the operating system, behind one seam.

    The base class is also the honest answer for a platform the agent does
    not know: it advertises nothing and refuses every capability.
    """

    os_name = ""
    capabilities: frozenset = frozenset()

    def agent_data_dir(self) -> str:
        """Where the agent keeps its own state on this platform.

        The store and the credentials directory both live under this root.

        Returns:
            The absolute directory path.
        """
        return AGENT_DATA_DIR_POSIX

    def human_accounts(self) -> list:
        """The accounts this platform judges to be people.

        Root and system accounts are never listed; the floor that separates
        them is each platform's own.

        Returns:
            Account names, sorted.

        Raises:
            PlatformUnsupportedError: When the platform cannot enumerate.
        """
        raise PlatformUnsupportedError("cannot enumerate accounts here")

    def account_home(self, account: str) -> str:
        """One account's home directory, from the account database.

        Never read from ``$HOME``: the agent runs as root, so the
        environment names root's home, not the account's.

        Args:
            account: The account.

        Returns:
            The absolute home path.

        Raises:
            PlatformUnsupportedError: When the platform cannot answer.
            KeyError: When the account database has no such account.
        """
        raise PlatformUnsupportedError("cannot resolve an account home here")

    def control_socket_path(self) -> str:
        """Where the agent's control socket lives on this platform.

        Returns:
            The absolute socket path.

        Raises:
            PlatformUnsupportedError: When the platform has no control socket.
        """
        raise PlatformUnsupportedError("no control socket here")

    def run_as_account(
        self,
        account: str,
        argv: list,
        *,
        stdin: str = "",
        timeout_s: int = AGENT_STEP_DOWN_TIMEOUT_S,
    ) -> "subprocess.CompletedProcess":
        """Run a process as an account.

        Args:
            account: The account; empty runs as the agent itself.
            argv: Argument vector.
            stdin: Sent to the process's standard input.
            timeout_s: How long to wait.

        Returns:
            The completed process, with text output captured.

        Raises:
            PlatformUnsupportedError: When the platform cannot step down.
        """
        raise PlatformUnsupportedError("cannot run as another account here")

    def read_agent_service_state(self) -> str:
        """The state of the agent's own service.

        Returns:
            ``running``, an init-system state word, or ``unknown``.

        Raises:
            PlatformUnsupportedError: When there is no service to ask about.
        """
        raise PlatformUnsupportedError("no agent service to read here")

    def start_agent_service(self) -> None:
        """Enable and start the agent's own service. Best-effort.

        Raises:
            PlatformUnsupportedError: When there is no service to start.
        """
        raise PlatformUnsupportedError("no agent service to start here")

    def agent_service_start_hint(self) -> str:
        """The command a person runs to start the agent's own service.

        Each platform words its own mechanism; the CLI wraps this in the
        advice sentence, so no surface prints another platform's command.

        Returns:
            A one-line command, empty where the platform has no service.
        """
        return ""

    def power(self, action: str) -> "tuple[int, str]":
        """Run one power action.

        Args:
            action: ``reboot`` or ``poweroff``.

        Returns:
            The exit code and combined output.

        Raises:
            PlatformUnsupportedError: When the platform has no power actions.
        """
        raise PlatformUnsupportedError("no power actions here")

    def read_host_metrics(self):
        """One sample of the machine's health.

        Returns:
            A :class:`~neutrino_agent.core.metrics.HostMetrics`.

        Raises:
            PlatformUnsupportedError: When the platform cannot be sampled.
        """
        raise PlatformUnsupportedError("no metrics here")

    def install_package(self, path: str, *, package_kind: str, entry: dict) -> None:
        """Install one downloaded package of a kind.

        Args:
            path: The downloaded file.
            package_kind: ``deb`` or ``rpm``.
            entry: The manifest's platform entry.

        Raises:
            PlatformUnsupportedError: When the platform installs nothing.
        """
        raise PlatformUnsupportedError("cannot install packages here")

    def uninstall_package(self, command: str) -> None:
        """Remove a package the way its manifest says to.

        Args:
            command: The manifest's removal command for this platform.

        Raises:
            PlatformUnsupportedError: When the platform removes nothing.
        """
        raise PlatformUnsupportedError("cannot remove packages here")

    def install_system_packages(self, names: list) -> str:
        """Install packages by name with the machine's own package manager.

        Args:
            names: The package names.

        Returns:
            The installers' combined output.

        Raises:
            InstallError: If the package manager refuses.
            PlatformUnsupportedError: When the platform has no package
                manager to ask.
        """
        raise PlatformUnsupportedError("cannot install system packages here")

    def remove_system_packages(self, names: list) -> str:
        """Remove packages by name with the machine's own package manager.

        Args:
            names: The package names.

        Returns:
            The removal's combined output.

        Raises:
            InstallError: If the package manager refuses.
            PlatformUnsupportedError: When the platform has no package
                manager to ask.
        """
        raise PlatformUnsupportedError("cannot remove system packages here")
