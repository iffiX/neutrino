"""code-server on macOS: one LaunchDaemon per account.

Each instance is a LaunchDaemon whose plist names the account in
``UserName``, so root's launchd starts the release's launcher as that
account, in its home, listening on the socket in that account's run
directory, which the agent makes the account's own, mode 0700, before the
job loads. Its output goes to the account's file under
``/Library/Logs/Neutrino/agent``.

Not pure: writes under ``/Library`` and the state root, and drives launchd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import plistlib
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server import installer
from neutrino_agent.modules.code_server.constants import (
    CODE_SERVER_DARWIN_LOG_DIR,
    CODE_SERVER_DARWIN_LOG_PREFIX,
    CODE_SERVER_DARWIN_PATH,
    CODE_SERVER_LAUNCHD_DIR,
    CODE_SERVER_LAUNCHD_PREFIX,
    CODE_SERVER_LOG_SUFFIX,
)
from neutrino_agent.modules.subprocess_run import run as run_command
from neutrino_agent.modules.vscode.installer import write_if_changed

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

PLIST_SUFFIX = ".plist"


def render_plist(
    *, label: str, account: str, arguments: list, home: str, shell: str, log_path: str
) -> bytes:
    """One instance's LaunchDaemon.

    Args:
        label: The job's label.
        account: The account it runs as.
        arguments: The launcher and its flags.
        home: The account's home, where it runs.
        shell: The account's login shell, which code-server's terminal opens.
        log_path: The file its output and its errors are appended to.

    Returns:
        The plist, as XML.
    """
    return plistlib.dumps(
        {
            "Label": label,
            "UserName": account,
            "ProgramArguments": list(arguments),
            "EnvironmentVariables": {
                "HOME": home,
                "USER": account,
                "LOGNAME": account,
                "SHELL": shell,
                "PATH": CODE_SERVER_DARWIN_PATH,
            },
            "WorkingDirectory": home,
            "StandardOutPath": log_path,
            "StandardErrorPath": log_path,
            "RunAtLoad": True,
            "KeepAlive": True,
        }
    )


def _account_entry(account: str) -> tuple:
    """One account's uid, gid, home and login shell.

    Raises:
        KeyError: When the account database has no such account.
    """
    if pwd is None:
        raise KeyError(account)
    entry = pwd.getpwnam(account)
    return entry.pw_uid, entry.pw_gid, entry.pw_dir, entry.pw_shell


class CodeServerDarwinApplier:
    """Runs each instance as a LaunchDaemon of its account."""

    os_name = "darwin"

    def __init__(
        self,
        *,
        module_dir: str,
        record_dir: str,
        run=None,
        lookup_account=None,
        chown=None,
        launchd_dir: str = CODE_SERVER_LAUNCHD_DIR,
        log_dir: str = CODE_SERVER_DARWIN_LOG_DIR,
    ):
        """
        Args:
            module_dir: Where the release and the run directories are.
            record_dir: Where the records live, root-only.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            lookup_account: Returns an account's ``(uid, gid, home,
                shell)`` or raises KeyError; None asks the account database.
            chown: Changes a file's owner as :func:`os.chown` does; None is
                that.
            launchd_dir: Where the plists are written.
            log_dir: Where the instances' log files are.
        """
        self.module_dir = module_dir
        self.record_dir = record_dir
        self._run = run if run is not None else run_command
        self._lookup_account = (
            lookup_account if lookup_account is not None else _account_entry
        )
        self._chown = chown if chown is not None else os.chown
        self._launchd_dir = launchd_dir
        self._log_dir = log_dir

    def apply(self, config) -> list:
        """Load one LaunchDaemon per instance and unload the rest.

        Args:
            config: The validated :class:`CodeServerConfig`.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``account_unknown`` for an account the Mac does
                not have, ``account_invalid`` for one whose socket path is
                too long, ``code_server_download_failed`` with no release.
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When launchd refuses.
        """
        if not os.path.isfile(installer.launcher_path(self.module_dir)):
            raise ModuleApplyError("code_server_download_failed", {})
        entries = {}
        for instance in config.instances:
            try:
                entries[instance.account] = self._lookup_account(instance.account)
            except KeyError:
                raise ModuleApplyError(
                    "account_unknown", {"account": instance.account}
                ) from None
            installer.check_socket_path(self.module_dir, instance.account, "darwin")
        notes = []
        wanted = {instance.account for instance in config.instances}
        for account in self.held_accounts():
            if account not in wanted:
                self._retire(account)
                notes.append(f"stopped code-server of {account}")
        os.makedirs(self._log_dir, mode=0o755, exist_ok=True)
        for instance in config.instances:
            uid, gid, home, shell = entries[instance.account]
            installer.prepare_run_dir(
                self.module_dir, instance.account, uid, gid, self._chown
            )
            log_path = self.log_path(instance.account)
            self._prepare_log(log_path, uid, gid)
            label = CODE_SERVER_LAUNCHD_PREFIX + instance.account
            plist = render_plist(
                label=label,
                account=instance.account,
                arguments=installer.server_arguments(self.module_dir, instance.account),
                home=home,
                shell=shell or "/bin/zsh",
                log_path=log_path,
            )
            is_changed = write_if_changed(
                self._plist_path(instance.account), plist.decode("utf-8"), 0o644
            )
            if is_changed or not self._is_loaded(label):
                self._run(["launchctl", "bootout", f"system/{label}"], is_checked=False)
                self._run(
                    [
                        "launchctl",
                        "bootstrap",
                        "system",
                        self._plist_path(instance.account),
                    ]
                )
                notes.append(f"started code-server of {instance.account}")
        return notes

    def stop(self) -> None:
        """Unload every instance's job; its plist loads it again at boot."""
        for account in self.held_accounts():
            self._run(
                [
                    "launchctl",
                    "bootout",
                    f"system/{CODE_SERVER_LAUNCHD_PREFIX}{account}",
                ],
                is_checked=False,
            )

    def remove(self) -> None:
        """Unload every instance and delete its plist and its log."""
        for account in self.held_accounts():
            self._retire(account)

    def states(self, accounts: list) -> dict:
        """Whether launchd runs each account's job.

        Args:
            accounts: The accounts asked about.

        Returns:
            Account to ``{"is_running", "code"}``.
        """
        return {
            account: {
                "is_running": self._is_running(CODE_SERVER_LAUNCHD_PREFIX + account),
                "code": "",
            }
            for account in accounts
        }

    def units(self) -> list:
        """No journal: launchd keeps none."""
        return []

    def log_path(self, account: str) -> str:
        """The file one account's code-server writes its output to.

        Args:
            account: The account.

        Returns:
            ``/Library/Logs/Neutrino/agent/code_server_<account>.log``.
        """
        return os.path.join(
            self._log_dir,
            CODE_SERVER_DARWIN_LOG_PREFIX + account + CODE_SERVER_LOG_SUFFIX,
        )

    def log_paths(self, accounts: list) -> list:
        """Each instance's log file.

        Args:
            accounts: The accounts asked about.

        Returns:
            ``[(account, path)]``, in that order.
        """
        return [(account, self.log_path(account)) for account in accounts]

    def held_accounts(self) -> list:
        """The accounts a plist is written for."""
        try:
            names = os.listdir(self._launchd_dir)
        except OSError:
            return []
        return sorted(
            name[len(CODE_SERVER_LAUNCHD_PREFIX) : -len(PLIST_SUFFIX)]
            for name in names
            if name.startswith(CODE_SERVER_LAUNCHD_PREFIX)
            and name.endswith(PLIST_SUFFIX)
        )

    def _prepare_log(self, path: str, uid: int, gid: int) -> None:
        """Make one log file the account's own, mode 0600, keeping what it holds."""
        with open(path, "a", encoding="utf-8"):
            pass
        os.chmod(path, 0o600)
        self._chown(path, uid, gid)

    def _is_loaded(self, label: str) -> bool:
        return self._run(
            ["launchctl", "print", f"system/{label}"], is_checked=False
        ).is_success

    def _is_running(self, label: str) -> bool:
        try:
            result = self._run(
                ["launchctl", "print", f"system/{label}"], is_checked=False
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.is_success and "state = running" in result.stdout

    def _retire(self, account: str) -> None:
        self._run(
            ["launchctl", "bootout", f"system/{CODE_SERVER_LAUNCHD_PREFIX}{account}"],
            is_checked=False,
        )
        for path in (self._plist_path(account), self.log_path(account)):
            with contextlib.suppress(OSError):
                os.unlink(path)
        installer.remove_run_dir(self.module_dir, account)

    def _plist_path(self, account: str) -> str:
        return os.path.join(
            self._launchd_dir, CODE_SERVER_LAUNCHD_PREFIX + account + PLIST_SUFFIX
        )
