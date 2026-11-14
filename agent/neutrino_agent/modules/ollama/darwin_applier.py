"""Ollama on macOS: a hidden account, a LaunchDaemon, the publisher's app.

The program is unpacked under ``ollama/`` in the module's directory, and the
models live in ``ollama_data`` under the state root, which is the account's
home, mode 0700, given to it on its open descriptor; ``models`` and
``.ollama`` inside it are made as the account, and a handover gives those
two alone, by open descriptor following no link. The account is
``neutrino_ollama``, made with ``sysadminctl`` and read back before it
counts, as Gitea's is. The LaunchDaemon ``com.neutrino.ollama`` runs
``ollama serve`` as that account with the module's environment. A person's
Ollama here is the publisher's app, which the module never starts or stops.

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
import subprocess
import time

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.gitea.constants import GITEA_DARWIN_ACCOUNT_KEYS
from neutrino_agent.modules.ollama.constants import (
    OLLAMA_DARWIN_ACCOUNT,
    OLLAMA_DARWIN_ACCOUNT_FULL_NAME,
    OLLAMA_DARWIN_APP_PATHS,
    OLLAMA_DARWIN_LABEL,
    OLLAMA_DARWIN_LAUNCHD_DIR,
    OLLAMA_DARWIN_OUTPUT_PATH,
    OLLAMA_DARWIN_OWN_PARTS,
    OLLAMA_DARWIN_PATH,
    OLLAMA_DARWIN_SHELL,
    OLLAMA_DARWIN_UNLOAD_POLL_S,
    OLLAMA_DARWIN_UNLOAD_TIMEOUT_S,
    OLLAMA_DATA_DIR_NAME,
    OLLAMA_ENVIRONMENT,
    OLLAMA_HOST,
    OLLAMA_MODELS_DIR_NAME,
    OLLAMA_NAME,
    OLLAMA_PERSON_UNIT,
    OLLAMA_PORT,
    OLLAMA_PROGRAM_DIR_NAME,
    OLLAMA_SERVE_ARGUMENTS,
)
from neutrino_agent.modules.samba.darwin_applier import tool_line
from neutrino_agent.modules.shared.account_files import AccountFiles
from neutrino_agent.modules.shared.account_service import write_if_changed
from neutrino_agent.modules.shared.handle_walk import give_tree, make_dirs, open_dir
from neutrino_agent.modules.shared.subprocess_run import run as run_command
from neutrino_agent.modules.shared.unpacked_tree import remove_tree

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

PLIST_SUFFIX = ".plist"


def render_plist(*, program: str, data_dir: str) -> bytes:
    """The server's LaunchDaemon. Pure.

    Args:
        program: The ``ollama`` program.
        data_dir: The data directory, its home and where it runs.

    Returns:
        The plist, as XML.
    """
    return plistlib.dumps(
        {
            "Label": OLLAMA_DARWIN_LABEL,
            "UserName": OLLAMA_DARWIN_ACCOUNT,
            "ProgramArguments": [program, *OLLAMA_SERVE_ARGUMENTS],
            "EnvironmentVariables": {
                "HOME": data_dir,
                "USER": OLLAMA_DARWIN_ACCOUNT,
                "PATH": OLLAMA_DARWIN_PATH,
                "OLLAMA_HOST": f"{OLLAMA_HOST}:{OLLAMA_PORT}",
                "OLLAMA_MODELS": os.path.join(data_dir, OLLAMA_MODELS_DIR_NAME),
                **OLLAMA_ENVIRONMENT,
            },
            "WorkingDirectory": data_dir,
            "StandardOutPath": OLLAMA_DARWIN_OUTPUT_PATH,
            "StandardErrorPath": OLLAMA_DARWIN_OUTPUT_PATH,
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


class OllamaDarwinApplier:
    """Runs Ollama as a LaunchDaemon of its own hidden account.

    Attributes:
        account: The hidden account the server runs as.
        is_app_system: True: a person's Ollama here is the publisher's app.
    """

    account = OLLAMA_DARWIN_ACCOUNT
    is_app_system = True

    def __init__(
        self,
        *,
        state_dir: str,
        platform=None,
        run=None,
        lookup_account=None,
        chown=None,
        launchd_dir: str = OLLAMA_DARWIN_LAUNCHD_DIR,
        output_path: str = OLLAMA_DARWIN_OUTPUT_PATH,
        app_paths: tuple = OLLAMA_DARWIN_APP_PATHS,
        sleep=time.sleep,
    ):
        """
        Args:
            state_dir: The agent's state root.
            platform: The machine's platform, which steps down to the
                account for every file in the data directory.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            lookup_account: Called with the account; returns ``(uid, gid)``
                or raises ``KeyError``. None reads the account database.
            chown: Called with ``(path or descriptor, uid, gid)``; None is
                ``os.chown``.
            launchd_dir: Where the LaunchDaemon's plist goes.
            output_path: Where launchd writes the server's output.
            app_paths: Where the publisher's app is looked for.
            sleep: Waits a number of seconds.
        """
        self.module_dir = os.path.join(state_dir, OLLAMA_NAME)
        self.data_dir = os.path.join(state_dir, OLLAMA_DATA_DIR_NAME)
        self.program_path = os.path.join(
            self.module_dir, OLLAMA_PROGRAM_DIR_NAME, OLLAMA_NAME
        )
        self._platform = platform
        self._run = run if run is not None else run_command
        self._lookup = lookup_account if lookup_account is not None else _account_entry
        self._chown = chown if chown is not None else os.chown
        self._plist_path = os.path.join(launchd_dir, OLLAMA_DARWIN_LABEL + PLIST_SUFFIX)
        self._output_path = output_path
        self._app_paths = tuple(app_paths)
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
        """The publisher's app on this Mac, empty when it is not there."""
        for path in self._app_paths:
            if os.path.isdir(path):
                return path
        return ""

    def ensure_account(self, *, log=None) -> bool:
        """Make the account when it is missing, and the data directory its own.

        When another uid owns ``models`` or ``.ollama``, those two alone are
        given to the account with everything under them.

        Args:
            log: Called with a line for each entry the handover leaves
                outside its part; None for nobody listening.

        Returns:
            Whether a part changed hands.

        Raises:
            ModuleApplyError: ``user_create_failed {user, detail}`` when the
                system will not make the account.
            OSError: When a directory cannot be made or given.
        """
        uid, gid = self._ensure_account()
        is_given = False
        for part in OLLAMA_DARWIN_OWN_PARTS:
            folder = os.path.join(self.data_dir, part)
            try:
                if os.lstat(folder).st_uid == uid:
                    continue
            except FileNotFoundError:
                continue
            is_given = True
            for path in give_tree(folder, uid, gid):
                if log is not None:
                    log(f"ollama: left {path}, which is outside {folder}")
        self._prepare_data(uid, gid)
        return is_given

    def apply(self, *, is_started: bool = True) -> str:
        """Write the LaunchDaemon and run the server on it; with ``is_started`` false, write it alone.

        Args:
            is_started: Whether the job is enabled and loaded.

        Returns:
            ``unchanged``, ``written``, ``restarted`` or ``started``.

        Raises:
            ModuleApplyError: ``user_create_failed`` when the account is gone
                and cannot be made again.
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When launchd refuses the job.
        """
        uid, gid = self._ensure_account()
        self._prepare_data(uid, gid)
        plist = render_plist(program=self.program_path, data_dir=self.data_dir)
        is_changed = write_if_changed(self._plist_path, plist.decode("utf-8"), 0o644)
        self._prepare_output(uid, gid)
        if not is_started:
            return "written" if is_changed else "unchanged"
        if self._is_loaded():
            if not is_changed:
                return "unchanged"
            self._unload()
            self._load()
            return "restarted"
        self._load()
        return "started"

    def stop(self) -> None:
        """Disable the job and unload it, so it stays unloaded at boot until the next start."""
        self._run(
            ["launchctl", "disable", f"system/{OLLAMA_DARWIN_LABEL}"], is_checked=False
        )
        self._unload()

    def is_active(self) -> bool:
        """Whether launchd runs the server now."""
        try:
            result = self._run(
                ["launchctl", "print", f"system/{OLLAMA_DARWIN_LABEL}"],
                is_checked=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.is_success and "state = running" in result.stdout

    def uninstall(self) -> str:
        """Unload and delete the LaunchDaemon and the program; the data directory and the account stay.

        Returns:
            Empty.
        """
        self._unload()
        with contextlib.suppress(OSError):
            os.unlink(self._plist_path)
        remove_tree(self.module_dir)
        return ""

    def journal_units(self) -> list:
        """No journal: launchd keeps none."""
        return []

    def output_path(self) -> str:
        """The file launchd writes the server's output to."""
        return self._output_path

    def _ensure_account(self) -> tuple:
        """The account's uid and gid, made first when it is missing.

        Raises:
            ModuleApplyError: ``user_create_failed {user, detail}`` when the
                record is not a usable account afterwards.
        """
        if self._is_usable():
            return self._lookup(OLLAMA_DARWIN_ACCOUNT)
        made = self._run(
            [
                "sysadminctl",
                "-addUser",
                OLLAMA_DARWIN_ACCOUNT,
                "-fullName",
                OLLAMA_DARWIN_ACCOUNT_FULL_NAME,
                "-shell",
                OLLAMA_DARWIN_SHELL,
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
                {"user": OLLAMA_DARWIN_ACCOUNT, "detail": tool_line(made)},
            )
        self._run(
            ["dscl", ".", "-create", f"/Users/{OLLAMA_DARWIN_ACCOUNT}", "IsHidden", "1"]
        )
        return self._lookup(OLLAMA_DARWIN_ACCOUNT)

    def _is_usable(self) -> bool:
        """Whether the account's record holds every key a process needs."""
        result = self._run(
            [
                "dscl",
                ".",
                "-read",
                f"/Users/{OLLAMA_DARWIN_ACCOUNT}",
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
        """Make the data directory the account's by open descriptor, and its parts as the account.

        Raises:
            OSError: When a level is a link, or a folder cannot be made or
                given.
        """
        make_dirs(self.data_dir, 0o700)
        descriptor = open_dir(self.data_dir)
        try:
            os.fchmod(descriptor, 0o700)
            self._chown(descriptor, uid, gid)
        finally:
            os.close(descriptor)
        files = AccountFiles(platform=self._platform, account=OLLAMA_DARWIN_ACCOUNT)
        for part in OLLAMA_DARWIN_OWN_PARTS:
            files.make_dir(os.path.join(self.data_dir, part))

    def _prepare_output(self, uid: int, gid: int) -> None:
        """Make the file launchd writes the output to the account's own."""
        os.makedirs(os.path.dirname(self._output_path), exist_ok=True)
        with open(self._output_path, "a", encoding="utf-8"):
            pass
        os.chmod(self._output_path, 0o600)
        self._chown(self._output_path, uid, gid)

    def _is_loaded(self) -> bool:
        return self._run(
            ["launchctl", "print", f"system/{OLLAMA_DARWIN_LABEL}"], is_checked=False
        ).is_success

    def _load(self) -> None:
        """Enable the job, then load it."""
        self._run(["launchctl", "enable", f"system/{OLLAMA_DARWIN_LABEL}"])
        self._run(["launchctl", "bootstrap", "system", self._plist_path])

    def _unload(self) -> None:
        """Boot the job out and wait until launchd lets go of its label."""
        self._run(
            ["launchctl", "bootout", f"system/{OLLAMA_DARWIN_LABEL}"], is_checked=False
        )
        waited = 0.0
        while self._is_loaded() and waited < OLLAMA_DARWIN_UNLOAD_TIMEOUT_S:
            self._sleep(OLLAMA_DARWIN_UNLOAD_POLL_S)
            waited += OLLAMA_DARWIN_UNLOAD_POLL_S
