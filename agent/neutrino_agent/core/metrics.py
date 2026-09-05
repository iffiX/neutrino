"""The shapes a heartbeat's metrics travel in.

Reading the numbers is each platform's own work — the Linux platform samples
``/proc`` and ``/sys`` — but every platform serializes into these same
shapes, so the hub draws one kind of device tile whatever answers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import socket
from dataclasses import dataclass, field


def hostname() -> str:
    """Read the device's hostname.

    Returns:
        The hostname, or ``unknown`` when it cannot be determined.
    """
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _rounded(value: "float | None", digits: int) -> "float | None":
    return round(value, digits) if value is not None else None


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
