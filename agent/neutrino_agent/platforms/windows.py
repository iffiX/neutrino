"""The Windows platform: presence, vitals, the service, the machine's own id.

The agent runs as the ``neutrino_agent`` service under LocalSystem and keeps
its configuration, state and log under ``%ProgramData%\\Neutrino\\agent``.
Metrics come from kernel32, ntdll, PDH and the graphics kernel through
ctypes, with ``nvidia-smi`` for NVIDIA cards and PowerShell for the thermal
zones; the interfaces and the accounts come from PowerShell, the machine id
from the registry. The file share module drives Windows' own SMB server.
Windows has no account this agent steps down to and no package it installs,
so those capabilities are not advertised.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import json
import ntpath
import os
import re
import shutil
import subprocess
import time

from neutrino_agent.constants import (
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_CONTROL_PIPE_NAME,
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
from neutrino_agent.modules.powershell_run import listed, run_powershell
from neutrino_agent.modules.samba.constants import SAMBA_WINDOWS_MARKER
from neutrino_agent.modules.samba.windows_applier import SambaWindowsApplier
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.base import AgentPlatform

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

# Every adapter and every address, as one JSON object. The loopback pseudo
# interface holds addresses but is no adapter, so it is left out by the join.
WINDOWS_INTERFACES_SCRIPT = (
    "$a = @(Get-NetAdapter | Select-Object Name, ifIndex, MacAddress); "
    "$i = @(Get-NetIPAddress | Select-Object InterfaceIndex, IPAddress); "
    "@{adapters = $a; addresses = $i} | ConvertTo-Json -Compress -Depth 3"
)
WINDOWS_INTERFACES_COMMAND = (
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    WINDOWS_INTERFACES_SCRIPT,
)
WINDOWS_INTERFACES_TIMEOUT_S = 20
# How long one reading of the interfaces is believed. PowerShell takes a
# second or more to start, and a report goes up every few seconds.
WINDOWS_INTERFACES_TTL_S = 30.0

# Every enabled local account with its description.
WINDOWS_ACCOUNTS_SCRIPT = """
$users = @()
foreach ($user in @(Get-LocalUser | Where-Object { $_.Enabled })) {
  $users += @{name = "$($user.Name)"; description = "$($user.Description)"}
}
@{users = $users} | ConvertTo-Json -Compress -Depth 3
"""
# One account's profile directory, empty when it has signed in nowhere yet.
WINDOWS_ACCOUNT_HOME_SCRIPT = """
$user = Get-LocalUser -Name $d.name -ErrorAction SilentlyContinue
$home_path = ''
if ($user) {
  $sid = $user.SID.Value
  $held = Get-CimInstance Win32_UserProfile -Filter "SID = '$sid'"
  $home_path = "$($held.LocalPath)"
}
@{is_present = [bool]$user; home = $home_path} | ConvertTo-Json -Compress
"""
# One directory and everything under it readable and runnable by the Users
# group, named by its well-known SID so no language's group name matters.
WINDOWS_OPEN_TO_ACCOUNTS_SCRIPT = """
$code = Invoke-Icacls $d.directory '/grant' '*S-1-5-32-545:(OI)(CI)RX'
if ($code -ne 0) { throw "icacls exited $code" }
@{is_open = $true} | ConvertTo-Json -Compress
"""
# The accounts Windows makes for itself, by their lower-case names.
WINDOWS_BUILTIN_ACCOUNTS = frozenset(
    {"administrator", "guest", "defaultaccount", "wdagutilityaccount"}
)
# How long one reading of the accounts is believed.
WINDOWS_ACCOUNTS_TTL_S = 30.0

# Where Windows keeps the id it gave this installation.
WINDOWS_MACHINE_GUID_KEY = "SOFTWARE\\Microsoft\\Cryptography"
WINDOWS_MACHINE_GUID_VALUE = "MachineGuid"
# Read from the 64-bit view whatever the process is.
WINDOWS_KEY_WOW64_64KEY = 0x0100

# The thermal zones the firmware exposes, in tenths of a kelvin; none on
# most machines.
WINDOWS_THERMAL_ZONES_SCRIPT = """
$readings = @()
try {
  $zones = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature)
  foreach ($zone in $zones) { $readings += [double]$zone.CurrentTemperature }
} catch {}
@{readings = $readings} | ConvertTo-Json -Compress
"""
WINDOWS_METRICS_POWERSHELL_TIMEOUT_S = 20
# How long one reading of the thermal zones is believed.
WINDOWS_TEMPERATURE_TTL_S = 60.0
WINDOWS_KELVIN_OFFSET = 273.15

# The cores one processor group holds, and where the process table's buffer
# starts; a buffer too small grows to what the kernel asks for.
WINDOWS_CORE_SLOTS = 64
WINDOWS_PROCESS_BUFFER_BYTES = 512 * 1024
WINDOWS_QUERY_ATTEMPTS = 4
WINDOWS_QUERY_SLACK_BYTES = 64 * 1024
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


def windows_agent_dir(name: str) -> str:
    """One of the agent's roots under ``%ProgramData%\\Neutrino\\agent``.

    Args:
        name: ``config``, ``state`` or ``log``.

    Returns:
        The absolute directory path.
    """
    program_data = os.environ.get("ProgramData") or AGENT_WINDOWS_PROGRAM_DATA_DEFAULT
    return ntpath.join(program_data, *AGENT_WINDOWS_AGENT_SUBDIR, name)


def _mac_of(text: str) -> str:
    """One adapter's MAC as the other platforms spell it, empty when none."""
    mac = str(text or "").strip().replace("-", ":").lower()
    return "" if not mac or set(mac) <= {"0", ":"} else mac


def _listed(value) -> list:
    """A PowerShell JSON member as a list: one object comes back bare."""
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, dict) else []


def _run_metrics_powershell(script: str, document: dict) -> dict:
    """Run one metrics script, waiting no longer than a report can."""
    return run_powershell(
        script, document, timeout_s=WINDOWS_METRICS_POWERSHELL_TIMEOUT_S
    )


def _image_name(name: "win32.UnicodeString") -> str:
    """A process's image name, empty for the idle process."""
    if not name.Buffer or not name.Length:
        return ""
    return ctypes.string_at(name.Buffer, name.Length).decode("utf-16-le", "replace")


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
    """Windows behind the platform contract."""

    os_name = "windows"
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
            "process_terminate",
        }
    )

    def __init__(self, *, kernel32=None, shell32=None, powershell=None):
        """
        Args:
            kernel32: The bound kernel32; None binds the real one on first
                use.
            shell32: The bound shell32; None binds the real one on first
                use.
            powershell: Called with ``(script, document)``; returns the JSON
                object the script printed. None runs PowerShell.
        """
        self._kernel32 = kernel32
        self._shell32 = shell32
        self._powershell = powershell if powershell is not None else run_powershell
        self._metrics_reader = WindowsHostMetricsReader(
            kernel32=kernel32, powershell=powershell
        )
        self._interfaces: list = []
        self._interfaces_at: "float | None" = None
        self._accounts: list = []
        self._accounts_at: "float | None" = None

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
        """The enabled local accounts that are people, read at most every 30 s.

        The accounts Windows makes for itself and the ones the file share
        made, whose description starts with its marker, are left out.

        Returns:
            Account names, sorted; empty when PowerShell cannot answer.
        """
        now = time.monotonic()
        if (
            self._accounts_at is not None
            and now - self._accounts_at < WINDOWS_ACCOUNTS_TTL_S
        ):
            return list(self._accounts)
        self._accounts = self._read_accounts()
        self._accounts_at = now
        return list(self._accounts)

    def account_home(self, account: str) -> str:
        """One account's profile directory, as Windows records it.

        Args:
            account: The account.

        Returns:
            The absolute profile path.

        Raises:
            KeyError: When the machine has no such account, or the account
                has no profile yet.
            OSError: When PowerShell cannot answer.
        """
        try:
            read = self._powershell(WINDOWS_ACCOUNT_HOME_SCRIPT, {"name": account})
        except subprocess.SubprocessError as error:
            raise OSError(f"powershell did not answer: {error}") from error
        home = str(read.get("home", "") or "")
        if not read.get("is_present") or not home:
            raise KeyError(account)
        return home

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
        kernel32 = self._kernel32 or win32.libraries().kernel32
        process = kernel32.OpenProcess(win32.PROCESS_TERMINATE, False, pid)
        if not process:
            error = win32.last_error()
            if getattr(error, "winerror", None) == win32.ERROR_INVALID_PARAMETER:
                raise ProcessLookupError(pid)
            raise error
        try:
            if not kernel32.TerminateProcess(process, win32.TERMINATED_EXIT_CODE):
                raise win32.last_error()
        finally:
            kernel32.CloseHandle(process)

    def read_host_metrics(self) -> HostMetrics:
        """One sample of the machine's health.

        Returns:
            The current metrics; any unreadable source contributes its
            default rather than raising.
        """
        return self._metrics_reader.read()

    def read_network_interfaces(self) -> list:
        """Every adapter with its MAC and addresses, read at most every 30 s.

        Returns:
            ``[{"name", "mac", "addresses"}]`` in PowerShell's order; empty
            when PowerShell is missing, fails, or prints no JSON.
        """
        now = time.monotonic()
        if (
            self._interfaces_at is not None
            and now - self._interfaces_at < WINDOWS_INTERFACES_TTL_S
        ):
            return [dict(entry) for entry in self._interfaces]
        self._interfaces = self._read_interfaces()
        self._interfaces_at = now
        return [dict(entry) for entry in self._interfaces]

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
                winreg.KEY_READ | WINDOWS_KEY_WOW64_64KEY,
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
            OSError: When PowerShell or icacls fails.
        """
        try:
            self._powershell(WINDOWS_OPEN_TO_ACCOUNTS_SCRIPT, {"directory": directory})
        except subprocess.SubprocessError as error:
            raise OSError(f"powershell did not answer: {error}") from error

    def smb_server_applier(self) -> SambaWindowsApplier:
        """The applier that drives Windows' own SMB server.

        Returns:
            A :class:`SambaWindowsApplier` running PowerShell.
        """
        return SambaWindowsApplier()

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

    def _read_accounts(self) -> list:
        """Run PowerShell once and keep the accounts that are people."""
        try:
            read = self._powershell(WINDOWS_ACCOUNTS_SCRIPT, {})
        except (OSError, subprocess.SubprocessError):
            return []
        accounts = set()
        for entry in listed(read.get("users")):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "") or "")
            description = str(entry.get("description", "") or "")
            if not name or name.lower() in WINDOWS_BUILTIN_ACCOUNTS:
                continue
            if description.startswith(SAMBA_WINDOWS_MARKER):
                continue
            accounts.add(name)
        return sorted(accounts)

    def _read_interfaces(self) -> list:
        """Run PowerShell once and join adapters to their addresses."""
        try:
            result = subprocess.run(
                WINDOWS_INTERFACES_COMMAND,
                capture_output=True,
                text=True,
                timeout=WINDOWS_INTERFACES_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []
        try:
            read = json.loads(result.stdout or "")
        except ValueError:
            return []
        if not isinstance(read, dict):
            return []
        addresses: dict = {}
        for entry in _listed(read.get("addresses")):
            if not isinstance(entry, dict):
                continue
            address = str(entry.get("IPAddress", "") or "").split("%", 1)[0]
            if address:
                addresses.setdefault(entry.get("InterfaceIndex"), []).append(address)
        interfaces = []
        for adapter in _listed(read.get("adapters")):
            if not isinstance(adapter, dict):
                continue
            name = str(adapter.get("Name", "") or "")
            if not name:
                continue
            interfaces.append(
                {
                    "name": name,
                    "mac": _mac_of(adapter.get("MacAddress", "")),
                    "addresses": addresses.get(adapter.get("ifIndex"), []),
                }
            )
        return interfaces


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
            powershell: Called with ``(script, document)``; returns the JSON
                object the script printed. None runs PowerShell.
        """
        self._kernel32 = kernel32
        self._ntdll = ntdll
        self._advapi32 = advapi32
        self._pdh = pdh
        self._gdi32 = gdi32
        self._powershell = (
            powershell if powershell is not None else _run_metrics_powershell
        )
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
        answer = self._query_system_information(
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
        if (
            self._temperature_at is not None
            and now - self._temperature_at < WINDOWS_TEMPERATURE_TTL_S
        ):
            return self._temperature_c
        self._temperature_at = now
        self._temperature_c = self._read_thermal_zones()
        return self._temperature_c

    def _read_thermal_zones(self) -> "float | None":
        try:
            read = self._powershell(WINDOWS_THERMAL_ZONES_SCRIPT, {})
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        readings = []
        for value in listed(read.get("readings")):
            try:
                tenths_kelvin = float(value)
            except (TypeError, ValueError):
                continue
            if tenths_kelvin > 0:
                readings.append(tenths_kelvin / 10.0 - WINDOWS_KELVIN_OFFSET)
        return max(readings) if readings else None

    def _read_processes(self) -> "list[ProcessMetrics]":
        ntdll = self._bound("ntdll")
        if ntdll is None:
            return []
        answer = self._query_system_information(
            ntdll, win32.SYSTEM_PROCESS_INFORMATION_CLASS, self._process_buffer_bytes
        )
        if answer is None:
            return []
        buffer, _length = answer
        self._process_buffer_bytes = len(buffer)

        current_times: "dict[int, int]" = {}
        processes = []
        entry_size = ctypes.sizeof(win32.SystemProcessInformation)
        offset = 0
        while offset + entry_size <= len(buffer):
            entry = win32.SystemProcessInformation.from_buffer(buffer, offset)
            pid = entry.UniqueProcessId or 0
            # Pid 0 is the idle process, whose time is the machine's idleness.
            if pid:
                times = entry.UserTime + entry.KernelTime
                current_times[pid] = times
                processes.append(self._process_metrics(pid, entry, times))
            if entry.NextEntryOffset == 0:
                break
            offset += entry.NextEntryOffset

        # Replaced wholesale so the times of exited processes are not kept,
        # and a recycled pid cannot inherit a dead process's total.
        self._previous_process_times = current_times
        chosen = busiest_processes(processes)
        for process in chosen:
            process.user = self._process_user(process.pid)
        return chosen

    def _process_metrics(
        self, pid: int, entry: "win32.SystemProcessInformation", times: int
    ) -> ProcessMetrics:
        previous = self._previous_process_times.get(pid, times)
        cpu_percent = 0.0
        if self._total_time_delta > 0:
            share = (times - previous) / self._total_time_delta
            cpu_percent = max(0.0, 100.0 * share * self._core_count)
        memory_percent = 0.0
        if self._memory_total_bytes > 0:
            memory_percent = 100.0 * entry.WorkingSetSize / self._memory_total_bytes
        return ProcessMetrics(
            pid=pid,
            user="",
            name=_image_name(entry.ImageName),
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
        )

    def _query_system_information(self, ntdll, info_class: int, size: int):
        """One system information class, the buffer grown until it fits.

        Returns:
            The buffer and the length the kernel filled, or None when the
            kernel refuses.
        """
        for _attempt in range(WINDOWS_QUERY_ATTEMPTS):
            buffer = ctypes.create_string_buffer(size)
            needed = win32.DWORD(0)
            status = ntdll.NtQuerySystemInformation(
                info_class, buffer, size, ctypes.byref(needed)
            )
            if status == 0:
                return buffer, min(needed.value, size)
            if status != win32.STATUS_INFO_LENGTH_MISMATCH:
                return None
            size = max(size * 2, needed.value + WINDOWS_QUERY_SLACK_BYTES)
        return None

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
