"""The contract every platform implements.

The contract names intents, not mechanisms: enumerate human accounts;
resolve an account's home; run a process as an account, or a step of the
agent's own code as one; control the agent's
own service; power actions; read host metrics; read the network interfaces;
read the machine id; install and remove a package of a kind; drive the SMB
server the system carries; unpack the hub's software; find the agent's own
log; end a process where the system has no signals; take away what the
agent's modules added when the agent itself is removed; read the addresses
the machine's containers reach the machine at, and give the system's
firewall the rules of the agent's relays there. A new platform is a new
class, and nothing above this seam changes.

Each platform advertises the capabilities it has in ``capabilities``.
Invoking one it does not have raises :class:`PlatformUnsupportedError`, whose
``code`` every surface reports as ``{"code": "unsupported_platform"}``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from neutrino_agent.constants import (
    AGENT_ADDED_FOREIGN_WORDS,
    AGENT_BIN_DIR_LINUX,
    AGENT_DATA_DIR_POSIX,
    AGENT_STEP_DOWN_TIMEOUT_S,
    AGENT_VAR_DIR,
)
from neutrino_agent.exceptions import PlatformUnsupportedError

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

# What ends the word after a name's prefix.
ADDED_NAME_WORD_END = re.compile(r"[_.@-]")


def login_shell_of(account: str) -> str:
    """An account's login shell from the account database.

    Args:
        account: The account.

    Returns:
        The shell's path; empty where there is no account database, as on
        Windows, or no such account.
    """
    if pwd is None:
        return ""
    try:
        return str(pwd.getpwnam(account).pw_shell or "")
    except KeyError:
        return ""


@dataclass(frozen=True)
class RelayAddress:
    """One address the machine's containers reach the machine at.

    Attributes:
        interface: The interface that holds it: a Podman bridge on Linux,
            WSL's vEthernet adapter on Windows.
        index: The interface's index, which a relay bound to the interface
            stays on; 0 where no relay is bound to an interface.
        address: The interface's IPv4 address, where the relays listen.
        prefix: The length of the interface's network; 0 where it is not
            read.
    """

    interface: str
    index: int
    address: str
    prefix: int


@dataclass(frozen=True)
class RelayRule:
    """The firewall rule one relay needs: its interface, its address and its port.

    Attributes:
        interface: The interface the relay listens on.
        address: The relay's address.
        prefix: The length of the interface's network; 0 where it is not
            read.
        port: The relayed port, over TCP.
    """

    interface: str
    address: str
    prefix: int
    port: int


def is_added_name(name: str, prefix: str) -> bool:
    """Whether a unit, job, task or rule is one the agent's modules added.

    Such a name starts with ``prefix`` and its next word is none of
    :data:`AGENT_ADDED_FOREIGN_WORDS`, which name the hub, the client and the
    agent's own service.

    Args:
        name: The unit, label, task or rule name, compared without case.
        prefix: ``neutrino_`` or ``com.neutrino.``.

    Returns:
        Whether removing the agent takes it away.
    """
    folded = name.lower()
    if not folded.startswith(prefix):
        return False
    word = ADDED_NAME_WORD_END.split(folded[len(prefix) :], maxsplit=1)[0]
    return bool(word) and word not in AGENT_ADDED_FOREIGN_WORDS


class AgentPlatform:
    """What the agent asks of the operating system, behind one seam.

    The base class is also the honest answer for a platform the agent does
    not know: it advertises nothing and refuses every capability.

    Attributes:
        powershell_host: Windows: the agent's PowerShell host; None
            elsewhere.
        process_table: Windows: the machine's processes, read and ended as
            :class:`WindowsProcessTable` does; None elsewhere.
    """

    os_name = ""
    capabilities: frozenset = frozenset()
    powershell_host = None
    process_table = None

    def agent_data_dir(self) -> str:
        """Where the agent keeps what the hub decided on this platform.

        The store, the desired state and the credentials directory live
        under this root.

        Returns:
            The absolute directory path.
        """
        return AGENT_DATA_DIR_POSIX

    def agent_var_dir(self) -> str:
        """Where the agent keeps what this machine accumulated on this platform.

        The configured marks, a package in transit, the last reinstall's
        result, and each module's software from the hub, in a directory of
        the module's own name, live under this root.

        Returns:
            The absolute directory path.
        """
        return AGENT_VAR_DIR

    def agent_bin_dir(self) -> str:
        """Where the agent's package puts the Go programs the agent runs.

        ``neutrino_transport`` and ``neutrino_ssh_server`` live here.

        Returns:
            The absolute directory path.
        """
        return AGENT_BIN_DIR_LINUX

    def agent_log_path(self) -> str:
        """The file the agent's own log goes to on this platform.

        Returns:
            The absolute file path, empty where the service manager's
            journal keeps the log.
        """
        return ""

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

    def account_details(self) -> list:
        """Each human account with its home and its login shell, as the
        account form shows their defaults.

        Returns:
            ``[{account, home, shell}]`` in the order of
            :meth:`human_accounts`: ``home`` in the machine's own form, empty
            when it cannot be read, and ``shell`` the login shell, empty on
            Windows.

        Raises:
            PlatformUnsupportedError: When the platform cannot enumerate.
        """
        details = []
        for account in self.human_accounts():
            try:
                home = self.account_home(account)
            except (KeyError, OSError, PlatformUnsupportedError):
                home = ""
            details.append(
                {"account": account, "home": home, "shell": login_shell_of(account)}
            )
        return details

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
        password: str = "",
        environment: "dict | None" = None,
    ) -> "subprocess.CompletedProcess":
        """Run a process as an account.

        Args:
            account: The account; empty runs as the agent itself.
            argv: Argument vector.
            stdin: Sent to the process's standard input.
            timeout_s: How long to wait.
            password: The account's login, which Windows needs to run as it;
                ignored elsewhere.
            environment: Variables set for the process beside the account's
                own; None sets none.

        Returns:
            The completed process, with text output captured.

        Raises:
            PlatformUnsupportedError: When the platform cannot step down.
        """
        raise PlatformUnsupportedError("cannot run as another account here")

    def account_process(self, account: str, argv: list) -> tuple:
        """How a long-lived process starts as an account, the way ``run_as_account`` steps down.

        Args:
            account: The account.
            argv: Argument vector.

        Returns:
            ``(argv, popen_arguments)``: what to start, and what
            :class:`subprocess.Popen` takes beside it to put the process in
            the account's home with its environment and identity.

        Raises:
            KeyError: When the account database has no such account.
            PlatformUnsupportedError: When the platform cannot step down.
        """
        raise PlatformUnsupportedError("cannot run as another account here")

    def run_as_account_answering(
        self,
        account: str,
        argv: list,
        *,
        prompt: str,
        answer: str,
        timeout_s: int = AGENT_STEP_DOWN_TIMEOUT_S,
        password: str = "",
        environment: "dict | None" = None,
    ) -> tuple:
        """Run a process as an account on a terminal of its own, answering one question.

        Args:
            account: The account.
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long to wait.
            password: The account's login, which Windows needs to run as it;
                ignored elsewhere.
            environment: Variables set for the process beside the account's
                own; None sets none.

        Returns:
            ``(returncode, output)``, the output as the terminal drew it.

        Raises:
            PlatformUnsupportedError: When the platform cannot step down or
                make a terminal.
        """
        raise PlatformUnsupportedError("cannot run as another account here")

    def as_account(self, account: str, step, *arguments, password: str = ""):
        """Run one step of the agent's own code on this thread, acting as an account.

        Args:
            account: The account.
            step: Called with ``arguments``; what it reaches, it reaches with
                the account's rights.
            *arguments: What the step is called with.
            password: The account's login.

        Returns:
            What the step returned.

        Raises:
            PlatformUnsupportedError: When the platform cannot act as an
                account inside the agent's own process.
        """
        raise PlatformUnsupportedError("cannot act as another account here")

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

    def stop_agent_service(self) -> None:
        """Stop the agent's own service, leaving it to start at the next boot.

        Best-effort: the caller reads the state afterwards.

        Raises:
            PlatformUnsupportedError: When there is no service to stop.
        """
        raise PlatformUnsupportedError("no agent service to stop here")

    def disable_agent_service(self) -> None:
        """Keep the agent's own service from starting at the next boot, as
        the package's removal leaves it. Best-effort.

        Raises:
            PlatformUnsupportedError: When there is no service to disable.
        """
        raise PlatformUnsupportedError("no agent service to disable here")

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

    def terminate_process(self, pid: int) -> None:
        """End one process at once, on a system without signals.

        Args:
            pid: The process to end.

        Raises:
            PlatformUnsupportedError: When the platform ends processes by
                signal instead.
        """
        raise PlatformUnsupportedError("processes are ended by signal here")

    def read_host_metrics(self):
        """One sample of the machine's health.

        Returns:
            A :class:`~neutrino_agent.core.metrics.HostMetrics`.

        Raises:
            PlatformUnsupportedError: When the platform cannot be sampled.
        """
        raise PlatformUnsupportedError("no metrics here")

    def read_network_interfaces(self) -> list:
        """Every interface but loopback, with its MAC and addresses.

        Returns:
            ``[{"name", "mac", "addresses"}]``, the MAC empty where the
            interface has none.

        Raises:
            PlatformUnsupportedError: When the platform cannot list them.
        """
        raise PlatformUnsupportedError("no interfaces to read here")

    def read_machine_id(self) -> str:
        """The id the operating system gave this machine.

        Returns:
            The id, empty where the machine has none.

        Raises:
            PlatformUnsupportedError: When the platform keeps no machine id.
        """
        raise PlatformUnsupportedError("no machine id to read here")

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

    def smb_server_applier(self):
        """The applier that drives the SMB server the system itself carries.

        Returns:
            An applier with ``read_status``, ``apply``, ``withdraw``,
            ``set_password`` and ``reload_fence``.

        Raises:
            PlatformUnsupportedError: When the system carries no SMB server
                the agent drives.
        """
        raise PlatformUnsupportedError("no system SMB server here")

    def open_to_accounts(self, directory: str) -> None:
        """Let every account read and run what is under one directory.

        The rest of the state root stays the agent's own; this is for a
        module's software from the hub alone.

        Args:
            directory: An existing directory.

        Raises:
            OSError: When its permissions cannot be changed.
        """
        os.chmod(directory, 0o755)

    def label_programs(self, path: str) -> None:
        """Label a module's unpack so the system's service manager runs its programs.

        Nothing is labelled here; Linux labels under SELinux.

        Args:
            path: The unpack, a directory or one file.
        """

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

    def remove_added(self) -> list:
        """Stop and delete what the agent's modules added in order to run and
        to fence: their units, launchd jobs, scheduled tasks and firewall
        rules, found by name, and the file share's fence. Shares, accounts
        and the modules' data stay.

        Returns:
            What was removed, one line each.

        Raises:
            PlatformUnsupportedError: When the platform has nothing the
                agent knows how to remove.
        """
        raise PlatformUnsupportedError("nothing to remove here")

    def read_relay_addresses(self) -> list:
        """The addresses the machine's containers reach the machine at, read now.

        Returns:
            One :class:`RelayAddress` per address; none on a platform where
            the agent opens no relay, macOS among them.
        """
        return []

    def sync_relay_rules(self, rules: frozenset) -> list:
        """Make the system's firewall hold the agent's rule for each relay, and
        no rule of the agent's for anything else.

        Args:
            rules: One :class:`RelayRule` per relay the agent opens.

        Returns:
            What changed, one line each; none on a platform whose firewall
            the agent gives no rule.

        Raises:
            OSError: When the firewall cannot be read or changed.
            subprocess.SubprocessError: When a firewall command fails.
        """
        return []

    def remove_agent_program(self) -> list:
        """Remove the agent itself where no package manager does.

        Returns:
            What was removed, one line each.

        Raises:
            PlatformUnsupportedError: Where a package manager removes the
                agent.
        """
        raise PlatformUnsupportedError("the package manager removes the agent here")
