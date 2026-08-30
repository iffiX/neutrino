"""Reading host metrics with nothing but the standard library.

psutil is not available on a stock Raspbian or a minimal Ubuntu, and asking an
operator to pip-install onto every managed device defeats the point of a
one-click agent. Everything here comes from ``/proc`` and ``/sys`` instead,
with one exception: NVIDIA exposes nothing readable in sysfs, so those cards
are read through ``nvidia-smi`` when the driver has installed it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None
from dataclasses import dataclass, field

PROC_PATH = "/proc"
PROC_STAT_PATH = "/proc/stat"
PROC_MEMINFO_PATH = "/proc/meminfo"
PROC_UPTIME_PATH = "/proc/uptime"
THERMAL_ZONE_GLOB = "/sys/class/thermal"

DRM_CARDS_PATH = "/sys/class/drm"
DRM_CARD_PATTERN = re.compile(r"^card\d+$")
AMD_VENDOR_ID = "0x1002"

NVIDIA_SMI_TIMEOUT_S = 4
NVIDIA_SMI_COMMAND = (
    "nvidia-smi",
    "--query-gpu=name,utilization.gpu,memory.used,memory.total,"
    "temperature.gpu,power.draw",
    "--format=csv,noheader,nounits",
)

PROCESS_TOP_COUNT = 12


@dataclass
class GpuMetrics:
    """One graphics card's load.

    Attributes:
        vendor: ``nvidia`` or ``amd``.
        name: Marketing name when the driver reports one.
        utilization_percent: Compute load, when readable.
        memory_used_mb: Video memory in use, when readable.
        memory_total_mb: Video memory installed, when readable.
        temperature_c: Core temperature, when readable.
        power_w: Draw in watts, when readable.
    """

    vendor: str
    name: str
    utilization_percent: float | None = None
    memory_used_mb: int | None = None
    memory_total_mb: int | None = None
    temperature_c: float | None = None
    power_w: float | None = None

    def to_dict(self) -> dict:
        """Serialize for the heartbeat payload.

        Returns:
            A JSON-ready object.
        """
        return {
            "vendor": self.vendor,
            "name": self.name,
            "utilization_percent": _rounded(self.utilization_percent, 1),
            "memory_used_mb": self.memory_used_mb,
            "memory_total_mb": self.memory_total_mb,
            "temperature_c": _rounded(self.temperature_c, 1),
            "power_w": _rounded(self.power_w, 1),
        }


@dataclass
class ProcessMetrics:
    """One process, as the panel's monitor lists it.

    Attributes:
        pid: Process id.
        user: Owning account name, or the numeric uid when unresolvable.
        name: Command name from ``/proc/<pid>/comm``.
        cpu_percent: Share of one core since the previous sample.
        memory_percent: Resident share of physical memory.
    """

    pid: int
    user: str
    name: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0

    def to_dict(self) -> dict:
        """Serialize for the heartbeat payload.

        Returns:
            A JSON-ready object.
        """
        return {
            "pid": self.pid,
            "user": self.user,
            "name": self.name,
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_percent": round(self.memory_percent, 1),
        }


@dataclass
class HostMetrics:
    """One sample of the device's health.

    Attributes:
        cpu_percent: Processor load since the previous sample.
        cpu_core_percents: The same, per core, in core order.
        memory_percent: Share of memory in use.
        disk_percent: Share of the root filesystem in use.
        temperature_c: Highest thermal zone reading, when the device has one.
        uptime_s: Seconds since boot.
        load_average: The one, five, and fifteen minute load averages.
        gpus: Graphics cards the device exposes, when any.
        processes: The busiest processes, ordered by processor share.
    """

    cpu_percent: float = 0.0
    cpu_core_percents: list[float] = field(default_factory=list)
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    temperature_c: float | None = None
    uptime_s: int = 0
    load_average: list[float] = field(default_factory=list)
    gpus: list[GpuMetrics] = field(default_factory=list)
    processes: list[ProcessMetrics] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for the heartbeat payload.

        Returns:
            A JSON-ready object.
        """
        return {
            "cpu_percent": round(self.cpu_percent, 1),
            "cpu_core_percents": [round(value, 1) for value in self.cpu_core_percents],
            "memory_percent": round(self.memory_percent, 1),
            "disk_percent": round(self.disk_percent, 1),
            "temperature_c": _rounded(self.temperature_c, 1),
            "uptime_s": self.uptime_s,
            "load_average": [round(value, 2) for value in self.load_average],
            "gpus": [gpu.to_dict() for gpu in self.gpus],
            "processes": [process.to_dict() for process in self.processes],
        }


def hostname() -> str:
    """Read the device's hostname.

    Returns:
        The hostname, or ``unknown`` when it cannot be determined.
    """
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _rounded(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


def _csv_number(text: str) -> float | None:
    """Parse one ``nvidia-smi`` CSV field, which may be a not-available marker.

    Args:
        text: The raw field.

    Returns:
        The value, or None when the driver reports none.
    """
    try:
        return float(text.strip())
    except ValueError:
        return None


def _read_int(path: str) -> int | None:
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return int(stream.read().strip())
    except (OSError, ValueError):
        return None


class HostMetricsReader:
    """Samples host metrics, remembering the previous counters.

    Processor load — of the host, of each core, and of each process — is a
    rate, so the first sample after start has nothing to compare against and
    reports zero rather than a misleading average-since-boot figure.
    """

    def __init__(self):
        self._previous_cpu: dict[str, tuple[int, int]] = {}
        self._previous_process_jiffies: dict[int, int] = {}
        self._total_jiffies_delta = 0
        self._core_count = 1
        self._memory_total_kb = 0
        # /proc is Linux-only; on other systems the process table stays empty
        # and the agent reports what it can.
        self._page_bytes = (
            os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        )
        self._users: dict[int, str] = {}

    def read(self) -> HostMetrics:
        """Take one sample.

        Returns:
            The current metrics. Any source that cannot be read contributes its
            default rather than raising, so an unusual device still reports what
            it can.
        """
        cpu_percent, core_percents = self._read_cpu_percents()
        return HostMetrics(
            cpu_percent=cpu_percent,
            cpu_core_percents=core_percents,
            memory_percent=self._read_memory_percent(),
            disk_percent=self._read_disk_percent(),
            temperature_c=self._read_temperature_c(),
            uptime_s=self._read_uptime_s(),
            load_average=self._read_load_average(),
            gpus=self._read_gpus(),
            processes=self._read_processes(),
        )

    def _read_cpu_percents(self) -> tuple[float, list[float]]:
        try:
            with open(PROC_STAT_PATH, "r", encoding="utf-8") as stream:
                lines = [line.split() for line in stream if line.startswith("cpu")]
        except OSError:
            return 0.0, []

        overall = 0.0
        cores = []
        for fields in lines:
            if len(fields) < 5:
                continue
            key = fields[0]
            values = [int(value) for value in fields[1:]]
            total = sum(values)
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            busy = total - idle

            previous_busy, previous_total = self._previous_cpu.get(key, (0, 0))
            busy_delta = busy - previous_busy
            total_delta = total - previous_total
            self._previous_cpu[key] = (busy, total)
            percent = (
                max(0.0, min(100.0, 100.0 * busy_delta / total_delta))
                if total_delta > 0
                else 0.0
            )
            if key == "cpu":
                overall = percent
                # Remembered for process shares: a process's jiffies are
                # measured against this same all-core delta.
                self._total_jiffies_delta = total_delta
            else:
                cores.append(percent)
        self._core_count = max(1, len(cores))
        return overall, cores

    def _read_memory_percent(self) -> float:
        try:
            with open(PROC_MEMINFO_PATH, "r", encoding="utf-8") as stream:
                info = {}
                for line in stream:
                    key, _, rest = line.partition(":")
                    info[key] = int(rest.split()[0])
        except (OSError, ValueError, IndexError):
            return 0.0
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", info.get("MemFree", 0))
        self._memory_total_kb = total
        if total <= 0:
            return 0.0
        return 100.0 * (total - available) / total

    def _read_disk_percent(self) -> float:
        try:
            usage = shutil.disk_usage("/")
        except OSError:
            return 0.0
        if usage.total <= 0:
            return 0.0
        return 100.0 * usage.used / usage.total

    def _read_temperature_c(self) -> float | None:
        readings = []
        try:
            zones = os.listdir(THERMAL_ZONE_GLOB)
        except OSError:
            return None
        for zone in zones:
            if not zone.startswith("thermal_zone"):
                continue
            path = os.path.join(THERMAL_ZONE_GLOB, zone, "temp")
            try:
                with open(path, "r", encoding="utf-8") as stream:
                    readings.append(int(stream.read().strip()) / 1000.0)
            except (OSError, ValueError):
                continue
        return max(readings) if readings else None

    def _read_uptime_s(self) -> int:
        try:
            with open(PROC_UPTIME_PATH, "r", encoding="utf-8") as stream:
                return int(float(stream.read().split()[0]))
        except (OSError, ValueError, IndexError):
            return int(time.time())

    def _read_load_average(self) -> list[float]:
        try:
            return list(os.getloadavg())
        except (OSError, AttributeError):
            return []

    def _read_gpus(self) -> list[GpuMetrics]:
        return self._read_nvidia_gpus() + self._read_amd_gpus()

    def _read_nvidia_gpus(self) -> list[GpuMetrics]:
        if shutil.which(NVIDIA_SMI_COMMAND[0]) is None:
            return []
        try:
            result = subprocess.run(
                NVIDIA_SMI_COMMAND,
                capture_output=True,
                text=True,
                timeout=NVIDIA_SMI_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []

        gpus = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 6:
                continue
            memory_used = _csv_number(parts[2])
            memory_total = _csv_number(parts[3])
            gpus.append(
                GpuMetrics(
                    vendor="nvidia",
                    name=parts[0],
                    utilization_percent=_csv_number(parts[1]),
                    memory_used_mb=(
                        int(memory_used) if memory_used is not None else None
                    ),
                    memory_total_mb=(
                        int(memory_total) if memory_total is not None else None
                    ),
                    temperature_c=_csv_number(parts[4]),
                    power_w=_csv_number(parts[5]),
                )
            )
        return gpus

    def _read_amd_gpus(self) -> list[GpuMetrics]:
        try:
            cards = sorted(
                entry
                for entry in os.listdir(DRM_CARDS_PATH)
                if DRM_CARD_PATTERN.match(entry)
            )
        except OSError:
            return []

        gpus = []
        for card in cards:
            device = os.path.join(DRM_CARDS_PATH, card, "device")
            try:
                with open(
                    os.path.join(device, "vendor"), "r", encoding="utf-8"
                ) as stream:
                    vendor = stream.read().strip()
            except OSError:
                continue
            if vendor != AMD_VENDOR_ID:
                continue

            busy = _read_int(os.path.join(device, "gpu_busy_percent"))
            used_bytes = _read_int(os.path.join(device, "mem_info_vram_used"))
            total_bytes = _read_int(os.path.join(device, "mem_info_vram_total"))
            temperature, power = self._read_amd_hwmon(device)
            gpus.append(
                GpuMetrics(
                    vendor="amd",
                    name="AMD GPU",
                    utilization_percent=float(busy) if busy is not None else None,
                    memory_used_mb=(
                        used_bytes // (1024 * 1024) if used_bytes is not None else None
                    ),
                    memory_total_mb=(
                        total_bytes // (1024 * 1024)
                        if total_bytes is not None
                        else None
                    ),
                    temperature_c=temperature,
                    power_w=power,
                )
            )
        return gpus

    def _read_amd_hwmon(self, device: str) -> tuple[float | None, float | None]:
        root = os.path.join(device, "hwmon")
        try:
            monitors = os.listdir(root)
        except OSError:
            return None, None
        for monitor in monitors:
            temp_raw = _read_int(os.path.join(root, monitor, "temp1_input"))
            power_raw = _read_int(os.path.join(root, monitor, "power1_average"))
            if temp_raw is not None or power_raw is not None:
                return (
                    temp_raw / 1000.0 if temp_raw is not None else None,
                    power_raw / 1_000_000.0 if power_raw is not None else None,
                )
        return None, None

    def _read_processes(self) -> list[ProcessMetrics]:
        try:
            entries = [entry for entry in os.listdir(PROC_PATH) if entry.isdigit()]
        except OSError:
            return []

        current_jiffies: dict[int, int] = {}
        processes = []
        for entry in entries:
            pid = int(entry)
            sample = self._read_process(pid)
            if sample is None:
                continue
            process, jiffies = sample
            current_jiffies[pid] = jiffies
            processes.append(process)

        # Replaced wholesale so counters of exited processes are not kept, and
        # a recycled pid cannot inherit a dead process's total.
        self._previous_process_jiffies = current_jiffies
        processes.sort(
            key=lambda process: (process.cpu_percent, process.memory_percent),
            reverse=True,
        )
        return processes[:PROCESS_TOP_COUNT]

    def _read_process(self, pid: int) -> tuple[ProcessMetrics, int] | None:
        base = os.path.join(PROC_PATH, str(pid))
        try:
            with open(os.path.join(base, "stat"), "r", encoding="utf-8") as stream:
                stat = stream.read()
            with open(os.path.join(base, "comm"), "r", encoding="utf-8") as stream:
                name = stream.read().strip()
            with open(os.path.join(base, "statm"), "r", encoding="utf-8") as stream:
                resident_pages = int(stream.read().split()[1])
            uid = os.stat(base).st_uid
        except (OSError, ValueError, IndexError):
            return None

        # The command name sits in parentheses and may contain spaces, so the
        # fields after it are found from the last ") " rather than by splitting
        # the whole line.
        try:
            fields = stat.rsplit(") ", 1)[1].split()
            jiffies = int(fields[11]) + int(fields[12])
        except (IndexError, ValueError):
            return None

        previous = self._previous_process_jiffies.get(pid, jiffies)
        cpu_percent = 0.0
        if self._total_jiffies_delta > 0:
            share = (jiffies - previous) / self._total_jiffies_delta
            cpu_percent = max(0.0, 100.0 * share * self._core_count)

        memory_percent = 0.0
        if self._memory_total_kb > 0:
            resident_kb = resident_pages * self._page_bytes / 1024
            memory_percent = 100.0 * resident_kb / self._memory_total_kb

        return (
            ProcessMetrics(
                pid=pid,
                user=self._user_name(uid),
                name=name,
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
            ),
            jiffies,
        )

    def _user_name(self, uid: int) -> str:
        if uid not in self._users:
            try:
                self._users[uid] = pwd.getpwuid(uid).pw_name
            except (KeyError, AttributeError):
                self._users[uid] = str(uid)
        return self._users[uid]
