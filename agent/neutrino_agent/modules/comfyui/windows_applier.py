"""ComfyUI on Windows: a scheduled task of LOCAL SERVICE's, the shared folders' access lists.

The module's directory grants the Users group read and execute, inherited,
which LOCAL SERVICE's token holds. The data directory ``comfyui_data`` under
the state root is LOCAL SERVICE's to change by inheritance, beside SYSTEM
and the administrators. The task ``neutrino_comfyui``, registered as LOCAL
SERVICE through the agent's PowerShell host, runs ``cmd.exe`` on a script in
the module's ``run`` folder that sets the server's environment and appends
its output to ``comfyui.log`` in the data directory; it starts at boot and
again a minute after it stops, and its description carries a digest of the
script. uv and every other command as LOCAL SERVICE run in a one-shot task
of LOCAL SERVICE's on a script of the same folder, with
``UV_STACK_SIZE=16777216`` and its output to a file in the data directory.
The shared folders' access lists are set on each folder's and file's handle
with no reparse point followed.

Not pure: writes under ``%ProgramData%``, drives the Task Scheduler and
ends processes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import hashlib
import ntpath
import os
import stat
import subprocess
import time

from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_BASE_DIR,
    COMFYUI_DATA_DIR_NAME,
    COMFYUI_NAME,
    COMFYUI_PYCACHE_DIR,
    COMFYUI_PYTHON_DIR,
    COMFYUI_READ_FOLDERS,
    COMFYUI_RUN_DIR,
    COMFYUI_SERVICE_FOLDERS,
    COMFYUI_TMP_DIR,
    COMFYUI_UV_CACHE_DIR,
    COMFYUI_VENV_DIR,
    COMFYUI_WINDOWS_ACCOUNT,
    COMFYUI_WINDOWS_KEPT_SIDS,
    COMFYUI_WINDOWS_LOG_NAME,
    COMFYUI_WINDOWS_REMOVE_RETRY_S,
    COMFYUI_WINDOWS_REMOVE_TRIES,
    COMFYUI_WINDOWS_SCRIPT_NAME,
    COMFYUI_WINDOWS_SERVICE_SID,
    COMFYUI_WINDOWS_STEP_OUTPUT_NAME,
    COMFYUI_WINDOWS_STEP_POLL_S,
    COMFYUI_WINDOWS_STEP_SCRIPT_NAME,
    COMFYUI_WINDOWS_STEP_TASK,
    COMFYUI_WINDOWS_STOP_RETRY_S,
    COMFYUI_WINDOWS_STOP_TRIES,
    COMFYUI_WINDOWS_TASK,
    COMFYUI_WINDOWS_TASK_MARKER,
    COMFYUI_WRITE_FOLDERS,
)
from neutrino_agent.modules.comfyui.server import (
    ComfyuiServer,
    server_command,
    server_environment,
)
from neutrino_agent.modules.shared.account_service import write_if_changed
from neutrino_agent.modules.shared.subprocess_run import run
from neutrino_agent.modules.shared.unpacked_tree import remove_tree
from neutrino_agent.modules.shared.windows_acl import grant_account_alone

# The shell the tasks run their script with, a running task's state, the
# states of a task that has not ended, and the last result of a task that
# has not run yet.
WINDOWS_SHELL = "cmd.exe"
TASK_RUNNING = "Running"
TASK_WAITING = ("Running", "Queued")
TASK_HAS_NOT_RUN = 0x41303
# How much of a step's output is read back.
STEP_OUTPUT_BYTES = 64 * 1024
# The reparse point attribute of a file.
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def cmd_quoted(text: str) -> str:
    """One argument as ``cmd.exe`` reads it in a script. Pure."""
    return subprocess.list2cmdline([text])


def render_script(lines: list, environment: dict) -> str:
    """A ``.cmd`` script that sets an environment and runs its lines. Pure.

    Args:
        lines: The commands, each one line.
        environment: The variables set first, by name.

    Returns:
        The script's text, CRLF line ends.
    """
    held = ["@echo off"]
    held += [f'set "{name}={value}"' for name, value in sorted(environment.items())]
    held += list(lines)
    return "\r\n".join(held) + "\r\n"


def task_description(script: str) -> str:
    """The description the task carries: a digest of the script it runs. Pure."""
    return (
        COMFYUI_WINDOWS_TASK_MARKER
        + hashlib.sha256(script.encode("utf-8")).hexdigest()[:16]
    )


class ComfyuiWindowsApplier:
    """Runs ComfyUI as a scheduled task of LOCAL SERVICE's.

    Attributes:
        account: Empty: LOCAL SERVICE is the system's own.
    """

    account = ""

    def __init__(
        self,
        *,
        state_dir: str,
        platform=None,
        powershell=None,
        processes=None,
        folder_access=None,
        account_sid=None,
        join=ntpath.join,
        sleep=time.sleep,
        clock=time.monotonic,
        run_command=run,
    ):
        """
        Args:
            state_dir: The agent's state root.
            platform: The machine's platform, whose PowerShell host, process
                table and folder access are used when none is given.
            powershell: The agent's PowerShell host.
            processes: The machine's process table.
            folder_access: Sets access lists on handles, as
                :class:`WindowsFolderAccess`.
            account_sid: Called with an account; its SID as text. None
                reads it from the system.
            join: Joins path parts, Windows' way unless told otherwise.
            sleep: Waits a number of seconds.
            clock: The monotonic clock a step's wait is counted on.
            run_command: Runs one command as :func:`subprocess_run.run` does.
        """
        self.os_name = "windows"
        self._join = join
        self.module_dir = join(state_dir, COMFYUI_NAME)
        self.data_dir = join(state_dir, COMFYUI_DATA_DIR_NAME)
        self.base_dir = join(self.data_dir, COMFYUI_BASE_DIR)
        self._run_dir = join(self.module_dir, COMFYUI_RUN_DIR)
        self.script_path = join(self._run_dir, COMFYUI_WINDOWS_SCRIPT_NAME)
        self._step_script = join(self._run_dir, COMFYUI_WINDOWS_STEP_SCRIPT_NAME)
        self._step_output = join(self.data_dir, COMFYUI_WINDOWS_STEP_OUTPUT_NAME)
        self.log_path = join(self.data_dir, COMFYUI_WINDOWS_LOG_NAME)
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
        self._folder_access = folder_access
        self._account_sid_of = account_sid
        self._sleep = sleep
        self._clock = clock
        self._run = run_command

    def ensure_account(self, *, log=None) -> bool:
        """Make nothing: LOCAL SERVICE is the system's own.

        Args:
            log: Unused: nothing is handed over.

        Returns:
            Always False.
        """
        return False

    def prepare_data(self) -> None:
        """Make the data directory LOCAL SERVICE's to change by inheritance when it is new, and its folders.

        Raises:
            OSError: When a folder cannot be made or icacls refuses.
        """
        if not os.path.isdir(self.data_dir):
            os.makedirs(self.data_dir)
            grant_account_alone(
                self._run, self.data_dir, COMFYUI_WINDOWS_SERVICE_SID, "M", is_tree=True
            )
        for name in (COMFYUI_UV_CACHE_DIR, COMFYUI_TMP_DIR, COMFYUI_PYCACHE_DIR):
            os.makedirs(self._join(self.data_dir, name), exist_ok=True)
        for name in (
            COMFYUI_WRITE_FOLDERS + COMFYUI_READ_FOLDERS + COMFYUI_SERVICE_FOLDERS
        ):
            os.makedirs(self._join(self.base_dir, name), exist_ok=True)

    def run_as_service(self, argv: list, environment: dict, timeout_s: int) -> tuple:
        """Run one command as LOCAL SERVICE in a one-shot task, its output to a file in the data directory.

        Args:
            argv: The argument vector.
            environment: Its variables, beside the task's own.
            timeout_s: How long it may run.

        Returns:
            ``(exit_code, output)``: the task's last result and the end of
            the command's output; 127 with the error when it could not run.
        """
        output = self._step_output
        script = render_script(
            [
                f"cd /d {cmd_quoted(self.data_dir)}",
                f"{subprocess.list2cmdline(argv)} > {cmd_quoted(output)} 2>&1",
                "exit /b %ERRORLEVEL%",
            ],
            environment,
        )
        try:
            os.makedirs(self._run_dir, exist_ok=True)
            write_if_changed(self._step_script, script, 0o644)
            self._powershell.call(
                "task_run_service",
                {
                    "task": COMFYUI_WINDOWS_STEP_TASK,
                    "account": COMFYUI_WINDOWS_ACCOUNT,
                    "program": WINDOWS_SHELL,
                    "arguments": subprocess.list2cmdline(["/c", self._step_script]),
                    "timeout_s": int(timeout_s),
                },
            )
            code = self._wait_step(timeout_s)
        except Exception as error:  # noqa: BLE001 - the step's failure names it
            return 127, str(error) or type(error).__name__
        finally:
            with contextlib.suppress(Exception):
                self._powershell.call(
                    "task_remove", {"task": COMFYUI_WINDOWS_STEP_TASK}
                )
        return code, self._read_output(output)

    def remove_as_service(self, path: str) -> None:
        """Delete one tree of the data directory as LOCAL SERVICE.

        Raises:
            OSError: When the tree is still there afterwards.
        """
        if not os.path.lexists(path):
            return
        code, output = self.run_as_service(
            [WINDOWS_SHELL, "/c", "rmdir", "/s", "/q", path], {}, 600
        )
        if os.path.lexists(path):
            raise OSError(
                f"could not remove {path}: exit {code} {output.strip()[-200:]}"
            )

    def write_access(self, account: str) -> list:
        """Give the default account its entries on the shared folders and every file and folder under them.

        Every other account's own allow entry on ``data\\`` and the five
        folders goes. ``data\\`` takes read and execute for the account
        alone, the write folders ``(OI)(CI)M`` and the read folders
        ``(OI)(CI)RX``; every file and folder under them takes the account's
        right and LOCAL SERVICE's modify, each on its own handle.

        Args:
            account: The default account; empty names none.

        Returns:
            The paths left as they are.

        Raises:
            OSError: When a top folder's access list cannot be set.
        """
        access = self._access()
        kept = set(COMFYUI_WINDOWS_KEPT_SIDS)
        if account:
            kept.add(self._account_sid(account))
        folders = [self.base_dir] + [
            self._join(self.base_dir, name)
            for name in COMFYUI_WRITE_FOLDERS + COMFYUI_READ_FOLDERS
        ]
        left: list = []
        for folder in folders:
            try:
                others = [sid for sid in access.allowed_sids(folder) if sid not in kept]
                access.revoke_sids(folder, others)
            except OSError:
                left.append(folder)
        if not account:
            return left
        access.grant_rights(
            self.base_dir, [(account, "RX")], is_folder=True, is_inherited=False
        )
        for name in COMFYUI_WRITE_FOLDERS + COMFYUI_READ_FOLDERS:
            right = "M" if name in COMFYUI_WRITE_FOLDERS else "RX"
            folder = self._join(self.base_dir, name)
            try:
                access.grant_rights(
                    folder, [(account, right)], is_folder=True, is_inherited=True
                )
            except OSError:
                left.append(folder)
                continue
            self._walk(access, folder, account, right, left)
        return left

    def service_text(self, server: ComfyuiServer) -> str:
        """The script the service's task runs."""
        command = subprocess.list2cmdline(
            server_command(
                server,
                module_dir=self.module_dir,
                data_dir=self.data_dir,
                os_name="windows",
            )
        )
        return render_script(
            [f"{command} >> {cmd_quoted(self.log_path)} 2>&1"],
            server_environment(server, data_dir=self.data_dir, os_name="windows"),
        )

    def written_text(self) -> str:
        """The script as it is written now; empty for none."""
        try:
            with open(self.script_path, "r", encoding="utf-8", newline="") as stream:
                return stream.read()
        except OSError:
            return ""

    def apply(self, server: ComfyuiServer, *, is_started: bool = True) -> str:
        """Write the script and register the task; with ``is_started``, run it.

        A task whose description names another script is registered again,
        and a running one is stopped first.

        Args:
            server: What the start takes.
            is_started: Whether the task is enabled and started.

        Returns:
            ``unchanged``, ``written``, ``restarted`` or ``started``.

        Raises:
            ModuleApplyError: When the PowerShell host refuses.
            OSError: When a file cannot be written.
        """
        os.makedirs(self._run_dir, exist_ok=True)
        script = self.service_text(server)
        write_if_changed(self.script_path, script, 0o644)
        description = task_description(script)
        held = self._powershell.call("task_read", {"task": COMFYUI_WINDOWS_TASK})
        is_running = held.get("state") == TASK_RUNNING
        is_changed = (
            not held.get("is_present") or held.get("description") != description
        )
        if is_changed:
            if is_running:
                self._end()
            self._powershell.call(
                "task_write_service",
                {
                    "task": COMFYUI_WINDOWS_TASK,
                    "account": COMFYUI_WINDOWS_ACCOUNT,
                    "description": description,
                    "program": WINDOWS_SHELL,
                    "arguments": subprocess.list2cmdline(["/c", self.script_path]),
                },
            )
        if not is_started:
            if is_changed:
                self._powershell.call("task_stop", {"task": COMFYUI_WINDOWS_TASK})
            return "written" if is_changed else "unchanged"
        if is_running and not is_changed:
            return "unchanged"
        self._powershell.call("task_start", {"task": COMFYUI_WINDOWS_TASK})
        return "restarted" if is_running else "started"

    def stop(self) -> None:
        """Stop and disable the task and end the server's processes; it stays stopped across a reboot."""
        self._end()

    def is_active(self) -> bool:
        """Whether the task runs now."""
        try:
            held = self._powershell.call("task_read", {"task": COMFYUI_WINDOWS_TASK})
        except Exception:  # noqa: BLE001 - a read that fails reads as not running
            return False
        return held.get("state") == TASK_RUNNING

    def uninstall(self) -> None:
        """Unregister the task and delete the module's directory; the data directory stays."""
        self._end()
        self._powershell.call("task_remove", {"task": COMFYUI_WINDOWS_TASK})
        for _turn in range(COMFYUI_WINDOWS_REMOVE_TRIES):
            remove_tree(self.module_dir)
            if not os.path.exists(self.module_dir):
                break
            self._sleep(COMFYUI_WINDOWS_REMOVE_RETRY_S)

    def journal_units(self) -> list:
        """No journal: Windows runs no unit."""
        return []

    def output_path(self) -> str:
        """The log the server's output is appended to."""
        return self.log_path

    def _account_sid(self, account: str) -> str:
        """One account's SID as text."""
        if self._account_sid_of is None:
            from neutrino_agent.platforms.windows_accounts import account_sid

            self._account_sid_of = account_sid
        return self._account_sid_of(account)

    def _access(self):
        """The folder access the shared folders' lists are set with."""
        if self._folder_access is None:
            from neutrino_agent.platforms.windows_folder import WindowsFolderAccess

            self._folder_access = WindowsFolderAccess()
        return self._folder_access

    def _walk(self, access, folder: str, account: str, right: str, left: list) -> None:
        """Give every file and folder under one shared folder its entries, no reparse point followed."""
        rights = [(account, right), (COMFYUI_WINDOWS_SERVICE_SID, "M")]
        try:
            entries = list(os.scandir(folder))
        except OSError:
            left.append(folder)
            return
        for entry in entries:
            try:
                facts = entry.stat(follow_symlinks=False)
            except OSError:
                left.append(entry.path)
                continue
            if getattr(facts, "st_file_attributes", 0) & REPARSE_POINT:
                continue
            is_folder = stat.S_ISDIR(facts.st_mode)
            try:
                access.grant_rights(
                    entry.path, rights, is_folder=is_folder, is_inherited=is_folder
                )
            except OSError:
                left.append(entry.path)
                continue
            if is_folder:
                self._walk(access, entry.path, account, right, left)

    def _wait_step(self, timeout_s: int) -> int:
        """Wait for the one-shot task to end, and give its last result.

        Raises:
            OSError: When it runs past its time.
        """
        deadline = self._clock() + timeout_s + 60
        while True:
            self._sleep(COMFYUI_WINDOWS_STEP_POLL_S)
            held = self._powershell.call(
                "task_states", {"prefix": COMFYUI_WINDOWS_STEP_TASK}
            )
            tasks = [
                task
                for task in held.get("tasks") or []
                if task.get("name") == COMFYUI_WINDOWS_STEP_TASK
            ]
            if tasks:
                state = str(tasks[0].get("state", "") or "")
                result = int(tasks[0].get("last_result", 0) or 0)
                if state not in TASK_WAITING and result != TASK_HAS_NOT_RUN:
                    return result
            if self._clock() >= deadline:
                raise OSError(f"the task {COMFYUI_WINDOWS_STEP_TASK} ran past its time")

    def _read_output(self, path: str) -> str:
        """The end of a step's output, read only when the file is no reparse point."""
        try:
            facts = os.lstat(path)
            if getattr(facts, "st_file_attributes", 0) & REPARSE_POINT:
                return ""
            with open(path, "rb") as stream:
                size = stream.seek(0, os.SEEK_END)
                stream.seek(max(0, size - STEP_OUTPUT_BYTES))
                return stream.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def _end(self) -> None:
        """Stop and disable the task, then end every process of the server and wait for them."""
        self._powershell.call("task_stop", {"task": COMFYUI_WINDOWS_TASK})
        if self._processes is None:
            return
        for _turn in range(COMFYUI_WINDOWS_STOP_TRIES):
            pids = self._own_pids()
            if not pids:
                return
            self._processes.end(pids)
            self._sleep(COMFYUI_WINDOWS_STOP_RETRY_S)

    def _own_pids(self) -> list:
        """The processes started from the venv or from the module's Python."""
        folders = [
            ntpath.normcase(self._join(self.data_dir, COMFYUI_VENV_DIR)) + "\\",
            ntpath.normcase(self._join(self.module_dir, COMFYUI_PYTHON_DIR)) + "\\",
        ]
        try:
            entries = self._processes.entries()
        except OSError:
            return []
        found = []
        for entry in entries:
            if not entry.pid:
                continue
            image = ntpath.normcase(self._processes.image_path(entry.pid))
            if any(image.startswith(folder) for folder in folders):
                found.append(entry.pid)
        return found
