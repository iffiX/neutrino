"""The Windows platform behind the contract.

The client runs in the person's own session, so a share is a drive mapping
made by this process itself: a mapping belongs to the logon session that
made it, and one made anywhere else is reachable by name yet drawn as
disconnected in File Explorer. The login travels in a structure, on no
argument vector. The control channel is a named pipe of the person's own,
whose peer identity comes from pipe impersonation and must be the same
account. An EasyTier network is asked of the EasyTier daemon, a service
running as SYSTEM, over its named pipe; the daemon keeps its state under
ProgramData in a directory only SYSTEM and the administrators may open, and
ties the core it starts to its own life with a job object. The files
daemon, a service running as SYSTEM too, answers on a pipe of its own and
gives the wintun adapter tun2socks opens its address through PowerShell.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import base64
import ctypes
import getpass
import os
import re
import subprocess
import sys
import threading
import time

from neutrino_client.constants import (
    CLIENT_AGENT_PROGRAM_SUBDIR_WINDOWS,
    CLIENT_CONTROL_PIPE_NAME_PREFIX,
    CLIENT_CONTROL_PIPE_PREFIX,
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_EASYTIER_PIPE_WINDOWS,
    CLIENT_EASYTIER_STATE_NAME_WINDOWS,
    CLIENT_FILES_ADAPTER_ADDRESS,
    CLIENT_FILES_ADAPTER_METRIC,
    CLIENT_FILES_ADAPTER_NAME,
    CLIENT_FILES_ADAPTER_SCRIPT_TIMEOUT_S,
    CLIENT_FILES_ADAPTER_WAIT_S,
    CLIENT_FILES_NETWORK,
    CLIENT_FILES_PIPE_WINDOWS,
    CLIENT_RELAUNCH_ARGUMENTS,
    CLIENT_RELAUNCH_TASK_PREFIX_WINDOWS,
    CLIENT_RELAUNCH_TIMEOUT_S,
    CLIENT_WINDOWED_PROGRAM_WINDOWS,
    CLIENT_LOG_SUBDIR_WINDOWS,
    CLIENT_STATE_SUBDIR_WINDOWS,
)
from neutrino_client.platforms import win32
from neutrino_client.exceptions import (
    PlatformUnsupportedError,
    ShareAttachError,
)
from neutrino_client.platforms.base import (
    ClientPlatform,
    read_share_credentials,
    run_quietly,
    share_parts,
)
from neutrino_client.platforms.windows_console import (
    WindowsConsoleApi,
    WindowsRawConsole,
)
from neutrino_client.platforms.windows_identity import WindowsIdentityApi
from neutrino_client.words import language_for_tag

# This person's client directory under the roaming and the local profile
# roots.
WINDOWS_CLIENT_DIR_PARTS = ("Neutrino", "client")
WINDOWS_MOUNT_TIMEOUT_S = 60
WINDOWS_PROGRAM_DATA_DEFAULT = "C:\\ProgramData"
WINDOWS_PROGRAM_FILES_DEFAULT = "C:\\Program Files"
# The id Windows gave this installation, read from the 64-bit view of the
# registry whatever the process is; the agent reads the same.
WINDOWS_MACHINE_GUID_KEY = "SOFTWARE\\Microsoft\\Cryptography"
WINDOWS_MACHINE_GUID_VALUE = "MachineGuid"
WINDOWS_KEY_WOW64_64KEY = 0x0100
WINDOWS_SYSTEM_ROOT_DEFAULT = "C:\\Windows"

# A share that File Explorer never hears about stands there as a disconnected
# drive while every other program reaches it; the shell is told after a
# mapping comes or goes.
SHCNE_DRIVEADD = win32.SHCNE_DRIVEADD
SHCNE_DRIVEREMOVED = win32.SHCNE_DRIVEREMOVED
# How often a job's wait looks at its live processes again.
WINDOWS_JOB_WAIT_INTERVAL_S = 0.05


def _program_data() -> str:
    """``%ProgramData%``, or its usual value when the variable is unset."""
    return os.environ.get("PROGRAMDATA", "") or WINDOWS_PROGRAM_DATA_DEFAULT


def _pipe_safe_name(account: str) -> str:
    """An account name with the characters a pipe name refuses replaced."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", account)


# What WNetAddConnection2 answers a share with, as the typed refusals every
# platform words alike. Anything outside the table is ``mount_failed`` with
# the Win32 message.
SHARE_REFUSALS = {
    win32.ERROR_LOGON_FAILURE: "share_login_rejected",
    win32.ERROR_INVALID_PASSWORD: "share_login_rejected",
    win32.ERROR_ACCESS_DENIED: "share_access_denied",
    win32.ERROR_BAD_NET_NAME: "share_not_found",
    win32.ERROR_BAD_NETPATH: "share_unreachable",
    win32.ERROR_NO_NET_OR_BAD_PATH: "share_unreachable",
    win32.ERROR_NO_NETWORK: "share_unreachable",
    win32.ERROR_SESSION_CREDENTIAL_CONFLICT: "share_session_conflict",
}


# The EasyTier daemon's state directory: SYSTEM and the administrators alone,
# every file in it the same, nothing taken from ProgramData above it.
EASYTIER_STATE_SDDL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"

# Gives the files adapter its address once tun2socks has opened it: waits
# for the adapter to be up, puts its metric past every other, adds the
# address in the active store alone, and keeps it out of DNS. No gateway, so
# no default route. A failure prints its message alone and exits 1.
FILES_ADAPTER_SCRIPT = """
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
  $alias = '@NAME@'
  $deadline = (Get-Date).AddSeconds(@WAIT@)
  while ($true) {
    $adapter = Get-NetAdapter -Name $alias -ErrorAction SilentlyContinue
    $ipv4 = Get-NetIPInterface -InterfaceAlias $alias -AddressFamily IPv4 `
      -ErrorAction SilentlyContinue
    if ($adapter -and $adapter.Status -eq 'Up' -and $ipv4) { break }
    if ((Get-Date) -gt $deadline) { throw "the adapter $alias is not up" }
    Start-Sleep -Milliseconds 200
  }
  Set-NetIPInterface -InterfaceAlias $alias -AddressFamily IPv4 `
    -InterfaceMetric @METRIC@
  $present = Get-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 `
    -IPAddress '@ADDRESS@' -ErrorAction SilentlyContinue
  if (-not $present) {
    New-NetIPAddress -InterfaceAlias $alias -IPAddress '@ADDRESS@' `
      -PrefixLength @PREFIX@ -PolicyStore ActiveStore | Out-Null
  }
  Set-DnsClient -InterfaceAlias $alias -RegisterThisConnectionsAddress $false
  Set-DnsClientServerAddress -InterfaceAlias $alias -ResetServerAddresses
} catch {
  [Console]::Out.WriteLine($_.Exception.Message)
  exit 1
}
"""


def files_adapter_command() -> list:
    """How PowerShell gives the files adapter its address, metric and DNS settings.

    Returns:
        The argument vector; the script travels encoded, so no quoting of the
        command line can change it.
    """
    script = (
        FILES_ADAPTER_SCRIPT.replace("@NAME@", CLIENT_FILES_ADAPTER_NAME)
        .replace("@WAIT@", str(CLIENT_FILES_ADAPTER_WAIT_S))
        .replace("@METRIC@", str(CLIENT_FILES_ADAPTER_METRIC))
        .replace("@ADDRESS@", CLIENT_FILES_ADAPTER_ADDRESS)
        .replace("@PREFIX@", CLIENT_FILES_NETWORK.rsplit("/", 1)[1])
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [
        _powershell_path(),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]


def relaunch_task_command(name: str, program: str) -> list:
    """How ``schtasks`` registers one account's relaunch task.

    A one-time trigger at midnight today, already past, never fires; the
    task runs when the installer starts it.

    Args:
        name: The task's name.
        program: The windowed program the task starts.

    Returns:
        The argument vector.
    """
    return [
        "schtasks",
        "/create",
        "/tn",
        name,
        "/tr",
        f'"{program}" {CLIENT_RELAUNCH_ARGUMENTS}',
        "/sc",
        "once",
        "/st",
        "00:00",
        "/rl",
        "limited",
        "/it",
        "/f",
    ]


def _powershell_path() -> str:
    """Windows PowerShell under ``%SystemRoot%``, whatever the service's PATH."""
    root = os.environ.get("SystemRoot", "") or WINDOWS_SYSTEM_ROOT_DEFAULT
    return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


class WindowsPlatform(ClientPlatform):
    """Windows behind the platform contract."""

    os_name = "windows"
    mount_location_shape = "drive_letter"

    def __init__(self, *, win32=None):
        """
        Args:
            win32: The Win32 seam; None builds the real one on first use.
        """
        self._win32_api = win32
        self._job: "int | None" = None

    def config_dir(self) -> str:
        """``%APPDATA%\\Neutrino\\client``."""
        root = os.environ.get("APPDATA", "") or os.path.join(
            self.home(), "AppData", "Roaming"
        )
        return os.path.join(root, *WINDOWS_CLIENT_DIR_PARTS)

    def os_machine_id(self) -> str:
        """The ``MachineGuid`` Windows keeps in the registry."""
        try:
            import winreg
        except ImportError:
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

    def agent_program_dir(self) -> str:
        """``%ProgramFiles%\\Neutrino\\agent``."""
        root = os.environ.get("ProgramFiles", "") or WINDOWS_PROGRAM_FILES_DEFAULT
        return os.path.join(root, *CLIENT_AGENT_PROGRAM_SUBDIR_WINDOWS)

    def log_dir(self) -> str:
        """``%LOCALAPPDATA%\\Neutrino\\client``."""
        root = os.environ.get("LOCALAPPDATA", "") or os.path.join(
            self.home(), "AppData", "Local"
        )
        return os.path.join(root, *WINDOWS_CLIENT_DIR_PARTS)

    def system_language(self) -> str:
        """The language this account's Windows UI is in.

        Returns:
            One of ``CLIENT_LANGUAGES``; the default where Windows cannot
            be asked.
        """
        try:
            language_id = self._win32().user_ui_language_id()
        except OSError:
            return CLIENT_DEFAULT_LANGUAGE
        primary = language_id & win32.LANGUAGE_PRIMARY_MASK
        if primary == win32.LANGUAGE_PRIMARY_CHINESE:
            return language_for_tag("zh")
        return CLIENT_DEFAULT_LANGUAGE

    def control_socket_path(self) -> str:
        """This person's own named pipe."""
        return (
            CLIENT_CONTROL_PIPE_PREFIX
            + CLIENT_CONTROL_PIPE_NAME_PREFIX
            + _pipe_safe_name(self.current_account())
        )

    def current_account(self) -> str:
        """The account this process runs as."""
        return getpass.getuser()

    def read_peer_identity(self, connection) -> dict:
        """A pipe peer's identity, from pipe impersonation.

        The token is taken under impersonation and read after reverting: an
        elevated peer is impersonated at identification level, under which
        its account name cannot be looked up.

        Args:
            connection: The accepted pipe connection.

        Returns:
            ``{"account", "uid", "is_same_user", "is_elevated"}``; ``uid`` is
            -1 because Windows reports names.

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
        except OSError as error:
            raise PlatformUnsupportedError(str(error))
        finally:
            win32.revert_to_self()
        try:
            account = win32.token_account(token)
            is_elevated = win32.token_is_elevated(token)
        except OSError as error:
            raise PlatformUnsupportedError(str(error))
        finally:
            win32.close_handle(token)
        return {
            "account": account,
            "uid": -1,
            "is_same_user": account.lower() == self.current_account().lower(),
            "is_elevated": is_elevated,
        }

    def validate_mount_location(self, *, location: str) -> "dict | None":
        """Judge a proposed mount location: a single drive letter plus a colon.

        Args:
            location: The proposed location, as typed.

        Returns:
            None for an unused drive letter such as ``Z:``, otherwise the
            typed refusal ``{"code", "params"}``.
        """
        if re.fullmatch(r"[A-Za-z]:", location) is None:
            return {"code": "mountpoint_not_drive_letter", "params": {}}
        if os.path.exists(location + "\\"):
            return {"code": "mountpoint_not_empty", "params": {}}
        return None

    def mount_location_choices(self) -> list:
        """Every drive letter still open, from the top down.

        Returns:
            Free letters with their colon, e.g. ``["Z:", "Y:", ...]``.
        """
        return [
            f"{letter}:"
            for letter in "ZYXWVUTSRQPONMLKJIHGFE"
            if not os.path.exists(f"{letter}:\\")
        ]

    def suggest_mount_location(self) -> str:
        """The first unused drive letter, from the top down.

        Returns:
            A letter with its colon, or empty when every letter is taken.
        """
        free = self.mount_location_choices()
        return free[0] if free else ""

    def prepare_mount_location(self, *, location: str) -> "dict | None":
        """A drive letter needs no preparation."""
        return None

    def attach_share(
        self, *, share_url: str, location: str, credentials_path: str, port: int = 0
    ) -> str:
        """Map a share in this person's own session.

        Args:
            share_url: The share, as ``//host/name``.
            port: The port the server answers SMB on; 0 for its own.
            location: The drive letter.
            credentials_path: The credentials file the login is read from.

        Returns:
            The drive letter given.

        Raises:
            ShareAttachError: ``credentials_missing`` without the file; the
                share refusal the Win32 code names, ``share_login_rejected``
                for a wrong username or password among them; ``mount_failed``
                with the Win32 message for any other code.
        """
        host, share = share_parts(share_url)
        if not host or not share:
            raise ShareAttachError("mount_failed", detail="unreadable share url")
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        username, password = read_share_credentials(credentials_path)
        code = self._win32().add_connection(
            local=location,
            remote=f"\\\\{host}\\{share}",
            username=username,
            password=password,
        )
        if code != win32.NO_ERROR:
            raise ShareAttachError(
                SHARE_REFUSALS.get(code, "mount_failed"), detail=win32.win_error(code)
            )
        self._announce_drive(location, SHCNE_DRIVEADD)
        return location

    def detach_share(self, *, location: str) -> None:
        """Take the mapping at a drive letter down, in this session.

        Args:
            location: The mapped drive letter.

        Raises:
            ShareAttachError: ``unmount_failed`` with the Win32 error.
        """
        code = self._win32().cancel_connection(location)
        # A letter only remembered from an earlier build is taken off the
        # profile and answered as not connected: gone either way.
        if code not in (win32.NO_ERROR, win32.ERROR_NOT_CONNECTED):
            raise ShareAttachError("unmount_failed", detail=win32.win_error(code))
        self._announce_drive(location, SHCNE_DRIVEREMOVED)

    def is_share_attached(self, *, location: str) -> bool:
        """Whether a mapping stands at a drive letter.

        Args:
            location: The mapped drive letter.

        Returns:
            True when ``net use <drive>`` names a remote path.
        """
        try:
            result = run_quietly(
                ["net", "use", location], timeout_s=WINDOWS_MOUNT_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and "\\" in (result.stdout or "")

    def run_answering(
        self, argv: list, *, prompt: str, answer: str, timeout_s: float
    ) -> tuple:
        """Run a program on a pseudo console and answer one prompt.

        Args:
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long the whole run may take.

        Returns:
            ``(returncode, output)``.

        Raises:
            PlatformUnsupportedError: When no pseudo console can be made.
        """
        # Enter on a Windows console is a carriage return.
        return self._win32().run_on_console(
            argv, prompt=prompt, answer=answer.replace("\n", "\r"), timeout_s=timeout_s
        )

    def raw_terminal(self) -> WindowsRawConsole:
        """This process's console in raw VT mode."""
        return WindowsRawConsole()

    def read_clipboard(self) -> str:
        """The clipboard's text, read through ``OpenClipboard``.

        Returns:
            The text; empty when the clipboard holds none.

        Raises:
            OSError: When another program holds the clipboard or Windows
                refuses.
        """
        return self._win32().clipboard_text()

    def write_clipboard(self, text: str) -> None:
        """Put text on the clipboard through ``SetClipboardData``.

        Args:
            text: The text.

        Raises:
            OSError: When another program holds the clipboard or Windows
                refuses.
        """
        self._win32().set_clipboard_text(text)

    def easytier_daemon_address(self) -> str:
        """The pipe named ``neutrino_client_easytier``."""
        return CLIENT_EASYTIER_PIPE_WINDOWS

    def easytier_state_dir(self) -> str:
        """``easytier`` under ``Neutrino\\client\\state`` in ProgramData."""
        return os.path.join(self.state_dir(), CLIENT_EASYTIER_STATE_NAME_WINDOWS)

    def easytier_log_dir(self) -> str:
        """``%ProgramData%\\Neutrino\\client\\log``."""
        return os.path.join(_program_data(), *CLIENT_LOG_SUBDIR_WINDOWS)

    def state_dir(self) -> str:
        """``%ProgramData%\\Neutrino\\client\\state``."""
        return os.path.join(_program_data(), *CLIENT_STATE_SUBDIR_WINDOWS)

    def secure_easytier_state_dir(self, path: str) -> None:
        """Make the state directory, SYSTEM's and the administrators' alone.

        Args:
            path: The directory.

        Raises:
            OSError: When it cannot be made or its access list set.
        """
        os.makedirs(path, exist_ok=True)
        self._win32().protect_directory(path, EASYTIER_STATE_SDDL)

    def files_daemon_address(self) -> str:
        """The pipe named ``neutrino_client_files``."""
        return CLIENT_FILES_PIPE_WINDOWS

    def configure_files_adapter(self) -> None:
        """Give the files adapter its address, metric and DNS settings.

        Raises:
            OSError: When PowerShell cannot run, runs out its time, or says
                what failed.
        """
        try:
            result = run_quietly(
                files_adapter_command(),
                timeout_s=CLIENT_FILES_ADAPTER_SCRIPT_TIMEOUT_S,
            )
        except subprocess.SubprocessError as error:
            raise OSError(f"PowerShell did not finish: {error}")
        if result.returncode != 0:
            words = (result.stdout or "").strip() or (result.stderr or "").strip()
            raise OSError(words or f"PowerShell exited {result.returncode}")

    def relaunch_task_name(self) -> str:
        """The relaunch task of this account."""
        return CLIENT_RELAUNCH_TASK_PREFIX_WINDOWS + _pipe_safe_name(
            self.current_account()
        )

    def register_relaunch(self) -> bool:
        """Register this account's relaunch task, for the installer to start.

        The task has no trigger that fires, runs at the limited level and only
        while the account is signed in, so it starts the windowed program in
        that person's own session, never elevated.

        Returns:
            True when the task was registered; False where no windowed
            program stands beside this one, as in a checkout.

        Raises:
            OSError: When ``schtasks`` cannot run or refuses.
        """
        program = os.path.join(
            os.path.dirname(sys.executable), CLIENT_WINDOWED_PROGRAM_WINDOWS
        )
        if not os.path.isfile(program):
            return False
        command = relaunch_task_command(self.relaunch_task_name(), program)
        try:
            result = run_quietly(command, timeout_s=CLIENT_RELAUNCH_TIMEOUT_S)
        except subprocess.SubprocessError as error:
            raise OSError(f"schtasks did not finish: {error}")
        if result.returncode != 0:
            words = (result.stderr or "").strip() or (result.stdout or "").strip()
            raise OSError(words or f"schtasks exited {result.returncode}")
        return True

    def forget_relaunch(self) -> None:
        """Delete this account's relaunch task, when one stands. Best-effort."""
        try:
            run_quietly(
                ["schtasks", "/delete", "/tn", self.relaunch_task_name(), "/f"],
                timeout_s=CLIENT_RELAUNCH_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def files_peer(self, connection) -> dict:
        """The files daemon pipe's peer: its account and its process.

        Args:
            connection: The accepted pipe connection.

        Returns:
            ``{"account", "pid"}``.

        Raises:
            PlatformUnsupportedError: When the peer is not a pipe or its
                token cannot be read.
            OSError: When the process id cannot be read.
        """
        identity = self.read_peer_identity(connection)
        pid = self._win32().pipe_client_process_id(connection.pipe_handle)
        return {"account": identity["account"], "pid": pid}

    def watch_process(self, pid: int) -> "WindowsProcessWatch":
        """A handle on one running process, to see whether it has ended.

        Args:
            pid: The process id.

        Returns:
            The watch.

        Raises:
            OSError: When the process cannot be opened.
        """
        api = self._win32()
        return WindowsProcessWatch(api=api, handle=api.open_process_to_wait(pid))

    def bind_child_process(self, process) -> None:
        """Put a child in a job that ends it when the daemon ends.

        Args:
            process: The started ``subprocess.Popen``.

        Raises:
            OSError: When the job cannot be made or the child put in it.
        """
        api = self._win32()
        if self._job is None:
            self._job = api.create_kill_on_close_job()
        api.assign_to_job(self._job, int(process._handle))

    def start_on_screen(self, argv: list):
        """Start a windowed program, followed through every process it starts.

        The program and each process it starts share a job of their own, so
        a program that starts a copy of itself and exits is still running
        while the copy runs.

        Args:
            argv: Argument vector.

        Returns:
            A :class:`WindowsJobProcess`; the bare process when Windows
            refuses the job.

        Raises:
            OSError: When the program cannot be started.
        """
        process = super().start_on_screen(argv)
        api = self._win32()
        try:
            job = api.create_kill_on_close_job()
        except OSError:
            return process
        try:
            api.assign_to_job(job, int(process._handle))
        except OSError:
            api.close_handle(job)
            return process
        return WindowsJobProcess(api=api, process=process, job=job)

    def _announce_drive(self, location: str, event: int) -> None:
        """Tell the shell a drive letter came or went.

        A share that File Explorer never hears about stands there as a
        disconnected drive while every other program reaches it.

        Args:
            location: The drive letter, as ``Z:``.
            event: ``SHCNE_DRIVEADD`` or ``SHCNE_DRIVEREMOVED``.
        """
        try:
            self._win32().notify_drive(location + "\\", event)
        except OSError:
            # The mapping stands either way; only the icon is at stake.
            pass

    def _win32(self):
        """The Win32 seam, built on first use."""
        if self._win32_api is None:
            self._win32_api = _WindowsApi()
        return self._win32_api


class WindowsJobProcess:
    """One started program and every process it starts, held in one job.

    It answers ``poll``, ``wait``, ``terminate`` and ``kill`` as a
    ``subprocess.Popen`` does, for the job as a whole: running while any
    process in the job runs. The job ends what is left in it when its handle
    closes.
    """

    def __init__(self, *, api, process, job: int):
        """
        Args:
            api: The Win32 seam the job is asked through.
            process: The started ``subprocess.Popen``.
            job: The job's handle, the process already in it.
        """
        self._api = api
        self._process = process
        self._job: "int | None" = job
        self._lock = threading.Lock()
        self.args = process.args
        self.pid = process.pid
        self.returncode: "int | None" = None

    def poll(self) -> "int | None":
        """Whether the job still runs a process.

        Returns:
            None while a process in the job runs; the started process's exit
            status once none does, the job's handle then closed.
        """
        with self._lock:
            if self._job is None:
                return self.returncode
            try:
                active = self._api.job_active_processes(self._job)
            except OSError:
                active = 0
            if active:
                return None
            status = self._process.poll()
            self.returncode = 0 if status is None else status
            self._api.close_handle(self._job)
            self._job = None
            return self.returncode

    def wait(self, timeout: "float | None" = None) -> int:
        """Wait for the job to run no process.

        Args:
            timeout: Seconds to wait; None waits as long as it takes.

        Returns:
            The exit status ``poll`` gives.

        Raises:
            subprocess.TimeoutExpired: When the wait ran out first.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(WINDOWS_JOB_WAIT_INTERVAL_S)
        return self.returncode

    def terminate(self) -> None:
        """End every process in the job.

        Raises:
            OSError: When Windows refuses.
        """
        with self._lock:
            if self._job is not None:
                self._api.terminate_job(self._job)

    def kill(self) -> None:
        """End every process in the job, as ``terminate`` does.

        Raises:
            OSError: When Windows refuses.
        """
        self.terminate()


class WindowsProcessWatch:
    """One process the daemon waits on, through a handle it keeps open."""

    def __init__(self, *, api, handle: int):
        """
        Args:
            api: The Win32 seam.
            handle: The process handle, opened to wait on.
        """
        self._api = api
        self._handle: "int | None" = handle

    def is_running(self) -> bool:
        """Whether the process has not ended.

        Returns:
            True while it runs.

        Raises:
            OSError: When Windows refuses the wait.
        """
        if self._handle is None:
            return False
        return self._api.is_waitable_running(self._handle)

    def close(self) -> None:
        """Let the handle go. Idempotent."""
        handle = self._handle
        self._handle = None
        if handle is not None:
            self._api.close_handle(handle)


class _WindowsApi:
    """The Win32 the Windows platform reaches, one seam tests replace whole.

    Mount, the shell notification and the pseudo console run here; the pipe
    identity is :class:`WindowsIdentityApi`, held so a peer's account is
    read the one way it is read anywhere.
    """

    def __init__(self):
        self._identity = WindowsIdentityApi()
        self._console = WindowsConsoleApi()

    def protect_directory(self, path: str, sddl: str) -> None:
        """Set a directory's access list whole, cut off from its parent's.

        Args:
            path: The directory.
            sddl: The descriptor whose access list it takes.

        Raises:
            OSError: When the descriptor or the directory refuses.
        """
        libraries = win32.libraries()
        advapi32 = libraries.advapi32
        descriptor = ctypes.c_void_p()
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, win32.SDDL_REVISION_1, ctypes.byref(descriptor), None
        ):
            raise win32.last_error()
        try:
            is_present = ctypes.c_int()
            dacl = ctypes.c_void_p()
            is_defaulted = ctypes.c_int()
            if not advapi32.GetSecurityDescriptorDacl(
                descriptor,
                ctypes.byref(is_present),
                ctypes.byref(dacl),
                ctypes.byref(is_defaulted),
            ):
                raise win32.last_error()
            status = advapi32.SetNamedSecurityInfoW(
                path,
                win32.SE_FILE_OBJECT,
                win32.DACL_SECURITY_INFORMATION
                | win32.PROTECTED_DACL_SECURITY_INFORMATION,
                None,
                None,
                dacl,
                None,
            )
            if status != win32.NO_ERROR:
                raise ctypes.WinError(status)
        finally:
            libraries.kernel32.LocalFree(descriptor)

    def create_kill_on_close_job(self) -> int:
        """A job whose processes end when its last handle closes.

        Returns:
            The job's handle, held for the life of this process.

        Raises:
            OSError: When the job cannot be made or limited.
        """
        kernel32 = win32.libraries().kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise win32.last_error()
        limits = win32.JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = (
            win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not kernel32.SetInformationJobObject(
            job,
            win32.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = win32.last_error()
            kernel32.CloseHandle(job)
            raise error
        return job

    def assign_to_job(self, job: int, process_handle: int) -> None:
        """Put one process in a job.

        Args:
            job: The job's handle.
            process_handle: The process's handle.

        Raises:
            OSError: When Windows refuses.
        """
        if not win32.libraries().kernel32.AssignProcessToJobObject(job, process_handle):
            raise win32.last_error()

    def job_active_processes(self, job: int) -> int:
        """How many processes in a job still run.

        Args:
            job: The job's handle.

        Returns:
            The count.

        Raises:
            OSError: When Windows refuses.
        """
        accounting = win32.JobObjectBasicAccountingInformation()
        if not win32.libraries().kernel32.QueryInformationJobObject(
            job,
            win32.JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            raise win32.last_error()
        return int(accounting.ActiveProcesses)

    def terminate_job(self, job: int) -> None:
        """End every process in a job.

        Args:
            job: The job's handle.

        Raises:
            OSError: When Windows refuses.
        """
        if not win32.libraries().kernel32.TerminateJobObject(job, 1):
            raise win32.last_error()

    def clipboard_text(self) -> str:
        """The clipboard's Unicode text, the clipboard closed again after.

        Returns:
            The text; empty when the clipboard holds no text.

        Raises:
            OSError: When the clipboard cannot be opened or its text locked.
        """
        libraries = win32.libraries()
        user32 = libraries.user32
        kernel32 = libraries.kernel32
        if not user32.OpenClipboard(None):
            raise win32.last_error()
        try:
            handle = user32.GetClipboardData(win32.CF_UNICODETEXT)
            if not handle:
                return ""
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise win32.last_error()
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def set_clipboard_text(self, text: str) -> None:
        """Replace the clipboard's content with Unicode text.

        Args:
            text: The text.

        Raises:
            OSError: When the clipboard cannot be opened, the memory cannot
                be had, or Windows refuses the data.
        """
        libraries = win32.libraries()
        user32 = libraries.user32
        kernel32 = libraries.kernel32
        data = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(data)
        if not user32.OpenClipboard(None):
            raise win32.last_error()
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(win32.GMEM_MOVEABLE, size)
            if not handle:
                raise win32.last_error()
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                error = win32.last_error()
                kernel32.GlobalFree(handle)
                raise error
            try:
                ctypes.memmove(pointer, data, size)
            finally:
                kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(win32.CF_UNICODETEXT, handle):
                error = win32.last_error()
                kernel32.GlobalFree(handle)
                raise error
        finally:
            user32.CloseClipboard()

    def add_connection(
        self, *, local: str, remote: str, username: str, password: str
    ) -> int:
        """Map a share into this process's own logon session, not persisted.

        The login travels in a structure rather than on any argument vector,
        and the session is this one, which is what leaves the drive standing
        for every program the person runs. It is not written to the profile:
        the client remounts what it holds, so Windows need not, and a
        persisted mapping is what File Explorer keeps drawing after it is
        gone.

        Args:
            local: The drive letter, as ``Z:``.
            remote: The share, as ``\\\\host\\share``.
            username: The share's own username.
            password: The share's own password.

        Returns:
            ``win32.NO_ERROR``, or the Win32 error number.
        """
        resource = win32.NetResource()
        resource.dwType = win32.RESOURCETYPE_DISK
        resource.lpLocalName = local
        resource.lpRemoteName = remote
        return int(
            win32.libraries().mpr.WNetAddConnection2W(
                ctypes.byref(resource), password, username, 0
            )
        )

    def cancel_connection(self, local: str) -> int:
        """Take a drive mapping down, and off the profile if remembered there.

        Args:
            local: The drive letter, as ``Z:``.

        Returns:
            ``win32.NO_ERROR``, or the Win32 error number.
        """
        return int(
            win32.libraries().mpr.WNetCancelConnection2W(
                local, win32.CONNECT_UPDATE_PROFILE, True
            )
        )

    def user_ui_language_id(self) -> int:
        """The LANGID of the UI language this account signed in with.

        Returns:
            The LANGID Windows answers with.

        Raises:
            OSError: When kernel32 cannot be reached, which is every call
                off Windows.
        """
        return int(win32.libraries().kernel32.GetUserDefaultUILanguage())

    def notify_drive(self, path: str, event: int) -> None:
        """Raise the shell's own drive-changed notification.

        Args:
            path: The drive's root, as ``Z:\\``.
            event: ``win32.SHCNE_DRIVEADD`` or ``win32.SHCNE_DRIVEREMOVED``.
        """
        win32.libraries().shell32.SHChangeNotify(event, win32.SHCNF_PATHW, path, None)

    def run_on_console(
        self, argv: list, *, prompt: str, answer: str, timeout_s: float
    ) -> tuple:
        """Run a program on a pseudo console and answer one prompt.

        Args:
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long the whole run may take.

        Returns:
            ``(returncode, output)``.

        Raises:
            PlatformUnsupportedError: When the console API is not there.
        """
        return self._console.run(
            argv, prompt=prompt, answer=answer, timeout_s=timeout_s
        )

    def impersonate_named_pipe_client(self, handle: int) -> None:
        """Impersonate the pipe's client on this thread."""
        self._identity.impersonate_named_pipe_client(handle)

    def revert_to_self(self) -> None:
        """Drop the impersonation. Best-effort."""
        self._identity.revert_to_self()

    def open_thread_token(self) -> int:
        """This thread's impersonation token, for querying."""
        return self._identity.open_thread_token()

    def token_account(self, token: int) -> str:
        """The account name a token belongs to."""
        return self._identity.token_account(token)

    def token_is_elevated(self, token: int) -> bool:
        """Whether a token is an elevated administrator's."""
        return self._identity.token_is_elevated(token)

    def close_handle(self, handle: int) -> None:
        """Close a handle. Best-effort."""
        self._identity.close_handle(handle)

    def pipe_client_process_id(self, handle: int) -> int:
        """The id of the process on the client end of a pipe instance.

        Args:
            handle: The connected pipe instance.

        Returns:
            The process id.

        Raises:
            OSError: When Windows refuses.
        """
        pid = ctypes.c_ulong(0)
        if not win32.libraries().kernel32.GetNamedPipeClientProcessId(
            ctypes.c_void_p(handle), ctypes.byref(pid)
        ):
            raise win32.last_error()
        return int(pid.value)

    def open_process_to_wait(self, pid: int) -> int:
        """A handle on a process that can be waited on.

        Args:
            pid: The process id.

        Returns:
            The handle.

        Raises:
            OSError: When the process cannot be opened.
        """
        handle = win32.libraries().kernel32.OpenProcess(
            win32.SYNCHRONIZE | win32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            raise win32.last_error()
        return handle

    def is_waitable_running(self, handle: int) -> bool:
        """Whether the object a handle names is not signalled yet.

        Args:
            handle: A process handle opened to wait on.

        Returns:
            True while the process runs.

        Raises:
            OSError: When the wait fails.
        """
        result = win32.libraries().kernel32.WaitForSingleObject(handle, 0)
        if result == win32.WAIT_TIMEOUT:
            return True
        if result == win32.WAIT_OBJECT_0:
            return False
        raise win32.last_error()
