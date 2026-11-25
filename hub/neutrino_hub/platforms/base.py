"""The contract every platform implements.

The contract names what differs between Linux, macOS and Windows and
nothing else: whether this process may act on the installed hub, running
``nhub`` elevated, the controller of the daemons the hub runs, the one
service on macOS and Windows, opening a page, a lock on a file, the
commands the hub runs of itself and of its agent, the system's own
resolvers, and the machine's accounts as the agent reads them, with the
test an account passes before setup takes it as the default. A new system
is a new class.
"""

import ipaddress
import os
import sys
from pathlib import Path

try:
    import pwd
except ImportError:  # Windows has no account database of this kind.
    pwd = None

from neutrino_hub.exceptions import AccountTestRefusedError
from neutrino_hub.platforms.constants import (
    PLATFORM_AGENT_COMMANDS,
    PLATFORM_CODE_ACCOUNT_NO_LOGIN,
    PLATFORM_CODE_ACCOUNT_UNKNOWN,
    PLATFORM_NO_LOGIN_SHELLS,
    PLATFORM_RESOLVER_FILES,
)


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

    def run_elevated(self, arguments: list) -> bool:
        """Run ``nhub`` with these arguments elevated, asking the person first.

        Args:
            arguments: What follows ``nhub``.

        Returns:
            True when it ran and exited 0; False when nothing here can ask,
            the person declined, or it failed.
        """
        return False

    def process_controller(self):
        """A controller of the daemons the hub runs.

        Returns:
            A :class:`neutrino_hub.system.process_control.ProcessController`.

        Raises:
            NotImplementedError: On a system with no class of its own.
        """
        raise NotImplementedError(f"no process controller for {sys.platform}")

    def make_root_only(self, path) -> None:
        """Leave one file readable and writable by root alone.

        Args:
            path: The file.

        Raises:
            OSError: When its permissions cannot be set.
        """
        os.chmod(path, 0o600)

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

    def system_resolvers(self) -> list:
        """The resolvers the system itself asks, where the hub does not
        address the machine.

        Read from systemd-resolved's list of its upstreams when it runs, else
        from ``/etc/resolv.conf``, which macOS keeps current too.

        Returns:
            The addresses in the order the file lists them, loopback and
            link-local left out; empty when neither file names one.
        """
        for path in PLATFORM_RESOLVER_FILES:
            try:
                text = Path(path).read_text(encoding="utf-8")
            except OSError:
                continue
            addresses = parse_resolv_conf(text)
            if addresses:
                return addresses
        return []

    def human_accounts(self) -> list:
        """The machine's accounts that can log in and have their home, as the agent reads them.

        Returns:
            Account names, sorted; none on a system the hub has no rule for.
        """
        return []

    def runner_account(self) -> str:
        """The account that ran this elevated process: the one sudo names.

        Returns:
            ``SUDO_USER``; empty when it names none or root.
        """
        account = os.environ.get("SUDO_USER", "")
        return "" if account == "root" else account

    def seated_account(self) -> str:
        """The account at the screen.

        Returns:
            Its name; empty when nobody is signed in there or it cannot be
            read.
        """
        return ""

    def test_account(self, account: str, password: str) -> None:
        """Test an account before setup takes it as the default.

        On Linux and macOS the account's login shell is neither ``nologin``
        nor ``false`` and its home exists; the password is not read.

        Args:
            account: The account.
            password: Its password, read on Windows alone.

        Raises:
            AccountTestRefusedError: ``account_unknown {account}`` for an
                account the system does not have, ``account_no_login
                {account}`` for one that cannot log in or has no home.
        """
        del password
        if pwd is None:
            raise AccountTestRefusedError(
                PLATFORM_CODE_ACCOUNT_UNKNOWN, {"account": account}
            )
        try:
            entry = pwd.getpwnam(account)
        except KeyError as error:
            raise AccountTestRefusedError(
                PLATFORM_CODE_ACCOUNT_UNKNOWN, {"account": account}
            ) from error
        if not is_login_account(entry.pw_shell, entry.pw_dir):
            raise AccountTestRefusedError(
                PLATFORM_CODE_ACCOUNT_NO_LOGIN, {"account": account}
            )


def is_login_account(shell: str, home: str) -> bool:
    """Whether an account can log in: a login shell that is neither ``nologin`` nor ``false``, and a home that exists.

    The agent's rule, copied (agent/accounts.md, "The default account").

    Args:
        shell: The account's login shell, by its path.
        home: The account's home.

    Returns:
        True when both hold.
    """
    name = os.path.basename(str(shell or ""))
    if not name or name in PLATFORM_NO_LOGIN_SHELLS:
        return False
    return bool(home) and os.path.isdir(home)


def parse_resolv_conf(text: str) -> list:
    """The resolvers a ``resolv.conf`` names.

    Args:
        text: The file.

    Returns:
        Each ``nameserver`` address in order, once; a loopback stub, a
        link-local address and a line that is not an address are left out.
    """
    addresses = []
    for line in text.splitlines():
        words = line.split()
        if len(words) < 2 or words[0] != "nameserver":
            continue
        try:
            address = ipaddress.ip_address(words[1])
        except ValueError:
            continue
        if address.is_loopback or address.is_link_local:
            continue
        if str(address) not in addresses:
            addresses.append(str(address))
    return addresses
