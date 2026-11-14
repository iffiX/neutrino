"""Ollama on Windows: a scheduled task of SYSTEM's, the publisher's app.

The program is unpacked under ``ollama\\`` in the module's directory, and the
models live in ``ollama_data`` under the state root, which the root's own
grants keep to SYSTEM and the administrators. ``ollama.exe`` is no service
program, so the task ``neutrino_ollama``, registered as SYSTEM through the
agent's PowerShell host, runs ``cmd.exe`` on a script beside the program
that sets the module's environment and appends the server's output to its
log. The task starts at boot and again a minute after it stops, and its
description carries a digest of the script, so an unchanged task is left
running. A stop ends the task and every process of the module's program. A
person's Ollama here is the publisher's per-user app, which the module
never starts or stops.

Not pure: writes under ``%ProgramData%``, drives the Task Scheduler and
ends processes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import glob
import hashlib
import ntpath
import os
import subprocess
import time

from neutrino_agent.modules.ollama.constants import (
    OLLAMA_DATA_DIR_NAME,
    OLLAMA_ENVIRONMENT,
    OLLAMA_HOST,
    OLLAMA_MODELS_DIR_NAME,
    OLLAMA_NAME,
    OLLAMA_PERSON_UNIT,
    OLLAMA_PORT,
    OLLAMA_PROGRAM_DIR_NAME,
    OLLAMA_SERVE_ARGUMENTS,
    OLLAMA_WINDOWS_APP_PARTS,
    OLLAMA_WINDOWS_LOG_NAME,
    OLLAMA_WINDOWS_PROGRAM_NAME,
    OLLAMA_WINDOWS_REMOVE_RETRY_S,
    OLLAMA_WINDOWS_REMOVE_TRIES,
    OLLAMA_WINDOWS_SCRIPT_PARTS,
    OLLAMA_WINDOWS_STOP_RETRY_S,
    OLLAMA_WINDOWS_STOP_TRIES,
    OLLAMA_WINDOWS_TASK,
    OLLAMA_WINDOWS_TASK_MARKER,
)
from neutrino_agent.modules.shared.account_service import write_if_changed
from neutrino_agent.modules.shared.unpacked_tree import remove_tree

# The shell the task runs the script with, and the state of a running task.
WINDOWS_SHELL = "cmd.exe"
TASK_RUNNING = "Running"


def render_script(*, program: str, data_dir: str, log: str) -> str:
    """The script the task runs. Pure.

    Args:
        program: ``ollama.exe``.
        data_dir: The data directory.
        log: The file the server's output is appended to.

    Returns:
        The ``.cmd`` text, CRLF line ends: the environment set, then the
        server run with its output appended to the log.
    """
    environment = {
        "OLLAMA_HOST": f"{OLLAMA_HOST}:{OLLAMA_PORT}",
        "OLLAMA_MODELS": ntpath.join(data_dir, OLLAMA_MODELS_DIR_NAME),
        **OLLAMA_ENVIRONMENT,
    }
    lines = ["@echo off"]
    lines += [f'set "{name}={value}"' for name, value in sorted(environment.items())]
    command = subprocess.list2cmdline([program, *OLLAMA_SERVE_ARGUMENTS])
    lines.append(f'{command} >> "{log}" 2>&1')
    return "\r\n".join(lines) + "\r\n"


def task_description(script: str) -> str:
    """The description the task carries: a digest of the script it runs. Pure.

    Args:
        script: The script's text.

    Returns:
        ``neutrino:`` and 16 hex digits.
    """
    return (
        OLLAMA_WINDOWS_TASK_MARKER
        + hashlib.sha256(script.encode("utf-8")).hexdigest()[:16]
    )


class OllamaWindowsApplier:
    """Runs Ollama as a scheduled task of SYSTEM's.

    Attributes:
        account: Empty: the server runs as SYSTEM.
        is_app_system: True: a person's Ollama here is the publisher's app.
    """

    account = ""
    is_app_system = True

    def __init__(
        self,
        *,
        state_dir: str,
        platform=None,
        powershell=None,
        processes=None,
        users_dir: str = "",
        join=ntpath.join,
        sleep=time.sleep,
    ):
        """
        Args:
            state_dir: The agent's state root.
            platform: The machine's platform, whose PowerShell host and
                process table are used when none is given.
            powershell: The agent's PowerShell host; None takes the
                platform's.
            processes: The machine's process table; None takes the
                platform's.
            users_dir: The folder that holds the profiles; empty reads it
                from ``PUBLIC``'s parent.
            join: Joins path parts, Windows' way unless told otherwise.
            sleep: Waits a number of seconds.
        """
        self._join = join
        self.module_dir = join(state_dir, OLLAMA_NAME)
        self.data_dir = join(state_dir, OLLAMA_DATA_DIR_NAME)
        self.program_path = join(
            self.module_dir, OLLAMA_PROGRAM_DIR_NAME, OLLAMA_WINDOWS_PROGRAM_NAME
        )
        self.script_path = join(self.module_dir, *OLLAMA_WINDOWS_SCRIPT_PARTS)
        self.log_path = join(self.data_dir, OLLAMA_WINDOWS_LOG_NAME)
        self._powershell = (
            powershell
            if powershell is not None
            else getattr(platform, "powershell_host", None)
        )
        self._processes = (
            processes
            if processes is not None
            else getattr(platform, "process_table", None)
        )
        self._users_dir = users_dir or ntpath.dirname(
            os.environ.get("PUBLIC", "C:\\Users\\Public")
        )
        self._sleep = sleep

    def person_unit_path(self) -> str:
        """Empty: a person's unit is Linux's."""
        return ""

    def person_unit_name(self) -> str:
        """The name a person's unit has on Linux."""
        return OLLAMA_PERSON_UNIT

    def person_unit_state(self) -> dict:
        """Nothing: there is no person's unit here."""
        return {}

    def start_person(self) -> None:
        """Nothing: a person's app is the person's to start."""

    def stop_person(self) -> None:
        """Nothing: a person's app is the person's to stop."""

    def restore_person(self, found: dict) -> None:
        """Nothing: a person's app was never moved.

        Args:
            found: Unread.
        """

    def app_path(self) -> str:
        """The publisher's app in any profile, empty when none has it."""
        pattern = self._join(
            glob.escape(self._users_dir), "*", *OLLAMA_WINDOWS_APP_PARTS
        )
        found = sorted(glob.glob(pattern))
        return found[0] if found else ""

    def ensure_account(self, *, log=None) -> bool:
        """Make nothing: the server runs as SYSTEM.

        Args:
            log: Unused: nothing is handed over.

        Returns:
            Always False.
        """
        return False

    def apply(self, *, is_started: bool = True) -> str:
        """Write the script and register the task; with ``is_started``, run it.

        A task whose description names another script is registered again,
        and a running one is stopped first.

        Args:
            is_started: Whether the task is enabled and started.

        Returns:
            ``unchanged``, ``written``, ``restarted`` or ``started``.

        Raises:
            ModuleApplyError: When the PowerShell host refuses.
            OSError: When a file cannot be written.
        """
        os.makedirs(self._join(self.data_dir, OLLAMA_MODELS_DIR_NAME), exist_ok=True)
        os.makedirs(ntpath.dirname(self.script_path), exist_ok=True)
        script = render_script(
            program=self.program_path, data_dir=self.data_dir, log=self.log_path
        )
        write_if_changed(self.script_path, script, 0o644)
        description = task_description(script)
        held = self._powershell.call("task_read", {"task": OLLAMA_WINDOWS_TASK})
        is_running = held.get("state") == TASK_RUNNING
        is_changed = (
            not held.get("is_present") or held.get("description") != description
        )
        if is_changed:
            if is_running:
                self._end()
            self._powershell.call(
                "task_write_system",
                {
                    "task": OLLAMA_WINDOWS_TASK,
                    "description": description,
                    "program": WINDOWS_SHELL,
                    "arguments": subprocess.list2cmdline(["/c", self.script_path]),
                },
            )
        if not is_started:
            if is_changed:
                self._powershell.call("task_stop", {"task": OLLAMA_WINDOWS_TASK})
            return "written" if is_changed else "unchanged"
        if is_running and not is_changed:
            return "unchanged"
        self._powershell.call("task_start", {"task": OLLAMA_WINDOWS_TASK})
        return "restarted" if is_running else "started"

    def stop(self) -> None:
        """Stop and disable the task and end the program's processes; it stays stopped across a reboot."""
        self._end()

    def is_active(self) -> bool:
        """Whether the task runs now."""
        try:
            held = self._powershell.call("task_read", {"task": OLLAMA_WINDOWS_TASK})
        except Exception:  # noqa: BLE001 - a read that fails reads as not running
            return False
        return held.get("state") == TASK_RUNNING

    def uninstall(self) -> str:
        """Unregister the task and delete the program and its script; the data directory stays.

        Returns:
            Empty.
        """
        self._end()
        self._powershell.call("task_remove", {"task": OLLAMA_WINDOWS_TASK})
        for _turn in range(OLLAMA_WINDOWS_REMOVE_TRIES):
            remove_tree(self.module_dir)
            if not os.path.exists(self.module_dir):
                break
            self._sleep(OLLAMA_WINDOWS_REMOVE_RETRY_S)
        return ""

    def journal_units(self) -> list:
        """No journal: Windows runs no unit."""
        return []

    def output_path(self) -> str:
        """The log the server's output is appended to."""
        return self.log_path

    def _end(self) -> None:
        """Stop and disable the task, then end every process of the module's program and wait for them."""
        self._powershell.call("task_stop", {"task": OLLAMA_WINDOWS_TASK})
        if self._processes is None:
            return
        for _turn in range(OLLAMA_WINDOWS_STOP_TRIES):
            pids = self._own_pids()
            if not pids:
                return
            self._processes.end(pids)
            self._sleep(OLLAMA_WINDOWS_STOP_RETRY_S)

    def _own_pids(self) -> list:
        """The processes started from the module's program folder."""
        folder = ntpath.normcase(ntpath.dirname(self.program_path)) + "\\"
        try:
            entries = self._processes.entries()
        except OSError:
            return []
        return [
            entry.pid
            for entry in entries
            if entry.pid
            and ntpath.normcase(self._processes.image_path(entry.pid)).startswith(
                folder
            )
        ]
