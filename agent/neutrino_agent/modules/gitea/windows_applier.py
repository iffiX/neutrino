"""The git server on Windows: a service run as LocalSystem, the machine's git.

The binary goes into the module's own directory under the state root, the
server's data and its ``app.ini`` into ``gitea_data`` beside it, which the
state root's own grants keep to SYSTEM and the administrators. The service
``neutrino_gitea`` runs the server as LocalSystem, made with ``sc.exe`` as
Gitea's own page for a Windows service describes, so ``RUN_USER`` is the
name LocalSystem goes by, ``<computer name>$``. The agent is LocalSystem
too, so it runs the gitea CLI itself. Git is the module's own MinGit,
unpacked under the module's directory and named in ``app.ini`` alone, and
Gitea writes its hooks for MinGit's ``sh``.

Not pure: writes under ``%ProgramData%``, drives ``sc.exe``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ntpath
import os
import subprocess
import time

from neutrino_agent.modules.gitea.applier import (
    GiteaState,
    read_listen_port,
    read_root_url,
)
from neutrino_agent.modules.gitea.constants import (
    GITEA_BINARY_DIR_NAME,
    GITEA_CONF_PARTS,
    GITEA_DATA_DIR_NAME,
    GITEA_DATA_PARTS,
    GITEA_LOG_PARTS,
    GITEA_VERSION_PREFIX,
    GITEA_WINDOWS_DISPLAY_NAME,
    GITEA_WINDOWS_GIT_PARTS,
    GITEA_WINDOWS_SCRIPT_TYPE,
    GITEA_WINDOWS_SERVICE,
    GITEA_WINDOWS_STOP_POLL_S,
    GITEA_WINDOWS_REMOVE_RETRY_S,
    GITEA_WINDOWS_REMOVE_TRIES,
    GITEA_WINDOWS_STOP_TIMEOUT_S,
)
from neutrino_agent.modules.gitea.renderer import GiteaLayout
from neutrino_agent.modules.shared.log_tail import file_tail
from neutrino_agent.modules.shared.package import place_binary
from neutrino_agent.modules.shared.subprocess_run import run as run_command
from neutrino_agent.modules.shared.unpacked_tree import remove_tree
from neutrino_agent.modules.shared.account_service import write_if_changed

# What ``sc.exe`` exits with for a service that does not exist, and for a
# start of one that already runs.
SC_SERVICE_DOES_NOT_EXIST = 1060
SC_ALREADY_RUNNING = 1056
# What ``sc.exe failure`` is told: start it again five seconds after each
# failure, and count failures afresh after a day.
SC_FAILURE_ACTIONS = (
    "reset=",
    "86400",
    "actions=",
    "restart/5000/restart/5000/restart/5000",
)


def run_user() -> str:
    """The name LocalSystem goes by in its own environment.

    Returns:
        ``USERNAME`` as the agent's service sees it, which is the server's
        service's too, else ``<computer name>$``.
    """
    return os.environ.get("USERNAME") or os.environ.get("COMPUTERNAME", "") + "$"


def _service_command(binary: str, conf: str) -> str:
    """The command line the service runs, its paths quoted."""
    return f'"{binary}" web --config "{conf}"'


class GiteaWindowsApplier:
    """Runs the git server as a Windows service.

    Attributes:
        account: Empty: the server runs as LocalSystem.
    """

    is_git_required = True
    has_git_step = False
    account = ""

    def __init__(
        self,
        *,
        state_dir: str,
        run=None,
        is_file=None,
        join=ntpath.join,
        user: "str | None" = None,
        sleep=time.sleep,
    ):
        """
        Args:
            state_dir: The agent's state root.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            is_file: Called with a path; whether a file is there. None asks
                the file system.
            join: Joins path parts, Windows' way unless told otherwise.
            user: The name the server runs as; None reads it from the
                agent's own environment.
            sleep: Waits a number of seconds.
        """
        self._join = join
        self.module_dir = join(state_dir, GITEA_BINARY_DIR_NAME)
        self.data_dir = join(state_dir, GITEA_DATA_DIR_NAME)
        self.binary_path = join(self.module_dir, "gitea.exe")
        self.conf_path = join(self.data_dir, *GITEA_CONF_PARTS)
        self._run = run if run is not None else run_command
        self._is_file = is_file if is_file is not None else os.path.isfile
        self._user = user
        self._sleep = sleep

    def find_git(self) -> str:
        """The module's own MinGit's git.

        Returns:
            ``git\\cmd\\git.exe`` under the module's directory; empty
            while the MinGit artifact is not unpacked there.
        """
        path = self._join(self.module_dir, *GITEA_WINDOWS_GIT_PARTS)
        return path if self._is_file(path) else ""

    def layout(self, git_path: str) -> GiteaLayout:
        """Where the server runs on this machine.

        Args:
            git_path: The git :meth:`find_git` found.

        Returns:
            LocalSystem's name, the data directory and that git with ``/``
            between the parts, the service's name, and MinGit's ``sh`` for
            the hooks.
        """
        return GiteaLayout(
            run_user=self._user if self._user is not None else run_user(),
            work_path=self.data_dir.replace("\\", "/"),
            git_path=git_path.replace("\\", "/"),
            windows_service_name=GITEA_WINDOWS_SERVICE,
            script_type=GITEA_WINDOWS_SCRIPT_TYPE,
        )

    def install(self, binary_path: str) -> None:
        """Put the binary in place and register the service.

        A running server is stopped first, so its binary can be replaced.

        Args:
            binary_path: The release binary the hub handed down.

        Raises:
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When ``sc.exe`` refuses.
        """
        for parts in GITEA_DATA_PARTS:
            os.makedirs(self._join(self.data_dir, *parts), exist_ok=True)
        os.makedirs(self.module_dir, exist_ok=True)
        if self._service_exists():
            self._stop_and_wait()
        place_binary(binary_path, self.binary_path)
        command = _service_command(self.binary_path, self.conf_path)
        if self._service_exists():
            self._run(["sc.exe", "config", GITEA_WINDOWS_SERVICE, "binPath=", command])
        else:
            self._run(
                [
                    "sc.exe",
                    "create",
                    GITEA_WINDOWS_SERVICE,
                    "binPath=",
                    command,
                    "start=",
                    "auto",
                    "DisplayName=",
                    GITEA_WINDOWS_DISPLAY_NAME,
                ]
            )
        self._run(["sc.exe", "failure", GITEA_WINDOWS_SERVICE, *SC_FAILURE_ACTIONS])

    def ensure_account(self, *, log=None) -> bool:
        """Make nothing: the server runs as LocalSystem.

        Args:
            log: Unused: nothing is handed over.

        Returns:
            Always False.
        """
        return False

    def uninstall(self) -> None:
        """Stop and delete the service, the binary, MinGit and ``app.ini``.

        The data directory stays.
        """
        self._stop_and_wait()
        self._run(["sc.exe", "delete", GITEA_WINDOWS_SERVICE], is_checked=False)
        with contextlib.suppress(OSError):
            os.unlink(self.conf_path)
        self._remove_module_dir()

    def apply(self, rendered: str, *, git_path: str, is_started: bool = True) -> str:
        """Install ``app.ini`` and run the service on it.

        Args:
            rendered: The full ``app.ini`` text.
            git_path: The git the server runs, named in ``app.ini`` already.
            is_started: Whether the service is started on the file. False
                writes the file alone.

        Returns:
            ``unchanged``, ``written``, ``restarted`` or ``started``.

        Raises:
            OSError: When the file cannot be written.
            subprocess.CalledProcessError: When the service will not start.
        """
        os.makedirs(self._join(self.data_dir, *GITEA_CONF_PARTS[:-1]), exist_ok=True)
        is_changed = write_if_changed(self.conf_path, rendered, 0o600)
        if not is_started:
            return "written" if is_changed else "unchanged"
        if self.is_active():
            if not is_changed:
                return "unchanged"
            self._stop_and_wait()
            self._start()
            return "restarted"
        self._start()
        return "started"

    def stop(self) -> None:
        """Stop the service and give it the start type ``disabled`` until the next apply."""
        self._stop_and_wait()
        self._run(
            ["sc.exe", "config", GITEA_WINDOWS_SERVICE, "start=", "disabled"],
            is_checked=False,
        )

    def is_active(self) -> bool:
        """Whether the service runs now."""
        return self._service_state() == "RUNNING"

    def survey(self, *, version: str = "") -> GiteaState:
        """Whether the binary is there, its version, and the administrators.

        Args:
            version: The version the program file reads as; empty runs
                ``gitea --version``.

        Returns:
            What the machine has.
        """
        if not self._is_file(self.binary_path):
            return GiteaState(is_installed=False, version="", admin_usernames=[])
        if not version:
            output = self._run(
                [self.binary_path, "--version"], is_checked=False, timeout_s=30
            ).stdout
            if output.lower().startswith(GITEA_VERSION_PREFIX):
                version = output.split()[2]
        return GiteaState(
            is_installed=True, version=version, admin_usernames=self._admin_names()
        )

    def create_admin(self, *, username: str, password: str, email: str) -> None:
        """Create an administrator account through the gitea CLI.

        Raises:
            subprocess.CalledProcessError: When Gitea refuses.
        """
        self._run(
            self._cli(
                "admin",
                "user",
                "create",
                "--admin",
                "--username",
                username,
                "--password",
                password,
                "--email",
                email,
                "--must-change-password=false",
            )
        )

    def change_password(self, *, username: str, password: str) -> None:
        """Reset an administrator's password through the gitea CLI.

        Raises:
            subprocess.CalledProcessError: When Gitea refuses.
        """
        self._run(
            self._cli(
                "admin",
                "user",
                "change-password",
                "--username",
                username,
                "--password",
                password,
                "--must-change-password=false",
            )
        )

    def read_listen_port(self) -> int:
        """The port the installed ``app.ini`` names, 0 for none."""
        return read_listen_port(self.conf_path)

    def read_root_url(self) -> str:
        """The root URL the installed ``app.ini`` names, empty for none."""
        return read_root_url(self.conf_path)

    def journal_units(self) -> list:
        """No journal: the service writes its own log file."""
        return []

    def log_path(self) -> str:
        """The server's own log file."""
        return self._join(self.data_dir, *GITEA_LOG_PARTS)

    def server_log_path(self) -> str:
        """The log file the server writes itself."""
        return self.log_path()

    def server_log_tail(self, lines: int) -> list:
        """The last lines of the server's own log, in SYSTEM's data directory.

        Raises:
            OSError: When the log exists and cannot be read.
        """
        return file_tail(self.log_path(), lines)

    def output_path(self) -> str:
        """The server's own log file: the service's output goes nowhere else."""
        return self.log_path()

    def _cli(self, *arguments: str) -> list:
        return [self.binary_path, *arguments, "--config", self.conf_path]

    def _admin_names(self) -> list:
        if not self._is_file(self.conf_path):
            return []
        try:
            result = self._run(
                self._cli("admin", "user", "list", "--admin"),
                is_checked=False,
                timeout_s=30,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if not result.is_success:
            return []
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        return [line.split()[1] for line in lines[1:] if len(line.split()) > 1]

    def _service_state(self) -> str:
        """The service's state word from ``sc.exe query``, empty for none."""
        try:
            result = self._run(
                ["sc.exe", "query", GITEA_WINDOWS_SERVICE], is_checked=False
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        for line in result.stdout.splitlines():
            if line.strip().startswith("STATE"):
                words = line.split()
                return words[-1] if words else ""
        return ""

    def _service_exists(self) -> bool:
        try:
            result = self._run(
                ["sc.exe", "query", GITEA_WINDOWS_SERVICE], is_checked=False
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.exit_code != SC_SERVICE_DOES_NOT_EXIST

    def _start(self) -> None:
        """Give the service the start type ``auto``, then start it."""
        self._run(["sc.exe", "config", GITEA_WINDOWS_SERVICE, "start=", "auto"])
        result = self._run(["sc.exe", "start", GITEA_WINDOWS_SERVICE], is_checked=False)
        if result.is_success or result.exit_code == SC_ALREADY_RUNNING:
            return
        raise subprocess.CalledProcessError(
            result.exit_code, ["sc.exe"], output=result.stdout, stderr=result.stderr
        )

    def _remove_module_dir(self) -> None:
        """Delete the module's directory, MinGit's sealed unpack with it, trying again while a file of it stays."""
        for _turn in range(GITEA_WINDOWS_REMOVE_TRIES):
            remove_tree(self.module_dir)
            if not os.path.exists(self.module_dir):
                return
            self._sleep(GITEA_WINDOWS_REMOVE_RETRY_S)

    def _stop_and_wait(self) -> None:
        """Stop the service and wait until it has stopped, at most a while."""
        self._run(["sc.exe", "stop", GITEA_WINDOWS_SERVICE], is_checked=False)
        waited = 0.0
        while waited < GITEA_WINDOWS_STOP_TIMEOUT_S:
            if self._service_state() in ("STOPPED", ""):
                return
            self._sleep(GITEA_WINDOWS_STOP_POLL_S)
            waited += GITEA_WINDOWS_STOP_POLL_S
