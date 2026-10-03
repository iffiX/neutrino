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
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_CONTROL_SOCKET_PATH_DARWIN,
    AGENT_DARWIN_LOG_PATH,
    AGENT_DATA_DIR_DARWIN,
    AGENT_LAUNCHD_LABEL,
    AGENT_LAUNCHD_PLIST_PATH,
    AGENT_VAR_DIR_DARWIN,
)
from neutrino_agent.core.metrics import (
    GpuMetrics,
    HostMetrics,
    ProcessMetrics,
    busiest_processes,
    gpu_vendor,
)
from neutrino_agent.modules.samba.constants import SAMBA_DARWIN_PF_RULES_NAME
from neutrino_agent.modules.samba.darwin_applier import SambaDarwinApplier
from neutrino_agent.platforms.base import AgentPlatform

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

# Accounts below this uid, and every name starting with an underscore, are
# the system's.
DARWIN_HUMAN_UID_FLOOR = 501
DARWIN_HOMES_DIR = "/Users/"
DARWIN_ACCOUNTS_COMMAND = ("dscl", ".", "-list", "/Users", "UniqueID")

DARWIN_POWER_COMMANDS = {
    "reboot": ["shutdown", "-r", "now"],
    "poweroff": ["shutdown", "-h", "now"],
}

DARWIN_LAUNCHD_TARGET = f"system/{AGENT_LAUNCHD_LABEL}"
DARWIN_LAUNCHD_STATE_PATTERN = re.compile(r"^\s*state\s*=\s*(\S+)", re.MULTILINE)
DARWIN_COMMAND_TIMEOUT_S = 10

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

DARWIN_PS_COMMAND = ("ps", "-axo", "pid,user,comm,%cpu,%mem")

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
    """The busiest processes out of ``ps -axo pid,user,comm,%cpu,%mem``.

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
            cpu_percent = float(fields[-2])
            memory_percent = float(fields[-1])
        except ValueError:
            continue
        command = " ".join(fields[2:-2])
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
            "accounts",
            "control_socket",
            "agent_service",
            "power",
            "metrics",
            "network",
            "machine_id",
            "smb_server",
            "hub_packages",
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
