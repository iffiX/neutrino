"""The agent's copy of RustDesk on macOS, under upstream's two launchd jobs.

With the switch on the agent writes ``com.carriez.RustDesk_service`` into
``/Library/LaunchDaemons`` and ``com.carriez.RustDesk_server`` into
``/Library/LaunchAgents``, both running its copy, and bootstraps the service
into the system domain and the session job into the seated account's. A
plist found under either name that is not the agent's is moved to
``kept/`` first. With the switch off both jobs are booted out and the
agent's plists deleted; what was kept is moved back and bootstrapped again.

Not pure: drives launchd, writes plists and ends processes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import plistlib
import posixpath
import shutil
import signal
import time

from neutrino_agent.modules.remote_desktop.constants import (
    REMOTE_DESKTOP_DARWIN_APP,
    REMOTE_DESKTOP_DARWIN_PROGRAM_MARK,
    REMOTE_DESKTOP_DARWIN_ROOT_SETTINGS,
    REMOTE_DESKTOP_DARWIN_SEAT_SETTINGS,
    REMOTE_DESKTOP_DARWIN_SERVICE_LABEL,
    REMOTE_DESKTOP_DARWIN_SERVICE_PLIST,
    REMOTE_DESKTOP_DARWIN_SESSION_LABEL,
    REMOTE_DESKTOP_DARWIN_SESSION_PLIST,
    REMOTE_DESKTOP_POLL_S,
    REMOTE_DESKTOP_STOP_TIMEOUT_S,
)
from neutrino_agent.modules.remote_desktop.linux_applier import is_viewer
from neutrino_agent.modules.subprocess_run import run as run_command

LAUNCHCTL = "/bin/launchctl"
LSOF = "/usr/sbin/lsof"
PS = "/bin/ps"
# launchd starts a job with no locale.
LAUNCHD_LANG = "en_US.UTF-8"
# The bundle the session job is shown as in the privacy settings.
RUSTDESK_BUNDLE_ID = "com.carriez.rustdesk"


def elapsed_seconds(printed: str) -> "int | None":
    """Seconds since a process started, from what ``ps -o etime=`` printed.

    Args:
        printed: ``[[dd-]hh:]mm:ss``.

    Returns:
        The seconds; None when the text is not that.
    """
    days, _, clock = printed.strip().rpartition("-")
    parts = clock.split(":")
    if not printed.strip() or len(parts) > 3 or not all(p.isdigit() for p in parts):
        return None
    if days and not days.isdigit():
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds + int(days or 0) * 86400


def service_job(app: str) -> dict:
    """The system daemon's job for one RustDesk bundle.

    Args:
        app: The bundle's path.

    Returns:
        The plist's dictionary.
    """
    macos_dir = posixpath.join(app, "Contents", "MacOS")
    return {
        "Label": REMOTE_DESKTOP_DARWIN_SERVICE_LABEL,
        "ProgramArguments": [posixpath.join(macos_dir, "service")],
        "RunAtLoad": True,
        "KeepAlive": True,
        "WorkingDirectory": macos_dir,
        "EnvironmentVariables": {"LANG": LAUNCHD_LANG},
    }


def session_job(app: str) -> dict:
    """The per-session agent's job for one RustDesk bundle.

    Args:
        app: The bundle's path.

    Returns:
        The plist's dictionary.
    """
    macos_dir = posixpath.join(app, "Contents", "MacOS")
    return {
        "Label": REMOTE_DESKTOP_DARWIN_SESSION_LABEL,
        "ProgramArguments": [posixpath.join(macos_dir, "RustDesk"), "--server"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "LimitLoadToSessionType": ["Aqua", "LoginWindow"],
        "AssociatedBundleIdentifiers": RUSTDESK_BUNDLE_ID,
        "WorkingDirectory": macos_dir,
        "EnvironmentVariables": {"LANG": LAUNCHD_LANG},
    }


def console_uid() -> "int | None":
    """The uid signed in at the Mac's screen, None for nobody."""
    from neutrino_agent.rdp.darwin_seat import console_user

    seated = console_user()
    return seated[1] if seated else None


class RemoteDesktopDarwinApplier:
    """Takes RustDesk over on macOS and gives it back."""

    def __init__(
        self,
        *,
        kept_dir: str,
        run=None,
        app: str = REMOTE_DESKTOP_DARWIN_APP,
        service_plist: str = REMOTE_DESKTOP_DARWIN_SERVICE_PLIST,
        session_plist: str = REMOTE_DESKTOP_DARWIN_SESSION_PLIST,
        kill=os.kill,
        sleep=time.sleep,
        seat_uid=None,
    ):
        """
        Args:
            kept_dir: Where what is kept aside goes.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            app: The agent's copy of the bundle.
            service_plist: Where the system daemon's plist goes.
            session_plist: Where the session agent's plist goes.
            kill: Sends a signal to a pid.
            sleep: Waits a number of seconds.
            seat_uid: Returns the uid at the screen, None for nobody; None
                asks the system configuration.
        """
        self.program = posixpath.join(app, "Contents", "MacOS", "RustDesk")
        self._app = app
        self._kept_dir = kept_dir
        self._run = run if run is not None else run_command
        self._plists = (
            (REMOTE_DESKTOP_DARWIN_SERVICE_LABEL, service_plist, service_job),
            (REMOTE_DESKTOP_DARWIN_SESSION_LABEL, session_plist, session_job),
        )
        self._kill = kill
        self._sleep = sleep
        self._seat_uid = seat_uid if seat_uid is not None else console_uid

    def is_copy_present(self) -> bool:
        """Whether the agent's copy is on the machine."""
        return os.path.isfile(self.program)

    def settings_dirs(self, seat_home: str) -> list:
        """Where root's and the seated account's settings are.

        Args:
            seat_home: The home of the account at the screen, empty for
                nobody.

        Returns:
            The folders, root's first.
        """
        dirs = [REMOTE_DESKTOP_DARWIN_ROOT_SETTINGS]
        if seat_home:
            dirs.append(posixpath.join(seat_home, REMOTE_DESKTOP_DARWIN_SEAT_SETTINGS))
        return dirs

    def is_registered(self) -> bool:
        """Whether both of the agent's plists are in place."""
        return all(self._is_own(path) for _, path, _ in self._plists)

    def keep_aside(self) -> dict:
        """Move aside each plist under upstream's names that is not the
        agent's.

        Returns:
            ``{"plists": [file name, ...]}``, empty when none was found.

        Raises:
            OSError: When a plist cannot be moved.
        """
        moved = []
        for _, path, _ in self._plists:
            if os.path.isfile(path) and not self._is_own(path):
                os.makedirs(self._kept_dir, mode=0o700, exist_ok=True)
                shutil.move(
                    path, posixpath.join(self._kept_dir, posixpath.basename(path))
                )
                moved.append(posixpath.basename(path))
        return {"plists": moved} if moved else {}

    def stop_hosts(self) -> None:
        """Boot both jobs out and end every RustDesk host left, viewers
        aside."""
        self._bootout()
        self._end(self.host_pids())

    def register(self) -> None:
        """Write the agent's two plists.

        Raises:
            OSError: When a plist cannot be written.
        """
        for _, path, job in self._plists:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temporary = f"{path}.tmp"
            with open(temporary, "wb") as stream:
                plistlib.dump(job(self._app), stream)
            os.chmod(temporary, 0o644)
            if os.geteuid() == 0:
                os.chown(temporary, 0, 0)
            os.replace(temporary, path)

    def start(self, seat_uid: "int | None") -> None:
        """Bootstrap the service, then the seated account's session job.

        Args:
            seat_uid: The uid at the screen; None for nobody, whose session
                job launchd starts at the next login.

        Raises:
            subprocess.CalledProcessError: When launchd refuses the service.
        """
        service_plist = self._plists[0][1]
        session_plist = self._plists[1][1]
        self._run([LAUNCHCTL, "bootstrap", "system", service_plist])
        if seat_uid:
            self._run(
                [LAUNCHCTL, "bootstrap", f"gui/{seat_uid}", session_plist],
                is_checked=False,
            )

    def unregister(self) -> None:
        """Boot both jobs out, delete the agent's plists, end its copy."""
        self._bootout()
        for _, path, _ in self._plists:
            if self._is_own(path):
                os.unlink(path)
        self._end(self.copy_pids())

    def restore(self) -> None:
        """Move the kept plists back and bootstrap them again.

        Raises:
            OSError: When a kept plist cannot be moved back.
        """
        seat_uid = self._seat_uid()
        for label, path, _ in self._plists:
            kept = posixpath.join(self._kept_dir, posixpath.basename(path))
            if not os.path.isfile(kept):
                continue
            shutil.move(kept, path)
            if label == REMOTE_DESKTOP_DARWIN_SERVICE_LABEL:
                self._run([LAUNCHCTL, "bootstrap", "system", path], is_checked=False)
            elif seat_uid:
                self._run(
                    [LAUNCHCTL, "bootstrap", f"gui/{seat_uid}", path],
                    is_checked=False,
                )

    def copy_pids(self) -> list:
        """The processes of the agent's copy."""
        prefix = self._app + "/"
        return [
            pid for pid, program, _ in self._rustdesk() if program.startswith(prefix)
        ]

    def stale_pids(self) -> list:
        """The copy's processes that started before the copy on disk was
        written: the package replaced the bundle under them.

        Returns:
            Their pids; empty when the copy is not on disk.
        """
        try:
            status = os.stat(self.program)
        except OSError:
            return []
        written = max(status.st_mtime, status.st_ctime)
        now = time.time()
        stale = []
        for pid in self.copy_pids():
            elapsed = self._run(
                [PS, "-o", "etime=", "-p", str(pid)], is_checked=False
            ).stdout.strip()
            seconds = elapsed_seconds(elapsed)
            if seconds is not None and now - seconds < written:
                stale.append(pid)
        return stale

    def host_pids(self) -> list:
        """Every RustDesk process that is not a viewer."""
        return [
            pid for pid, _, arguments in self._rustdesk() if not is_viewer(arguments)
        ]

    def listening_programs(self, port: int) -> list:
        """The programs listening on one TCP port, from the socket table.

        Args:
            port: The port.

        Returns:
            Each listener's program; an empty string where it cannot be read.
        """
        result = self._run(
            [LSOF, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
            is_checked=False,
            timeout_s=10,
        )
        pids = [
            int(line[1:])
            for line in result.stdout.splitlines()
            if line.startswith("p") and line[1:].isdigit()
        ]
        programs = self._programs()
        return [programs.get(pid, "") for pid in pids]

    def _rustdesk(self) -> list:
        """Every RustDesk process: ``(pid, program, arguments)``."""
        programs = self._programs()
        found = []
        for pid, program in programs.items():
            if REMOTE_DESKTOP_DARWIN_PROGRAM_MARK not in program:
                continue
            if "rustdesk" not in program.lower():
                continue
            found.append((pid, program, self._arguments(pid)))
        return found

    def _programs(self) -> dict:
        """Every process's program path, by pid."""
        result = self._run([PS, "-axww", "-o", "pid=,comm="], is_checked=False)
        programs = {}
        for line in result.stdout.splitlines():
            pid, _, program = line.strip().partition(" ")
            if pid.isdigit():
                programs[int(pid)] = program.strip()
        return programs

    def _arguments(self, pid: int) -> list:
        result = self._run([PS, "-ww", "-o", "args=", "-p", str(pid)], is_checked=False)
        return result.stdout.split()

    def _bootout(self) -> None:
        seat_uid = self._seat_uid()
        if seat_uid:
            self._run(
                [
                    LAUNCHCTL,
                    "bootout",
                    f"gui/{seat_uid}/{REMOTE_DESKTOP_DARWIN_SESSION_LABEL}",
                ],
                is_checked=False,
            )
        self._run(
            [LAUNCHCTL, "bootout", f"system/{REMOTE_DESKTOP_DARWIN_SERVICE_LABEL}"],
            is_checked=False,
        )
        self._wait_for(
            lambda: self._run(
                [LAUNCHCTL, "print", f"system/{REMOTE_DESKTOP_DARWIN_SERVICE_LABEL}"],
                is_checked=False,
            ).exit_code
            != 0
        )

    def _is_own(self, path: str) -> bool:
        try:
            with open(path, "rb") as stream:
                job = plistlib.load(stream)
        except (OSError, ValueError, plistlib.InvalidFileException):
            return False
        arguments = job.get("ProgramArguments") if isinstance(job, dict) else None
        return isinstance(arguments, list) and any(
            str(argument).startswith(self._app + "/") for argument in arguments
        )

    def _end(self, pids: list) -> None:
        """End processes: SIGTERM, then SIGKILL for those still there."""
        for pid in pids:
            try:
                self._kill(pid, signal.SIGTERM)
            except OSError:
                continue
        if not pids:
            return
        self._wait_for(lambda: not any(self._is_alive(pid) for pid in pids))
        for pid in pids:
            if self._is_alive(pid):
                try:
                    self._kill(pid, signal.SIGKILL)
                except OSError:
                    continue

    def _is_alive(self, pid: int) -> bool:
        try:
            self._kill(pid, 0)
        except OSError:
            return False
        return True

    def _wait_for(self, is_done) -> None:
        waited = 0.0
        while not is_done() and waited < REMOTE_DESKTOP_STOP_TIMEOUT_S:
            self._sleep(REMOTE_DESKTOP_POLL_S)
            waited += REMOTE_DESKTOP_POLL_S
