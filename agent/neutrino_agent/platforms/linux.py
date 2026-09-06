"""The Linux platform, complete.

Metrics come from ``/proc`` and ``/sys`` with nothing but the standard
library: psutil is not available on a stock Raspbian or a minimal Ubuntu,
and asking an operator to pip-install onto every managed device defeats the
point of a one-click agent. NVIDIA is the one exception — it exposes nothing
readable in sysfs, so those cards are read through ``nvidia-smi`` when the
driver has installed it.

Stepping down to an account is ``runuser -u <account> --``, never ``sudo``;
the reasoning is docs/standard/design/privilege.md.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import shutil
import socket
import struct
import subprocess
import time

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_agent.modules import installers
from neutrino_agent.constants import (
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_CONTROL_SOCKET_PATH,
    AGENT_SERVICE_NAME,
    AGENT_STEP_DOWN_TIMEOUT_S,
)
from neutrino_agent.core.metrics import GpuMetrics, HostMetrics, ProcessMetrics
from neutrino_agent.platforms.base import AgentPlatform, ShareAttachError

# Accounts below this uid are the system's, not people's.
LINUX_HUMAN_UID_FLOOR = 1000
LINUX_NOBODY_UID = 65534
LINUX_NO_LOGIN_SHELLS = ("nologin", "false")

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

CIFS_HELPER = "mount.cifs"
CIFS_MOUNT_TIMEOUT_S = 60
PROC_MOUNTS_PATH = "/proc/mounts"
# How /proc/mounts spells the characters a mount point may not carry plainly.
PROC_MOUNTS_ESCAPES = (
    ("\\", "\\134"),
    (" ", "\\040"),
    ("\t", "\\011"),
    ("\n", "\\012"),
)

POWER_COMMANDS = {
    "reboot": ["systemctl", "reboot"],
    "poweroff": ["systemctl", "poweroff"],
}


def _csv_number(text: str) -> "float | None":
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


def _read_int(path: str) -> "int | None":
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return int(stream.read().strip())
    except (OSError, ValueError):
        return None


class LinuxPlatform(AgentPlatform):
    """Linux behind the platform contract."""

    os_name = "linux"
    capabilities = frozenset(
        {
            "accounts",
            "account_files",
            "run_as",
            "control_socket",
            "agent_service",
            "power",
            "metrics",
            "packages",
            "system_packages",
            "openssh",
            "shares",
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
        if pwd is None:
            return []
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
        if pwd is None:
            raise KeyError(account)
        return pwd.getpwnam(account).pw_dir

    def control_socket_path(self) -> str:
        """Where the agent's control socket lives.

        Returns:
            The absolute socket path.
        """
        return AGENT_CONTROL_SOCKET_PATH

    def read_peer_identity(self, connection) -> dict:
        """The peer's identity, from the kernel's ``SO_PEERCRED``.

        Args:
            connection: The accepted socket.

        Returns:
            ``{"account", "uid", "is_privileged"}``.

        Raises:
            KeyError: When the peer's uid names no account.
        """
        data = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
        )
        _pid, uid, _gid = struct.unpack("3i", data)
        if uid == 0:
            return {"account": "root", "uid": 0, "is_privileged": True}
        if pwd is None:
            raise KeyError(uid)
        return {
            "account": pwd.getpwuid(uid).pw_name,
            "uid": uid,
            "is_privileged": False,
        }

    def run_as_account(
        self,
        account: str,
        argv: list,
        *,
        stdin: str = "",
        timeout_s: int = AGENT_STEP_DOWN_TIMEOUT_S,
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

        Returns:
            The completed process, with text output captured.
        """
        command = list(argv)
        env = None
        if account and os.geteuid() == 0:
            command = ["runuser", "-u", account, "--"] + command
            env = self._account_env(account)
        return subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )

    def has_mount_tooling(self) -> bool:
        """Whether ``mount.cifs`` is on this machine."""
        return shutil.which(CIFS_HELPER) is not None

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

    def write_share_credentials(
        self, *, credentials_path: str, username: str, password: str
    ) -> None:
        """Keep a share's login as a root-only credentials file."""
        self._write_share_credentials(credentials_path, username, password)

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

    def attach_share(
        self,
        *,
        account: str,
        share_url: str,
        username: str,
        password: str,
        location: str,
        credentials_path: str = "",
    ) -> None:
        """Mount a CIFS share, ownership-mapped under the account's own home.

        The password becomes the credentials file and never a command-line
        argument. A location under the asking account's home carries ``uid=``
        and ``gid=`` so what appears belongs to the account; anywhere else
        the share's own permissions rule.

        Args:
            account: The asking account.
            share_url: The share, as ``//host/name``.
            username: The share's own username.
            password: The share's own password; empty reattaches with the
                credentials file already there.
            location: The mount point.
            credentials_path: Where this attachment's credentials file lives.

        Raises:
            ShareAttachError: ``cifs_missing`` without ``mount.cifs``,
                ``credentials_missing`` without the file, ``mount_failed``
                with the tool's own words otherwise.
        """
        if shutil.which(CIFS_HELPER) is None:
            raise ShareAttachError("cifs_missing")
        if password:
            self._write_share_credentials(credentials_path, username, password)
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        options = self._mount_options(
            account=account, location=location, credentials_path=credentials_path
        )
        command = ["mount", "-t", "cifs", share_url, location, "-o", options]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=CIFS_MOUNT_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError("mount_failed", detail=str(error)[:200])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-200:]
            raise ShareAttachError("mount_failed", detail=detail)

    def detach_share(self, *, location: str) -> None:
        """Unmount the share at a location.

        Args:
            location: The mount point.

        Raises:
            ShareAttachError: ``unmount_failed`` with the tool's own words.
        """
        try:
            result = subprocess.run(
                ["umount", location],
                capture_output=True,
                text=True,
                timeout=CIFS_MOUNT_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError("unmount_failed", detail=str(error)[:200])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-200:]
            raise ShareAttachError("unmount_failed", detail=detail)

    def is_share_attached(self, *, location: str) -> bool:
        """Whether anything is mounted at a location, read from the kernel.

        Args:
            location: The mount point.

        Returns:
            True when ``/proc/mounts`` names it.
        """
        encoded = location
        for character, escape in PROC_MOUNTS_ESCAPES:
            encoded = encoded.replace(character, escape)
        try:
            with open(PROC_MOUNTS_PATH, "r", encoding="utf-8") as stream:
                lines = stream.readlines()
        except OSError:
            return False
        for line in lines:
            fields = line.split()
            if len(fields) >= 2 and fields[1] == encoded:
                return True
        return False

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

    def install_openssh(self, entry: dict) -> None:
        """Install the SSH server package and start its unit.

        Args:
            entry: The manifest's platform entry, naming the packages and
                the service.

        Raises:
            InstallError: If the install or systemd refuses.
        """
        if shutil.which("sshd") is None and not os.path.exists("/usr/sbin/sshd"):
            for package in entry.get("packages") or ["openssh-server"]:
                self._install_system_package(package)
        service = entry.get("service", "ssh")
        installers.run_checked(["systemctl", "enable", "--now", service])

    def uninstall_openssh(self, entry: dict) -> None:
        """Stop the SSH server's unit and remove its package.

        Args:
            entry: The manifest's platform entry, naming the packages and
                the service.

        Raises:
            InstallError: If systemd or the package manager refuses.
        """
        service = entry.get("service", "ssh")
        installers.run_checked(["systemctl", "disable", "--now", service])
        self.remove_system_packages(entry.get("packages") or ["openssh-server"])

    def read_openssh_status(self, entry: dict) -> bool:
        """Whether the SSH server is installed and running.

        Args:
            entry: The manifest's platform entry.

        Returns:
            True when the service is active.
        """
        try:
            result = subprocess.run(
                ["systemctl", "is-active", entry.get("service", "ssh")],
                capture_output=True,
                text=True,
                timeout=AGENT_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.stdout.strip() == "active"

    def _mount_options(
        self, *, account: str, location: str, credentials_path: str
    ) -> str:
        """The mount options one attachment takes.

        Args:
            account: The asking account.
            location: The mount point.
            credentials_path: The credentials file.

        Returns:
            The ``-o`` string: the credentials file, plus ``uid=``/``gid=``
            when the location sits under the account's own home.
        """
        options = [f"credentials={credentials_path}"]
        try:
            entry = pwd.getpwnam(account) if pwd is not None and account else None
        except KeyError:
            entry = None
        if entry is not None:
            home = entry.pw_dir.rstrip("/")
            if home and (location == home or location.startswith(home + "/")):
                options.append(f"uid={entry.pw_uid}")
                options.append(f"gid={entry.pw_gid}")
        return ",".join(options)

    def _write_share_credentials(self, path: str, username: str, password: str) -> None:
        """Write one attachment's credentials file, root-only mode 0600.

        Args:
            path: The credentials file.
            username: The share's own username.
            password: The share's own password.
        """
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
            os.chmod(directory, 0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"username={username}\npassword={password}\n")

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
            entry = pwd.getpwnam(account) if pwd is not None else None
        except KeyError:
            entry = None
        if entry is None:
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
        return self._read_nvidia_gpus() + self._read_amd_gpus()

    def _read_nvidia_gpus(self) -> "list[GpuMetrics]":
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
        processes.sort(
            key=lambda process: (process.cpu_percent, process.memory_percent),
            reverse=True,
        )
        return processes[:PROCESS_TOP_COUNT]

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
            except (KeyError, AttributeError):
                self._users[uid] = str(uid)
        return self._users[uid]
