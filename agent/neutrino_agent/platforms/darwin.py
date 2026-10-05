"""The macOS platform: presence, vitals, accounts, launchd, the machine's id.

The agent runs as the ``com.neutrino.agent`` LaunchDaemon and keeps its
state under ``/Library/Application Support``. The accounts come from the
directory service, the metrics from ``host_statistics``,
``host_processor_info``, ``vm_stat``, ``sysctl``, ``ps``, ``ioreg`` and
``powermetrics``, the interfaces from ``ifconfig``, the machine id from the
platform expert. The file share module drives macOS's own SMB server. It
steps down to no account and installs no package, so those capabilities are
not advertised.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import time

from neutrino_agent.constants import (
    AGENT_ADDED_LAUNCHD_PREFIX,
    AGENT_ADDED_NAME_PREFIX,
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_CONTROL_SOCKET_PATH_DARWIN,
    AGENT_DARWIN_LINK_PATH,
    AGENT_DARWIN_LOG_PATH,
    AGENT_DARWIN_PACKAGE_ID,
    AGENT_DARWIN_PROGRAM_DIR,
    AGENT_DARWIN_RUSTDESK_APP,
    AGENT_DATA_DIR_DARWIN,
    AGENT_LAUNCHD_DAEMON_DIR,
    AGENT_LAUNCHD_LABEL,
    AGENT_LAUNCHD_PLIST_PATH,
    AGENT_PF_PARENT_ANCHOR,
    AGENT_STEP_DOWN_TIMEOUT_S,
    AGENT_VAR_DIR_DARWIN,
)
from neutrino_agent.core.metrics import (
    GpuMetrics,
    HostMetrics,
    ProcessMetrics,
    busiest_processes,
    gpu_vendor,
)
from neutrino_agent.modules.samba.constants import (
    SAMBA_DARWIN_PF_ANCHOR,
    SAMBA_DARWIN_PF_RULES_NAME,
)
from neutrino_agent.modules.samba.darwin_applier import SambaDarwinApplier
from neutrino_agent.platforms.answered_run import run_on_pty
from neutrino_agent.platforms.base import AgentPlatform, is_added_name

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

# Accounts below this uid, and every name starting with an underscore, are
# the system's.
DARWIN_HUMAN_UID_FLOOR = 501
DARWIN_HOMES_DIR = "/Users/"
# The PATH a command run as an account starts from.
DARWIN_ACCOUNT_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
DARWIN_ACCOUNTS_COMMAND = ("dscl", ".", "-list", "/Users", "UniqueID")

DARWIN_POWER_COMMANDS = {
    "reboot": ["shutdown", "-r", "now"],
    "poweroff": ["shutdown", "-h", "now"],
}

DARWIN_LAUNCHD_TARGET = f"system/{AGENT_LAUNCHD_LABEL}"
DARWIN_LAUNCHD_STATE_PATTERN = re.compile(r"^\s*state\s*=\s*(\S+)", re.MULTILINE)
DARWIN_COMMAND_TIMEOUT_S = 10
# How long one launchctl bootout, pfctl or rm of a removal may take.
DARWIN_REMOVAL_TIMEOUT_S = 60
DARWIN_PLIST_SUFFIX = ".plist"

DARWIN_LOOPBACK_NAME = "lo0"
DARWIN_INTERFACE_HEADER = re.compile(r"^([A-Za-z0-9_.]+): flags=")

DARWIN_MACHINE_ID_COMMAND = ("ioreg", "-rd1", "-c", "IOPlatformExpertDevice")
DARWIN_MACHINE_ID_PATTERN = re.compile(r'"IOPlatformUUID"\s*=\s*"([^"]+)"')

# The library the Mach calls live in, and host_statistics' own names.
DARWIN_LIBSYSTEM = "/usr/lib/libSystem.B.dylib"
DARWIN_HOST_CPU_LOAD_INFO = 3
DARWIN_CPU_STATE_COUNT = 4
DARWIN_CPU_STATE_IDLE = 2
DARWIN_PROCESSOR_CPU_LOAD_INFO = 2
DARWIN_MACH_TASK_SELF_SYMBOL = "mach_task_self_"

DARWIN_VM_STAT_PAGE_SIZE = re.compile(r"page size of (\d+) bytes")
DARWIN_VM_STAT_LINE = re.compile(r'^"?([^":]+)"?:\s+(\d+)\.?$', re.MULTILINE)
# The pages vm_stat counts as there for the taking.
DARWIN_VM_STAT_AVAILABLE = ("Pages free", "Pages inactive", "Pages speculative")
DARWIN_BOOTTIME_PATTERN = re.compile(r"sec\s*=\s*(\d+)")

DARWIN_PS_COMMAND = ("ps", "-axo", "pid,user,%cpu,%mem,comm")

# Every graphics accelerator, without its children.
DARWIN_IOREG_GPU_COMMAND = ("ioreg", "-r", "-c", "IOAccelerator", "-d", "1")
DARWIN_IOREG_NODE_START = re.compile(r"^(?=\+-o )", re.MULTILINE)
DARWIN_IOREG_NODE = re.compile(r"^\+-o\s+\S+\s+<class\s+([^,>]+)")
DARWIN_IOREG_MODEL = re.compile(r'"model"\s*=\s*<?"([^"]+)"')
DARWIN_IOREG_PERFORMANCE = re.compile(r'"PerformanceStatistics"\s*=\s*\{([^}]*)\}')
DARWIN_IOREG_STATISTIC = re.compile(r'"([^"]+)"\s*=\s*(\d+)')
DARWIN_GPU_UTILIZATION_KEY = "Device Utilization %"
# The memory in use, by the key each driver names it with: AMD, Apple,
# Intel.
DARWIN_GPU_MEMORY_USED_KEYS = (
    "vramUsedBytes",
    "In use system memory",
    "inUseVidMemoryBytes",
)
DARWIN_GPU_MEMORY_FREE_KEY = "vramFreeBytes"
DARWIN_BYTES_PER_MB = 1024 * 1024

# The SMC's reading of the processor die; Apple silicon has no such line.
DARWIN_POWERMETRICS_COMMAND = (
    "powermetrics",
    "--samplers",
    "smc",
    "-n",
    "1",
    "-i",
    "1",
)
DARWIN_CPU_DIE_TEMPERATURE = re.compile(r"CPU die temperature:\s*([0-9.]+)\s*C")
# How long one reading of the temperature is believed.
DARWIN_TEMPERATURE_TTL_S = 30.0


def _run(command) -> str:
    """One command's standard output, empty when it fails or is missing."""
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=DARWIN_COMMAND_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "") if result.returncode == 0 else ""


def _run_removal(command: list) -> None:
    """Run one step of a removal; a step that fails or is missing is skipped."""
    try:
        subprocess.run(
            command, capture_output=True, timeout=DARWIN_REMOVAL_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _unlink(path: str) -> None:
    """Delete one file or link; a missing one is no error."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def parse_ifconfig(text: str) -> list:
    """Every interface but loopback out of ``ifconfig -a``.

    Args:
        text: What ``ifconfig -a`` printed.

    Returns:
        ``[{"name", "mac", "addresses"}]`` in its order, the MAC empty where
        the interface has none.
    """
    interfaces = []
    current = None
    for line in text.splitlines():
        header = DARWIN_INTERFACE_HEADER.match(line)
        if header is not None:
            current = {"name": header.group(1), "mac": "", "addresses": []}
            if current["name"] != DARWIN_LOOPBACK_NAME:
                interfaces.append(current)
            continue
        fields = line.split()
        if current is None or len(fields) < 2:
            continue
        if fields[0] == "ether":
            current["mac"] = fields[1].lower()
        elif fields[0] in ("inet", "inet6"):
            current["addresses"].append(fields[1].split("%", 1)[0])
    return interfaces


def parse_ps(text: str) -> "list[ProcessMetrics]":
    """The busiest processes out of ``ps -axo pid,user,%cpu,%mem,comm``.

    The command comes last: ``ps`` cuts every column but the last to its
    width, and a path under ``/System/Library`` is longer than that.

    Args:
        text: What ``ps`` printed, its header first.

    Returns:
        The processes a report lists, each named by its executable's file
        name.
    """
    processes = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 5:
            continue
        try:
            pid = int(fields[0])
            cpu_percent = float(fields[2])
            memory_percent = float(fields[3])
        except ValueError:
            continue
        command = " ".join(fields[4:])
        processes.append(
            ProcessMetrics(
                pid=pid,
                user=fields[1],
                name=os.path.basename(command) or command,
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
            )
        )
    return busiest_processes(processes)


def parse_ioreg_gpus(text: str) -> "list[GpuMetrics]":
    """The graphics cards out of ``ioreg -r -c IOAccelerator -d 1``.

    Args:
        text: What ``ioreg`` printed.

    Returns:
        One entry per accelerator in its order, named by its model where the
        node carries one and by its driver's class where it does not.
    """
    gpus = []
    for node in DARWIN_IOREG_NODE_START.split(text):
        header = DARWIN_IOREG_NODE.match(node)
        if header is None:
            continue
        driver = header.group(1).strip()
        model = DARWIN_IOREG_MODEL.search(node)
        name = model.group(1) if model else driver
        performance = DARWIN_IOREG_PERFORMANCE.search(node)
        statistics = {}
        if performance is not None:
            statistics = {
                key: int(value)
                for key, value in DARWIN_IOREG_STATISTIC.findall(performance.group(1))
            }
        utilization = statistics.get(DARWIN_GPU_UTILIZATION_KEY)
        used = next(
            (
                statistics[key]
                for key in DARWIN_GPU_MEMORY_USED_KEYS
                if key in statistics
            ),
            None,
        )
        free = statistics.get(DARWIN_GPU_MEMORY_FREE_KEY)
        gpus.append(
            GpuMetrics(
                vendor=gpu_vendor(name) or gpu_vendor(driver),
                name=name,
                utilization_percent=(
                    float(utilization) if utilization is not None else None
                ),
                memory_used_mb=(
                    used // DARWIN_BYTES_PER_MB if used is not None else None
                ),
                memory_total_mb=(
                    (used + free) // DARWIN_BYTES_PER_MB
                    if used is not None and free is not None
                    else None
                ),
            )
        )
    return gpus


def _mach_task_self(libsystem) -> "int | None":
    """This process's task port, which libSystem keeps as a variable."""
    try:
        return ctypes.c_uint.in_dll(libsystem, DARWIN_MACH_TASK_SELF_SYMBOL).value
    except (AttributeError, TypeError, ValueError):
        return None


class DarwinPlatform(AgentPlatform):
    """macOS behind the platform contract."""

    os_name = "darwin"
    capabilities = frozenset(
        {
            "run_as",
            "accounts",
            "control_socket",
            "agent_service",
            "power",
            "metrics",
            "network",
            "machine_id",
            "smb_server",
            "hub_packages",
            "removal",
            "self_removal",
        }
    )

    def __init__(self, *, libsystem=None):
        """
        Args:
            libsystem: The loaded libSystem; None loads the real one on
                first use.
        """
        self._metrics_reader = DarwinHostMetricsReader(libsystem=libsystem)

    def agent_data_dir(self) -> str:
        """Where the agent keeps what the hub decided on a Mac.

        Returns:
            The absolute directory path.
        """
        return AGENT_DATA_DIR_DARWIN

    def agent_var_dir(self) -> str:
        """Where the agent keeps what this Mac accumulated.

        Returns:
            The absolute directory path.
        """
        return AGENT_VAR_DIR_DARWIN

    def agent_log_path(self) -> str:
        """The file the agent's LaunchDaemon writes its output to.

        Returns:
            ``/Library/Logs/Neutrino/agent/agent.log``.
        """
        return AGENT_DARWIN_LOG_PATH

    def human_accounts(self) -> list:
        """The accounts that are people: uid at the floor or above, a name
        that does not start with an underscore, a home under ``/Users``.

        Returns:
            Account names, sorted.
        """
        accounts = []
        for line in _run(DARWIN_ACCOUNTS_COMMAND).splitlines():
            fields = line.split()
            if len(fields) != 2 or fields[0].startswith("_"):
                continue
            try:
                uid = int(fields[1])
            except ValueError:
                continue
            if uid < DARWIN_HUMAN_UID_FLOOR:
                continue
            try:
                home = self.account_home(fields[0])
            except KeyError:
                continue
            if home.startswith(DARWIN_HOMES_DIR) and os.path.isdir(home):
                accounts.append(fields[0])
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
        return pwd.getpwnam(account).pw_dir

    def _account_process(self, account: str) -> dict:
        """How a child runs as an account: its uid, its group, its home, its names.

        Raises:
            KeyError: When the account database has no such account.
        """
        entry = pwd.getpwnam(account)
        return {
            "user": entry.pw_uid,
            "group": entry.pw_gid,
            "extra_groups": [],
            "cwd": entry.pw_dir,
            "env": {
                "HOME": entry.pw_dir,
                "USER": entry.pw_name,
                "LOGNAME": entry.pw_name,
                "PATH": DARWIN_ACCOUNT_PATH,
            },
        }

    def run_as_account(
        self,
        account: str,
        argv: list,
        *,
        stdin: str = "",
        timeout_s: int = AGENT_STEP_DOWN_TIMEOUT_S,
        password: str = "",
    ) -> "subprocess.CompletedProcess":
        """Run a process as an account: its uid and group, no other groups, in its home.

        Args:
            account: The account; empty runs as the agent itself.
            argv: Argument vector.
            stdin: Sent to the process's standard input.
            timeout_s: How long to wait.
            password: Unused here; Windows needs it.

        Returns:
            The completed process, with text output captured.

        Raises:
            KeyError: When the account database has no such account.
        """
        extra = self._account_process(account) if account else {}
        return subprocess.run(
            list(argv),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            **extra,
        )

    def run_as_account_answering(
        self,
        account: str,
        argv: list,
        *,
        prompt: str,
        answer: str,
        timeout_s: int = AGENT_STEP_DOWN_TIMEOUT_S,
        password: str = "",
    ) -> tuple:
        """Run a process as an account on a pseudo-terminal, answering one question.

        Args:
            account: The account.
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long to wait.
            password: Unused here; Windows needs it.

        Returns:
            ``(returncode, output)``; 127 when it could not start.

        Raises:
            KeyError: When the account database has no such account.
        """
        extra = self._account_process(account)
        return run_on_pty(
            list(argv),
            prompt=prompt,
            answer=answer,
            timeout_s=timeout_s,
            env=extra["env"],
            cwd=extra["cwd"],
            user=extra["user"],
            group=extra["group"],
        )

    def control_socket_path(self) -> str:
        """Where the agent's control socket lives on a Mac.

        Returns:
            The absolute socket path.
        """
        return AGENT_CONTROL_SOCKET_PATH_DARWIN

    def read_agent_service_state(self) -> str:
        """What launchd says about the agent's own job.

        Returns:
            ``running``, another launchd state word, ``stopped`` when the job
            is not loaded, or ``unknown`` when launchctl cannot be run.
        """
        try:
            result = subprocess.run(
                ["launchctl", "print", DARWIN_LAUNCHD_TARGET],
                capture_output=True,
                text=True,
                timeout=DARWIN_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        if result.returncode != 0:
            return "stopped"
        match = DARWIN_LAUNCHD_STATE_PATTERN.search(result.stdout or "")
        return match.group(1) if match else "unknown"

    def start_agent_service(self) -> None:
        """Load and start the agent's own job. Best-effort."""
        for command in (
            ["launchctl", "bootstrap", "system", AGENT_LAUNCHD_PLIST_PATH],
            ["launchctl", "kickstart", DARWIN_LAUNCHD_TARGET],
        ):
            subprocess.run(command, capture_output=True, timeout=30, check=False)

    def stop_agent_service(self) -> None:
        """Unload the agent's own job; its plist loads it at the next boot.

        Best-effort.
        """
        subprocess.run(
            ["launchctl", "bootout", DARWIN_LAUNCHD_TARGET],
            capture_output=True,
            timeout=30,
            check=False,
        )

    def remove_added(self) -> list:
        """Unload and delete the launchd jobs the agent's modules wrote, and
        empty the file share's fence.

        A job is the modules' when its plist under ``/Library/LaunchDaemons``
        is named as :func:`is_added_name` says. The fence is every
        ``com.apple`` sub-anchor whose name starts ``neutrino_``, emptied,
        and its rules file under the state root, deleted. Share points and
        accounts stay, and so does the agent's own job.

        Returns:
            What was removed, one line each.
        """
        removed = []
        try:
            entries = sorted(os.listdir(AGENT_LAUNCHD_DAEMON_DIR))
        except OSError:
            entries = []
        for name in entries:
            if not name.endswith(DARWIN_PLIST_SUFFIX):
                continue
            label = name[: -len(DARWIN_PLIST_SUFFIX)]
            if not is_added_name(label, AGENT_ADDED_LAUNCHD_PREFIX):
                continue
            _run_removal(["launchctl", "bootout", f"system/{label}"])
            _unlink(os.path.join(AGENT_LAUNCHD_DAEMON_DIR, name))
            removed.append(label)
        anchors = {SAMBA_DARWIN_PF_ANCHOR}
        listed = _run(["pfctl", "-a", AGENT_PF_PARENT_ANCHOR, "-s", "Anchors"])
        for line in listed.splitlines():
            anchor = line.strip()
            if not anchor:
                continue
            if "/" not in anchor:
                anchor = f"{AGENT_PF_PARENT_ANCHOR}/{anchor}"
            if is_added_name(anchor.rsplit("/", 1)[-1], AGENT_ADDED_NAME_PREFIX):
                anchors.add(anchor)
        for anchor in sorted(anchors):
            _run_removal(["pfctl", "-a", anchor, "-F", "all"])
            removed.append(f"pf anchor {anchor}")
        _unlink(os.path.join(self.agent_var_dir(), SAMBA_DARWIN_PF_RULES_NAME))
        return removed

    def remove_agent_program(self) -> list:
        """Remove the agent from this Mac, which has no uninstaller.

        RustDesk's two jobs and the agent's own are unloaded, their plists,
        RustDesk, the program and its link are deleted, and the package's
        receipt is forgotten. The configuration, the state and the log stay,
        as a Linux package's removal leaves them, so an install that comes
        after finds the binding and the file share's record.

        Returns:
            What was removed, one line each.
        """
        from neutrino_agent.modules.rustdesk import (
            RUSTDESK_DARWIN_SERVICE_LABEL,
            RUSTDESK_DARWIN_SERVICE_PLIST,
            RUSTDESK_DARWIN_SESSION_LABEL,
            RUSTDESK_DARWIN_SESSION_PLIST,
        )

        from neutrino_agent.rdp.darwin_seat import console_user

        seated = console_user()
        seat = seated[1] if seated else 0
        if seat != 0:
            _run_removal(
                ["launchctl", "bootout", f"gui/{seat}/{RUSTDESK_DARWIN_SESSION_LABEL}"]
            )
        _run_removal(
            ["launchctl", "bootout", f"system/{RUSTDESK_DARWIN_SERVICE_LABEL}"]
        )
        _run_removal(["launchctl", "bootout", DARWIN_LAUNCHD_TARGET])
        for path in (
            RUSTDESK_DARWIN_SESSION_PLIST,
            RUSTDESK_DARWIN_SERVICE_PLIST,
            AGENT_LAUNCHD_PLIST_PATH,
            AGENT_DARWIN_LINK_PATH,
        ):
            _unlink(path)
        _run_removal(["pkgutil", "--forget", AGENT_DARWIN_PACKAGE_ID])
        _run_removal(["rm", "-rf", AGENT_DARWIN_RUSTDESK_APP, AGENT_DARWIN_PROGRAM_DIR])
        return [
            AGENT_LAUNCHD_LABEL,
            RUSTDESK_DARWIN_SERVICE_LABEL,
            RUSTDESK_DARWIN_SESSION_LABEL,
            AGENT_DARWIN_RUSTDESK_APP,
            AGENT_DARWIN_PROGRAM_DIR,
        ]

    def agent_service_start_hint(self) -> str:
        """The launchctl command that loads the agent's own job."""
        return f"sudo launchctl bootstrap system {AGENT_LAUNCHD_PLIST_PATH}"

    def power(self, action: str) -> "tuple[int, str]":
        """Run one power action, at once.

        Args:
            action: ``reboot`` or ``poweroff``.

        Returns:
            The exit code and combined output.
        """
        completed = subprocess.run(
            DARWIN_POWER_COMMANDS[action],
            capture_output=True,
            text=True,
            timeout=AGENT_COMMAND_TIMEOUT_S,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode, output

    def read_host_metrics(self) -> HostMetrics:
        """One sample of the machine's health.

        Returns:
            The current metrics; any unreadable source contributes its
            default rather than raising.
        """
        return self._metrics_reader.read()

    def read_network_interfaces(self) -> list:
        """Every interface but loopback, from ``ifconfig -a``.

        Returns:
            ``[{"name", "mac", "addresses"}]``; empty when ifconfig fails.
        """
        return parse_ifconfig(_run(["ifconfig", "-a"]))

    def smb_server_applier(self) -> SambaDarwinApplier:
        """The applier that drives macOS's own SMB server.

        Returns:
            A :class:`SambaDarwinApplier` keeping its pf rules under the
            work root.
        """
        return SambaDarwinApplier(
            rules_path=os.path.join(self.agent_var_dir(), SAMBA_DARWIN_PF_RULES_NAME)
        )

    def read_machine_id(self) -> str:
        """The platform UUID the firmware reports.

        Returns:
            The id, empty when ioreg does not name one.
        """
        match = DARWIN_MACHINE_ID_PATTERN.search(_run(DARWIN_MACHINE_ID_COMMAND))
        return match.group(1) if match else ""


class DarwinHostMetricsReader:
    """Samples host metrics on a Mac, remembering the last CPU ticks.

    Processor load, of the host and of each core, is a rate, so the first
    sample after start has nothing to compare against and reports zero.
    """

    def __init__(self, *, libsystem=None):
        """
        Args:
            libsystem: The loaded libSystem; None loads the real one on
                first use.
        """
        self._libsystem = libsystem
        self._previous_cpu: "tuple[int, int] | None" = None
        self._previous_cores: "dict[int, tuple[int, int]]" = {}
        self._temperature_c: "float | None" = None
        self._temperature_at: "float | None" = None

    def read(self) -> HostMetrics:
        """Take one sample.

        Returns:
            The current metrics. Any source that cannot be read contributes
            its default rather than raising.
        """
        return HostMetrics(
            cpu_percent=self._read_cpu_percent(),
            cpu_core_percents=self._read_core_percents(),
            memory_percent=self._read_memory_percent(),
            disk_percent=self._read_disk_percent(),
            temperature_c=self._read_temperature_c(),
            uptime_s=self._read_uptime_s(),
            load_average=self._read_load_average(),
            gpus=parse_ioreg_gpus(_run(DARWIN_IOREG_GPU_COMMAND)),
            processes=parse_ps(_run(DARWIN_PS_COMMAND)),
        )

    def _bound_libsystem(self):
        """libSystem, loaded on first use; None where it cannot be."""
        if self._libsystem is None:
            try:
                self._libsystem = ctypes.CDLL(DARWIN_LIBSYSTEM)
            except OSError:
                return None
        return self._libsystem

    def _read_cpu_percent(self) -> float:
        libsystem = self._bound_libsystem()
        if libsystem is None:
            return 0.0
        ticks = (ctypes.c_uint * DARWIN_CPU_STATE_COUNT)()
        count = ctypes.c_uint(DARWIN_CPU_STATE_COUNT)
        try:
            outcome = libsystem.host_statistics(
                libsystem.mach_host_self(),
                DARWIN_HOST_CPU_LOAD_INFO,
                ctypes.byref(ticks),
                ctypes.byref(count),
            )
        except (AttributeError, OSError):
            return 0.0
        if outcome != 0:
            return 0.0
        total = sum(ticks)
        busy = total - ticks[DARWIN_CPU_STATE_IDLE]
        previous = self._previous_cpu
        self._previous_cpu = (busy, total)
        if previous is None or total <= previous[1]:
            return 0.0
        share = (busy - previous[0]) / (total - previous[1])
        return max(0.0, min(100.0, 100.0 * share))

    def _read_core_percents(self) -> "list[float]":
        percents = []
        for index, ticks in enumerate(self._read_core_ticks()):
            total = sum(ticks)
            busy = total - ticks[DARWIN_CPU_STATE_IDLE]
            previous = self._previous_cores.get(index)
            self._previous_cores[index] = (busy, total)
            if previous is None or total <= previous[1]:
                percents.append(0.0)
                continue
            share = (busy - previous[0]) / (total - previous[1])
            percents.append(max(0.0, min(100.0, 100.0 * share)))
        return percents

    def _read_core_ticks(self) -> "list[tuple]":
        """Each core's user, system, idle and nice ticks, in core order."""
        libsystem = self._bound_libsystem()
        if libsystem is None:
            return []
        core_count = ctypes.c_uint(0)
        info = ctypes.c_void_p()
        info_count = ctypes.c_uint(0)
        try:
            outcome = libsystem.host_processor_info(
                libsystem.mach_host_self(),
                DARWIN_PROCESSOR_CPU_LOAD_INFO,
                ctypes.byref(core_count),
                ctypes.byref(info),
                ctypes.byref(info_count),
            )
        except (AttributeError, OSError):
            return []
        if outcome != 0 or not info.value:
            return []
        try:
            values = (
                ctypes.c_uint * (core_count.value * DARWIN_CPU_STATE_COUNT)
            ).from_address(info.value)
            return [
                tuple(values[start : start + DARWIN_CPU_STATE_COUNT])
                for start in range(0, len(values), DARWIN_CPU_STATE_COUNT)
            ]
        finally:
            self._deallocate(
                libsystem, info.value, info_count.value * ctypes.sizeof(ctypes.c_int)
            )

    def _deallocate(self, libsystem, address: int, size: int) -> None:
        """Hand back the array the kernel allocated in this task."""
        task = _mach_task_self(libsystem)
        if task is None:
            return
        try:
            libsystem.vm_deallocate(
                ctypes.c_uint(task), ctypes.c_size_t(address), ctypes.c_size_t(size)
            )
        except (AttributeError, OSError):
            return

    def _read_memory_percent(self) -> float:
        try:
            total = int(_run(["sysctl", "-n", "hw.memsize"]).strip())
        except ValueError:
            return 0.0
        printed = _run(["vm_stat"])
        page = DARWIN_VM_STAT_PAGE_SIZE.search(printed)
        if total <= 0 or page is None:
            return 0.0
        pages = {
            name.strip(): int(value)
            for name, value in DARWIN_VM_STAT_LINE.findall(printed)
        }
        available = sum(pages.get(name, 0) for name in DARWIN_VM_STAT_AVAILABLE)
        used = total - available * int(page.group(1))
        return max(0.0, min(100.0, 100.0 * used / total))

    def _read_disk_percent(self) -> float:
        try:
            usage = shutil.disk_usage("/")
        except OSError:
            return 0.0
        if usage.total <= 0:
            return 0.0
        return 100.0 * usage.used / usage.total

    def _read_uptime_s(self) -> int:
        match = DARWIN_BOOTTIME_PATTERN.search(_run(["sysctl", "-n", "kern.boottime"]))
        if match is None:
            return 0
        return max(0, int(time.time()) - int(match.group(1)))

    def _read_load_average(self) -> "list[float]":
        try:
            return list(os.getloadavg())
        except (OSError, AttributeError):
            return []

    def _read_temperature_c(self) -> "float | None":
        now = time.monotonic()
        if (
            self._temperature_at is not None
            and now - self._temperature_at < DARWIN_TEMPERATURE_TTL_S
        ):
            return self._temperature_c
        self._temperature_at = now
        match = DARWIN_CPU_DIE_TEMPERATURE.search(_run(DARWIN_POWERMETRICS_COMMAND))
        self._temperature_c = float(match.group(1)) if match else None
        return self._temperature_c
