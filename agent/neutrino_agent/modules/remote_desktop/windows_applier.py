"""The agent's copy of RustDesk on Windows, as the ``RustDesk`` service.

With the switch on the service ``RustDesk`` runs the agent's copy,
``AUTO_START`` as LocalSystem, and is created when none exists. A service
of that name found running something else is reconfigured, and its image
path, start type and whether it ran are kept in ``kept\\service.json``
first. With the switch off the agent's service is stopped; it is deleted
when the agent created it, and otherwise given back what was kept and
started again when it ran.

Not pure: drives the service manager and ends processes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import ntpath
import os
import re
import time

from neutrino_agent.modules.powershell_run import listed, run_powershell
from neutrino_agent.modules.remote_desktop.constants import (
    REMOTE_DESKTOP_KEPT_SERVICE_NAME,
    REMOTE_DESKTOP_POLL_S,
    REMOTE_DESKTOP_STOP_TIMEOUT_S,
    REMOTE_DESKTOP_VIEWER_FLAGS,
    REMOTE_DESKTOP_WINDOWS_DISPLAY_NAME,
    REMOTE_DESKTOP_WINDOWS_PROGRAM_FILES_DEFAULT,
    REMOTE_DESKTOP_WINDOWS_PROGRAM_PARTS,
    REMOTE_DESKTOP_WINDOWS_SERVICE,
    REMOTE_DESKTOP_WINDOWS_SETTINGS_PARTS,
    REMOTE_DESKTOP_WINDOWS_SYSTEM_ROOT_DEFAULT,
)
from neutrino_agent.modules.remote_desktop.records import read_json, write_json
from neutrino_agent.modules.subprocess_run import run as run_command

SC = "sc.exe"
TASKKILL = "taskkill.exe"
NETSTAT_COMMAND = ("netstat", "-ano", "-p", "TCP")
NETSTAT_V6_COMMAND = ("netstat", "-ano", "-p", "TCPv6")
STOPPED_PATTERN = re.compile(r"STATE\s*:\s*1\b")
# The start types sc.exe takes, by the word Win32_Service reports.
START_TYPES = {"auto": "auto", "manual": "demand", "disabled": "disabled"}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# What the service of RustDesk's name is, if there is one.
READ_SERVICE_SCRIPT = """
$s = Get-CimInstance Win32_Service -Filter "Name='RustDesk'"
if ($null -eq $s) { @{is_present = $false} | ConvertTo-Json -Compress; exit 0 }
@{is_present = $true; image_path = [string]$s.PathName;
  start_mode = [string]$s.StartMode; state = [string]$s.State;
  display_name = [string]$s.DisplayName} | ConvertTo-Json -Compress
"""

# Every RustDesk process, with its program and its command line.
PROCESSES_SCRIPT = """
$found = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'rustdesk%'" |
  ForEach-Object { @{pid = [int]$_.ProcessId; program = [string]$_.ExecutablePath;
    command = [string]$_.CommandLine;
    started = [long]([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds()} })
@{processes = $found} | ConvertTo-Json -Compress -Depth 4
"""


def program_path() -> str:
    """Where the agent's copy is."""
    root = (
        os.environ.get("ProgramFiles") or REMOTE_DESKTOP_WINDOWS_PROGRAM_FILES_DEFAULT
    )
    return ntpath.join(root, *REMOTE_DESKTOP_WINDOWS_PROGRAM_PARTS)


def image_path(program: str) -> str:
    """The service's command line for one program."""
    return f'"{program}" --service'


def is_viewer_command(command: str) -> bool:
    """Whether a RustDesk command line is a viewer a person may be using.

    Args:
        command: The process's command line.

    Returns:
        True when it names one of the viewer flags.
    """
    words = command.split()
    return any(flag in words for flag in REMOTE_DESKTOP_VIEWER_FLAGS)


def listening_pids(printed: str, port: int) -> list:
    """The pids netstat ``-ano`` shows listening on one TCP port.

    Args:
        printed: What netstat printed.
        port: The port.

    Returns:
        The pids, in the order shown.
    """
    pids = []
    for row in printed.splitlines():
        fields = row.split()
        if len(fields) != 5 or fields[0].upper() != "TCP":
            continue
        if fields[3] != "LISTENING" or not fields[4].isdigit():
            continue
        if fields[1].rpartition(":")[2] == str(port):
            pids.append(int(fields[4]))
    return pids


def process_program(pid: int) -> str:
    """One process's program, by ``QueryFullProcessImageNameW``.

    Args:
        pid: The process.

    Returns:
        Its full path; empty when it cannot be read.
    """
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return ""
    kernel32 = windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


class RemoteDesktopWindowsApplier:
    """Takes RustDesk over on Windows and gives it back."""

    def __init__(
        self,
        *,
        kept_dir: str,
        run=None,
        powershell=None,
        program: str = "",
        program_of=process_program,
        sleep=time.sleep,
    ):
        """
        Args:
            kept_dir: Where what is kept aside goes.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            powershell: Runs one script as :func:`run_powershell` does;
                None runs it.
            program: The agent's copy; empty is the one under Program Files.
            program_of: Reads one pid's program.
            sleep: Waits a number of seconds.
        """
        self.program = program or program_path()
        self._kept_dir = kept_dir
        self._run = run if run is not None else run_command
        self._powershell = powershell if powershell is not None else run_powershell
        self._program_of = program_of
        self._sleep = sleep

    def is_copy_present(self) -> bool:
        """Whether the agent's copy is on the machine."""
        return os.path.isfile(self.program)

    def settings_dirs(self, seat_home: str) -> list:
        """Where the service's settings are: LocalService's, whoever is seated.

        Args:
            seat_home: Unused: the service and its session host share one
                folder.

        Returns:
            The one folder.
        """
        root = (
            os.environ.get("SystemRoot") or REMOTE_DESKTOP_WINDOWS_SYSTEM_ROOT_DEFAULT
        )
        return [ntpath.join(root, *REMOTE_DESKTOP_WINDOWS_SETTINGS_PARTS)]

    def is_registered(self) -> bool:
        """Whether the service of RustDesk's name runs the agent's copy."""
        return self._is_own(self._service())

    def keep_aside(self) -> dict:
        """Record the service of RustDesk's name when it is not the agent's.

        Returns:
            ``{"image_path", "start_mode", "is_running", "display_name"}``,
            empty when there is none or it is the agent's.

        Raises:
            OSError: When the record cannot be written.
        """
        service = self._service()
        if not service.get("is_present") or self._is_own(service):
            return {}
        kept = {
            "image_path": str(service.get("image_path", "")),
            "start_mode": str(service.get("start_mode", "")),
            "is_running": str(service.get("state", "")).lower() == "running",
            "display_name": str(service.get("display_name", "")),
        }
        write_json(os.path.join(self._kept_dir, REMOTE_DESKTOP_KEPT_SERVICE_NAME), kept)
        return kept

    def stop_hosts(self) -> None:
        """Stop the service and end every RustDesk host left, viewers aside."""
        self._stop_service()
        self._end(self.host_pids())

    def register(self) -> None:
        """Point the service of RustDesk's name at the agent's copy, creating
        it when there is none.

        Raises:
            subprocess.CalledProcessError: When sc.exe refuses.
        """
        verb = "config" if self._service().get("is_present") else "create"
        self._run(
            [
                SC,
                verb,
                REMOTE_DESKTOP_WINDOWS_SERVICE,
                "binPath=",
                image_path(self.program),
                "start=",
                "auto",
                "obj=",
                "LocalSystem",
                "DisplayName=",
                REMOTE_DESKTOP_WINDOWS_DISPLAY_NAME,
            ]
        )

    def start(self, seat_uid: "int | None") -> None:
        """Start the service.

        Args:
            seat_uid: Unused on Windows: the service starts the session's
                host.

        Raises:
            subprocess.CalledProcessError: When sc.exe refuses.
        """
        self._run([SC, "start", REMOTE_DESKTOP_WINDOWS_SERVICE])

    def unregister(self) -> None:
        """Stop the agent's service, delete it unless a kept one is to be
        given back, and end its copy.

        Raises:
            subprocess.CalledProcessError: When sc.exe refuses the delete.
        """
        if self._is_own(self._service()):
            self._stop_service()
            if not os.path.isfile(self._kept_path()):
                self._run([SC, "delete", REMOTE_DESKTOP_WINDOWS_SERVICE])
        self._end(self.copy_pids())

    def restore(self) -> None:
        """Give the service back what :meth:`keep_aside` kept, and start it
        when it ran.

        Raises:
            subprocess.CalledProcessError: When sc.exe refuses.
        """
        kept = read_json(self._kept_path())
        if not kept:
            return
        verb = "config" if self._service().get("is_present") else "create"
        command = [
            SC,
            verb,
            REMOTE_DESKTOP_WINDOWS_SERVICE,
            "binPath=",
            str(kept.get("image_path", "")),
            "start=",
            START_TYPES.get(str(kept.get("start_mode", "")).lower(), "auto"),
        ]
        if kept.get("display_name"):
            command += ["DisplayName=", str(kept["display_name"])]
        self._run(command)
        if kept.get("is_running"):
            self._run([SC, "start", REMOTE_DESKTOP_WINDOWS_SERVICE])
        os.unlink(self._kept_path())

    def copy_pids(self) -> list:
        """The processes of the agent's copy."""
        own = self.program.lower()
        return [pid for pid, program, _ in self._rustdesk() if program.lower() == own]

    def stale_pids(self) -> list:
        """The hosts created before the copy on disk was written: an upgrade
        replaced the executable under them.

        Windows Installer moves an executable that is in use aside into
        ``Config.Msi`` until the next restart, so a host it left running (the
        tray in the signed-in session) names a program that is no longer
        there rather than the copy.

        Returns:
            Their pids; empty when the copy is not on disk.
        """
        try:
            status = os.stat(self.program)
        except OSError:
            return []
        written = max(status.st_mtime, status.st_ctime)
        own = self.program.lower()
        return [
            pid
            for pid, program, command, started in self._rustdesk_started()
            if started
            and started < written
            and not is_viewer_command(command)
            and program
            and (program.lower() == own or not os.path.isfile(program))
        ]

    def host_pids(self) -> list:
        """Every RustDesk process that is not a viewer."""
        return [
            pid
            for pid, _, command in self._rustdesk()
            if not is_viewer_command(command)
        ]

    def listening_programs(self, port: int) -> list:
        """The programs listening on one TCP port, from the socket table.

        Args:
            port: The port.

        Returns:
            Each listener's program; an empty string where it cannot be read.
        """
        pids = []
        for command in (NETSTAT_COMMAND, NETSTAT_V6_COMMAND):
            result = self._run(list(command), is_checked=False, timeout_s=10)
            pids.extend(listening_pids(result.stdout, port))
        return [self._program_of(pid) for pid in dict.fromkeys(pids)]

    def _service(self) -> dict:
        try:
            return self._powershell(READ_SERVICE_SCRIPT, {})
        except OSError:
            return {}

    def _is_own(self, service: dict) -> bool:
        return self.program.lower() in str(service.get("image_path", "")).lower()

    def _kept_path(self) -> str:
        return os.path.join(self._kept_dir, REMOTE_DESKTOP_KEPT_SERVICE_NAME)

    def _stop_service(self) -> None:
        self._run([SC, "stop", REMOTE_DESKTOP_WINDOWS_SERVICE], is_checked=False)
        waited = 0.0
        while waited < REMOTE_DESKTOP_STOP_TIMEOUT_S:
            result = self._run(
                [SC, "query", REMOTE_DESKTOP_WINDOWS_SERVICE], is_checked=False
            )
            if not result.is_success or STOPPED_PATTERN.search(result.stdout):
                return
            self._sleep(REMOTE_DESKTOP_POLL_S)
            waited += REMOTE_DESKTOP_POLL_S

    def _rustdesk(self) -> list:
        """Every RustDesk process: ``(pid, program, command line)``."""
        return [entry[:3] for entry in self._rustdesk_started()]

    def _rustdesk_started(self) -> list:
        """Every RustDesk process: ``(pid, program, command line, started)``,
        ``started`` in seconds since the epoch, 0 when not known."""
        try:
            answer = self._powershell(PROCESSES_SCRIPT, {})
        except OSError:
            return []
        found = []
        for process in listed(answer.get("processes")):
            if not isinstance(process, dict):
                continue
            found.append(
                (
                    int(process.get("pid") or 0),
                    str(process.get("program") or ""),
                    str(process.get("command") or ""),
                    int(process.get("started") or 0),
                )
            )
        return [entry for entry in found if entry[0]]

    def _end(self, pids: list) -> None:
        if not pids:
            return
        command = [TASKKILL, "/F"]
        for pid in pids:
            command += ["/PID", str(pid)]
        self._run(command, is_checked=False)
