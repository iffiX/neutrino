"""The Linux platform, complete.

Metrics come from ``/proc`` and ``/sys`` with nothing but the standard
library: psutil is not available on a stock Raspbian or a minimal Ubuntu,
and asking an operator to pip-install onto every managed device defeats the
point of a one-click agent. NVIDIA is the one exception — it exposes nothing
readable in sysfs, so those cards are read through ``nvidia-smi`` when the
driver has installed it.

Stepping down to an account is ``runuser -u <account> --``, never ``sudo``;
the reasoning is skills/core-code-author/design/privilege.md.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time

from neutrino_agent.constants import (
    AGENT_ADDED_NAME_PREFIX,
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_CONTROL_SOCKET_PATH,
    AGENT_SERVICE_NAME,
    AGENT_STEP_DOWN_TIMEOUT_S,
    AGENT_SYSTEMD_UNIT_DIR,
)
from neutrino_agent.core.metrics import (
    GpuMetrics,
    HostMetrics,
    ProcessMetrics,
    busiest_processes,
    read_nvidia_gpus,
)
from neutrino_agent.modules import installers
from neutrino_agent.platforms.answered_run import run_on_pty
from neutrino_agent.platforms.base import AgentPlatform, is_added_name

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

# Accounts below this uid are the system's, not people's.
LINUX_HUMAN_UID_FLOOR = 1000
LINUX_NOBODY_UID = 65534
LINUX_NO_LOGIN_SHELLS = ("nologin", "false")

PROC_PATH = "/proc"
PROC_STAT_PATH = "/proc/stat"
PROC_MEMINFO_PATH = "/proc/meminfo"
PROC_UPTIME_PATH = "/proc/uptime"
THERMAL_ZONE_GLOB = "/sys/class/thermal"

# The directories beside the units that hold an enabled unit's links.
SYSTEMD_LINK_DIR_SUFFIXES = (".wants", ".requires")
SYSTEMD_DROP_IN_SUFFIX = ".d"
SYSTEMD_TIMEOUT_S = 30

DRM_CARDS_PATH = "/sys/class/drm"
DRM_CARD_PATTERN = re.compile(r"^card\d+$")
AMD_VENDOR_ID = "0x1002"

# Where systemd and dbus keep the machine id; the first that holds one wins.
LINUX_MACHINE_ID_PATHS = ("/etc/machine-id", "/var/lib/dbus/machine-id")

IP_ADDR_COMMAND = ("ip", "-j", "addr")
IP_ADDR_TIMEOUT_S = 10
LINUX_LOOPBACK_NAME = "lo"
LINUX_UNSET_MAC = "00:00:00:00:00:00"

# Forced: the panel's button means now. Without it systemd stops every unit
# in order and waits out each one's stop timeout, which on a desktop can be
# minutes; with one `--force` processes are ended and the filesystems still
# synced and unmounted.
POWER_COMMANDS = {
    "reboot": ["systemctl", "reboot", "--force"],
    "poweroff": ["systemctl", "poweroff", "--force"],
}


def _read_int(path: str) -> "int | None":
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return int(stream.read().strip())
    except (OSError, ValueError):
        return None


def _interface_mac(entry: dict) -> str:
    """One iproute2 entry's MAC, empty when it has none or an all-zero one."""
    mac = str(entry.get("address", "") or "").strip().lower()
    return "" if mac == LINUX_UNSET_MAC else mac


def _interface_addresses(entry: dict) -> list:
    """One iproute2 entry's IPv4 and IPv6 addresses, in its order."""
    addresses = []
    for info in entry.get("addr_info", []) or []:
        if not isinstance(info, dict) or info.get("family") not in ("inet", "inet6"):
            continue
        local = str(info.get("local", "") or "")
        if local:
            addresses.append(local)
    return addresses


def _systemctl(arguments: list) -> str:
    """Run one systemctl command, best-effort.

    Args:
        arguments: What follows ``systemctl``.

    Returns:
        Its standard output, empty when it could not run.
    """
    try:
        result = subprocess.run(
            ["systemctl", *arguments],
            capture_output=True,
            text=True,
            timeout=SYSTEMD_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout or ""


def _remove_path(path: str) -> None:
    """Delete one file, link or directory tree; a missing one is no error."""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)
    except FileNotFoundError:
        pass


class LinuxPlatform(AgentPlatform):
    """Linux behind the platform contract."""

    os_name = "linux"
    capabilities = frozenset(
        {
            "accounts",
            "run_as",
            "account_shell",
            "control_socket",
            "agent_service",
            "power",
            "metrics",
            "network",
            "machine_id",
            "packages",
            "system_packages",
            "removal",
        }
    )

    def __init__(self):
        self._metrics_reader = HostMetricsReader()

    def human_accounts(self) -> list:
        """The accounts that are people: uid at the floor or above, a shell
        someone can log in with, and a home directory that exists.

        Returns:
            Account names, sorted.
        """
        accounts = []
        for entry in pwd.getpwall():
            if entry.pw_uid < LINUX_HUMAN_UID_FLOOR:
                continue
            if entry.pw_uid == LINUX_NOBODY_UID:
                continue
            shell = entry.pw_shell or ""
            if not shell or os.path.basename(shell) in LINUX_NO_LOGIN_SHELLS:
                continue
            if not entry.pw_dir or not os.path.isdir(entry.pw_dir):
                continue
            accounts.append(entry.pw_name)
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
        """Where the agent's control socket lives.

        Returns:
            The absolute socket path.
        """
        return AGENT_CONTROL_SOCKET_PATH

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
        """Run a process as an account, through ``runuser`` when root.

        ``runuser`` passes the environment through, so the child gets the
        account's own ``HOME``, ``USER`` and ``LOGNAME`` set here — otherwise
        anything resolving ``~`` under a root agent lands in root's home.

        Args:
            account: The account; empty runs as the agent itself.
            argv: Argument vector.
            stdin: Sent to the process's standard input.
            timeout_s: How long to wait.
            password: Unused here; Windows needs it.
            environment: Variables set for the process beside the account's
                own; None sets none.

        Returns:
            The completed process, with text output captured.
        """
        command = list(argv)
        env = None
        if account and os.geteuid() == 0:
            command = ["runuser", "-u", account, "--"] + command
            env = self._account_env(account)
        if environment:
            env = dict(env if env is not None else os.environ, **environment)
        return subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )

    def account_process(self, account: str, argv: list) -> tuple:
        """How a long-lived process starts as an account: through ``runuser`` when root.

        Args:
            account: The account.
            argv: Argument vector.

        Returns:
            ``(argv, popen_arguments)``: ``runuser -u <account> --`` before
            the argument vector when the agent is root, the account's home
            as the working directory, and the environment with its ``HOME``,
            ``USER`` and ``LOGNAME``.

        Raises:
            KeyError: When the account database has no such account.
        """
        entry = pwd.getpwnam(account)
        command = list(argv)
        if os.geteuid() == 0:
            command = ["runuser", "-u", account, "--"] + command
        return command, {"cwd": entry.pw_dir, "env": self._account_env(account)}

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
        """Run a process as an account on a pseudo-terminal, answering one question.

        Args:
            account: The account.
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long to wait.
            password: Unused here; Windows needs it.
            environment: Variables set for the process beside the account's
                own; None sets none.

        Returns:
            ``(returncode, output)``; 127 when it could not start.

        Raises:
            PlatformUnsupportedError: Where this interpreter has no
                pseudo-terminal.
        """
        command = list(argv)
        env = None
        if account and os.geteuid() == 0:
            command = ["runuser", "-u", account, "--"] + command
            env = self._account_env(account)
        if environment:
            env = dict(env if env is not None else os.environ, **environment)
        return run_on_pty(
            command, prompt=prompt, answer=answer, timeout_s=timeout_s, env=env
        )

    def install_system_packages(self, names: list) -> str:
        """Install packages by name with apt, dnf or yum.

        Args:
            names: The package names.

        Returns:
            The installers' combined output.

        Raises:
            InstallError: If the package manager refuses — no repository
                reachable, or a package unknown.
        """
        return "\n".join(self._install_system_package(name) for name in names)

    def remove_system_packages(self, names: list) -> str:
        """Remove packages by name, purging their configuration on apt.

        Args:
            names: The package names.

        Returns:
            The removal's combined output.

        Raises:
            InstallError: If the package manager refuses.
        """
        if not names:
            return ""
        if shutil.which("apt-get"):
            command = ["apt-get", "purge", "-y"] + list(names)
        else:
            manager = "dnf" if shutil.which("dnf") else "yum"
            command = [manager, "remove", "-y"] + list(names)
        return installers.run_checked(command, timeout_s=installers.INSTALL_TIMEOUT_S)

    def _install_system_package(self, package: str) -> str:
        if shutil.which("apt-get"):
            return installers.run_checked(
                ["apt-get", "install", "-y", package],
                timeout_s=installers.INSTALL_TIMEOUT_S,
            )
        manager = "dnf" if shutil.which("dnf") else "yum"
        return installers.run_checked(
            [manager, "install", "-y", package],
            timeout_s=installers.INSTALL_TIMEOUT_S,
        )

    def read_agent_service_state(self) -> str:
        """What systemd says about the agent's own service.

        Returns:
            ``running``, a systemd state word, or ``unknown``.
        """
        try:
            result = subprocess.run(
                ["systemctl", "is-active", AGENT_SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        state = result.stdout.strip()
        return "running" if state == "active" else (state or "unknown")

    def start_agent_service(self) -> None:
        """Enable and start the agent's own service. Best-effort."""
        subprocess.run(
            ["systemctl", "enable", "--now", AGENT_SERVICE_NAME],
            capture_output=True,
            timeout=30,
            check=False,
        )

    def stop_agent_service(self) -> None:
        """Stop the agent's own service; it stays enabled. Best-effort."""
        subprocess.run(
            ["systemctl", "stop", AGENT_SERVICE_NAME],
            capture_output=True,
            timeout=30,
            check=False,
        )

    def disable_agent_service(self) -> None:
        """Disable the agent's own unit. Best-effort."""
        subprocess.run(
            ["systemctl", "disable", AGENT_SERVICE_NAME],
            capture_output=True,
            timeout=30,
            check=False,
        )

    def remove_added(self) -> list:
        """Disable, stop and delete the units the agent's modules wrote.

        A unit is the modules' when :func:`is_added_name` says so: every
        loaded one, template instances included, and every file under
        ``/etc/systemd/system``. Each is disabled and stopped, then its
        file, its drop-in directory and its links in the targets' wants are
        deleted. Units the packages installed under ``/lib`` and the hub's
        own are not touched.

        Returns:
            The units removed.
        """
        prefix = AGENT_ADDED_NAME_PREFIX
        units = {
            line.split()[0]
            for line in _systemctl(
                [
                    "list-units",
                    "--all",
                    "--plain",
                    "--no-legend",
                    "--full",
                    f"{prefix}*",
                ]
            ).splitlines()
            if line.strip() and is_added_name(line.split()[0], prefix)
        }
        try:
            entries = sorted(os.listdir(AGENT_SYSTEMD_UNIT_DIR))
        except OSError:
            entries = []
        files = [name for name in entries if is_added_name(name, prefix)]
        for name in files:
            if name.endswith(SYSTEMD_DROP_IN_SUFFIX):
                name = name[: -len(SYSTEMD_DROP_IN_SUFFIX)]
            units.add(name)
        for unit in sorted(units):
            _systemctl(["disable", "--now", unit])
        for entry in entries:
            directory = os.path.join(AGENT_SYSTEMD_UNIT_DIR, entry)
            if not entry.endswith(SYSTEMD_LINK_DIR_SUFFIXES):
                continue
            if not os.path.isdir(directory):
                continue
            for link in os.listdir(directory):
                if is_added_name(link, prefix):
                    _remove_path(os.path.join(directory, link))
        for name in files:
            _remove_path(os.path.join(AGENT_SYSTEMD_UNIT_DIR, name))
        _systemctl(["daemon-reload"])
        for unit in sorted(units):
            _systemctl(["reset-failed", unit])
        return sorted(units)

    def agent_service_start_hint(self) -> str:
        """The systemctl command that starts the agent's own service."""
        return f"sudo systemctl enable --now {AGENT_SERVICE_NAME}"

    def power(self, action: str) -> "tuple[int, str]":
        """Run one power action through systemd.

        Args:
            action: ``reboot`` or ``poweroff``.

        Returns:
            The exit code and combined output.
        """
        completed = subprocess.run(
            POWER_COMMANDS[action],
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
        """Every interface but loopback, from iproute2.

        Returns:
            ``[{"name", "mac", "addresses"}]`` in iproute2's order, the MAC
            empty where the interface has none or an all-zero one; empty
            when ``ip`` is missing, exits non-zero, or prints no JSON.
        """
        try:
            result = subprocess.run(
                IP_ADDR_COMMAND,
                capture_output=True,
                text=True,
                timeout=IP_ADDR_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []
        try:
            entries = json.loads(result.stdout or "")
        except ValueError:
            return []
        if not isinstance(entries, list):
            return []
        interfaces = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("ifname", "") or "")
            if not name or name == LINUX_LOOPBACK_NAME:
                continue
            interfaces.append(
                {
                    "name": name,
                    "mac": _interface_mac(entry),
                    "addresses": _interface_addresses(entry),
                }
            )
        return interfaces

    def read_machine_id(self) -> str:
        """The machine id systemd or dbus wrote.

        Returns:
            The id, empty when neither file holds one.
        """
        for path in LINUX_MACHINE_ID_PATHS:
            try:
                with open(path, "r", encoding="utf-8") as stream:
                    value = stream.read().strip()
            except OSError:
                continue
            if value:
                return value
        return ""

    def install_package(self, path: str, *, package_kind: str, entry: dict) -> None:
        """Install one downloaded package.

        Args:
            path: The downloaded file.
            package_kind: The package kind.
            entry: The manifest's platform entry.

        Raises:
            InstallError: If the installer fails or the kind is unknown.
        """
        installers.install_package(path, package_kind=package_kind, entry=entry)

    def uninstall_package(self, command: str) -> None:
        """Remove a package the way its manifest says to.

        Args:
            command: The manifest's removal command.

        Raises:
            InstallError: If the removal fails.
        """
        installers.uninstall_package(command)

    def _account_env(self, account: str) -> "dict | None":
        """The environment a stepped-down child runs with.

        Args:
            account: The target account.

        Returns:
            The environment with the account's own identity variables, or
            None when the account database has no entry — ``runuser`` then
            refuses the unknown account itself.
        """
        try:
            entry = pwd.getpwnam(account)
        except KeyError:
            return None
        env = dict(os.environ)
        env["HOME"] = entry.pw_dir
        env["USER"] = entry.pw_name
        env["LOGNAME"] = entry.pw_name
        return env


class HostMetricsReader:
    """Samples host metrics, remembering the previous counters.

    Processor load — of the host, of each core, and of each process — is a
    rate, so the first sample after start has nothing to compare against and
    reports zero rather than a misleading average-since-boot figure.
    """

    def __init__(self):
        self._previous_cpu: "dict[str, tuple[int, int]]" = {}
        self._previous_process_jiffies: "dict[int, int]" = {}
        self._total_jiffies_delta = 0
        self._core_count = 1
        self._memory_total_kb = 0
        self._page_bytes = (
            os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        )
        self._users: "dict[int, str]" = {}

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

    def _read_cpu_percents(self) -> "tuple[float, list[float]]":
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

    def _read_temperature_c(self) -> "float | None":
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

    def _read_load_average(self) -> "list[float]":
        try:
            return list(os.getloadavg())
        except (OSError, AttributeError):
            return []

    def _read_gpus(self) -> "list[GpuMetrics]":
        return read_nvidia_gpus() + self._read_amd_gpus()

    def _read_amd_gpus(self) -> "list[GpuMetrics]":
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

    def _read_amd_hwmon(self, device: str) -> "tuple[float | None, float | None]":
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

    def _read_processes(self) -> "list[ProcessMetrics]":
        try:
            entries = [entry for entry in os.listdir(PROC_PATH) if entry.isdigit()]
        except OSError:
            return []

        current_jiffies: "dict[int, int]" = {}
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
        return busiest_processes(processes)

    def _read_process(self, pid: int) -> "tuple[ProcessMetrics, int] | None":
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
            except KeyError:
                self._users[uid] = str(uid)
        return self._users[uid]
