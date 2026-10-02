"""The contract every platform implements.

The contract names what differs between Linux, macOS and Windows and
nothing else: whether this process may act on the installed hub, the
controller of the daemons the hub runs, the one service on macOS and
Windows, opening a page, a lock on a file, and the commands the hub runs
of itself and of its agent. A new system is a new class.
"""

import os
import sys

from neutrino_hub.platforms.constants import PLATFORM_AGENT_COMMANDS


def is_compiled() -> bool:
    """Whether this hub is the one binary Nuitka compiled.

    Returns:
        True inside a compiled ``nhub``.
    """
    return "__compiled__" in globals()


class HubPlatform:
    """What the hub asks of the operating system, behind one seam.

    The base answers as a Unix system does where the answer is shared, and
    refuses what only a system class can say.
    """

    os_name = ""
    # Who a command that acts on the installed hub must run as.
    elevation_word = "root"

    def is_elevated(self) -> bool:
        """Whether this process may act on the installed hub.

        Returns:
            True when the effective user is root.
        """
        return os.geteuid() == 0

    def elevation_hint(self, arguments: str) -> str:
        """The command a person runs to repeat this one with the rights it needs.

        Args:
            arguments: What followed ``nhub`` on the command line.

        Returns:
            One command line.
        """
        return f"sudo nhub {arguments}".rstrip()

    def process_controller(self):
        """A controller of the daemons the hub runs.

        Returns:
            A :class:`neutrino_hub.system.process_control.ProcessController`.

        Raises:
            NotImplementedError: On a system with no class of its own.
        """
        raise NotImplementedError(f"no process controller for {sys.platform}")

    def open_browser(self, url: str) -> bool:
        """Open a page in this machine's browser.

        Args:
            url: The page.

        Returns:
            True when an opener was started; False when nothing here can
            open a page.
        """
        return False

    def try_lock(self, descriptor: int) -> bool:
        """Take an exclusive lock on an open file without waiting.

        Args:
            descriptor: The open file.

        Returns:
            True when the lock is held now; False when another holds it.

        Raises:
            OSError: When the file cannot be locked at all.
        """
        import fcntl

        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def unlock(self, descriptor: int) -> None:
        """Let go of a lock :meth:`try_lock` took.

        Args:
            descriptor: The open file.

        Raises:
            OSError: When the lock cannot be released.
        """
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)

    def service_state(self) -> str:
        """What the service manager says about the hub's one service.

        Returns:
            ``running``, ``stopped``, another state word, or ``unknown``.

        Raises:
            NotImplementedError: Where the hub is a set of units instead.
        """
        raise NotImplementedError("the hub runs as a set of units here")

    def start_service(self) -> None:
        """Start the hub's one service.

        Raises:
            NotImplementedError: Where the hub is a set of units instead.
        """
        raise NotImplementedError("the hub runs as a set of units here")

    def stop_service(self) -> None:
        """Stop the hub's one service, and every child with it.

        Raises:
            NotImplementedError: Where the hub is a set of units instead.
        """
        raise NotImplementedError("the hub runs as a set of units here")

    def restart_service(self) -> None:
        """Stop the hub's one service and start it again.

        Raises:
            NotImplementedError: Where the hub is a set of units instead.
        """
        raise NotImplementedError("the hub runs as a set of units here")

    def log_hint(self, name: str, unit: str) -> str:
        """Where a person reads one daemon's log.

        Args:
            name: The daemon's own name.
            unit: The systemd unit it runs as on Linux.

        Returns:
            A command or a path.
        """
        from neutrino_hub.utils.constants import UTILS_LOG_ROOT

        return str(UTILS_LOG_ROOT / f"{name}.log")

    def hub_command(self, *arguments: str) -> list:
        """The command line that runs ``nhub`` with these arguments.

        Args:
            *arguments: What follows ``nhub``.

        Returns:
            The argument vector: this interpreter and the entry module, or
            the compiled binary itself.
        """
        if is_compiled():
            return [sys.executable, *arguments]
        return [sys.executable, "-m", "neutrino_hub.cli.entry", *arguments]

    def agent_command(self) -> str:
        """The agent's command once its package is installed.

        Returns:
            A command name or an absolute path.
        """
        return PLATFORM_AGENT_COMMANDS.get(self.os_name, "nagent")

    def agent_install_command(self, package: str) -> list:
        """The command that installs the agent's package file.

        Args:
            package: The package file.

        Returns:
            The argument vector.

        Raises:
            NotImplementedError: Where the package manager installs it.
        """
        raise NotImplementedError("the package manager installs the agent here")

    def netbird_daemon_address(self) -> str:
        """The address the hub's own NetBird daemon answers on.

        Returns:
            A ``--daemon-addr`` value; empty for NetBird's own default.
        """
        return ""
