"""The git server on macOS: a hidden account, a LaunchDaemon, the machine's git.

The binary goes into the module's own directory under the state root, the
server's data and its ``app.ini`` into ``gitea_data`` beside it, the
account's own, mode 0700. The account is ``neutrino_gitea``, made with
``sysadminctl`` the way the file share makes its accounts and read back
before it counts, since ``sysadminctl`` can refuse and still exit 0. The
LaunchDaemon ``com.neutrino.gitea`` runs the server as that account. The
gitea CLI runs as the account too, since Gitea refuses root. Git is the one
the developer tools, Xcode or Homebrew put on the machine, looked for by
its own path; ``/usr/bin/git`` is never run.

Not pure: writes under ``/Library``, drives ``sysadminctl``, ``dscl`` and
launchd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import plistlib
import re
import secrets
import shutil
import subprocess
import time

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.gitea.applier import GiteaState, read_listen_port
from neutrino_agent.modules.gitea.constants import (
    GITEA_BINARY_DIR_NAME,
    GITEA_CONF_PARTS,
    GITEA_DARWIN_ACCOUNT,
    GITEA_DARWIN_ACCOUNT_FULL_NAME,
    GITEA_DARWIN_ACCOUNT_KEYS,
    GITEA_DARWIN_GIT_PATHS,
    GITEA_DARWIN_LABEL,
    GITEA_DARWIN_LAUNCHD_DIR,
    GITEA_DARWIN_OUTPUT_PATH,
    GITEA_DARWIN_PATH,
    GITEA_DARWIN_SHELL,
    GITEA_DARWIN_UNLOAD_POLL_S,
    GITEA_DARWIN_UNLOAD_TIMEOUT_S,
    GITEA_DATA_DIR_NAME,
    GITEA_DATA_PARTS,
    GITEA_LOG_PARTS,
)
from neutrino_agent.modules.gitea.renderer import GiteaLayout
from neutrino_agent.modules.samba.darwin_applier import tool_line
from neutrino_agent.modules.subprocess_run import CommandResult
from neutrino_agent.modules.subprocess_run import run as run_command
from neutrino_agent.modules.vscode.installer import write_if_changed

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

PLIST_SUFFIX = ".plist"
VERSION_PREFIX = "Gitea version"


def render_plist(*, binary: str, conf: str, data_dir: str, git_dir: str) -> bytes:
    """The server's LaunchDaemon.

    Args:
        binary: The gitea binary.
        conf: Its ``app.ini``.
        data_dir: Its data directory, where it runs and its home.
        git_dir: The directory of the git it runs, first on its ``PATH``.

    Returns:
        The plist, as XML.
    """
    path = f"{git_dir}:{GITEA_DARWIN_PATH}" if git_dir else GITEA_DARWIN_PATH
    return plistlib.dumps(
        {
            "Label": GITEA_DARWIN_LABEL,
            "UserName": GITEA_DARWIN_ACCOUNT,
            "ProgramArguments": [binary, "web", "--config", conf],
            "EnvironmentVariables": {
                "HOME": data_dir,
                "USER": GITEA_DARWIN_ACCOUNT,
                "GITEA_WORK_DIR": data_dir,
                "PATH": path,
            },
            "WorkingDirectory": data_dir,
            "StandardOutPath": GITEA_DARWIN_OUTPUT_PATH,
            "StandardErrorPath": GITEA_DARWIN_OUTPUT_PATH,
            "RunAtLoad": True,
            "KeepAlive": True,
        }
    )


def _account_entry(account: str) -> tuple:
    """One account's uid and gid.

    Raises:
        KeyError: When the account database has no such account.
    """
    if pwd is None:
        raise KeyError(account)
    entry = pwd.getpwnam(account)
    return entry.pw_uid, entry.pw_gid


def _run_as(entry: tuple, command: list, *, environment: dict, cwd: str):
    """Run one command as an account, with this environment alone."""
    uid, gid = entry
    completed = subprocess.run(
        command,
        user=uid,
        group=gid,
        extra_groups=[],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return CommandResult(
        list(command), completed.returncode, completed.stdout, completed.stderr
    )


class GiteaDarwinApplier:
    """Runs the git server as a LaunchDaemon of its own hidden account."""

    is_git_required = True

    def __init__(
        self,
        *,
        state_dir: str,
        run=None,
        run_as=None,
        lookup_account=None,
        chown=None,
        is_executable=None,
        launchd_dir: str = GITEA_DARWIN_LAUNCHD_DIR,
        output_path: str = GITEA_DARWIN_OUTPUT_PATH,
        sleep=time.sleep,
    ):
        """
        Args:
            state_dir: The agent's state root.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            run_as: Called with ``(entry, command, environment=, cwd=)``;
                runs a command as the account and returns a
                ``CommandResult``. None runs it.
            lookup_account: Called with the account; returns ``(uid, gid)``
                or raises ``KeyError``. None reads the account database.
            chown: Called with ``(path, uid, gid)``; None is ``os.chown``.
            is_executable: Called with a path; whether it is a program.
                None asks the file system.
            launchd_dir: Where the LaunchDaemon's plist goes.
            output_path: Where launchd writes the server's output.
            sleep: Waits a number of seconds.
        """
        self.module_dir = os.path.join(state_dir, GITEA_BINARY_DIR_NAME)
        self.data_dir = os.path.join(state_dir, GITEA_DATA_DIR_NAME)
        self.binary_path = os.path.join(self.module_dir, "gitea")
        self.conf_path = os.path.join(self.data_dir, *GITEA_CONF_PARTS)
        self._run = run if run is not None else run_command
        self._run_as = run_as if run_as is not None else _run_as
        self._lookup = lookup_account if lookup_account is not None else _account_entry
        self._chown = chown if chown is not None else os.chown
        self._is_executable = (
            is_executable
            if is_executable is not None
            else (lambda path: os.path.isfile(path) and os.access(path, os.X_OK))
        )
        self._plist_path = os.path.join(launchd_dir, GITEA_DARWIN_LABEL + PLIST_SUFFIX)
        self._output_path = output_path
        self._sleep = sleep

    def find_git(self) -> str:
        """The git the server runs, by the tools' own paths.

        Returns:
            The first program among the developer tools', Xcode's and
            Homebrew's; empty when the machine has none.
        """
        for path in GITEA_DARWIN_GIT_PATHS:
            if self._is_executable(path):
                return path
        return ""

    def layout(self, git_path: str) -> GiteaLayout:
        """Where the server runs on this Mac.

        Args:
            git_path: The git :meth:`find_git` found.

        Returns:
            The account, the data directory, that git, and no SSH.
        """
        return GiteaLayout(
            run_user=GITEA_DARWIN_ACCOUNT,
            work_path=self.data_dir,
            git_path=git_path,
            is_ssh_served=False,
        )

    def install(self, binary_path: str) -> None:
        """Make the account and the data directory, and put the binary in place.

        Args:
            binary_path: The release binary the hub handed down.

        Raises:
            ModuleApplyError: ``user_create_failed {user, detail}`` when the
                system will not make the account.
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When a step refuses.
        """
        uid, gid = self._ensure_account()
        self._prepare_data(uid, gid)
        os.makedirs(self.module_dir, exist_ok=True)
        os.chmod(self.module_dir, 0o755)
        if self._is_loaded():
            self._unload()
        temporary = self.binary_path + ".new"
        shutil.copyfile(binary_path, temporary)
        os.chmod(temporary, 0o755)
        os.replace(temporary, self.binary_path)

    def uninstall(self) -> None:
        """Unload and delete the LaunchDaemon, the binary and ``app.ini``.

        The data directory and the account stay.
        """
        self._unload()
        for path in (self._plist_path, self.conf_path):
            with contextlib.suppress(OSError):
                os.unlink(path)
        shutil.rmtree(self.module_dir, ignore_errors=True)

    def apply(self, rendered: str, *, git_path: str) -> str:
        """Install ``app.ini`` and the LaunchDaemon, and run the server on them.

        Args:
            rendered: The full ``app.ini`` text.
            git_path: The git the server runs.

        Returns:
            ``unchanged``, ``restarted`` or ``started``.

        Raises:
            ModuleApplyError: ``user_create_failed`` when the account is gone
                and cannot be made again.
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When launchd refuses the job.
        """
        uid, gid = self._ensure_account()
        self._prepare_data(uid, gid)
        is_conf_changed = write_if_changed(self.conf_path, rendered, 0o600)
        self._chown(self.conf_path, uid, gid)
        plist = render_plist(
            binary=self.binary_path,
            conf=self.conf_path,
            data_dir=self.data_dir,
            git_dir=os.path.dirname(git_path),
        )
        is_job_changed = write_if_changed(
            self._plist_path, plist.decode("utf-8"), 0o644
        )
        self._prepare_output(uid, gid)
        if self._is_loaded():
            if is_job_changed:
                self._unload()
                self._load()
                return "restarted"
            if is_conf_changed:
                self._run(
                    ["launchctl", "kickstart", "-k", f"system/{GITEA_DARWIN_LABEL}"]
                )
                return "restarted"
            return "unchanged"
        self._load()
        return "started"

    def stop(self) -> None:
        """Unload the job until the next apply; its plist loads it at boot."""
        self._unload()

    def is_active(self) -> bool:
        """Whether launchd runs the server now."""
        try:
            result = self._run(
                ["launchctl", "print", f"system/{GITEA_DARWIN_LABEL}"], is_checked=False
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.is_success and "state = running" in result.stdout

    def survey(self) -> GiteaState:
        """Whether the binary is there, its version, and the administrators."""
        if not os.path.isfile(self.binary_path):
            return GiteaState(is_installed=False, version="", admin_usernames=[])
        output = self._run(
            [self.binary_path, "--version"], is_checked=False, timeout_s=30
        ).stdout
        version = output.split()[2] if output.startswith(VERSION_PREFIX) else ""
        return GiteaState(
            is_installed=True, version=version, admin_usernames=self._admin_names()
        )

    def create_admin(self, *, username: str, password: str, email: str) -> None:
        """Create an administrator account through the gitea CLI.

        Raises:
            subprocess.CalledProcessError: When Gitea refuses.
            KeyError: When the server's account is gone.
        """
        self._cli_checked(
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

    def change_password(self, *, username: str, password: str) -> None:
        """Reset an administrator's password through the gitea CLI.

        Raises:
            subprocess.CalledProcessError: When Gitea refuses.
            KeyError: When the server's account is gone.
        """
        self._cli_checked(
            "admin",
            "user",
            "change-password",
            "--username",
            username,
            "--password",
            password,
            "--must-change-password=false",
        )

    def read_listen_port(self) -> int:
        """The port the installed ``app.ini`` names, 0 for none."""
        return read_listen_port(self.conf_path)

    def journal_units(self) -> list:
        """No journal: launchd keeps none."""
        return []

    def log_path(self) -> str:
        """The server's own log file."""
        return os.path.join(self.data_dir, *GITEA_LOG_PARTS)

    def _ensure_account(self) -> tuple:
        """The account's uid and gid, made first when it is missing.

        Raises:
            ModuleApplyError: ``user_create_failed {user, detail}`` when the
                record is not a usable account afterwards.
        """
        if self._is_usable():
            return self._lookup(GITEA_DARWIN_ACCOUNT)
        made = self._run(
            [
                "sysadminctl",
                "-addUser",
                GITEA_DARWIN_ACCOUNT,
                "-fullName",
                GITEA_DARWIN_ACCOUNT_FULL_NAME,
                "-shell",
                GITEA_DARWIN_SHELL,
                "-home",
                self.data_dir,
                "-password",
                secrets.token_urlsafe(24),
            ],
            is_checked=False,
        )
        if not self._is_usable():
            raise ModuleApplyError(
                "user_create_failed",
                {"user": GITEA_DARWIN_ACCOUNT, "detail": tool_line(made)},
            )
        self._run(
            ["dscl", ".", "-create", f"/Users/{GITEA_DARWIN_ACCOUNT}", "IsHidden", "1"]
        )
        return self._lookup(GITEA_DARWIN_ACCOUNT)

    def _is_usable(self) -> bool:
        """Whether the account's record holds every key a process needs."""
        result = self._run(
            [
                "dscl",
                ".",
                "-read",
                f"/Users/{GITEA_DARWIN_ACCOUNT}",
                *GITEA_DARWIN_ACCOUNT_KEYS,
            ],
            is_checked=False,
        )
        text = result.stdout if result.is_success else ""
        return all(
            re.search(rf"^{key}:", text, re.MULTILINE)
            for key in GITEA_DARWIN_ACCOUNT_KEYS
        )

    def _prepare_data(self, uid: int, gid: int) -> None:
        """Make the data directory and its parts the account's own."""
        os.makedirs(self.data_dir, exist_ok=True)
        os.chmod(self.data_dir, 0o700)
        self._chown(self.data_dir, uid, gid)
        for parts in GITEA_DATA_PARTS:
            path = self.data_dir
            for part in parts:
                path = os.path.join(path, part)
                os.makedirs(path, exist_ok=True)
                self._chown(path, uid, gid)

    def _prepare_output(self, uid: int, gid: int) -> None:
        """Make the file launchd writes the output to the account's own."""
        os.makedirs(os.path.dirname(self._output_path), exist_ok=True)
        with open(self._output_path, "a", encoding="utf-8"):
            pass
        os.chmod(self._output_path, 0o600)
        self._chown(self._output_path, uid, gid)

    def _is_loaded(self) -> bool:
        return self._run(
            ["launchctl", "print", f"system/{GITEA_DARWIN_LABEL}"], is_checked=False
        ).is_success

    def _load(self) -> None:
        self._run(["launchctl", "bootstrap", "system", self._plist_path])

    def _unload(self) -> None:
        """Boot the job out and wait until launchd lets go of its label."""
        self._run(
            ["launchctl", "bootout", f"system/{GITEA_DARWIN_LABEL}"], is_checked=False
        )
        waited = 0.0
        while self._is_loaded() and waited < GITEA_DARWIN_UNLOAD_TIMEOUT_S:
            self._sleep(GITEA_DARWIN_UNLOAD_POLL_S)
            waited += GITEA_DARWIN_UNLOAD_POLL_S

    def _admin_names(self) -> list:
        if not os.path.exists(self.conf_path):
            return []
        try:
            result = self._cli("admin", "user", "list", "--admin")
        except (KeyError, OSError, subprocess.SubprocessError):
            return []
        if not result.is_success:
            return []
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        return [line.split()[1] for line in lines[1:] if len(line.split()) > 1]

    def _cli(self, *arguments: str) -> CommandResult:
        """Run the gitea CLI as the server's account."""
        return self._run_as(
            self._lookup(GITEA_DARWIN_ACCOUNT),
            [self.binary_path, *arguments, "--config", self.conf_path],
            environment={
                "HOME": self.data_dir,
                "USER": GITEA_DARWIN_ACCOUNT,
                "GITEA_WORK_DIR": self.data_dir,
                "PATH": GITEA_DARWIN_PATH,
            },
            cwd=self.data_dir,
        )

    def _cli_checked(self, *arguments: str) -> None:
        result = self._cli(*arguments)
        if not result.is_success:
            raise subprocess.CalledProcessError(
                result.exit_code,
                list(result.command[:1]),
                output=result.stdout,
                stderr=result.stderr,
            )
