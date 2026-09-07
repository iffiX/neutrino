"""The Windows platform behind the contract.

Windows has no general way to become another user without their password, so
account work is file work: the agent writes into the account's profile,
where inherited ACLs make the files the account's own, and a process runs as
an account only when that account has a logged-on session — console or RDP,
found by enumerating the sessions. The control channel is
a named pipe whose peer identity comes from pipe impersonation; privileged
is an elevated Administrators token, so an unelevated admin shell is an
ordinary account. A share is stored credentials plus a mapping made inside
the target account's own session, the SSH server is a Windows capability,
the agent runs as a service of the service control manager's own, and
metrics come from native Win32 calls. System packages stay refused: Windows
has no package manager the hub drives.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import json
import ntpath
import os
import re
import subprocess
import tempfile
from pathlib import Path

try:
    import msvcrt
except ImportError:  # Only Windows has the C-runtime handle bridge.
    msvcrt = None

from neutrino_agent.modules import installers
from neutrino_agent.constants import (
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_CONTROL_PIPE_NAME,
    AGENT_SERVICE_NAME_WINDOWS,
    AGENT_STEP_DOWN_TIMEOUT_S,
)
from neutrino_agent.core.metrics import HostMetrics
from neutrino_agent.platforms import windows_service
from neutrino_agent.platforms.base import (
    AgentPlatform,
    PlatformUnsupportedError,
    ShareAttachError,
)

WINDOWS_PROFILES_DIR = "C:\\Users"
WINDOWS_AGENT_DATA_DIR = "C:\\ProgramData\\Neutrino\\agent"
WINDOWS_OPENSSH_CAPABILITY = "OpenSSH.Server~~~~0.0.1.0"

# The last line a fully-run mapping script prints. PowerShell fed a script on
# standard input can discard it silently and still exit zero, so a zero exit
# without this marker is a failure, never a success.
WINDOWS_MOUNT_SUCCESS_MARKER = "NEUTRINO_MOUNT_OK"

# A person is a local profile: a non-special profile whose SID is a real
# user's (S-1-5-21-…) and not Guest, DefaultAccount or the Defender sandbox
# account. The built-in Administrator (RID 500) is not on that list: on a
# workstation it is disabled and has no profile, so it never shows; on a
# server it is the person, and a machine reached as it had nobody to mount
# for, switch at the gateway, or share a desktop as.
WINDOWS_HUMAN_SID_PREFIX = "S-1-5-21-"
WINDOWS_BUILTIN_ACCOUNT_RIDS = frozenset({501, 503, 504})

WINDOWS_PROFILES_SCRIPT = (
    "Get-CimInstance Win32_UserProfile -Filter 'Special=FALSE' | "
    "Select-Object SID, LocalPath | ConvertTo-Json"
)

WINDOWS_QUERY_TIMEOUT_S = 60
WINDOWS_MOUNT_TIMEOUT_S = 60

WINDOWS_POWER_COMMANDS = {
    "reboot": ["shutdown", "/r", "/t", "0"],
    "poweroff": ["shutdown", "/s", "/t", "0"],
}

# What "root-only" is here: inheritance off, SYSTEM and Administrators full.
WINDOWS_CREDENTIALS_DIR_GRANTS = (
    "*S-1-5-18:(OI)(CI)F",
    "*S-1-5-32-544:(OI)(CI)F",
)

# Win32 values, by their own names.
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1
TOKEN_ELEVATION_CLASS = 20
WIN_BUILTIN_ADMINISTRATORS_SID = 26
SECURITY_MAX_SID_BYTES = 68
WTS_USER_NAME_CLASS = 5
WTS_CONNECTSTATE_CLASS = 8
WTS_CONNECTSTATE_ACTIVE = 0
WTS_CONNECTSTATE_DISCONNECTED = 4
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
WAIT_TIMEOUT = 0x00000102


def _human_profiles(text: str) -> list:
    """The account names the profile listing judges to be people.

    Args:
        text: The profiles script's JSON output.

    Returns:
        Account names, sorted; unreadable output reads as none.
    """
    try:
        payload = json.loads(text or "[]")
    except ValueError:
        return []
    rows = payload if isinstance(payload, list) else [payload]
    accounts = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("SID", ""))
        if not sid.startswith(WINDOWS_HUMAN_SID_PREFIX):
            continue
        rid = sid.rsplit("-", 1)[-1]
        if not rid.isdigit() or int(rid) in WINDOWS_BUILTIN_ACCOUNT_RIDS:
            continue
        name = _profile_basename(str(row.get("LocalPath", "")))
        if name:
            accounts.add(name)
    return sorted(accounts)


def _cpu_percent_from_deltas(
    previous: "tuple[int, int, int] | None", current: "tuple[int, int, int]"
) -> float:
    """Aggregate processor load between two GetSystemTimes samples.

    Windows counts idle time inside kernel time, so the busy share is the
    non-idle part of kernel plus user across the interval. The first sample
    has nothing to compare against and reads as zero.

    Args:
        previous: The prior ``(idle, kernel, user)`` sample, or None.
        current: The current ``(idle, kernel, user)`` sample.

    Returns:
        The load as a percentage, clamped to 0-100.
    """
    if previous is None:
        return 0.0
    idle_delta = current[0] - previous[0]
    total_delta = (current[1] - previous[1]) + (current[2] - previous[2])
    if total_delta <= 0:
        return 0.0
    busy = total_delta - idle_delta
    return max(0.0, min(100.0, 100.0 * busy / total_delta))


def _filetime_ticks(value) -> int:
    """The 64-bit tick count a FILETIME's two halves make."""
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def _profile_basename(path: str) -> str:
    """The last segment of a profile path, whichever slash it uses."""
    return path.replace("/", "\\").rstrip("\\").rsplit("\\", 1)[-1]


def _share_parts(share_url: str) -> "tuple[str, str]":
    """The host and share a ``//host/name`` URL names.

    Args:
        share_url: The share URL.

    Returns:
        The host and the share name, either empty when unreadable.
    """
    trimmed = share_url.replace("\\", "/").strip("/")
    host, _, share = trimmed.partition("/")
    return host, share


def _read_share_credentials(path: str) -> "tuple[str, str]":
    """One credentials file's login.

    Args:
        path: The credentials file.

    Returns:
        The username and password, empty where unreadable.
    """
    values = {"username": "", "password": ""}
    try:
        with open(path, "r", encoding="utf-8") as stream:
            for line in stream:
                key, _, value = line.partition("=")
                if key.strip() in values:
                    values[key.strip()] = value.rstrip("\n")
    except OSError:
        pass
    return values["username"], values["password"]


def _powershell_literal(value: str) -> str:
    """A PowerShell single-quoted literal for one value."""
    return "'" + value.replace("'", "''") + "'"


def _mapping_script(
    *, host: str, share: str, location: str, username: str, password: str
) -> str:
    """The PowerShell that stores the login and maps the share in a session.

    Fed on standard input, so the login is on no argument vector. ``cmdkey``
    keeps the login for the host so a persistent mapping reconnects at logon,
    and ``New-SmbMapping`` makes the mapping in the session the script runs
    in — the account's own, which is what makes it visible to that person.

    PowerShell reading ``-Command -`` buffers a multi-line block like an
    interactive prompt and runs it only once a blank line closes it, so the
    script ends with one; without it the block is discarded at end of input
    with exit code zero. The success marker is the proof the script ran:
    the caller requires it on standard output.

    Args:
        host: The share's host.
        share: The share name.
        location: The drive letter the share appears at.
        username: The share's own username.
        password: The share's own password.

    Returns:
        The script text, closed by a trailing blank line.
    """
    remote = f"\\\\{host}\\{share}"
    return (
        f"$h = {_powershell_literal(host)}\n"
        f"$u = {_powershell_literal(username)}\n"
        f"$p = {_powershell_literal(password)}\n"
        f"$remote = {_powershell_literal(remote)}\n"
        f"$local = {_powershell_literal(location)}\n"
        "try {\n"
        "  cmdkey /add:$h /user:$u /pass:$p | Out-Null\n"
        "  Remove-SmbMapping -LocalPath $local -Force "
        "-ErrorAction SilentlyContinue | Out-Null\n"
        "  New-SmbMapping -LocalPath $local -RemotePath $remote "
        "-UserName $u -Password $p -Persistent $true -ErrorAction Stop | Out-Null\n"
        f"  Write-Output '{WINDOWS_MOUNT_SUCCESS_MARKER}'\n"
        "  exit 0\n"
        "} catch {\n"
        "  Write-Error $_\n"
        "  exit 1\n"
        "}\n"
        "\n"
    )


def _is_under(home: str, path: str) -> bool:
    """Whether a path sits at or below a profile directory."""
    normalized_home = os.path.normcase(home.replace("/", "\\")).rstrip("\\")
    normalized_path = os.path.normcase(path.replace("/", "\\")).rstrip("\\")
    if not normalized_home:
        return False
    return normalized_path == normalized_home or normalized_path.startswith(
        normalized_home + "\\"
    )


class WindowsPlatform(AgentPlatform):
    """Windows behind the platform contract."""

    os_name = "windows"
    mount_location_shape = "drive_letter"
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
            "openssh",
            "shares",
        }
    )

    def __init__(self, *, win32=None):
        """
        Args:
            win32: The Win32 seam for identity, step-down and metrics; None
                builds the real one on first use.
        """
        self._win32_api = win32
        # The previous GetSystemTimes sample, for the load between two beats.
        self._previous_cpu_times: "tuple[int, int, int] | None" = None
        # Account name to its resolved profile directory, so the database is
        # asked once per account rather than per file operation.
        self._home_cache: "dict[str, str]" = {}

    def agent_data_dir(self) -> str:
        """Where the agent keeps its own state: under ProgramData.

        Returns:
            The absolute directory path.
        """
        return WINDOWS_AGENT_DATA_DIR

    def human_accounts(self) -> list:
        """The accounts that are people: the machine's local profiles.

        Returns:
            Account names, sorted; built-in and system accounts never
            listed.
        """
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    WINDOWS_PROFILES_SCRIPT,
                ],
                capture_output=True,
                text=True,
                timeout=WINDOWS_QUERY_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []
        return _human_profiles(result.stdout or "")

    def account_home(self, account: str) -> str:
        """One account's profile directory, from the profile database.

        The database is where a service account such as SYSTEM points at its
        systemprofile rather than a ``C:\\Users`` child, so a name is never
        just joined to the profiles directory. A name the database cannot
        place — off Windows, or a profile not yet written — falls back to that
        join.

        Args:
            account: The account.

        Returns:
            The absolute profile path.
        """
        if not account:
            return str(Path(WINDOWS_PROFILES_DIR) / account)
        cached = self._home_cache.get(account)
        if cached is not None:
            return cached
        home = self._resolve_profile_dir(account) or str(
            Path(WINDOWS_PROFILES_DIR) / account
        )
        self._home_cache[account] = home
        return home

    def read_account_file(self, *, account: str, relative: str) -> str:
        """Read a file below an account's profile.

        Args:
            account: The account; empty reads below the agent's own home.
            relative: Path below the profile.

        Returns:
            The file's text, empty when it is absent or unreadable.
        """
        if not relative:
            return ""
        path = self._profile_file(account, relative)
        try:
            return path.read_text(encoding="utf-8") if path.is_file() else ""
        except OSError:
            return ""

    def read_account_file_mode(self, *, account: str, relative: str) -> str:
        """NTFS carries ACLs, not POSIX modes; there is nothing to report.

        Args:
            account: The account.
            relative: Path below the profile.

        Returns:
            Empty.
        """
        return ""

    def write_account_file(
        self, *, account: str, relative: str, text: str, mode: str = ""
    ) -> None:
        """Write a file below an account's profile, directly.

        The profile's inherited ACLs make the file the account's own.

        Args:
            account: The account; empty writes below the agent's own home.
            relative: Path below the profile.
            text: What to write.
            mode: Ignored; NTFS carries ACLs, not POSIX modes.
        """
        path = self._profile_file(account, relative)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            return

    def remove_account_file(self, *, account: str, relative: str) -> None:
        """Delete a file below an account's profile, absent being fine.

        Args:
            account: The account; empty removes below the agent's own home.
            relative: Path below the profile.
        """
        if not relative:
            return
        path = self._profile_file(account, relative)
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            return

    def control_socket_path(self) -> str:
        """Where the agent's control channel lives: the named pipe.

        Returns:
            The pipe name.
        """
        return AGENT_CONTROL_PIPE_NAME

    def read_peer_identity(self, connection) -> dict:
        """A pipe peer's identity, from pipe impersonation.

        Privileged is an elevated Administrators token; under UAC the same
        person's non-elevated shell is an ordinary account.

        Args:
            connection: The accepted pipe connection.

        Returns:
            ``{"account", "uid", "is_privileged"}``; ``uid`` is -1 because
            Windows reports names.

        Raises:
            PlatformUnsupportedError: When the peer is not a pipe or the
                token cannot be read.
        """
        handle = getattr(connection, "pipe_handle", None)
        if handle is None:
            raise PlatformUnsupportedError("not a pipe peer")
        win32 = self._win32()
        try:
            win32.impersonate_named_pipe_client(handle)
        except OSError as error:
            raise PlatformUnsupportedError(str(error))
        try:
            token = win32.open_thread_token()
            try:
                account = win32.token_account(token)
                is_privileged = win32.is_token_elevated(
                    token
                ) and win32.is_token_admin_member(token)
            finally:
                win32.close_handle(token)
        except OSError as error:
            raise PlatformUnsupportedError(str(error))
        finally:
            win32.revert_to_self()
        return {"account": account, "uid": -1, "is_privileged": bool(is_privileged)}

    def run_as_account(
        self,
        account: str,
        argv: list,
        *,
        stdin: str = "",
        timeout_s: int = AGENT_STEP_DOWN_TIMEOUT_S,
    ) -> "subprocess.CompletedProcess":
        """Run a process in the account's own logged-on session.

        Windows cannot become an arbitrary account without its password, so
        the step-down goes through a session token: the sessions are
        enumerated and the account's Active session — console or RDP — is
        picked, or failing that a Disconnected one it left behind.

        Args:
            account: The account; empty runs as the agent itself.
            argv: Argument vector.
            stdin: Sent to the process's standard input.
            timeout_s: How long to wait.

        Returns:
            The completed process, with text output captured.

        Raises:
            PlatformUnsupportedError: When the account has no logged-on
                session.
        """
        if not account:
            return subprocess.run(
                list(argv),
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        win32 = self._win32()
        session_id = self._account_session_id(account)
        if session_id is None:
            raise PlatformUnsupportedError("the account has no logged-on session")
        return win32.run_in_session(
            session_id, list(argv), stdin=stdin, timeout_s=timeout_s
        )

    def is_path_writable(self, *, account: str, path: str) -> bool:
        """Whether an account may write at a path, judged by its profile.

        Account work here is file work in the profile, so the judgment is
        the file-level one: inside the account's own profile is writable,
        anywhere else is refused rather than guessed. A drive letter is not a
        profile path but a mount location an ordinary logged-on account may
        claim, so a free one — already the only kind validation lets through —
        is writable.

        Args:
            account: The account; empty judges as the agent itself.
            path: The absolute path to ask about.

        Returns:
            True when the account may write there.
        """
        if not account:
            return True
        if re.fullmatch(r"[A-Za-z]:\\?", path):
            return True
        return _is_under(self.account_home(account), path)

    def list_directories(self, *, account: str, path: str) -> list:
        """The subdirectory names under a directory.

        An ordinary account browses only its own profile; the agent itself
        browses anywhere.

        Args:
            account: The account; empty lists as the agent itself.
            path: The absolute directory path.

        Returns:
            Subdirectory names, sorted, dot names left out.

        Raises:
            OSError: When the directory is outside the account's profile or
                cannot be listed.
        """
        if account and not _is_under(self.account_home(account), path):
            raise OSError("outside the account's profile")
        return sorted(
            entry.name
            for entry in os.scandir(path)
            if entry.is_dir() and not entry.name.startswith(".")
        )

    def make_directory(self, *, account: str, path: str) -> None:
        """Create a directory, parents included.

        A directory made inside a profile belongs to the account through
        the profile's inherited ACLs.

        Args:
            account: The account; empty creates as the agent itself.
            path: The absolute directory path.

        Raises:
            OSError: When the path is outside the account's profile or
                cannot be created.
        """
        if account and not _is_under(self.account_home(account), path):
            raise OSError("outside the account's profile")
        os.makedirs(path, exist_ok=True)

    def validate_mount_location(self, *, location: str) -> "dict | None":
        """Judge a proposed mount location: a single drive letter plus a colon.

        Args:
            location: The proposed location, as typed.

        Returns:
            None for an unused drive letter such as ``Z:``, otherwise the
            typed refusal ``{"code", "params"}``.
        """
        if re.fullmatch(r"[A-Za-z]:", location) is None:
            return {"code": "mountpoint_invalid", "params": {}}
        if os.path.exists(location + "\\"):
            return {"code": "mountpoint_not_empty", "params": {}}
        return None

    def prepare_mount_location(self, *, account: str, location: str) -> "dict | None":
        """A drive letter needs no preparation.

        Args:
            account: The asking account.
            location: The drive letter.

        Returns:
            None.
        """
        return None

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
        """Attach a share inside the asking account's own logged-on session.

        Drive mappings are per-session, so one made in the agent's SYSTEM
        session is invisible to the person's Explorer; the mapping is made in
        the account's session through the run-as seam instead. ``cmdkey`` and
        ``New-SmbMapping`` both take the login from a script fed on standard
        input, so the password is on no argument vector. The script's
        success marker must come back on standard output: a zero exit
        without it means PowerShell discarded the script, and reads as a
        failure carrying whatever the run printed.

        Args:
            account: The asking account, whose session the mapping lands in.
            share_url: The share, as ``//host/name``.
            username: The share's own username.
            password: The share's own password; empty reattaches with the
                credentials file already there.
            location: Where the share appears — a drive letter.
            credentials_path: Where this attachment's credentials file lives.

        Raises:
            ShareAttachError: ``credentials_missing`` without the file,
                ``no_logged_on_session`` when the account has no session,
                ``mount_failed`` with the tool's own words otherwise.
        """
        host, share = _share_parts(share_url)
        if not host or not share:
            raise ShareAttachError("mount_failed", detail="unreadable share url")
        if password:
            self.write_share_credentials(
                credentials_path=credentials_path,
                username=username,
                password=password,
            )
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        stored_username, stored_password = _read_share_credentials(credentials_path)
        script = _mapping_script(
            host=host,
            share=share,
            location=location,
            username=stored_username,
            password=stored_password,
        )
        try:
            result = self.run_as_account(
                account,
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", "-"],
                stdin=script,
                timeout_s=WINDOWS_MOUNT_TIMEOUT_S,
            )
        except PlatformUnsupportedError:
            raise ShareAttachError("no_logged_on_session")
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError("mount_failed", detail=str(error)[:200])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-200:]
            raise ShareAttachError("mount_failed", detail=detail)
        if WINDOWS_MOUNT_SUCCESS_MARKER not in (result.stdout or ""):
            detail = ((result.stdout or "") + (result.stderr or "")).strip()[-200:]
            raise ShareAttachError("mount_failed", detail=detail)

    def write_share_credentials(
        self, *, credentials_path: str, username: str, password: str
    ) -> None:
        """Keep a share's login in a directory only administrators read.

        Args:
            credentials_path: Where the file lives.
            username: The share's own username.
            password: The share's own password.
        """
        directory = ntpath.dirname(credentials_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
            self._restrict_directory(directory)
        with open(credentials_path, "w", encoding="utf-8") as stream:
            stream.write(f"username={username}\npassword={password}\n")

    def detach_share(self, *, location: str, account: str = "") -> None:
        """Delete the mapping at a location, inside the account's session.

        The mapping lives in the target account's own session, so the
        delete runs there too; an account with no session has no mapping to
        remove and is refused.

        Args:
            location: The mapped drive letter.
            account: The account whose session holds the mapping.

        Raises:
            ShareAttachError: ``no_logged_on_session`` when the account has
                no session, ``unmount_failed`` with the tool's own words.
        """
        if not account:
            raise ShareAttachError("no_logged_on_session")
        try:
            result = self.run_as_account(
                account,
                ["net", "use", location, "/delete", "/y"],
                timeout_s=WINDOWS_MOUNT_TIMEOUT_S,
            )
        except PlatformUnsupportedError:
            raise ShareAttachError("no_logged_on_session")
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError("unmount_failed", detail=str(error)[:200])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-200:]
            raise ShareAttachError("unmount_failed", detail=detail)

    def is_share_attached(self, *, location: str, account: str = "") -> bool:
        """Whether a mapping stands at a location in the account's session.

        The mapping is per-session, so the question is answered inside the
        target account's own session, where ``net use <drive>`` exits zero
        for a live mapping. An account with no session has nothing attached.

        Args:
            location: The mapped drive letter.
            account: The account whose session would hold the mapping.

        Returns:
            True when the account's session names the drive as mapped.
        """
        if not account:
            return False
        try:
            result = self.run_as_account(
                account,
                ["net", "use", location],
                timeout_s=WINDOWS_MOUNT_TIMEOUT_S,
            )
        except (PlatformUnsupportedError, OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and "\\\\" in (result.stdout or "")

    def read_agent_service_state(self) -> str:
        """What the service control manager says about the agent's service.

        Returns:
            The manager's own state word, or ``unknown`` when it does not
            answer — which includes the service not being installed.
        """
        return windows_service.read_state(AGENT_SERVICE_NAME_WINDOWS)

    def start_agent_service(self) -> None:
        """Ask the manager to start the agent's service. Best-effort."""
        windows_service.start(AGENT_SERVICE_NAME_WINDOWS)

    def agent_service_start_hint(self) -> str:
        """The command that starts the agent's service."""
        return f"sc start {AGENT_SERVICE_NAME_WINDOWS}"

    def power(self, action: str) -> "tuple[int, str]":
        """Run one power action through ``shutdown``.

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
        """One sample of the machine's health, from native Win32 calls.

        ``GetSystemTimes`` gives the aggregate processor load between two
        beats, ``GlobalMemoryStatusEx`` the memory, ``GetDiskFreeSpaceExW``
        the system drive and ``GetTickCount64`` the uptime — no subprocess per
        beat. Per-core numbers and the process list are not sampled: they cost
        a second interface the panel's Windows tile does not read.

        Returns:
            The current metrics; an unreadable machine contributes the
            defaults rather than raising.
        """
        try:
            win32 = self._win32()
            current = win32.system_times()
            memory_total, memory_available = win32.memory_status()
            drive = os.environ.get("SystemDrive", "C:") + "\\"
            disk_total, disk_free = win32.disk_space(drive)
            uptime_ms = win32.uptime_ms()
        except OSError:
            return HostMetrics()
        cpu_percent = _cpu_percent_from_deltas(self._previous_cpu_times, current)
        self._previous_cpu_times = current
        memory_percent = 0.0
        if memory_total:
            memory_percent = 100.0 * (memory_total - memory_available) / memory_total
        disk_percent = 0.0
        if disk_total:
            disk_percent = 100.0 * (disk_total - disk_free) / disk_total
        return HostMetrics(
            cpu_percent=cpu_percent,
            cpu_core_percents=[],
            memory_percent=max(0.0, min(100.0, memory_percent)),
            disk_percent=max(0.0, min(100.0, disk_percent)),
            uptime_s=max(0, uptime_ms // 1000),
            processes=[],
        )

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
        """Install the SSH server capability and start ``sshd``.

        ``Add-WindowsCapability`` pulls from Windows Update and takes
        minutes; the timeout budget allows for that.

        Args:
            entry: The manifest's platform entry, naming the capability.

        Raises:
            InstallError: If PowerShell refuses.
        """
        capability = entry.get("capability", WINDOWS_OPENSSH_CAPABILITY)
        installers.run_checked(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Add-WindowsCapability -Online -Name {capability}; "
                "Set-Service -Name sshd -StartupType Automatic; "
                "Start-Service sshd",
            ],
            timeout_s=installers.INSTALL_TIMEOUT_S,
        )

    def uninstall_openssh(self, entry: dict) -> None:
        """Stop ``sshd`` and remove the SSH server capability.

        Args:
            entry: The manifest's platform entry, naming the capability.

        Raises:
            InstallError: If PowerShell refuses.
        """
        capability = entry.get("capability", WINDOWS_OPENSSH_CAPABILITY)
        installers.run_checked(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Stop-Service sshd -ErrorAction SilentlyContinue; "
                f"Remove-WindowsCapability -Online -Name {capability}",
            ],
            timeout_s=installers.INSTALL_TIMEOUT_S,
        )

    def read_openssh_status(self, entry: dict) -> bool:
        """Whether ``sshd`` is installed and running.

        Args:
            entry: The manifest's platform entry.

        Returns:
            True when the service reports Running.
        """
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-Service sshd -ErrorAction SilentlyContinue).Status",
                ],
                capture_output=True,
                text=True,
                timeout=AGENT_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return "Running" in result.stdout

    def _profile_file(self, account: str, relative: str) -> Path:
        """The path one profile file lives at.

        Args:
            account: The account; empty means the agent's own home.
            relative: Path below the profile.

        Returns:
            The absolute path.
        """
        if not account:
            return Path(os.path.expanduser("~")) / relative
        return Path(self.account_home(account)) / relative

    def _win32(self):
        """The Win32 seam, built on first use."""
        if self._win32_api is None:
            self._win32_api = _Win32Api()
        return self._win32_api

    def _maybe_win32(self):
        """The Win32 seam only where one is available.

        An injected seam is used as given; otherwise the real one is built on
        Windows and withheld off it, so pure account-home logic still runs in
        a test without a Windows API to load.

        Returns:
            The seam, or None off Windows with none injected.
        """
        if self._win32_api is not None:
            return self._win32_api
        if os.name == "nt":
            return self._win32()
        return None

    def _resolve_profile_dir(self, account: str) -> str:
        """The account's profile directory from the database, empty if none."""
        win32 = self._maybe_win32()
        if win32 is None:
            return ""
        try:
            return win32.profile_directory(account)
        except OSError:
            return ""

    def _account_session_id(self, account: str) -> "int | None":
        """The session the target account is logged on in, None without one.

        An Active session of the account wins — console or RDP alike, which
        is what finds a person whose logon migrated off the console; failing
        that, a Disconnected session the account left behind still holds its
        mappings and is picked. Account names compare case-insensitively.

        Args:
            account: The target account.

        Returns:
            The session id, or None when the account has no session.
        """
        try:
            sessions = self._win32().sessions()
        except OSError:
            return None
        disconnected = None
        for session in sessions:
            if str(session.get("account", "")).lower() != account.lower():
                continue
            if session.get("state") == WTS_CONNECTSTATE_ACTIVE:
                return int(session["session_id"])
            if (
                disconnected is None
                and session.get("state") == WTS_CONNECTSTATE_DISCONNECTED
            ):
                disconnected = int(session["session_id"])
        return disconnected

    def _restrict_directory(self, directory: str) -> None:
        """Cut a directory's ACL to SYSTEM and Administrators.

        Args:
            directory: The directory to restrict.

        Raises:
            OSError: When ``icacls`` refuses.
        """
        command = [
            "icacls",
            directory,
            "/inheritance:r",
            "/grant:r",
            *WINDOWS_CREDENTIALS_DIR_GRANTS,
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=WINDOWS_QUERY_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise OSError(str(error))
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout or "").strip()[-200:])


class _Win32Api:
    """The Win32 identity and step-down calls, one seam tests replace whole."""

    def __init__(self):
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
        # Handles are pointers: without these prototypes a 64-bit handle
        # comes back truncated to an int.
        self._kernel32.GetCurrentThread.restype = ctypes.c_void_p
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self._kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        self._kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self._advapi32.ImpersonateNamedPipeClient.argtypes = [ctypes.c_void_p]
        self._advapi32.OpenThreadToken.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self._advapi32.GetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        self._advapi32.LookupAccountSidW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._advapi32.CheckTokenMembership.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._advapi32.CreateProcessAsUserW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._wtsapi32.WTSQuerySessionInformationW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._wtsapi32.WTSEnumerateSessionsW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._wtsapi32.WTSQueryUserToken.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        self._wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        self._kernel32.GetSystemTimes.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
        self._kernel32.GetDiskFreeSpaceExW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._advapi32.LookupAccountNameW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]

    def system_times(self) -> "tuple[int, int, int]":
        """Idle, kernel and user times in 100ns units, from GetSystemTimes.

        Returns:
            The three cumulative counters; kernel already contains idle.

        Raises:
            OSError: When the call is refused.
        """
        idle = _FileTime()
        kernel = _FileTime()
        user = _FileTime()
        ok = self._kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return _filetime_ticks(idle), _filetime_ticks(kernel), _filetime_ticks(user)

    def memory_status(self) -> "tuple[int, int]":
        """Total and available physical memory in bytes.

        Returns:
            ``(total, available)`` from GlobalMemoryStatusEx.

        Raises:
            OSError: When the call is refused.
        """
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        if not self._kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(status.ullTotalPhys), int(status.ullAvailPhys)

    def disk_space(self, path: str) -> "tuple[int, int]":
        """Total and free bytes on the volume holding a path.

        Args:
            path: A path on the volume, such as ``C:\\``.

        Returns:
            ``(total, free)`` from GetDiskFreeSpaceExW.

        Raises:
            OSError: When the call is refused.
        """
        free = ctypes.c_ulonglong(0)
        total = ctypes.c_ulonglong(0)
        ok = self._kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(path),
            ctypes.byref(free),
            ctypes.byref(total),
            None,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(total.value), int(free.value)

    def uptime_ms(self) -> int:
        """Milliseconds since boot, from GetTickCount64."""
        return int(self._kernel32.GetTickCount64())

    def profile_directory(self, account: str) -> str:
        """The account's profile directory from the profile database.

        The account name resolves to a SID, and the SID's ProfileList entry
        names the directory — where SYSTEM points at its systemprofile, not a
        ``C:\\Users`` child.

        Args:
            account: The account name.

        Returns:
            The absolute profile path, empty when the account has no profile.
        """
        sid = self._account_sid(account)
        if not sid:
            return ""
        try:
            import winreg
        except ImportError:
            return ""
        key_path = (
            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\" + sid
        )
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "ProfileImagePath")
        except OSError:
            return ""
        return os.path.expandvars(str(value))

    def _account_sid(self, account: str) -> str:
        """The string SID for an account name, empty when unresolvable."""
        size = ctypes.c_ulong(0)
        domain_size = ctypes.c_ulong(0)
        use = ctypes.c_ulong(0)
        self._advapi32.LookupAccountNameW(
            None,
            ctypes.c_wchar_p(account),
            None,
            ctypes.byref(size),
            None,
            ctypes.byref(domain_size),
            ctypes.byref(use),
        )
        if size.value == 0:
            return ""
        sid = ctypes.create_string_buffer(size.value)
        domain = ctypes.create_unicode_buffer(max(domain_size.value, 1))
        ok = self._advapi32.LookupAccountNameW(
            None,
            ctypes.c_wchar_p(account),
            sid,
            ctypes.byref(size),
            domain,
            ctypes.byref(domain_size),
            ctypes.byref(use),
        )
        if not ok:
            return ""
        string_sid = ctypes.c_wchar_p()
        if not self._advapi32.ConvertSidToStringSidW(sid, ctypes.byref(string_sid)):
            return ""
        try:
            return string_sid.value or ""
        finally:
            self._kernel32.LocalFree(string_sid)

    def impersonate_named_pipe_client(self, handle: int) -> None:
        """Impersonate the pipe's client on this thread.

        Args:
            handle: The pipe instance handle.

        Raises:
            OSError: When impersonation is refused.
        """
        if not self._advapi32.ImpersonateNamedPipeClient(ctypes.c_void_p(handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def revert_to_self(self) -> None:
        """Drop the impersonation. Best-effort."""
        self._advapi32.RevertToSelf()

    def open_thread_token(self) -> int:
        """This thread's impersonation token, for querying.

        Returns:
            The token handle.

        Raises:
            OSError: When the thread carries no token.
        """
        token = ctypes.c_void_p()
        ok = self._advapi32.OpenThreadToken(
            self._kernel32.GetCurrentThread(), TOKEN_QUERY, True, ctypes.byref(token)
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return token.value

    def token_account(self, token: int) -> str:
        """The account name a token belongs to.

        Args:
            token: The token handle.

        Returns:
            The account name.

        Raises:
            OSError: When the token's user cannot be read.
        """
        needed = ctypes.c_ulong(0)
        self._advapi32.GetTokenInformation(
            ctypes.c_void_p(token), TOKEN_USER_CLASS, None, 0, ctypes.byref(needed)
        )
        buffer = ctypes.create_string_buffer(max(needed.value, 64))
        ok = self._advapi32.GetTokenInformation(
            ctypes.c_void_p(token),
            TOKEN_USER_CLASS,
            buffer,
            len(buffer),
            ctypes.byref(needed),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        # TOKEN_USER starts with the SID pointer.
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        name = ctypes.create_unicode_buffer(256)
        domain = ctypes.create_unicode_buffer(256)
        name_size = ctypes.c_ulong(len(name))
        domain_size = ctypes.c_ulong(len(domain))
        use = ctypes.c_ulong(0)
        ok = self._advapi32.LookupAccountSidW(
            None,
            ctypes.c_void_p(sid),
            name,
            ctypes.byref(name_size),
            domain,
            ctypes.byref(domain_size),
            ctypes.byref(use),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return name.value

    def is_token_elevated(self, token: int) -> bool:
        """Whether a token is elevated.

        Args:
            token: The token handle.

        Returns:
            True for a full administrator token.

        Raises:
            OSError: When the elevation cannot be read.
        """
        elevation = ctypes.c_ulong(0)
        needed = ctypes.c_ulong(0)
        ok = self._advapi32.GetTokenInformation(
            ctypes.c_void_p(token),
            TOKEN_ELEVATION_CLASS,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(needed),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(elevation.value)

    def is_token_admin_member(self, token: int) -> bool:
        """Whether a token holds Administrators membership.

        Args:
            token: The token handle.

        Returns:
            True when the built-in Administrators group is in the token.

        Raises:
            OSError: When the membership cannot be checked.
        """
        sid = ctypes.create_string_buffer(SECURITY_MAX_SID_BYTES)
        size = ctypes.c_ulong(len(sid))
        ok = self._advapi32.CreateWellKnownSid(
            WIN_BUILTIN_ADMINISTRATORS_SID, None, sid, ctypes.byref(size)
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        member = ctypes.c_int(0)
        ok = self._advapi32.CheckTokenMembership(
            ctypes.c_void_p(token), sid, ctypes.byref(member)
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(member.value)

    def close_handle(self, handle: int) -> None:
        """Close a handle. Best-effort."""
        self._kernel32.CloseHandle(ctypes.c_void_p(handle))

    def sessions(self) -> list:
        """Every logon session with its account name and connect state.

        Returns:
            ``[{"session_id", "account", "state"}]``; a session with no
            account carries an empty name.

        Raises:
            OSError: When the enumeration is refused.
        """
        array = ctypes.c_void_p()
        count = ctypes.c_ulong(0)
        ok = self._wtsapi32.WTSEnumerateSessionsW(
            None, 0, 1, ctypes.byref(array), ctypes.byref(count)
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            rows = ctypes.cast(array, ctypes.POINTER(_WtsSessionInfo))
            listed = []
            for index in range(count.value):
                session_id = int(rows[index].SessionId)
                listed.append(
                    {
                        "session_id": session_id,
                        "account": self._session_account(session_id),
                        "state": self._session_state(session_id),
                    }
                )
            return listed
        finally:
            self._wtsapi32.WTSFreeMemory(array)

    def run_in_session(
        self, session_id: int, argv: list, *, stdin: str, timeout_s: int
    ) -> "subprocess.CompletedProcess":
        """Run a process in one session, as that session's own account.

        Args:
            session_id: The session whose token spawns the process.
            argv: Argument vector.
            stdin: Sent to the process's standard input.
            timeout_s: How long to wait.

        Returns:
            The completed process, with text output captured.

        Raises:
            OSError: When the session token or the spawn is refused.
            subprocess.TimeoutExpired: When the process outlives the wait.
        """
        token = ctypes.c_void_p()
        if not self._wtsapi32.WTSQueryUserToken(session_id, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return self._spawn_with_token(
                token.value, argv, stdin=stdin, timeout_s=timeout_s
            )
        finally:
            self._kernel32.CloseHandle(token)

    def _session_account(self, session_id: int) -> str:
        """One session's account name, empty for a session nobody owns."""
        buffer = ctypes.c_void_p()
        length = ctypes.c_ulong(0)
        ok = self._wtsapi32.WTSQuerySessionInformationW(
            None,
            session_id,
            WTS_USER_NAME_CLASS,
            ctypes.byref(buffer),
            ctypes.byref(length),
        )
        if not ok:
            return ""
        try:
            return ctypes.wstring_at(buffer.value) if buffer.value else ""
        finally:
            self._wtsapi32.WTSFreeMemory(buffer)

    def _session_state(self, session_id: int) -> int:
        """One session's WTS connect state, -1 where it cannot be read."""
        buffer = ctypes.c_void_p()
        length = ctypes.c_ulong(0)
        ok = self._wtsapi32.WTSQuerySessionInformationW(
            None,
            session_id,
            WTS_CONNECTSTATE_CLASS,
            ctypes.byref(buffer),
            ctypes.byref(length),
        )
        if not ok:
            return -1
        try:
            if not buffer.value:
                return -1
            return int(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int)).contents.value)
        finally:
            self._wtsapi32.WTSFreeMemory(buffer)

    def _spawn_with_token(
        self, token: int, argv: list, *, stdin: str, timeout_s: int
    ) -> "subprocess.CompletedProcess":
        """Spawn under a token with the standard streams on temporary files."""
        with tempfile.TemporaryDirectory(prefix="neutrino_agent_run_") as workdir:
            stdin_path = os.path.join(workdir, "stdin")
            stdout_path = os.path.join(workdir, "stdout")
            stderr_path = os.path.join(workdir, "stderr")
            with open(stdin_path, "w", encoding="utf-8") as stream:
                stream.write(stdin)
            descriptors = [
                os.open(stdin_path, os.O_RDONLY),
                os.open(stdout_path, os.O_WRONLY | os.O_CREAT),
                os.open(stderr_path, os.O_WRONLY | os.O_CREAT),
            ]
            try:
                handles = [
                    msvcrt.get_osfhandle(descriptor) for descriptor in descriptors
                ]
                for handle in handles:
                    os.set_handle_inheritable(handle, True)
                startup = _StartupInfo()
                startup.cb = ctypes.sizeof(startup)
                startup.dwFlags = STARTF_USESTDHANDLES
                startup.hStdInput = handles[0]
                startup.hStdOutput = handles[1]
                startup.hStdError = handles[2]
                info = _ProcessInformation()
                ok = self._advapi32.CreateProcessAsUserW(
                    ctypes.c_void_p(token),
                    None,
                    subprocess.list2cmdline(argv),
                    None,
                    None,
                    True,
                    CREATE_NO_WINDOW,
                    None,
                    None,
                    ctypes.byref(startup),
                    ctypes.byref(info),
                )
                if not ok:
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)
            try:
                waited = self._kernel32.WaitForSingleObject(
                    info.hProcess, int(timeout_s * 1000)
                )
                if waited == WAIT_TIMEOUT:
                    self._kernel32.TerminateProcess(info.hProcess, 1)
                    raise subprocess.TimeoutExpired(list(argv), timeout_s)
                code = ctypes.c_ulong(0)
                self._kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
            finally:
                self._kernel32.CloseHandle(info.hProcess)
                self._kernel32.CloseHandle(info.hThread)
            with open(stdout_path, "r", encoding="utf-8", errors="replace") as stream:
                stdout = stream.read()
            with open(stderr_path, "r", encoding="utf-8", errors="replace") as stream:
                stderr = stream.read()
        return subprocess.CompletedProcess(list(argv), int(code.value), stdout, stderr)


class _WtsSessionInfo(ctypes.Structure):
    """WTS_SESSION_INFOW, one enumerated logon session."""

    _fields_ = [
        ("SessionId", ctypes.c_ulong),
        ("pWinStationName", ctypes.c_wchar_p),
        ("State", ctypes.c_int),
    ]


class _FileTime(ctypes.Structure):
    """FILETIME, a 64-bit tick count split across two 32-bit halves."""

    _fields_ = [
        ("dwLowDateTime", ctypes.c_ulong),
        ("dwHighDateTime", ctypes.c_ulong),
    ]


class _MemoryStatusEx(ctypes.Structure):
    """MEMORYSTATUSEX, for GlobalMemoryStatusEx."""

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _StartupInfo(ctypes.Structure):
    """STARTUPINFOW, for the redirected standard streams."""

    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_ulong),
        ("dwY", ctypes.c_ulong),
        ("dwXSize", ctypes.c_ulong),
        ("dwYSize", ctypes.c_ulong),
        ("dwXCountChars", ctypes.c_ulong),
        ("dwYCountChars", ctypes.c_ulong),
        ("dwFillAttribute", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("wShowWindow", ctypes.c_ushort),
        ("cbReserved2", ctypes.c_ushort),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class _ProcessInformation(ctypes.Structure):
    """PROCESS_INFORMATION, for the spawned process's handles."""

    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_ulong),
        ("dwThreadId", ctypes.c_ulong),
    ]
