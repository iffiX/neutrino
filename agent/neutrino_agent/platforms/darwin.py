"""The macOS platform behind the contract.

People come from ``dscl``, the directory service's own answer, with the 501
uid floor, no service accounts and ``IsHidden`` respected. Stepping down to
an account is ``su``, macOS's own step-down, for the same reason Linux uses
``runuser`` and never ``sudo``. Shares attach with ``mount_smbfs``, the
password riding a transient ``/etc/nsmb.conf`` section and never an
argument; SMB is native, so there is no tooling to install. The SSH server
is Remote Login — the sealed system volume keeps the binaries, so install
and uninstall switch it on and off. The agent's own service is a
LaunchDaemon driven with ``launchctl bootstrap``/``bootout``, the modern
subcommands. Metrics come from ``sysctl``, ``vm_stat`` and ``top``, each
parsed defensively.

Everything here is unit-tested with fakes; the mechanisms are verified
interactively on one real Mac, never in the pipeline.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import shlex
import shutil
import struct
import subprocess
import time
from urllib.parse import quote

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_agent.modules import installers
from neutrino_agent.constants import (
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_CONTROL_SOCKET_PATH_DARWIN,
    AGENT_STEP_DOWN_TIMEOUT_S,
)
from neutrino_agent.core.metrics import HostMetrics
from neutrino_agent.platforms.base import (
    AgentPlatform,
    PlatformUnsupportedError,
    ShareAttachError,
)

# Accounts below this uid are the system's, not people's, and every macOS
# service account wears the underscore prefix.
DARWIN_HUMAN_UID_FLOOR = 501
DARWIN_SERVICE_ACCOUNT_PREFIX = "_"
DARWIN_HIDDEN_VALUES = ("1", "true", "yes")

# getsockopt(SOL_LOCAL, LOCAL_PEERCRED) fills a struct xucred:
# version, uid, then the group list.
DARWIN_SOL_LOCAL = 0
DARWIN_LOCAL_PEERCRED = 1
DARWIN_XUCRED_FORMAT = "II"
DARWIN_XUCRED_SIZE = 76
DARWIN_XUCRED_VERSION = 0

# Where mount_smbfs reads a root asker's credentials from, and how long a
# mount may take.
DARWIN_NSMB_CONF_PATH = "/etc/nsmb.conf"
DARWIN_SMB_MOUNT_TIMEOUT_S = 60

# The agent's LaunchDaemon, once a macOS package ships it.
DARWIN_AGENT_LABEL = "com.neutrino.agent"
DARWIN_AGENT_PLIST = "/Library/LaunchDaemons/com.neutrino.agent.plist"

DARWIN_POWER_COMMANDS = {
    "reboot": ["shutdown", "-r", "now"],
    "poweroff": ["shutdown", "-h", "now"],
}


class DarwinPlatform(AgentPlatform):
    """macOS behind the platform contract."""

    os_name = "darwin"
    capabilities = frozenset(
        {
            "accounts",
            "account_files",
            "run_as",
            "control_socket",
            "packages",
            "openssh",
            "shares",
            "agent_service",
            "power",
            "metrics",
        }
    )

    def human_accounts(self) -> list:
        """The accounts the directory service judges to be people.

        Uid at the floor or above, no underscore-prefixed service account,
        and nothing marked ``IsHidden``.

        Returns:
            Account names, sorted; empty when ``dscl`` cannot answer.
        """
        listing = self._dscl(["-list", "/Users", "UniqueID"])
        if listing is None:
            return []
        accounts = []
        for line in listing.splitlines():
            fields = line.split()
            if len(fields) < 2:
                continue
            name = fields[0]
            try:
                uid = int(fields[-1])
            except ValueError:
                continue
            if uid < DARWIN_HUMAN_UID_FLOOR:
                continue
            if name.startswith(DARWIN_SERVICE_ACCOUNT_PREFIX):
                continue
            if self._is_hidden(name):
                continue
            accounts.append(name)
        return sorted(accounts)

    def account_home(self, account: str) -> str:
        """One account's home directory, from the directory service.

        Args:
            account: The account.

        Returns:
            The absolute home path.

        Raises:
            KeyError: When the directory service has no such account.
        """
        answer = self._dscl(["-read", f"/Users/{account}", "NFSHomeDirectory"])
        if answer is None:
            raise KeyError(account)
        home = answer.replace("NFSHomeDirectory:", "", 1).strip().splitlines()
        if not home or not home[0].strip():
            raise KeyError(account)
        return home[0].strip()

    def control_socket_path(self) -> str:
        """Where the agent's control socket lives.

        Returns:
            The absolute socket path.
        """
        return AGENT_CONTROL_SOCKET_PATH_DARWIN

    def read_peer_identity(self, connection) -> dict:
        """The peer's identity, from the kernel's ``LOCAL_PEERCRED``.

        Args:
            connection: The accepted socket.

        Returns:
            ``{"account", "uid", "is_privileged"}``.

        Raises:
            PlatformUnsupportedError: When the credential cannot be read.
            KeyError: When the peer's uid names no account.
        """
        try:
            data = connection.getsockopt(
                DARWIN_SOL_LOCAL, DARWIN_LOCAL_PEERCRED, DARWIN_XUCRED_SIZE
            )
            version, uid = struct.unpack_from(DARWIN_XUCRED_FORMAT, data)
        except (OSError, struct.error) as error:
            raise PlatformUnsupportedError(str(error))
        if version != DARWIN_XUCRED_VERSION:
            raise PlatformUnsupportedError(f"unknown xucred version {version}")
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
        """Run a process as an account, through ``su`` when root.

        The login shell (``su -``) gives the child the account's own
        environment, home included.

        Args:
            account: The account; empty runs as the agent itself.
            argv: Argument vector.
            stdin: Sent to the process's standard input.
            timeout_s: How long to wait.

        Returns:
            The completed process, with text output captured.
        """
        command = list(argv)
        if account and os.geteuid() == 0:
            command = ["su", "-", account, "-c", shlex.join(argv)]
        return subprocess.run(
            command, input=stdin, capture_output=True, text=True, timeout=timeout_s
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
        """Mount an SMB share, ownership-mapped under the account's own home.

        The password becomes the credentials file, travels into a transient
        ``/etc/nsmb.conf`` section for the length of the mount, and is never
        a command-line argument. A location under the asking account's home
        carries ``-u``/``-g`` so what appears belongs to the account;
        anywhere else the share's own permissions rule.

        Args:
            account: The asking account.
            share_url: The share, as ``//host/name``.
            username: The share's own username.
            password: The share's own password; empty reattaches with the
                credentials file already there.
            location: The mount point.
            credentials_path: Where this attachment's credentials file lives.

        Raises:
            ShareAttachError: ``credentials_missing`` without the file,
                ``mount_failed`` with the tool's own words otherwise.
        """
        if password:
            self._write_share_credentials(credentials_path, username, password)
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        stored_username, stored_password = self._read_share_credentials(
            credentials_path
        )
        share_username = stored_username or username
        command = (
            ["mount_smbfs", "-N"]
            + self._ownership_options(account=account, location=location)
            + [self._smb_url(share_url, share_username), location]
        )
        original = self._read_nsmb_conf()
        self._write_nsmb_conf(
            (original or "")
            + self._nsmb_section(share_url, share_username, stored_password)
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=DARWIN_SMB_MOUNT_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError("mount_failed", detail=str(error)[:200])
        finally:
            self._restore_nsmb_conf(original)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-200:]
            raise ShareAttachError("mount_failed", detail=detail)

    def write_share_credentials(
        self, *, credentials_path: str, username: str, password: str
    ) -> None:
        """Keep a share's login as a root-only credentials file."""
        self._write_share_credentials(credentials_path, username, password)

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
                timeout=DARWIN_SMB_MOUNT_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError("unmount_failed", detail=str(error)[:200])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-200:]
            raise ShareAttachError("unmount_failed", detail=detail)

    def is_share_attached(self, *, location: str) -> bool:
        """Whether anything is mounted at a location, read from ``mount``.

        Args:
            location: The mount point.

        Returns:
            True when the mount table names it.
        """
        try:
            result = subprocess.run(
                ["mount"],
                capture_output=True,
                text=True,
                timeout=AGENT_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        for line in result.stdout.splitlines():
            if " on " not in line or " (" not in line:
                continue
            mounted_at = line.split(" on ", 1)[1].rsplit(" (", 1)[0]
            if mounted_at == location:
                return True
        return False

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
            command: The manifest's uninstall command.

        Raises:
            InstallError: If the uninstall fails.
        """
        installers.uninstall_package(command)

    def install_openssh(self, entry: dict) -> None:
        """Switch Remote Login on; the sealed system volume carries sshd.

        Args:
            entry: The manifest's platform entry.

        Raises:
            InstallError: If ``systemsetup`` refuses.
        """
        installers.run_checked(["systemsetup", "-setremotelogin", "on"])

    def uninstall_openssh(self, entry: dict) -> None:
        """Switch Remote Login off; no binary moves.

        Args:
            entry: The manifest's platform entry.

        Raises:
            InstallError: If ``systemsetup`` refuses.
        """
        installers.run_checked(["systemsetup", "-f", "-setremotelogin", "off"])

    def read_openssh_status(self, entry: dict) -> bool:
        """Whether Remote Login is on.

        Args:
            entry: The manifest's platform entry.

        Returns:
            True when ``systemsetup`` reports it on.
        """
        try:
            result = subprocess.run(
                ["systemsetup", "-getremotelogin"],
                capture_output=True,
                text=True,
                timeout=AGENT_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return "On" in result.stdout

    def read_agent_service_state(self) -> str:
        """What launchd says about the agent's own LaunchDaemon.

        Returns:
            ``running``, launchd's own state word, or ``unknown``.
        """
        try:
            result = subprocess.run(
                ["launchctl", "print", f"system/{DARWIN_AGENT_LABEL}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        if result.returncode != 0:
            return "unknown"
        match = re.search(r"state = (\w+)", result.stdout)
        if match is None:
            return "unknown"
        return match.group(1)

    def start_agent_service(self) -> None:
        """Load and start the agent's LaunchDaemon. Best-effort.

        ``bootstrap`` and ``kickstart`` are the modern launchctl
        subcommands; ``load`` is the deprecated pair.
        """
        subprocess.run(
            ["launchctl", "bootstrap", "system", DARWIN_AGENT_PLIST],
            capture_output=True,
            timeout=30,
            check=False,
        )
        subprocess.run(
            ["launchctl", "kickstart", f"system/{DARWIN_AGENT_LABEL}"],
            capture_output=True,
            timeout=30,
            check=False,
        )

    def agent_service_start_hint(self) -> str:
        """The launchctl command that loads the agent's LaunchDaemon."""
        return f"sudo launchctl bootstrap system {DARWIN_AGENT_PLIST}"

    def power(self, action: str) -> "tuple[int, str]":
        """Run one power action through ``shutdown``.

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
        metrics = HostMetrics()
        try:
            usage = shutil.disk_usage("/")
            metrics.disk_percent = usage.used / usage.total * 100.0
        except (OSError, ZeroDivisionError):
            pass
        try:
            metrics.load_average = list(os.getloadavg())
        except OSError:
            pass
        metrics.uptime_s = self._read_uptime_s()
        metrics.memory_percent = self._read_memory_percent()
        metrics.cpu_percent = self._read_cpu_percent()
        return metrics

    def _dscl(self, arguments: list) -> "str | None":
        """One directory-service query, None when it cannot answer.

        Args:
            arguments: Arguments after ``dscl .``.

        Returns:
            Standard output, or None on any refusal or failure.
        """
        try:
            result = subprocess.run(
                ["dscl", "."] + list(arguments),
                capture_output=True,
                text=True,
                timeout=AGENT_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    def _is_hidden(self, account: str) -> bool:
        """Whether the directory service marks one account hidden."""
        answer = self._dscl(["-read", f"/Users/{account}", "IsHidden"])
        if answer is None:
            return False
        value = answer.replace("IsHidden:", "", 1).strip().lower()
        return value in DARWIN_HIDDEN_VALUES

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

    @staticmethod
    def _read_share_credentials(path: str) -> "tuple[str, str]":
        """One attachment's stored login.

        Args:
            path: The credentials file.

        Returns:
            ``(username, password)``, each empty when the file lacks it.
        """
        username = ""
        password = ""
        try:
            with open(path, "r", encoding="utf-8") as stream:
                for line in stream:
                    key, _, value = line.rstrip("\n").partition("=")
                    if key == "username":
                        username = value
                    elif key == "password":
                        password = value
        except OSError:
            return "", ""
        return username, password

    def _ownership_options(self, *, account: str, location: str) -> list:
        """The ``-u``/``-g`` a mount takes when it sits in the asker's home.

        Args:
            account: The asking account.
            location: The mount point.

        Returns:
            The option list; empty outside the account's own home.
        """
        if pwd is None or not account:
            return []
        try:
            entry = pwd.getpwnam(account)
            home = self.account_home(account)
        except (KeyError, PlatformUnsupportedError):
            return []
        if not home or not location.startswith(home.rstrip("/") + "/"):
            return []
        return ["-u", str(entry.pw_uid), "-g", str(entry.pw_gid)]

    @staticmethod
    def _smb_url(share_url: str, username: str) -> str:
        """The mount URL with the username in it, never the password.

        Args:
            share_url: The share, as ``//host/name``.
            username: The share's own username.

        Returns:
            ``//username@host/name``.
        """
        stripped = share_url.lstrip("/")
        if not username:
            return f"//{stripped}"
        return f"//{quote(username, safe='')}@{stripped}"

    @staticmethod
    def _nsmb_section(share_url: str, username: str, password: str) -> str:
        """The transient nsmb.conf section that carries one mount's password.

        Args:
            share_url: The share, as ``//host/name``.
            username: The share's own username.
            password: The share's own password.

        Returns:
            One ``[SERVER:USER:SHARE]`` section, upper-cased the way
            ``nsmb.conf(5)`` writes its examples.
        """
        host, _, share = share_url.lstrip("/").partition("/")
        head = ":".join(part.upper() for part in (host, username, share))
        return f"\n[{head}]\npassword={password}\n"

    @staticmethod
    def _read_nsmb_conf() -> "str | None":
        """The nsmb.conf as it stands, None when there is none."""
        try:
            with open(DARWIN_NSMB_CONF_PATH, "r", encoding="utf-8") as stream:
                return stream.read()
        except OSError:
            return None

    @staticmethod
    def _write_nsmb_conf(text: str) -> None:
        """Write nsmb.conf root-only, mode 0600."""
        descriptor = os.open(
            DARWIN_NSMB_CONF_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)

    @staticmethod
    def _restore_nsmb_conf(original: "str | None") -> None:
        """Put nsmb.conf back exactly, removing it where there was none."""
        if original is None:
            try:
                os.unlink(DARWIN_NSMB_CONF_PATH)
            except OSError:
                pass
            return
        DarwinPlatform._write_nsmb_conf(original)

    @staticmethod
    def _read_uptime_s() -> int:
        """Seconds since boot, from ``kern.boottime``; 0 when unreadable."""
        try:
            result = subprocess.run(
                ["sysctl", "-n", "kern.boottime"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
        match = re.search(r"sec\s*=\s*(\d+)", result.stdout)
        if match is None:
            return 0
        uptime = int(time.time()) - int(match.group(1))
        return uptime if uptime > 0 else 0

    @staticmethod
    def _read_memory_percent() -> float:
        """Share of memory in use, from ``hw.memsize`` and ``vm_stat``.

        Active, wired and compressor pages count as used; 0 when either
        source cannot be read.
        """
        try:
            total_answer = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            pages_answer = subprocess.run(
                ["vm_stat"], capture_output=True, text=True, timeout=10
            )
            total = int(total_answer.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0.0
        if total <= 0:
            return 0.0
        page_match = re.search(r"page size of (\d+) bytes", pages_answer.stdout)
        if page_match is None:
            return 0.0
        page_size = int(page_match.group(1))
        used_pages = 0
        for name in (
            "Pages active",
            "Pages wired down",
            "Pages occupied by compressor",
        ):
            line_match = re.search(rf"{re.escape(name)}:\s+(\d+)", pages_answer.stdout)
            if line_match is not None:
                used_pages += int(line_match.group(1))
        return min(100.0, used_pages * page_size / total * 100.0)

    @staticmethod
    def _read_cpu_percent() -> float:
        """Processor load, as 100 minus ``top``'s idle share; 0 unreadable."""
        try:
            result = subprocess.run(
                ["top", "-l", "1", "-n", "0"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return 0.0
        match = re.search(r"CPU usage:.*?([\d.]+)% idle", result.stdout)
        if match is None:
            return 0.0
        idle = float(match.group(1))
        return min(100.0, max(0.0, 100.0 - idle))
