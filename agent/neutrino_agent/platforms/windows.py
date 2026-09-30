"""The Windows platform: presence, vitals, the service, the machine's own id.

The agent runs as the ``neutrino_agent`` service under LocalSystem and keeps
its state under ``%ProgramData%``. Metrics come from kernel32 through
ctypes, the interfaces from one PowerShell call, the machine id from the
registry. The file share module drives Windows' own SMB server. Windows
has no account this agent steps down to and no package it installs, so
those capabilities are not advertised.
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
    AGENT_WINDOWS_DATA_SUBDIR,
    AGENT_WINDOWS_PROGRAM_DATA_DEFAULT,
    AGENT_WINDOWS_SERVICE_NAME,
)
from neutrino_agent.core.metrics import HostMetrics
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

# Where Windows keeps the id it gave this installation.
WINDOWS_MACHINE_GUID_KEY = "SOFTWARE\\Microsoft\\Cryptography"
WINDOWS_MACHINE_GUID_VALUE = "MachineGuid"
# Read from the 64-bit view whatever the process is.
WINDOWS_KEY_WOW64_64KEY = 0x0100


def windows_data_dir() -> str:
    """The agent's data root under ``%ProgramData%``.

    Returns:
        The absolute directory path.
    """
    program_data = os.environ.get("ProgramData") or AGENT_WINDOWS_PROGRAM_DATA_DEFAULT
    return ntpath.join(program_data, *AGENT_WINDOWS_DATA_SUBDIR)


def _mac_of(text: str) -> str:
    """One adapter's MAC as the other platforms spell it, empty when none."""
    mac = str(text or "").strip().replace("-", ":").lower()
    return "" if not mac or set(mac) <= {"0", ":"} else mac


def _listed(value) -> list:
    """A PowerShell JSON member as a list: one object comes back bare."""
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, dict) else []


class WindowsPlatform(AgentPlatform):
    """Windows behind the platform contract."""

    os_name = "windows"
    capabilities = frozenset(
        {
            "control_socket",
            "agent_service",
            "power",
            "metrics",
            "network",
            "machine_id",
            "smb_server",
        }
    )

    def __init__(self, *, kernel32=None, shell32=None):
        """
        Args:
            kernel32: The bound kernel32; None binds the real one on first
                use.
            shell32: The bound shell32; None binds the real one on first
                use.
        """
        self._shell32 = shell32
        self._metrics_reader = WindowsHostMetricsReader(kernel32=kernel32)
        self._interfaces: list = []
        self._interfaces_at: "float | None" = None

    def agent_data_dir(self) -> str:
        """Where the agent keeps its own state: ``%ProgramData%\\Neutrino\\agent``.

        Returns:
            The absolute directory path.
        """
        return windows_data_dir()

    def agent_var_dir(self) -> str:
        """Where the agent keeps its own work: the same root as its state.

        Returns:
            The absolute directory path.
        """
        return windows_data_dir()

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
    """Samples host metrics through kernel32, remembering the last CPU times.

    Processor load is a rate, so the first sample after start has nothing
    to compare against and reports zero.
    """

    def __init__(self, *, kernel32=None):
        """
        Args:
            kernel32: The bound kernel32; None binds the real one on first
                use.
        """
        self._kernel32 = kernel32
        self._previous_cpu: "tuple[int, int] | None" = None

    def read(self) -> HostMetrics:
        """Take one sample.

        Returns:
            The current metrics. Any source that cannot be read contributes
            its default rather than raising.
        """
        kernel32 = self._bound_kernel32()
        return HostMetrics(
            cpu_percent=self._read_cpu_percent(kernel32),
            memory_percent=self._read_memory_percent(kernel32),
            disk_percent=self._read_disk_percent(),
            uptime_s=self._read_uptime_s(kernel32),
        )

    def _bound_kernel32(self):
        """kernel32, bound on first use; None where it cannot be."""
        if self._kernel32 is None:
            try:
                self._kernel32 = win32.libraries().kernel32
            except (OSError, AttributeError):
                return None
        return self._kernel32

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
            return 0.0
        share = (busy - previous[0]) / (total - previous[1])
        return max(0.0, min(100.0, 100.0 * share))

    def _read_memory_percent(self, kernel32) -> float:
        if kernel32 is None:
            return 0.0
        status = win32.MemoryStatusEx()
        status.dwLength = ctypes.sizeof(win32.MemoryStatusEx)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0.0
        if status.ullTotalPhys <= 0:
            return 0.0
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
