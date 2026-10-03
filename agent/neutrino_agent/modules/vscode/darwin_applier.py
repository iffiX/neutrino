"""VS Code's servers on macOS: one LaunchDaemon per account.

Each instance is a LaunchDaemon whose plist names the account in
``UserName``, so root's launchd starts the CLI as that account with no
password, its output appended to the account's file under
``/Library/Logs/Neutrino/agent``. The token file and the log file belong to
the account, mode 0600. A plist or a token that changed is loaded again, which
restarts the server.

Not pure: writes under ``/Library`` and drives launchd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import plistlib
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.subprocess_run import run as run_command
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.vscode.constants import (
    VSCODE_CLI_NAMES,
    VSCODE_DARWIN_LOG_DIR,
    VSCODE_DARWIN_LOG_PREFIX,
    VSCODE_DIR_NAME,
    VSCODE_LAUNCHD_DIR,
    VSCODE_LAUNCHD_PREFIX,
    VSCODE_LOG_SUFFIX,
    VSCODE_SERVE_ARGUMENTS,
    VSCODE_TOKEN_DIR_NAME,
)
from neutrino_agent.modules.vscode.installer import write_if_changed

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

PLIST_SUFFIX = ".plist"
TOKEN_SUFFIX = ".token"


def render_plist(
    *,
    label: str,
    account: str,
    cli_path: str,
    host: str,
    port: int,
    token_path: str,
    log_path: str,
) -> bytes:
    """One instance's LaunchDaemon.

    Args:
        label: The job's label.
        account: The account it runs as.
        cli_path: Where the CLI is.
        host: The address it listens on.
        port: The port.
        token_path: The account's token file.
        log_path: The file its output and its errors are appended to.

    Returns:
        The plist, as XML.
    """
    return plistlib.dumps(
        {
            "Label": label,
            "UserName": account,
            "ProgramArguments": [
                cli_path,
                *VSCODE_SERVE_ARGUMENTS,
                "--host",
                host,
                "--port",
                str(port),
                "--connection-token-file",
                token_path,
            ],
            "StandardOutPath": log_path,
            "StandardErrorPath": log_path,
            "RunAtLoad": True,
            "KeepAlive": True,
        }
    )


def _account_ids(account: str) -> tuple:
    """One account's uid and gid.

    Raises:
        KeyError: When the account database has no such account.
    """
    if pwd is None:
        raise KeyError(account)
    entry = pwd.getpwnam(account)
    return entry.pw_uid, entry.pw_gid


class VscodeDarwinApplier:
    """Runs each instance as a LaunchDaemon of its account."""

    def __init__(
        self,
        *,
        root: str,
        run=None,
        lookup_account=None,
        chown=None,
        launchd_dir: str = VSCODE_LAUNCHD_DIR,
        log_dir: str = VSCODE_DARWIN_LOG_DIR,
    ):
        """
        Args:
            root: The agent's state root; the CLI and the token files live
                under it.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            lookup_account: Returns an account's ``(uid, gid)`` or raises
                KeyError; None asks the account database.
            chown: Changes a file's owner as :func:`os.chown` does; None is
                that.
            launchd_dir: Where the plists are written.
            log_dir: Where the instances' log files are.
        """
        self.cli_dir = os.path.join(root, VSCODE_DIR_NAME)
        self._token_dir = os.path.join(self.cli_dir, VSCODE_TOKEN_DIR_NAME)
        self._run = run if run is not None else run_command
        self._lookup_account = (
            lookup_account if lookup_account is not None else _account_ids
        )
        self._chown = chown if chown is not None else os.chown
        self._launchd_dir = launchd_dir
        self._log_dir = log_dir

    @property
    def cli_path(self) -> str:
        """Where the CLI is."""
        return os.path.join(self.cli_dir, VSCODE_CLI_NAMES["darwin"])

    def apply(self, config: VscodeConfig) -> list:
        """Load one LaunchDaemon per instance and unload the ones gone.

        Args:
            config: The validated configuration.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``account_unknown`` for an account the Mac
                does not have.
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When launchd refuses.
        """
        owners = {}
        for instance in config.instances:
            try:
                owners[instance.account] = self._lookup_account(instance.account)
            except KeyError:
                raise ModuleApplyError(
                    "account_unknown", {"account": instance.account}
                ) from None
        os.makedirs(self._token_dir, mode=0o755, exist_ok=True)
        os.makedirs(self._log_dir, mode=0o755, exist_ok=True)
        notes = []
        wanted = {instance.account for instance in config.instances}
        for account in self._held_accounts():
            if account not in wanted:
                self._retire(account)
                notes.append(f"stopped the server of {account}")
        for instance in config.instances:
            token_path = os.path.join(self._token_dir, instance.account + TOKEN_SUFFIX)
            is_changed = write_if_changed(token_path, instance.token, 0o600)
            uid, gid = owners[instance.account]
            self._chown(token_path, uid, gid)
            log_path = self.log_path(instance.account)
            self._prepare_log(log_path, uid, gid)
            label = VSCODE_LAUNCHD_PREFIX + instance.account
            plist = render_plist(
                label=label,
                account=instance.account,
                cli_path=self.cli_path,
                host=config.host,
                port=instance.port,
                token_path=token_path,
                log_path=log_path,
            )
            is_changed |= write_if_changed(
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
                notes.append(f"started the server of {instance.account}")
        return notes

    def stop(self) -> None:
        """Unload every instance's job; its plist loads it again at boot."""
        for account in self._held_accounts():
            self._run(
                ["launchctl", "bootout", f"system/{VSCODE_LAUNCHD_PREFIX}{account}"],
                is_checked=False,
            )

    def remove(self) -> None:
        """Unload every instance and delete its plist and its token."""
        for account in self._held_accounts():
            self._retire(account)

    def states(self, config: "VscodeConfig | None") -> list:
        """Each instance and whether launchd runs it.

        Args:
            config: The applied configuration; None reads the instances
                from their plists.

        Returns:
            ``[{"account", "port", "url", "is_running", "code"}]``.
        """
        if config is not None:
            held = [(item.account, item.port) for item in config.instances]
            host = config.host
        else:
            held = [
                (account, self._held_port(account)) for account in self._held_accounts()
            ]
            host = VscodeConfig().host
        return [
            {
                "account": account,
                "port": port,
                "url": f"http://{host}:{port}/" if port else "",
                "is_running": self._is_running(VSCODE_LAUNCHD_PREFIX + account),
                "code": "",
            }
            for account, port in held
        ]

    def units(self) -> list:
        """No journal: launchd keeps none."""
        return []

    def log_path(self, account: str) -> str:
        """The file one account's server writes its output to.

        Args:
            account: The account.

        Returns:
            ``/Library/Logs/Neutrino/agent/vscode_<account>.log``.
        """
        return os.path.join(
            self._log_dir, VSCODE_DARWIN_LOG_PREFIX + account + VSCODE_LOG_SUFFIX
        )

    def log_paths(self, config: "VscodeConfig | None") -> list:
        """Each instance's log file.

        Args:
            config: The applied configuration; None reads the instances
                from their plists.

        Returns:
            ``[(account, path)]``, in the instances' order.
        """
        if config is not None:
            accounts = [item.account for item in config.instances]
        else:
            accounts = self._held_accounts()
        return [(account, self.log_path(account)) for account in accounts]

    def _held_accounts(self) -> list:
        try:
            names = os.listdir(self._launchd_dir)
        except OSError:
            return []
        return sorted(
            name[len(VSCODE_LAUNCHD_PREFIX) : -len(PLIST_SUFFIX)]
            for name in names
            if name.startswith(VSCODE_LAUNCHD_PREFIX) and name.endswith(PLIST_SUFFIX)
        )

    def _held_port(self, account: str) -> int:
        try:
            with open(self._plist_path(account), "rb") as stream:
                arguments = plistlib.load(stream).get("ProgramArguments") or []
            return int(arguments[arguments.index("--port") + 1])
        except (OSError, ValueError, IndexError, plistlib.InvalidFileException):
            return 0

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
            ["launchctl", "bootout", f"system/{VSCODE_LAUNCHD_PREFIX}{account}"],
            is_checked=False,
        )
        for path in (
            self._plist_path(account),
            os.path.join(self._token_dir, account + TOKEN_SUFFIX),
            self.log_path(account),
        ):
            with contextlib.suppress(OSError):
                os.unlink(path)

    def _plist_path(self, account: str) -> str:
        return os.path.join(
            self._launchd_dir, VSCODE_LAUNCHD_PREFIX + account + PLIST_SUFFIX
        )
