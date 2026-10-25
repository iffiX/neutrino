"""The Windows platform: presence, vitals, the service, the machine's own id.

The agent runs as the ``neutrino_agent`` service under LocalSystem and keeps
its configuration, state and log under ``%ProgramData%\\Neutrino\\agent``.
Metrics come from kernel32, ntdll, PDH and the graphics kernel through
ctypes, with ``nvidia-smi`` for NVIDIA cards and the agent's PowerShell host
for the thermal zones; the interfaces come from iphlpapi, the accounts from
netapi32, a home from the registry's profile list, the machine id from the
registry. The Task Scheduler, the file share, the relays' firewall rules
and the uninstall cleanup go through the PowerShell host. Windows has no
account this agent steps down to and no package it installs, so those
capabilities are not advertised.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import ntpath
import os
import re
import shutil
import subprocess
import threading
import time

from neutrino_agent.constants import (
    AGENT_ADDED_NAME_PREFIX,
    AGENT_ANSWER_VERB,
    AGENT_RELAY_RULE_PREFIX,
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_CONTROL_PIPE_NAME,
    AGENT_RUN_AS_DIR_NAME,
    AGENT_RUN_AS_POLL_S,
    AGENT_RUN_AS_TASK_PREFIX,
    AGENT_STEP_DOWN_TIMEOUT_S,
    AGENT_WINDOWS_BINARY_NAME,
    AGENT_WINDOWS_PROGRAM_FILES_DEFAULT,
    AGENT_WINDOWS_PROGRAM_SUBDIR,
    AGENT_WINDOWS_AGENT_SUBDIR,
    AGENT_WINDOWS_CONFIG_DIR_NAME,
    AGENT_WINDOWS_LOG_DIR_NAME,
    AGENT_WINDOWS_LOG_NAME,
    AGENT_WINDOWS_PROGRAM_DATA_DEFAULT,
    AGENT_WINDOWS_SERVICE_NAME,
    AGENT_WINDOWS_STATE_DIR_NAME,
)
from neutrino_agent.core.metrics import (
    GpuMetrics,
    HostMetrics,
    ProcessMetrics,
    busiest_processes,
    gpu_vendor,
    read_nvidia_gpus,
)
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.remote_desktop.rdp.windows_seat import WindowsSeat
from neutrino_agent.modules.samba.constants import SAMBA_WINDOWS_MARKER
from neutrino_agent.modules.samba.windows_applier import SambaWindowsApplier
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_WINDOWS_SHELL,
)
from neutrino_agent.modules.shared.account_service.windows import (
    remove_path,
    write_text,
)
from neutrino_agent.modules.shared.subprocess_run import run as run_command
from neutrino_agent.modules.shared.windows_acl import (
    grant_account_alone,
    open_to_users,
)
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.base import AgentPlatform, is_added_name
from neutrino_agent.platforms.powershell_host import agent_host
from neutrino_agent.platforms.windows_accounts import (
    account_home,
    impersonated,
    read_users,
)
from neutrino_agent.platforms.windows_net import read_interfaces
from neutrino_agent.platforms.windows_relay import rule_changes, wsl_addresses_from
from neutrino_agent.platforms.windows_processes import (
    WindowsProcessTable,
    process_entries,
    process_tree,
    query_system_information,
    terminate_process,
)

try:
    import winreg
except ImportError:  # Only Windows has the registry module.
    winreg = None

WINDOWS_POWER_COMMANDS = {
    "reboot": ["shutdown", "/r", "/t", "0"],
    "poweroff": ["shutdown", "/s", "/t", "0"],
}

# What ``sc query`` prints as a service's state number, by its word.
WINDOWS_SERVICE_STATES = {
    1: "stopped",
    2: "start_pending",
    3: "stop_pending",
    4: "running",
    5: "continue_pending",
    6: "pause_pending",
    7: "paused",
}
WINDOWS_SERVICE_STATE_PATTERN = re.compile(r"STATE\s*:\s*(\d+)")
WINDOWS_SERVICE_TIMEOUT_S = 10

# The exit code a command reports when its end was never written.
WINDOWS_RUN_AS_NO_EXIT = -1
# The accounts Windows makes for itself, by their lower-case names.
WINDOWS_BUILTIN_ACCOUNTS = frozenset(
    {"administrator", "guest", "defaultaccount", "wdagutilityaccount"}
)

# Where Windows keeps the id it gave this installation.
WINDOWS_MACHINE_GUID_KEY = "SOFTWARE\\Microsoft\\Cryptography"
WINDOWS_MACHINE_GUID_VALUE = "MachineGuid"

# How long the thermal zones are waited for, how long a reading is
# believed, and how long a machine whose firmware exposes none is believed.
WINDOWS_THERMAL_ZONES_TIMEOUT_S = 20
WINDOWS_TEMPERATURE_TTL_S = 60.0
WINDOWS_TEMPERATURE_ABSENT_TTL_S = 3600.0
WINDOWS_KELVIN_OFFSET = 273.15

# The cores one processor group holds, and where the process table's buffer
# starts.
WINDOWS_CORE_SLOTS = 64
WINDOWS_PROCESS_BUFFER_BYTES = 512 * 1024
WINDOWS_ACCOUNT_NAME_CHARS = 256

# The GPU counters, by their English paths, and how an instance names its
# adapter and its engine.
WINDOWS_GPU_ENGINE_COUNTER = "\\GPU Engine(*)\\Utilization Percentage"
WINDOWS_GPU_MEMORY_COUNTER = "\\GPU Adapter Memory(*)\\Dedicated Usage"
WINDOWS_GPU_LUID_PATTERN = re.compile(r"luid_0x([0-9a-f]+)_0x([0-9a-f]+)", re.I)
WINDOWS_GPU_ENGINE_TYPE_PATTERN = re.compile(r"engtype_(.*)$")
# How long the adapters' names are believed, and how long a GPU counter
# query that could not be opened waits before the next try.
WINDOWS_GPU_ADAPTERS_TTL_S = 300.0
WINDOWS_GPU_QUERY_RETRY_S = 300.0
WINDOWS_BYTES_PER_MB = 1024 * 1024

# The variable naming the drive Windows is installed on, and the drive taken
# when it is unset.
WINDOWS_SYSTEM_DRIVE_VARIABLE = "SystemDrive"
WINDOWS_SYSTEM_DRIVE_DEFAULT = "C:"


def windows_agent_dir(name: str) -> str:
    """One of the agent's roots under ``%ProgramData%\\Neutrino\\agent``.

    Args:
        name: ``config``, ``state`` or ``log``.

    Returns:
        The absolute directory path.
    """
    program_data = os.environ.get("ProgramData") or AGENT_WINDOWS_PROGRAM_DATA_DEFAULT
    return ntpath.join(program_data, *AGENT_WINDOWS_AGENT_SUBDIR, name)


def cmd_argument(argument: str) -> str:
    """One argument as a ``.cmd`` script's command line must carry it.

    Every argument is quoted, so ``&``, ``|``, ``<`` and ``>`` stay text,
    with the program's own rules for quotes and backslashes, and ``%`` is
    doubled so the script expands nothing.

    Args:
        argument: The argument.

    Returns:
        Its quoted form.
    """
    text = subprocess.list2cmdline([argument])
    if not text.startswith('"'):
        bare = text.rstrip("\\")
        text = '"' + bare + "\\" * (2 * (len(text) - len(bare))) + '"'
    return text.replace("%", "%%")


def run_as_script(
    argv: list,
    *,
    input_path: str,
    output_path: str,
    done_path: str,
    environment: "dict | None" = None,
) -> str:
    """The ``.cmd`` script a one-shot task runs a command with.

    Args:
        argv: Argument vector.
        input_path: The file its standard input is read from.
        output_path: The file its output and errors go to.
        done_path: The file its exit code is written to last.
        environment: Variables set before the command, each as
            ``set "NAME=value"`` with ``%`` doubled; None sets none.

    Returns:
        The script's text, CRLF line ends, starting in the account's profile.
    """
    command = " ".join(cmd_argument(argument) for argument in argv)
    settings = [
        'set "{}={}"'.format(name, str(value).replace("%", "%%"))
        for name, value in (environment or {}).items()
    ]
    lines = [
        "@echo off",
        'cd /d "%USERPROFILE%"',
        *settings,
        f"{command} < {cmd_argument(input_path)} > {cmd_argument(output_path)} 2>&1",
        f">{cmd_argument(done_path)} echo %errorlevel%",
    ]
    return "\r\n".join(lines) + "\r\n"


def agent_program_path() -> str:
    """The agent's own program, ``nagent.exe``, under Program Files."""
    root = os.environ.get("ProgramFiles", "") or AGENT_WINDOWS_PROGRAM_FILES_DEFAULT
    return ntpath.join(root, *AGENT_WINDOWS_PROGRAM_SUBDIR, AGENT_WINDOWS_BINARY_NAME)


def system_drive_root() -> str:
    """The root of the drive Windows is installed on, such as ``C:\\``.

    Returns:
        The absolute directory path.
    """
    drive = (
        os.environ.get(WINDOWS_SYSTEM_DRIVE_VARIABLE) or WINDOWS_SYSTEM_DRIVE_DEFAULT
    )
    return drive.rstrip("\\") + "\\"


def _file_text(path: str) -> str:
    """A file's text as UTF-8, empty when it is not there."""
    try:
        with open(path, "rb") as stream:
            data = stream.read()
    except OSError:
        return ""
    return data.decode("utf-8", "replace").lstrip("\ufeff")


def _exit_code_in(path: str) -> int:
    """The exit code a one-shot task's script wrote last; -1 when it wrote none."""
    try:
        return int(_file_text(path).strip())
    except ValueError:
        return WINDOWS_RUN_AS_NO_EXIT


def _utf16_text(units) -> str:
    """A fixed array of UTF-16 units, up to its first null."""
    return bytes(units).decode("utf-16-le", "replace").split("\x00", 1)[0].strip()


def _counter_luid(name: str) -> "tuple[int, int] | None":
    """The adapter a GPU counter instance names, as its LUID's two halves."""
    match = WINDOWS_GPU_LUID_PATTERN.search(name or "")
    if match is None:
        return None
    return int(match.group(1), 16), int(match.group(2), 16)


def _is_hardware_gpu(kind: int) -> bool:
    """Whether an adapter's type bits say a card that renders or computes."""
    if kind & win32.D3DKMT_ADAPTERTYPE_SOFTWARE_DEVICE:
        return False
    return bool(
        kind
        & (
            win32.D3DKMT_ADAPTERTYPE_RENDER_SUPPORTED
            | win32.D3DKMT_ADAPTERTYPE_COMPUTE_ONLY
        )
    )


class WindowsPlatform(AgentPlatform):
    """Windows behind the platform contract.

    Attributes:
        powershell_host: The agent's PowerShell host, asked as
            :meth:`WindowsPowerShellHost.call` is.
        process_table: The machine's processes, as
            :class:`WindowsProcessTable` reads and ends them.
    """

    os_name = "windows"
    capabilities = frozenset(
        {
            "run_as",
            "act_as",
            "accounts",
            "control_socket",
            "agent_service",
            "power",
            "metrics",
            "network",
            "machine_id",
            "smb_server",
            "hub_packages",
            "process_terminate",
            "removal",
        }
    )

    def __init__(
        self,
        *,
        kernel32=None,
        shell32=None,
        advapi32=None,
        iphlpapi=None,
        netapi32=None,
        powershell=None,
        processes=None,
        run=None,
        seat=None,
        sleep=time.sleep,
    ):
        """
        Args:
            kernel32: The bound kernel32; None binds the real one on first
                use.
            shell32: The bound shell32; None binds the real one on first
                use.
            advapi32: The bound advapi32, for an account's SID and logon;
                None binds the real one on first use.
            iphlpapi: The bound iphlpapi, for the interfaces; None binds the
                real one on first use.
            netapi32: The bound netapi32, for the accounts; None binds the
                real one on first use.
            powershell: The PowerShell host, asked as
                :meth:`WindowsPowerShellHost.call` is; None is the agent's
                one host.
            processes: The machine's processes, as
                :class:`WindowsProcessTable` reads them; None reads the
                process table.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            seat: Names the account signed in at the console; None reads
                the console session.
            sleep: Waits a number of seconds, between looks at a one-shot
                task's end.
        """
        self._kernel32 = kernel32
        self._shell32 = shell32
        self._advapi32 = advapi32
        self._iphlpapi = iphlpapi
        self._netapi32 = netapi32
        self._seat = seat if seat is not None else WindowsSeat()
        self._run = run if run is not None else run_command
        self._sleep = sleep
        # One lock per account, by its lower-case name, around a one-shot
        # task's whole cycle: the account's runs share the task's name and
        # its directory.
        self._run_as_locks: dict = {}
        self._run_as_locks_guard = threading.Lock()
        self.powershell_host = powershell if powershell is not None else agent_host()
        self.process_table = (
            processes
            if processes is not None
            else WindowsProcessTable(kernel32=kernel32)
        )
        self._metrics_reader = WindowsHostMetricsReader(
            kernel32=kernel32, powershell=self.powershell_host
        )

    def agent_data_dir(self) -> str:
        """Where the agent keeps what the hub decided: ``...\\agent\\config``.

        Returns:
            The absolute directory path.
        """
        return windows_agent_dir(AGENT_WINDOWS_CONFIG_DIR_NAME)

    def agent_var_dir(self) -> str:
        """Where the agent keeps what the machine accumulated: ``...\\agent\\state``.

        Returns:
            The absolute directory path.
        """
        return windows_agent_dir(AGENT_WINDOWS_STATE_DIR_NAME)

    def agent_log_path(self) -> str:
        """The service's log: ``agent.log`` under ``...\\agent\\log``.

        Returns:
            The absolute file path.
        """
        return ntpath.join(
            windows_agent_dir(AGENT_WINDOWS_LOG_DIR_NAME), AGENT_WINDOWS_LOG_NAME
        )

    def human_accounts(self) -> list:
        """The enabled local accounts that are people.

        The accounts Windows makes for itself and the ones the file share
        made, whose description starts with its marker, are left out.

        Returns:
            Account names, sorted; empty when the accounts cannot be listed.
        """
        try:
            users = read_users(self._netapi32)
        except (OSError, ValueError):
            return []
        accounts = set()
        for user in users:
            name = user["name"]
            if not user["is_enabled"] or not name:
                continue
            if name.lower() in WINDOWS_BUILTIN_ACCOUNTS:
                continue
            if user["description"].startswith(SAMBA_WINDOWS_MARKER):
                continue
            accounts.add(name)
        return sorted(accounts)

    def account_home(self, account: str) -> str:
        """One account's profile directory, as Windows records it.

        Args:
            account: The account.

        Returns:
            The absolute profile path.

        Raises:
            KeyError: When the machine has no such account, or the account
                has no profile yet.
            OSError: When the account's SID or the registry cannot be read.
        """
        return account_home(account, advapi32=self._advapi32, kernel32=self._kernel32)

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
        """Run a command as an account, in a one-shot scheduled task under its login.

        The task runs with a limited token in the account's profile; its
        script, its standard input, its output and its exit code are files
        in a directory only the account, SYSTEM and the administrators
        reach, all removed with the task once the exit code is read. Two
        runs for one account take turns, the second waiting until the
        first's task and files are removed; runs for two accounts do not
        wait on each other.

        Args:
            account: The account.
            argv: Argument vector.
            stdin: What the command reads on its standard input.
            timeout_s: How long the command may take.
            password: The account's login.
            environment: Variables the task's script sets before the
                command; None sets none.

        Returns:
            The completed process, its output and errors as standard output;
            its return code is -1 when the command never wrote its end.

        Raises:
            ModuleApplyError: ``credential_invalid {account}`` when Windows
                refuses the login.
            OSError: When the files cannot be written, or the host cannot
                register or start the task.
        """
        with self._run_as_lock(account):
            directory = ntpath.join(
                self.agent_var_dir(), AGENT_RUN_AS_DIR_NAME, account
            )
            paths = {
                name: ntpath.join(directory, f"command.{name}")
                for name in ("cmd", "input", "output", "done")
            }
            os.makedirs(directory, exist_ok=True)
            grant_account_alone(self._run, directory, account, "M", is_tree=True)
            for name in ("output", "done"):
                remove_path(paths[name])
            task = AGENT_RUN_AS_TASK_PREFIX + account
            try:
                write_text(
                    paths["cmd"],
                    run_as_script(
                        argv,
                        input_path=paths["input"],
                        output_path=paths["output"],
                        done_path=paths["done"],
                        environment=environment,
                    ),
                )
                write_text(paths["input"], stdin)
                self.powershell_host.call(
                    "task_run_once",
                    {
                        "task": task,
                        "program": ACCOUNT_SERVICE_WINDOWS_SHELL,
                        "arguments": f'/d /c "{paths["cmd"]}"',
                        "account": account,
                        "password": password,
                        "timeout_s": int(timeout_s),
                    },
                )
                deadline = time.monotonic() + timeout_s
                while not os.path.exists(paths["done"]) and time.monotonic() < deadline:
                    self._sleep(AGENT_RUN_AS_POLL_S)
                code = _exit_code_in(paths["done"])
                output = _file_text(paths["output"])
            finally:
                try:
                    self.powershell_host.call("task_remove", {"task": task})
                except (OSError, ModuleApplyError):
                    pass
                for path in paths.values():
                    remove_path(path)
            return subprocess.CompletedProcess(list(argv), code, output, "")

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
        """Run a command as an account on a pseudo console, answering one question.

        The one-shot task runs the agent's own ``nagent answer``, which makes
        the console inside the account's task and answers there.

        Args:
            account: The account.
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included; the console's
                own Enter replaces the newline.
            timeout_s: How long to wait.
            password: The account's login.
            environment: Variables the task's script sets before the
                command; None sets none.

        Returns:
            ``(returncode, output)``, the output as the console drew it.

        Raises:
            ModuleApplyError: ``credential_invalid {account}`` when Windows
                refuses the login.
            OSError: When the host cannot register or run the task.
        """
        command = [
            agent_program_path(),
            AGENT_ANSWER_VERB,
            "--prompt",
            prompt,
            "--answer",
            answer.rstrip("\r\n"),
            "--",
            *argv,
        ]
        done = self.run_as_account(
            account,
            command,
            timeout_s=timeout_s,
            password=password,
            environment=environment,
        )
        return done.returncode, done.stdout

    def as_account(self, account: str, step, *arguments, password: str = ""):
        """Run one step of the agent's own code on this thread, as an account.

        The thread acts as the account under a logon its password makes, and
        reverts once the step returns.

        Args:
            account: The account.
            step: Called with ``arguments``.
            *arguments: What the step is called with.
            password: The account's login.

        Returns:
            What the step returned.

        Raises:
            ModuleApplyError: ``credential_invalid {account}`` when Windows
                refuses the login.
            OSError: When no logon is granted or the thread cannot act as
                the account.
        """
        with impersonated(
            account, password, advapi32=self._advapi32, kernel32=self._kernel32
        ):
            return step(*arguments)

    def shell_start_dir(self) -> str:
        """Where a shell here starts.

        Returns:
            The profile directory of the account signed in at the console;
            the system drive's root when nobody is signed in, or the
            profile cannot be read or does not exist.
        """
        for account in self._seat.graphical_accounts() or []:
            try:
                home = self.account_home(account)
            except (KeyError, OSError):
                continue
            if os.path.isdir(home):
                return home
        return system_drive_root()

    def control_socket_path(self) -> str:
        """The named pipe the control channel serves on.

        Returns:
            The pipe name.
        """
        return AGENT_CONTROL_PIPE_NAME

    def read_agent_service_state(self) -> str:
        """What the service control manager says about the agent's service.

        Returns:
            ``running``, another state word, or ``unknown``.
        """
        try:
            result = subprocess.run(
                ["sc", "query", AGENT_WINDOWS_SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=WINDOWS_SERVICE_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        match = WINDOWS_SERVICE_STATE_PATTERN.search(result.stdout or "")
        if match is None:
            return "unknown"
        return WINDOWS_SERVICE_STATES.get(int(match.group(1)), "unknown")

    def start_agent_service(self) -> None:
        """Start the agent's own service. Best-effort."""
        subprocess.run(
            ["sc", "start", AGENT_WINDOWS_SERVICE_NAME],
            capture_output=True,
            timeout=30,
            check=False,
        )

    def stop_agent_service(self) -> None:
        """Stop the agent's own service; it keeps its start type. Best-effort."""
        subprocess.run(
            ["sc", "stop", AGENT_WINDOWS_SERVICE_NAME],
            capture_output=True,
            timeout=30,
            check=False,
        )

    def disable_agent_service(self) -> None:
        """Set the agent's own service's start type to disabled. Best-effort."""
        subprocess.run(
            ["sc", "config", AGENT_WINDOWS_SERVICE_NAME, "start=", "disabled"],
            capture_output=True,
            timeout=30,
            check=False,
        )

    def agent_service_start_hint(self) -> str:
        """The command that starts the agent's own service."""
        return f"sc start {AGENT_WINDOWS_SERVICE_NAME}"

    def power(self, action: str) -> "tuple[int, str]":
        """Run one power action, at once.

        Args:
            action: ``reboot`` or ``poweroff``.

        Returns:
            The exit code and combined output.
        """
        completed = subprocess.run(
            WINDOWS_POWER_COMMANDS[action],
            capture_output=True,
            text=True,
            timeout=AGENT_COMMAND_TIMEOUT_S,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode, output

    def terminate_process(self, pid: int) -> None:
        """End one process at once through ``TerminateProcess``.

        Args:
            pid: The process to end.

        Raises:
            ProcessLookupError: When no process holds the pid.
            OSError: When the process cannot be opened or ended.
        """
        terminate_process(self._kernel32 or win32.libraries().kernel32, pid)

    def read_host_metrics(self) -> HostMetrics:
        """One sample of the machine's health.

        Returns:
            The current metrics; any unreadable source contributes its
            default rather than raising.
        """
        return self._metrics_reader.read()

    def read_network_interfaces(self) -> list:
        """Every adapter with its MAC and addresses, read now.

        Returns:
            ``[{"name", "mac", "addresses"}]`` in iphlpapi's order, the
            loopback pseudo interface and the tunnels left out; empty when
            the adapters cannot be read.
        """
        try:
            return read_interfaces(self._iphlpapi)
        except (OSError, ValueError):
            return []

    def read_relay_addresses(self) -> list:
        """The computer's address on WSL's vEthernet adapter, read now.

        Returns:
            One :class:`RelayAddress` per IPv4 address on the adapter whose
            name starts ``vEthernet (WSL``; none while WSL has no adapter or
            the adapters cannot be read.
        """
        return wsl_addresses_from(self.read_network_interfaces())

    def sync_relay_rules(self, rules: frozenset) -> list:
        """Give Windows Firewall one inbound rule per relayed port, scoped to
        WSL's vEthernet adapter, and remove the agent's rules no relay asks for.

        Args:
            rules: One :class:`RelayRule` per relay the agent opens.

        Returns:
            What changed, one line each.

        Raises:
            OSError: When the PowerShell host cannot read or change the
                rules, or refuses.
        """
        try:
            found = self.powershell_host.call(
                "relay_rules_read", {"prefix": AGENT_RELAY_RULE_PREFIX}
            )
            add, remove = rule_changes(rules, list(found.get("rules") or []))
            if not add and not remove:
                return []
            self.powershell_host.call(
                "relay_rules_write", {"add": add, "remove": remove}
            )
        except ModuleApplyError as error:
            raise OSError(f"the relay rules were refused: {error}") from error
        return [f"removed firewall rule {name}" for name in remove] + [
            f"added firewall rule {rule['name']} on {rule['alias']}" for rule in add
        ]

    def read_machine_id(self) -> str:
        """The id Windows gave this installation, from the registry.

        Returns:
            The id, empty when the key cannot be read.
        """
        if winreg is None:
            return ""
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                WINDOWS_MACHINE_GUID_KEY,
                0,
                winreg.KEY_READ | win32.KEY_WOW64_64KEY,
            ) as key:
                value, _kind = winreg.QueryValueEx(key, WINDOWS_MACHINE_GUID_VALUE)
        except OSError:
            return ""
        return str(value or "").strip()

    def open_to_accounts(self, directory: str) -> None:
        """Grant the Users group read and run on one directory and what it holds.

        Args:
            directory: An existing directory under the state root.

        Raises:
            OSError: When icacls fails.
        """
        open_to_users(self._run, directory)

    def remove_added(self) -> list:
        """Delete the services, unregister the scheduled tasks and remove the
        firewall rules the agent's modules added, the file share's fence
        among them.

        A service, a task or a rule is the modules' when
        :func:`is_added_name` says so; the agent's own service, the hub's
        and the client's are not touched. Every process running from under
        the state root is ended with its descendants, so no instance
        outlives its task, and the one-shot tasks' files go. Shares and
        accounts stay.

        Returns:
            What was removed, one line each.

        Raises:
            OSError: When the host or the process table fails.
        """
        found = self.powershell_host.call(
            "added_list", {"prefix": AGENT_ADDED_NAME_PREFIX}
        )
        services, tasks, rules = (
            sorted(
                str(name)
                for name in found.get(kind) or []
                if is_added_name(str(name), AGENT_ADDED_NAME_PREFIX)
            )
            for kind in ("services", "tasks", "rules")
        )
        self.powershell_host.call(
            "added_remove", {"services": services, "tasks": tasks, "rules": rules}
        )
        state_root = self.agent_var_dir()
        self._end_processes_under(state_root)
        shutil.rmtree(
            ntpath.join(state_root, AGENT_RUN_AS_DIR_NAME), ignore_errors=True
        )
        return (
            [f"service {name}" for name in services]
            + [f"task {name}" for name in tasks]
            + [f"firewall rule {name}" for name in rules]
        )

    def smb_server_applier(self) -> SambaWindowsApplier:
        """The applier that drives Windows' own SMB server.

        Returns:
            A :class:`SambaWindowsApplier` asking the PowerShell host.
        """
        return SambaWindowsApplier(powershell=self.powershell_host, run=self._run)

    def is_elevated(self) -> bool:
        """Whether this process runs with an administrator's token.

        Returns:
            True for an elevated administrator or the SYSTEM account.
        """
        try:
            shell32 = self._shell32 or win32.libraries().shell32
            return bool(shell32.IsUserAnAdmin())
        except (OSError, AttributeError):
            return False

    def _end_processes_under(self, root: str) -> None:
        """End every process whose command line or program names a folder, and
        every process they started, a child never older than its parent."""
        table = self.process_table
        entries = table.entries()
        folded = root.lower()
        roots = [
            entry.pid
            for entry in entries
            if entry.pid
            and folded
            in f"{table.command_line(entry.pid)}|{table.image_path(entry.pid)}".lower()
        ]
        table.end(process_tree(entries, roots))

    def _run_as_lock(self, account: str) -> "threading.Lock":
        """The lock one account's one-shot task runs under, the same for any case."""
        with self._run_as_locks_guard:
            return self._run_as_locks.setdefault(account.lower(), threading.Lock())


class WindowsHostMetricsReader:
    """Samples host metrics through kernel32, ntdll, PDH and the graphics kernel.

    Processor load, of the host, of each core and of each process, is a rate
    against the previous sample, so the first sample after start reports
    zero; the GPU engines' load is empty until the second sample.
    """

    def __init__(
        self,
        *,
        kernel32=None,
        ntdll=None,
        advapi32=None,
        pdh=None,
        gdi32=None,
        powershell=None,
    ):
        """
        Args:
            kernel32: The bound kernel32; None binds the real one on first
                use.
            ntdll: The bound ntdll, for the per-core times and the process
                table; None binds the real one on first use.
            advapi32: The bound advapi32, for a process's account; None
                binds the real one on first use.
            pdh: The bound pdh, for the GPU counters; None binds the real
                one on first use.
            gdi32: The bound gdi32, for the adapters' names and memory; None
                binds the real one on first use.
            powershell: The PowerShell host, for the thermal zones, asked as
                :meth:`WindowsPowerShellHost.call` is; None is the agent's
                one host.
        """
        self._kernel32 = kernel32
        self._ntdll = ntdll
        self._advapi32 = advapi32
        self._pdh = pdh
        self._gdi32 = gdi32
        self._powershell = powershell if powershell is not None else agent_host()
        self._previous_cpu: "tuple[int, int] | None" = None
        self._previous_cores: "dict[int, tuple[int, int]]" = {}
        self._previous_process_times: "dict[int, int]" = {}
        self._total_time_delta = 0
        self._core_count = 1
        self._memory_total_bytes = 0
        self._process_buffer_bytes = WINDOWS_PROCESS_BUFFER_BYTES
        self._account_names: "dict[bytes, str]" = {}
        self._gpu_query: "tuple | None" = None
        self._gpu_query_tried_at: "float | None" = None
        self._adapters: "list | None" = None
        self._adapters_at: "float | None" = None
        self._temperature_c: "float | None" = None
        self._temperature_at: "float | None" = None

    def read(self) -> HostMetrics:
        """Take one sample.

        Returns:
            The current metrics. Any source that cannot be read contributes
            its default rather than raising.
        """
        kernel32 = self._bound("kernel32")
        cpu_percent = self._read_cpu_percent(kernel32)
        core_percents = self._read_core_percents()
        memory_percent = self._read_memory_percent(kernel32)
        return HostMetrics(
            cpu_percent=cpu_percent,
            cpu_core_percents=core_percents,
            memory_percent=memory_percent,
            disk_percent=self._read_disk_percent(),
            temperature_c=self._read_temperature_c(),
            uptime_s=self._read_uptime_s(kernel32),
            gpus=self._read_gpus(),
            processes=self._read_processes(),
        )

    def _bound(self, name: str):
        """One library, bound on first use; None where it cannot be."""
        library = getattr(self, "_" + name)
        if library is None:
            try:
                library = getattr(win32.libraries(), name)
            except (OSError, AttributeError):
                return None
            setattr(self, "_" + name, library)
        return library

    def _read_cpu_percent(self, kernel32) -> float:
        if kernel32 is None:
            return 0.0
        idle = win32.FileTime()
        kernel = win32.FileTime()
        user = win32.FileTime()
        if not kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return 0.0
        # The kernel time includes the idle time.
        total = kernel.value + user.value
        busy = total - idle.value
        previous = self._previous_cpu
        self._previous_cpu = (busy, total)
        if previous is None or total <= previous[1]:
            self._total_time_delta = 0
            return 0.0
        # Remembered for process shares: a process's times are measured
        # against this same all-core delta.
        self._total_time_delta = total - previous[1]
        share = (busy - previous[0]) / (total - previous[1])
        return max(0.0, min(100.0, 100.0 * share))

    def _read_core_percents(self) -> "list[float]":
        ntdll = self._bound("ntdll")
        if ntdll is None:
            return []
        entry_size = ctypes.sizeof(win32.SystemProcessorPerformanceInformation)
        answer = query_system_information(
            ntdll,
            win32.SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION_CLASS,
            entry_size * WINDOWS_CORE_SLOTS,
        )
        if answer is None:
            return []
        buffer, length = answer
        percents = []
        for index in range(length // entry_size):
            entry = win32.SystemProcessorPerformanceInformation.from_buffer(
                buffer, index * entry_size
            )
            # The kernel time includes the idle time.
            total = entry.KernelTime + entry.UserTime
            busy = total - entry.IdleTime
            previous = self._previous_cores.get(index)
            self._previous_cores[index] = (busy, total)
            if previous is None or total <= previous[1]:
                percents.append(0.0)
                continue
            share = (busy - previous[0]) / (total - previous[1])
            percents.append(max(0.0, min(100.0, 100.0 * share)))
        self._core_count = max(1, len(percents))
        return percents

    def _read_memory_percent(self, kernel32) -> float:
        if kernel32 is None:
            return 0.0
        status = win32.MemoryStatusEx()
        status.dwLength = ctypes.sizeof(win32.MemoryStatusEx)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0.0
        if status.ullTotalPhys <= 0:
            return 0.0
        self._memory_total_bytes = status.ullTotalPhys
        used = status.ullTotalPhys - status.ullAvailPhys
        return 100.0 * used / status.ullTotalPhys

    def _read_disk_percent(self) -> float:
        drive = (os.environ.get("SystemDrive") or "C:") + "\\"
        try:
            usage = shutil.disk_usage(drive)
        except OSError:
            return 0.0
        if usage.total <= 0:
            return 0.0
        return 100.0 * usage.used / usage.total

    def _read_uptime_s(self, kernel32) -> int:
        if kernel32 is None:
            return 0
        return int(kernel32.GetTickCount64()) // 1000

    def _read_temperature_c(self) -> "float | None":
        now = time.monotonic()
        if self._temperature_at is not None and now < self._temperature_at:
            return self._temperature_c
        self._temperature_c, is_absent = self._read_thermal_zones()
        self._temperature_at = now + (
            WINDOWS_TEMPERATURE_ABSENT_TTL_S if is_absent else WINDOWS_TEMPERATURE_TTL_S
        )
        return self._temperature_c

    def _read_thermal_zones(self) -> "tuple[float | None, bool]":
        """The hottest zone, and whether the firmware answered with none."""
        try:
            read = self._powershell.call(
                "thermal_zones", {}, timeout_s=WINDOWS_THERMAL_ZONES_TIMEOUT_S
            )
        except (OSError, ValueError, ModuleApplyError):
            return None, False
        values = read.get("readings")
        readings = []
        for value in values if isinstance(values, list) else []:
            try:
                tenths_kelvin = float(value)
            except (TypeError, ValueError):
                continue
            if tenths_kelvin > 0:
                readings.append(tenths_kelvin / 10.0 - WINDOWS_KELVIN_OFFSET)
        if not readings:
            return None, True
        return max(readings), False

    def _read_processes(self) -> "list[ProcessMetrics]":
        ntdll = self._bound("ntdll")
        if ntdll is None:
            return []
        answer = query_system_information(
            ntdll, win32.SYSTEM_PROCESS_INFORMATION_CLASS, self._process_buffer_bytes
        )
        if answer is None:
            return []
        buffer, _length = answer
        self._process_buffer_bytes = len(buffer)

        current_times: "dict[int, int]" = {}
        processes = []
        for entry in process_entries(buffer.raw, ctypes.addressof(buffer)):
            # Pid 0 is the idle process, whose time is the machine's idleness.
            if entry.pid:
                current_times[entry.pid] = entry.cpu_time
                processes.append(self._process_metrics(entry))

        # Replaced wholesale so the times of exited processes are not kept,
        # and a recycled pid cannot inherit a dead process's total.
        self._previous_process_times = current_times
        chosen = busiest_processes(processes)
        for process in chosen:
            process.user = self._process_user(process.pid)
        return chosen

    def _process_metrics(self, entry) -> ProcessMetrics:
        previous = self._previous_process_times.get(entry.pid, entry.cpu_time)
        cpu_percent = 0.0
        if self._total_time_delta > 0:
            share = (entry.cpu_time - previous) / self._total_time_delta
            cpu_percent = max(0.0, 100.0 * share * self._core_count)
        memory_percent = 0.0
        if self._memory_total_bytes > 0:
            memory_percent = 100.0 * entry.working_set / self._memory_total_bytes
        return ProcessMetrics(
            pid=entry.pid,
            user="",
            name=entry.name,
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
        )

    def _process_user(self, pid: int) -> str:
        """The account a process runs as; empty when its token cannot be read."""
        kernel32 = self._bound("kernel32")
        advapi32 = self._bound("advapi32")
        if kernel32 is None or advapi32 is None:
            return ""
        process = kernel32.OpenProcess(
            win32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not process:
            return ""
        try:
            token = ctypes.c_void_p()
            if not advapi32.OpenProcessToken(
                process, win32.TOKEN_QUERY, ctypes.byref(token)
            ):
                return ""
            try:
                return self._token_account(advapi32, token)
            finally:
                kernel32.CloseHandle(token)
        finally:
            kernel32.CloseHandle(process)

    def _token_account(self, advapi32, token) -> str:
        size = win32.DWORD(0)
        advapi32.GetTokenInformation(
            token, win32.TOKEN_USER_CLASS, None, 0, ctypes.byref(size)
        )
        if size.value < ctypes.sizeof(win32.SidAndAttributes):
            return ""
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, win32.TOKEN_USER_CLASS, buffer, size.value, ctypes.byref(size)
        ):
            return ""
        sid = win32.SidAndAttributes.from_buffer(buffer).Sid
        if not sid:
            return ""
        key = ctypes.string_at(sid, advapi32.GetLengthSid(sid))
        if key not in self._account_names:
            self._account_names[key] = self._lookup_account(advapi32, sid)
        return self._account_names[key]

    def _lookup_account(self, advapi32, sid) -> str:
        name = ctypes.create_unicode_buffer(WINDOWS_ACCOUNT_NAME_CHARS)
        domain = ctypes.create_unicode_buffer(WINDOWS_ACCOUNT_NAME_CHARS)
        name_size = win32.DWORD(WINDOWS_ACCOUNT_NAME_CHARS)
        domain_size = win32.DWORD(WINDOWS_ACCOUNT_NAME_CHARS)
        use = win32.DWORD(0)
        if not advapi32.LookupAccountSidW(
            None,
            sid,
            name,
            ctypes.byref(name_size),
            domain,
            ctypes.byref(domain_size),
            ctypes.byref(use),
        ):
            return ""
        return name.value

    def _read_gpus(self) -> "list[GpuMetrics]":
        return read_nvidia_gpus() or self._read_counter_gpus()

    def _read_counter_gpus(self) -> "list[GpuMetrics]":
        utilization, memory_used = self._read_gpu_counters()
        adapters = self._read_adapters()
        if adapters is None:
            adapters = [
                (luid, "", None) for luid in sorted(set(utilization) | set(memory_used))
            ]
        gpus = []
        for luid, name, memory_total in adapters:
            used = memory_used.get(luid)
            gpus.append(
                GpuMetrics(
                    vendor=gpu_vendor(name),
                    name=name,
                    utilization_percent=utilization.get(luid),
                    memory_used_mb=(
                        used // WINDOWS_BYTES_PER_MB if used is not None else None
                    ),
                    memory_total_mb=(
                        memory_total // WINDOWS_BYTES_PER_MB if memory_total else None
                    ),
                )
            )
        return gpus

    def _read_gpu_counters(self) -> "tuple[dict, dict]":
        """The engines' load and the dedicated memory in use, by adapter.

        An adapter's load is its busiest engine type's, each type summed
        over the processes using it.
        """
        query = self._open_gpu_query()
        pdh = self._bound("pdh")
        if query is None or pdh is None:
            return {}, {}
        handle, engine_counter, memory_counter = query
        if pdh.PdhCollectQueryData(handle) != 0:
            return {}, {}

        engine_sums: "dict[tuple, float]" = {}
        for name, value in self._counter_items(
            pdh, engine_counter, win32.PDH_FMT_DOUBLE
        ):
            luid = _counter_luid(name)
            engine = WINDOWS_GPU_ENGINE_TYPE_PATTERN.search(name)
            if luid is None:
                continue
            key = (luid, engine.group(1) if engine else "")
            engine_sums[key] = engine_sums.get(key, 0.0) + float(value)
        utilization: "dict[tuple, float]" = {}
        for (luid, _engine), total in engine_sums.items():
            utilization[luid] = min(100.0, max(utilization.get(luid, 0.0), total))

        memory_used: "dict[tuple, int]" = {}
        for name, value in self._counter_items(
            pdh, memory_counter, win32.PDH_FMT_LARGE
        ):
            luid = _counter_luid(name)
            if luid is not None:
                memory_used[luid] = memory_used.get(luid, 0) + int(value)
        return utilization, memory_used

    def _open_gpu_query(self) -> "tuple | None":
        """The GPU counter query, opened once; None while it cannot be."""
        if self._gpu_query is not None:
            return self._gpu_query
        now = time.monotonic()
        if (
            self._gpu_query_tried_at is not None
            and now - self._gpu_query_tried_at < WINDOWS_GPU_QUERY_RETRY_S
        ):
            return None
        self._gpu_query_tried_at = now
        pdh = self._bound("pdh")
        if pdh is None:
            return None
        handle = ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(handle)) != 0:
            return None
        counters = []
        for path in (WINDOWS_GPU_ENGINE_COUNTER, WINDOWS_GPU_MEMORY_COUNTER):
            counter = ctypes.c_void_p()
            if pdh.PdhAddEnglishCounterW(handle, path, 0, ctypes.byref(counter)) != 0:
                pdh.PdhCloseQuery(handle)
                return None
            counters.append(counter)
        self._gpu_query = (handle, counters[0], counters[1])
        return self._gpu_query

    def _counter_items(self, pdh, counter, value_format: int) -> list:
        """Every instance of one wildcard counter that carries a value.

        Returns:
            ``[(instance name, value)]``; empty when PDH refuses.
        """
        size = win32.DWORD(0)
        count = win32.DWORD(0)
        status = pdh.PdhGetFormattedCounterArrayW(
            counter, value_format, ctypes.byref(size), ctypes.byref(count), None
        )
        if status != win32.PDH_MORE_DATA or size.value == 0:
            return []
        buffer = ctypes.create_string_buffer(size.value)
        status = pdh.PdhGetFormattedCounterArrayW(
            counter, value_format, ctypes.byref(size), ctypes.byref(count), buffer
        )
        item_size = ctypes.sizeof(win32.PdhFmtCounterValueItem)
        if status != 0 or count.value * item_size > len(buffer):
            return []
        items = (win32.PdhFmtCounterValueItem * count.value).from_buffer(buffer)
        read = []
        for item in items:
            if item.FmtValue.CStatus not in (
                win32.PDH_CSTATUS_VALID_DATA,
                win32.PDH_CSTATUS_NEW_DATA,
            ):
                continue
            if value_format == win32.PDH_FMT_DOUBLE:
                value = item.FmtValue.value.doubleValue
            else:
                value = item.FmtValue.value.largeValue
            read.append((item.szName or "", value))
        return read

    def _read_adapters(self) -> "list | None":
        """The graphics cards, read at most every five minutes."""
        now = time.monotonic()
        if (
            self._adapters_at is not None
            and now - self._adapters_at < WINDOWS_GPU_ADAPTERS_TTL_S
        ):
            return self._adapters
        self._adapters = self._enumerate_adapters()
        self._adapters_at = now
        return self._adapters

    def _enumerate_adapters(self) -> "list | None":
        """Every card that renders or computes, from the graphics kernel.

        Returns:
            ``[(luid, name, dedicated memory bytes or None)]`` in the
            kernel's order, or None when the kernel cannot be asked.
        """
        gdi32 = self._bound("gdi32")
        if gdi32 is None or not hasattr(gdi32, "D3DKMTEnumAdapters2"):
            return None
        enumeration = win32.D3dkmtEnumAdapters2()
        if gdi32.D3DKMTEnumAdapters2(ctypes.byref(enumeration)) != 0:
            return None
        if enumeration.NumAdapters == 0:
            return []
        infos = (win32.D3dkmtAdapterInfo * enumeration.NumAdapters)()
        enumeration.pAdapters = ctypes.addressof(infos)
        if gdi32.D3DKMTEnumAdapters2(ctypes.byref(enumeration)) != 0:
            return None
        adapters = []
        for info in infos[: enumeration.NumAdapters]:
            try:
                adapter = self._describe_adapter(gdi32, info)
            finally:
                gdi32.D3DKMTCloseAdapter(
                    ctypes.byref(win32.D3dkmtCloseAdapter(hAdapter=info.hAdapter))
                )
            if adapter is not None:
                adapters.append(adapter)
        return adapters

    def _describe_adapter(self, gdi32, info: "win32.D3dkmtAdapterInfo"):
        """One adapter's LUID, name and memory; None for a software one."""
        kind = self._query_adapter(
            gdi32, info.hAdapter, win32.KMTQAITYPE_ADAPTERTYPE, ctypes.c_uint32()
        )
        if kind is not None and not _is_hardware_gpu(kind.value):
            return None
        registry = self._query_adapter(
            gdi32,
            info.hAdapter,
            win32.KMTQAITYPE_ADAPTERREGISTRYINFO,
            win32.D3dkmtAdapterRegistryInfo(),
        )
        segments = self._query_adapter(
            gdi32,
            info.hAdapter,
            win32.KMTQAITYPE_GETSEGMENTSIZE,
            win32.D3dkmtSegmentSizeInfo(),
        )
        luid = (info.AdapterLuid.HighPart & 0xFFFFFFFF, info.AdapterLuid.LowPart)
        name = _utf16_text(registry.AdapterString) if registry is not None else ""
        memory_total = (
            segments.DedicatedVideoMemorySize if segments is not None else None
        )
        return luid, name, memory_total or None

    def _query_adapter(self, gdi32, adapter: int, kind: int, answer):
        """Ask the graphics kernel one question; the answer or None."""
        query = win32.D3dkmtQueryAdapterInfo(
            hAdapter=adapter,
            Type=kind,
            pPrivateDriverData=ctypes.addressof(answer),
            PrivateDriverDataSize=ctypes.sizeof(answer),
        )
        if gdi32.D3DKMTQueryAdapterInfo(ctypes.byref(query)) != 0:
            return None
        return answer
