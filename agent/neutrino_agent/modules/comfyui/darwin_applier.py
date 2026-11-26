"""ComfyUI on macOS: a hidden account, a LaunchDaemon, the shared folders' access lists.

The data directory ``comfyui_data`` under the state root is the account's
home, mode 0700, given to it on its open descriptor; a tree another uid owns
is handed over by open descriptor following no link, and every folder in it
is made as the account. The account is ``neutrino_comfyui``, made with
``sysadminctl`` and read back before it counts, as Ollama's is. Every
command the agent runs as the account starts in the data directory. The
LaunchDaemon ``com.neutrino.comfyui`` runs the server as the account with
``Umask`` 23, its output in ``/Library/Logs/Neutrino/agent/comfyui.log``.

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
from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_ACCOUNT_STEP_TIMEOUT_S,
    COMFYUI_BASE_DIR,
    COMFYUI_DARWIN_ACCOUNT,
    COMFYUI_DARWIN_ACCOUNT_FULL_NAME,
    COMFYUI_DARWIN_LABEL,
    COMFYUI_DARWIN_LAUNCHD_DIR,
    COMFYUI_DARWIN_OUTPUT_PATH,
    COMFYUI_DARWIN_SHELL,
    COMFYUI_DARWIN_UMASK,
    COMFYUI_DARWIN_UNLOAD_POLL_S,
    COMFYUI_DARWIN_UNLOAD_TIMEOUT_S,
    COMFYUI_DATA_DIR_NAME,
    COMFYUI_NAME,
    COMFYUI_POSIX_PATH,
    COMFYUI_PYCACHE_DIR,
    COMFYUI_READ_FOLDERS,
    COMFYUI_SERVICE_FOLDERS,
    COMFYUI_TMP_DIR,
    COMFYUI_UV_CACHE_DIR,
    COMFYUI_WRITE_FOLDERS,
)
from neutrino_agent.modules.comfyui.darwin_access import DarwinFolderAccess
from neutrino_agent.modules.comfyui.linux_applier import scratch_command
from neutrino_agent.modules.comfyui.server import (
    ComfyuiServer,
    server_command,
    server_environment,
)
from neutrino_agent.modules.gitea.constants import GITEA_DARWIN_ACCOUNT_KEYS
from neutrino_agent.modules.samba.darwin_applier import tool_line
from neutrino_agent.modules.shared.account_files import AccountFiles
from neutrino_agent.modules.shared.account_service import write_if_changed
from neutrino_agent.modules.shared.handle_walk import give_tree, make_dirs, open_dir
from neutrino_agent.modules.shared.subprocess_run import run as run_command
from neutrino_agent.modules.shared.unpacked_tree import remove_tree

try:
    import grp
    import pwd
except ImportError:  # Windows has no account database module.
    grp = None
    pwd = None

PLIST_SUFFIX = ".plist"


def render_plist(
    server: ComfyuiServer, *, module_dir: str, data_dir: str, group: str
) -> bytes:
    """The server's LaunchDaemon. Pure.

    Args:
        server: What the start takes.
        module_dir: The module's directory.
        data_dir: The data directory, the account's home and where it runs.
        group: The account's primary group.

    Returns:
        The plist, as XML.
    """
    return plistlib.dumps(
        {
            "Label": COMFYUI_DARWIN_LABEL,
            "UserName": COMFYUI_DARWIN_ACCOUNT,
            "GroupName": group,
            "Umask": COMFYUI_DARWIN_UMASK,
            "ProgramArguments": server_command(
                server, module_dir=module_dir, data_dir=data_dir, os_name="darwin"
            ),
            "EnvironmentVariables": {
                **server_environment(server, data_dir=data_dir, os_name="darwin"),
                "USER": COMFYUI_DARWIN_ACCOUNT,
                "PATH": COMFYUI_POSIX_PATH,
            },
            "WorkingDirectory": data_dir,
            "StandardOutPath": COMFYUI_DARWIN_OUTPUT_PATH,
            "StandardErrorPath": COMFYUI_DARWIN_OUTPUT_PATH,
            "RunAtLoad": True,
            "KeepAlive": True,
        }
    )


class ComfyuiDarwinApplier:
    """Runs ComfyUI as a LaunchDaemon of its own hidden account.

    Attributes:
        account: The hidden account the server runs as.
    """

    account = COMFYUI_DARWIN_ACCOUNT

    def __init__(
        self,
        *,
        state_dir: str,
        platform=None,
        run=None,
        chown=None,
        launchd_dir: str = COMFYUI_DARWIN_LAUNCHD_DIR,
        output_path: str = COMFYUI_DARWIN_OUTPUT_PATH,
        sleep=time.sleep,
        files_factory=AccountFiles,
        access_factory=DarwinFolderAccess,
    ):
        """
        Args:
            state_dir: The agent's state root.
            platform: The machine's platform, which steps down to the
                account.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            chown: Called with ``(path or descriptor, uid, gid)``; None is
                ``os.chown``.
            launchd_dir: Where the LaunchDaemon's plist goes.
            output_path: Where launchd writes the server's output.
            sleep: Waits a number of seconds.
            files_factory: Makes the :class:`AccountFiles` of an account.
            access_factory: Makes the shared folders' writer.
        """
        self.os_name = "darwin"
        self.module_dir = os.path.join(state_dir, COMFYUI_NAME)
        self.data_dir = os.path.join(state_dir, COMFYUI_DATA_DIR_NAME)
        self.base_dir = os.path.join(self.data_dir, COMFYUI_BASE_DIR)
        self._platform = platform
        self._run = run if run is not None else run_command
        self._chown = chown if chown is not None else os.chown
        self._plist_path = os.path.join(
            launchd_dir, COMFYUI_DARWIN_LABEL + PLIST_SUFFIX
        )
        self._output_path = output_path
        self._sleep = sleep
        self._files_factory = files_factory
        self._access_factory = access_factory

    def ensure_account(self, *, log=None) -> bool:
        """Make the account when it is missing, and the data directory its own with its folders.

        Args:
            log: Called with a line for each entry the handover leaves
                outside the data directory; None for nobody listening.

        Returns:
            Whether the data directory changed hands.

        Raises:
            ModuleApplyError: ``user_create_failed {user, detail}`` when the
                system will not make the account.
            OSError: When a directory cannot be made or given.
        """
        uid, gid = self._ensure_account()
        try:
            is_given = os.lstat(self.data_dir).st_uid != uid
        except FileNotFoundError:
            is_given = False
        if is_given:
            for path in give_tree(self.data_dir, uid, gid):
                if log is not None:
                    log(f"comfyui: left {path}, which is outside {self.data_dir}")
        self.prepare_data()
        return is_given

    def prepare_data(self) -> None:
        """Make the data directory the account's by open descriptor, and each of its folders as the account.

        Raises:
            KeyError: When the account is missing.
            OSError: When a level is a link, or a folder cannot be made or
                given.
        """
        entry = pwd.getpwnam(COMFYUI_DARWIN_ACCOUNT)
        make_dirs(self.data_dir, 0o700)
        descriptor = open_dir(self.data_dir)
        try:
            os.fchmod(descriptor, 0o700)
            self._chown(descriptor, entry.pw_uid, entry.pw_gid)
        finally:
            os.close(descriptor)
        files = self.service_files()
        for name in (COMFYUI_UV_CACHE_DIR, COMFYUI_TMP_DIR, COMFYUI_PYCACHE_DIR):
            files.make_dir(os.path.join(self.data_dir, name), umask=0o077)
        files.make_dir(self.base_dir, umask=0o027)
        for name in COMFYUI_WRITE_FOLDERS + COMFYUI_READ_FOLDERS:
            files.make_dir(os.path.join(self.base_dir, name), umask=0o027)
        for name in COMFYUI_SERVICE_FOLDERS:
            files.make_dir(os.path.join(self.base_dir, name), umask=0o077)
        os.makedirs(os.path.dirname(self._output_path), exist_ok=True)
        with open(self._output_path, "a", encoding="utf-8"):
            pass
        os.chmod(self._output_path, 0o600)
        self._chown(self._output_path, entry.pw_uid, entry.pw_gid)

    def service_files(self) -> AccountFiles:
        """The service's account's places, each touched as that account."""
        return self._files_factory(
            platform=self._platform,
            account=COMFYUI_DARWIN_ACCOUNT,
            timeout_s=COMFYUI_ACCOUNT_STEP_TIMEOUT_S,
        )

    def run_as_service(self, argv: list, environment: dict, timeout_s: int) -> tuple:
        """Run one command as the service's account in the data directory under umask 077, its environment written from scratch.

        Args:
            argv: The argument vector.
            environment: Its variables.
            timeout_s: How long it may run.

        Returns:
            ``(exit_code, output)``; 127 with the error when it could not
            start or finish.
        """
        files = self._files_factory(
            platform=self._platform, account=COMFYUI_DARWIN_ACCOUNT, timeout_s=timeout_s
        )
        try:
            done = files.run(
                ["/bin/sh", "-c", 'cd -- "$0" && umask 077 && exec "$@"', self.data_dir]
                + scratch_command(argv, environment)
            )
        except OSError as error:
            return 127, str(error)
        words = (done.stdout or b"") + b"\n" + (done.stderr or b"")
        return done.returncode, words.decode("utf-8", "replace")

    def remove_as_service(self, path: str) -> None:
        """Delete one tree of the data directory as the service's account.

        Raises:
            OSError: When it cannot be deleted.
        """
        self.service_files().remove_tree(path)

    def write_access(self, account: str) -> list:
        """Write the default account's entries on the shared folders, or none while there is none.

        Args:
            account: The default account; empty names none.

        Returns:
            The paths left as they are.

        Raises:
            KeyError: When an account is missing.
            OSError: When a top folder cannot be opened or its list set.
        """
        service = pwd.getpwnam(COMFYUI_DARWIN_ACCOUNT)
        user = (account, pwd.getpwnam(account).pw_uid) if account else None
        return self._access_factory(
            data_dir=self.data_dir,
            base_dir=self.base_dir,
            service=(COMFYUI_DARWIN_ACCOUNT, service.pw_uid),
        ).write(user)

    def service_text(self, server: ComfyuiServer) -> str:
        """The LaunchDaemon a start writes."""
        group = ""
        with contextlib.suppress(KeyError, TypeError, AttributeError):
            group = grp.getgrgid(pwd.getpwnam(COMFYUI_DARWIN_ACCOUNT).pw_gid).gr_name
        return render_plist(
            server, module_dir=self.module_dir, data_dir=self.data_dir, group=group
        ).decode("utf-8")

    def written_text(self) -> str:
        """The LaunchDaemon as it is written now; empty for none."""
        try:
            with open(self._plist_path, "r", encoding="utf-8") as stream:
                return stream.read()
        except OSError:
            return ""

    def apply(self, server: ComfyuiServer, *, is_started: bool = True) -> str:
        """Write the LaunchDaemon and load it; with ``is_started`` false, write it alone.

        Args:
            server: What the start takes.
            is_started: Whether the job is enabled and loaded.

        Returns:
            ``unchanged``, ``written``, ``restarted`` or ``started``.

        Raises:
            subprocess.CalledProcessError: When launchd refuses.
            OSError: When the plist cannot be written.
        """
        is_changed = write_if_changed(
            self._plist_path, self.service_text(server), 0o644
        )
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
            ["launchctl", "disable", f"system/{COMFYUI_DARWIN_LABEL}"], is_checked=False
        )
        self._unload()

    def is_active(self) -> bool:
        """Whether launchd runs the server now."""
        try:
            result = self._run(
                ["launchctl", "print", f"system/{COMFYUI_DARWIN_LABEL}"],
                is_checked=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.is_success and "state = running" in result.stdout

    def uninstall(self) -> None:
        """Unload and delete the LaunchDaemon and the module's directory; the data directory and the account stay."""
        self._unload()
        with contextlib.suppress(OSError):
            os.unlink(self._plist_path)
        remove_tree(self.module_dir)

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
            entry = pwd.getpwnam(COMFYUI_DARWIN_ACCOUNT)
            return entry.pw_uid, entry.pw_gid
        made = self._run(
            [
                "sysadminctl",
                "-addUser",
                COMFYUI_DARWIN_ACCOUNT,
                "-fullName",
                COMFYUI_DARWIN_ACCOUNT_FULL_NAME,
                "-shell",
                COMFYUI_DARWIN_SHELL,
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
                {"user": COMFYUI_DARWIN_ACCOUNT, "detail": tool_line(made)},
            )
        self._run(
            [
                "dscl",
                ".",
                "-create",
                f"/Users/{COMFYUI_DARWIN_ACCOUNT}",
                "IsHidden",
                "1",
            ]
        )
        entry = pwd.getpwnam(COMFYUI_DARWIN_ACCOUNT)
        return entry.pw_uid, entry.pw_gid

    def _is_usable(self) -> bool:
        """Whether the account's record holds every key a process needs."""
        result = self._run(
            [
                "dscl",
                ".",
                "-read",
                f"/Users/{COMFYUI_DARWIN_ACCOUNT}",
                *GITEA_DARWIN_ACCOUNT_KEYS,
            ],
            is_checked=False,
        )
        text = result.stdout if result.is_success else ""
        return all(
            re.search(rf"^{key}:", text, re.MULTILINE)
            for key in GITEA_DARWIN_ACCOUNT_KEYS
        )

    def _is_loaded(self) -> bool:
        return self._run(
            ["launchctl", "print", f"system/{COMFYUI_DARWIN_LABEL}"], is_checked=False
        ).is_success

    def _load(self) -> None:
        """Enable the job, then load it."""
        self._run(["launchctl", "enable", f"system/{COMFYUI_DARWIN_LABEL}"])
        self._run(["launchctl", "bootstrap", "system", self._plist_path])

    def _unload(self) -> None:
        """Boot the job out and wait until launchd lets go of its label."""
        self._run(
            ["launchctl", "bootout", f"system/{COMFYUI_DARWIN_LABEL}"], is_checked=False
        )
        waited = 0.0
        while self._is_loaded() and waited < COMFYUI_DARWIN_UNLOAD_TIMEOUT_S:
            self._sleep(COMFYUI_DARWIN_UNLOAD_POLL_S)
            waited += COMFYUI_DARWIN_UNLOAD_POLL_S
