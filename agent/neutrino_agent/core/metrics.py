"""The shapes a heartbeat's metrics travel in.

Reading the numbers is each platform's own work, but every platform
serializes into these same shapes, so the hub draws one kind of device tile
whatever answers. The readings two platforms share live here: the NVIDIA
cards through ``nvidia-smi`` and the choice of processes a report lists.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import shutil
import socket
import subprocess
from dataclasses import dataclass, field

from neutrino_agent.constants import (
    AGENT_NVIDIA_SMI_COMMAND,
    AGENT_NVIDIA_SMI_TIMEOUT_S,
    AGENT_PROCESS_TOP_COUNT,
)

# The words a graphics card's name or driver carries, to its vendor.
GPU_VENDOR_WORDS = (
    ("nvidia", "nvidia"),
    ("geforce", "nvidia"),
    ("radeon", "amd"),
    ("amd", "amd"),
    ("intel", "intel"),
    ("apple", "apple"),
    ("agx", "apple"),
)


def hostname() -> str:
    """Read the device's hostname.

    Returns:
        The hostname, or ``unknown`` when it cannot be determined.
    """
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def read_nvidia_gpus() -> "list[GpuMetrics]":
    """Every NVIDIA card through ``nvidia-smi``, where the driver installed it.

    Returns:
        One entry per card; empty when the tool is missing or fails.
    """
    if shutil.which(AGENT_NVIDIA_SMI_COMMAND[0]) is None:
        return []
    try:
        result = subprocess.run(
            AGENT_NVIDIA_SMI_COMMAND,
            capture_output=True,
            text=True,
            timeout=AGENT_NVIDIA_SMI_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return parse_nvidia_smi(result.stdout or "")


def parse_nvidia_smi(text: str) -> "list[GpuMetrics]":
    """The cards out of ``nvidia-smi``'s CSV, one line per card.

    Args:
        text: What ``AGENT_NVIDIA_SMI_COMMAND`` printed.

    Returns:
        One entry per well-formed line, in its order.
    """
    gpus = []
    for line in text.splitlines():
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
                memory_used_mb=int(memory_used) if memory_used is not None else None,
                memory_total_mb=(
                    int(memory_total) if memory_total is not None else None
                ),
                temperature_c=_csv_number(parts[4]),
                power_w=_csv_number(parts[5]),
            )
        )
    return gpus


def gpu_vendor(text: str) -> str:
    """The vendor a card's name or driver class names.

    Args:
        text: The card's name, or its driver's class.

    Returns:
        ``nvidia``, ``amd``, ``intel`` or ``apple``; empty when the text
        names none of them.
    """
    lowered = (text or "").lower()
    for word, vendor in GPU_VENDOR_WORDS:
        if word in lowered:
            return vendor
    return ""


def busiest_processes(processes: "list[ProcessMetrics]") -> "list[ProcessMetrics]":
    """The processes a report lists: by processor share, then memory.

    Args:
        processes: Every process sampled.

    Returns:
        At most ``AGENT_PROCESS_TOP_COUNT`` of them, the busiest first.
    """
    ordered = sorted(
        processes,
        key=_process_load,
        reverse=True,
    )
    return ordered[:AGENT_PROCESS_TOP_COUNT]


def _csv_number(text: str) -> "float | None":
    """One ``nvidia-smi`` CSV field, None for its not-available marker."""
    try:
        return float(text.strip())
    except ValueError:
        return None


def _process_load(process: "ProcessMetrics") -> "tuple[float, float]":
    return process.cpu_percent, process.memory_percent


def _rounded(value: "float | None", digits: int) -> "float | None":
    return round(value, digits) if value is not None else None


@dataclass
class GpuMetrics:
    """One graphics card's load.

    Attributes:
        vendor: ``nvidia``, ``amd``, ``intel`` or ``apple``; empty when
            the source names none.
        name: Marketing name when the driver reports one.
        utilization_percent: Compute load, when readable.
        memory_used_mb: Video memory in use, when readable.
        memory_total_mb: Video memory installed, when readable.
        temperature_c: Core temperature, when readable.
        power_w: Draw in watts, when readable.
    """

    vendor: str
    name: str
    utilization_percent: "float | None" = None
    memory_used_mb: "int | None" = None
    memory_total_mb: "int | None" = None
    temperature_c: "float | None" = None
    power_w: "float | None" = None

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
        user: Owning account name; on Linux and macOS the numeric uid when
            unresolvable, on Windows empty when the token cannot be read.
        name: The command's name: ``/proc/<pid>/comm`` on Linux, the image
            name on Windows, the executable's file name on macOS.
        cpu_percent: Share of one core since the previous sample; on macOS
            the share ``ps`` reports.
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
    cpu_core_percents: "list[float]" = field(default_factory=list)
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    temperature_c: "float | None" = None
    uptime_s: int = 0
    load_average: "list[float]" = field(default_factory=list)
    gpus: "list[GpuMetrics]" = field(default_factory=list)
    processes: "list[ProcessMetrics]" = field(default_factory=list)

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
