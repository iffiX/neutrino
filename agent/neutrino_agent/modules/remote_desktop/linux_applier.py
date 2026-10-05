"""The agent's copy of RustDesk on Linux, registered as ``rustdesk.service``.

With the switch on the agent writes ``/etc/systemd/system/rustdesk.service``
running its copy, which overrides a packaged unit of that name, and enables
and starts it. A unit file of that name in ``/etc`` that is not the
agent's is moved to ``kept/``; whether the packaged unit was enabled and
running is kept in ``kept/service.json``. The host is stopped with
``systemctl kill``, never ``systemctl stop`` of upstream's own unit, whose
``ExecStop`` is ``pkill -f "rustdesk --"`` and would end a person's viewers
too. With the switch off the agent's unit is disabled, stopped and deleted,
and what was kept is put back as it was.

Not pure: drives systemd and ends processes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import posixpath
import re
import shutil
import signal
import time

from neutrino_agent.modules.remote_desktop.constants import (
    REMOTE_DESKTOP_KEPT_SERVICE_NAME,
    REMOTE_DESKTOP_LINUX_PROGRAM,
    REMOTE_DESKTOP_LINUX_ROOT_SETTINGS,
    REMOTE_DESKTOP_LINUX_SEAT_SETTINGS,
    REMOTE_DESKTOP_LINUX_UNIT,
    REMOTE_DESKTOP_LINUX_UNIT_PATH,
    REMOTE_DESKTOP_LINUX_UNIT_TEXT,
    REMOTE_DESKTOP_POLL_S,
    REMOTE_DESKTOP_STOP_TIMEOUT_S,
    REMOTE_DESKTOP_VIEWER_FLAGS,
)
from neutrino_agent.modules.remote_desktop.records import read_json, write_json
from neutrino_agent.modules.subprocess_run import run as run_command

# The line that marks the unit file as the agent's own.
UNIT_MARK = "Written by the Neutrino agent"
PROC_DIR = "/proc"
LISTENER_PID = re.compile(r"pid=(\d+)")


def is_viewer(arguments: list) -> bool:
    """Whether a RustDesk process is a viewer a person may be using.

    Args:
        arguments: Its argument vector.

    Returns:
        True when it names one of the viewer flags.
    """
    return any(flag in arguments for flag in REMOTE_DESKTOP_VIEWER_FLAGS)


class RemoteDesktopLinuxApplier:
    """Takes RustDesk over on Linux and gives it back."""

    def __init__(
        self,
        *,
        kept_dir: str,
        run=None,
        program: str = REMOTE_DESKTOP_LINUX_PROGRAM,
        unit_path: str = REMOTE_DESKTOP_LINUX_UNIT_PATH,
        proc_dir: str = PROC_DIR,
        kill=os.kill,
        sleep=time.sleep,
    ):
        """
        Args:
            kept_dir: Where what is kept aside goes.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            program: The agent's copy.
            unit_path: Where the agent's unit is written.
            proc_dir: The process table.
            kill: Sends a signal to a pid.
            sleep: Waits a number of seconds.
        """
        self.program = program
        self._kept_dir = kept_dir
        self._run = run if run is not None else run_command
        self._unit_path = unit_path
        self._proc_dir = proc_dir
        self._kill = kill
        self._sleep = sleep

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
        dirs = [REMOTE_DESKTOP_LINUX_ROOT_SETTINGS]
        if seat_home:
            dirs.append(posixpath.join(seat_home, REMOTE_DESKTOP_LINUX_SEAT_SETTINGS))
        return dirs

    def is_registered(self) -> bool:
        """Whether the agent's unit file is in place."""
        return self._is_own_unit(self._unit_path)

    def keep_aside(self) -> dict:
        """Record and move aside what is registered under ``rustdesk.service``
        and is not the agent's.

        Returns:
            What was kept: ``{"is_enabled", "is_active", "is_moved"}``, empty
            when nothing of anybody else's is registered.
        """
        shown = self._show()
        fragment = shown.get("FragmentPath", "")
        is_moved = os.path.isfile(self._unit_path) and not self._is_own_unit(
            self._unit_path
        )
        if not is_moved and (
            not fragment
            or fragment == self._unit_path
            or self.program in shown.get("ExecStart", "")
        ):
            return {}
        kept = {
            "is_enabled": shown.get("UnitFileState", "") == "enabled",
            "is_active": shown.get("ActiveState", "") == "active",
            "is_moved": is_moved,
        }
        os.makedirs(self._kept_dir, mode=0o700, exist_ok=True)
        if is_moved:
            shutil.move(
                self._unit_path,
                posixpath.join(self._kept_dir, REMOTE_DESKTOP_LINUX_UNIT),
            )
        write_json(
            posixpath.join(self._kept_dir, REMOTE_DESKTOP_KEPT_SERVICE_NAME), kept
        )
        return kept

    def stop_hosts(self) -> None:
        """End the unit's processes and every RustDesk host left, viewers
        aside."""
        self._run(
            ["systemctl", "kill", "--signal=SIGTERM", REMOTE_DESKTOP_LINUX_UNIT],
            is_checked=False,
        )
        self._wait_for(lambda: not self._is_active())
        self._end(self.host_pids())

    def register(self) -> None:
        """Write, enable and load the agent's unit.

        A packaged unit of the same name is disabled first, so its links do
        not stand in the way of the agent's; :meth:`restore` enables it
        again when it was.

        Raises:
            OSError: When the file cannot be written.
            subprocess.CalledProcessError: When systemd refuses.
        """
        self._run(["systemctl", "disable", REMOTE_DESKTOP_LINUX_UNIT], is_checked=False)
        os.makedirs(os.path.dirname(self._unit_path), exist_ok=True)
        with open(self._unit_path, "w", encoding="utf-8") as stream:
            stream.write(REMOTE_DESKTOP_LINUX_UNIT_TEXT.format(program=self.program))
        self._run(["systemctl", "daemon-reload"])
        self._run(["systemctl", "enable", REMOTE_DESKTOP_LINUX_UNIT])

    def start(self, seat_uid: "int | None") -> None:
        """Start the agent's unit.

        Args:
            seat_uid: Unused on Linux: the service starts the session's host.

        Raises:
            subprocess.CalledProcessError: When systemd refuses.
        """
        self._run(["systemctl", "restart", REMOTE_DESKTOP_LINUX_UNIT])

    def unregister(self) -> None:
        """Disable, stop and delete the agent's unit; end its copy's hosts.

        Raises:
            subprocess.CalledProcessError: When systemd refuses.
        """
        if self._is_own_unit(self._unit_path):
            self._run(
                ["systemctl", "disable", REMOTE_DESKTOP_LINUX_UNIT], is_checked=False
            )
            self._run(
                ["systemctl", "stop", REMOTE_DESKTOP_LINUX_UNIT], is_checked=False
            )
            os.unlink(self._unit_path)
            self._run(["systemctl", "daemon-reload"])
        self._end(self.copy_pids())

    def restore(self) -> None:
        """Put back what :meth:`keep_aside` kept, as it was.

        Raises:
            OSError: When a kept file cannot be moved back.
            subprocess.CalledProcessError: When systemd refuses.
        """
        kept_path = posixpath.join(self._kept_dir, REMOTE_DESKTOP_KEPT_SERVICE_NAME)
        kept = read_json(kept_path)
        moved = posixpath.join(self._kept_dir, REMOTE_DESKTOP_LINUX_UNIT)
        if os.path.isfile(moved):
            shutil.move(moved, self._unit_path)
            self._run(["systemctl", "daemon-reload"])
        if kept.get("is_enabled"):
            self._run(["systemctl", "enable", REMOTE_DESKTOP_LINUX_UNIT])
        if kept.get("is_active"):
            self._run(["systemctl", "start", REMOTE_DESKTOP_LINUX_UNIT])
        if os.path.isfile(kept_path):
            os.unlink(kept_path)

    def copy_pids(self) -> list:
        """The processes of the agent's copy that are hosts."""
        return [pid for pid, program, _ in self._rustdesk() if program == self.program]

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
            ["ss", "-ltnpH", f"sport = :{port}"], is_checked=False, timeout_s=10
        )
        programs = []
        for pid in LISTENER_PID.findall(result.stdout):
            programs.append(self._program_of(int(pid)))
        if not programs and result.stdout.strip():
            programs.append("")
        return programs

    def _rustdesk(self) -> list:
        """Every RustDesk process: ``(pid, program, arguments)``."""
        found = []
        try:
            names = os.listdir(self._proc_dir)
        except OSError:
            return found
        for name in names:
            if not name.isdigit():
                continue
            try:
                with open(
                    posixpath.join(self._proc_dir, name, "cmdline"), "rb"
                ) as stream:
                    arguments = [
                        part.decode("utf-8", "replace")
                        for part in stream.read().split(b"\0")
                        if part
                    ]
            except OSError:
                continue
            program = self._program_of(int(name))
            base = posixpath.basename(program or (arguments[0] if arguments else ""))
            if base.lower().startswith("rustdesk"):
                found.append((int(name), program, arguments))
        return found

    def _program_of(self, pid: int) -> str:
        try:
            program = os.readlink(posixpath.join(self._proc_dir, str(pid), "exe"))
        except OSError:
            return ""
        return program.replace(" (deleted)", "")

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
        return os.path.exists(posixpath.join(self._proc_dir, str(pid)))

    def _is_active(self) -> bool:
        return self._run(
            ["systemctl", "is-active", REMOTE_DESKTOP_LINUX_UNIT], is_checked=False
        ).stdout.strip() in ("active", "activating", "deactivating")

    def _show(self) -> dict:
        """What systemd says of ``rustdesk.service``: ``{key: value}``."""
        result = self._run(
            [
                "systemctl",
                "show",
                REMOTE_DESKTOP_LINUX_UNIT,
                "-p",
                "FragmentPath",
                "-p",
                "UnitFileState",
                "-p",
                "ActiveState",
                "-p",
                "ExecStart",
            ],
            is_checked=False,
        )
        shown = {}
        for line in result.stdout.splitlines():
            key, _, value = line.partition("=")
            shown[key.strip()] = value.strip()
        return shown

    def _is_own_unit(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as stream:
                return UNIT_MARK in stream.read()
        except OSError:
            return False

    def _wait_for(self, is_done) -> None:
        waited = 0.0
        while not is_done() and waited < REMOTE_DESKTOP_STOP_TIMEOUT_S:
            self._sleep(REMOTE_DESKTOP_POLL_S)
            waited += REMOTE_DESKTOP_POLL_S
