"""CloudCLI on macOS: one LaunchDaemon per account.

Each instance is a LaunchDaemon whose plist names the account in
``UserName``, so root's launchd starts the Node.js the agent unpacked with
the server script of the account's own app directory, as that account,
with the environment the plist holds and nothing else; the plist is
root-only, since that environment holds the instance's secrets. Its output
goes to the account's file under ``/Library/Logs/Neutrino/agent``. Before an
instance first runs, the account installs CloudCLI into its app directory
with that Node.js, and the service's ``PATH`` holds that Node.js's
directory and then the ``claude`` its login shell finds.

Not pure: writes under ``/Library``, runs commands as an account and drives
launchd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import plistlib
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli import installer
from neutrino_agent.modules.cloudcli.constants import (
    CLOUDCLI_DATABASE_NAME,
    CLOUDCLI_DARWIN_LOG_DIR,
    CLOUDCLI_DARWIN_LOG_PREFIX,
    CLOUDCLI_INSTALL_TIMEOUT_S,
    CLOUDCLI_LAUNCHD_DIR,
    CLOUDCLI_LAUNCHD_PREFIX,
    CLOUDCLI_LOG_SUFFIX,
    CLOUDCLI_LOOKUP_TIMEOUT_S,
    CLOUDCLI_VERSION,
)
from neutrino_agent.modules.subprocess_run import CommandResult
from neutrino_agent.modules.subprocess_run import run as run_command
from neutrino_agent.modules.vscode.installer import write_if_changed

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

PLIST_SUFFIX = ".plist"
# The PATH a command run as an account starts from.
ACCOUNT_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
INSTALL_SHELL = (
    'mkdir -p "$0" && rm -rf "$0/node_modules" && : > "$0/.npmrc" && exec "$@"'
)
CHECK_SHELL = 'cd "$0" && exec "$@"'


def render_plist(
    *,
    label: str,
    account: str,
    node: str,
    server: str,
    home: str,
    environment: dict,
    log_path: str,
) -> bytes:
    """One instance's LaunchDaemon.

    Args:
        label: The job's label.
        account: The account it runs as.
        node: The Node.js interpreter.
        server: The server script of the account's app directory.
        home: The account's home, where it runs.
        environment: Everything it runs with.
        log_path: The file its output and its errors are appended to.

    Returns:
        The plist, as XML.
    """
    return plistlib.dumps(
        {
            "Label": label,
            "UserName": account,
            "ProgramArguments": [node, server],
            "EnvironmentVariables": dict(environment),
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


def _run_as(entry: tuple, command: list, *, environment: dict, timeout_s: int):
    """Run one command as an account, in its home, with this environment alone."""
    uid, gid, home, _shell = entry
    completed = subprocess.run(
        command,
        user=uid,
        group=gid,
        extra_groups=[],
        cwd=home,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return CommandResult(
        list(command), completed.returncode, completed.stdout, completed.stderr
    )


class CloudcliDarwinApplier:
    """Runs each instance as a LaunchDaemon of its account."""

    def __init__(
        self,
        *,
        module_dir: str,
        record_dir: str,
        run=None,
        run_as=None,
        lookup_account=None,
        chown=None,
        launchd_dir: str = CLOUDCLI_LAUNCHD_DIR,
        log_dir: str = CLOUDCLI_DARWIN_LOG_DIR,
        log=print,
    ):
        """
        Args:
            module_dir: Where Node.js is unpacked.
            record_dir: Where the records live, root-only.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            run_as: Called with ``(entry, command, environment=,
                timeout_s=)``; runs a command as the account ``entry``
                names and returns a ``CommandResult``. None runs it.
            lookup_account: Returns an account's ``(uid, gid, home,
                shell)`` or raises KeyError; None asks the account database.
            chown: Changes a file's owner as :func:`os.chown` does; None is
                that.
            launchd_dir: Where the plists are written.
            log_dir: Where the instances' log files are.
            log: Callable used for progress messages.
        """
        self.module_dir = module_dir
        self.record_dir = record_dir
        self._run = run if run is not None else run_command
        self._run_as = run_as if run_as is not None else _run_as
        self._lookup_account = (
            lookup_account if lookup_account is not None else _account_entry
        )
        self._chown = chown if chown is not None else os.chown
        self._launchd_dir = launchd_dir
        self._log_dir = log_dir
        self._log = log
        # The account whose install the running apply waits on, if any.
        self.installing: frozenset = frozenset()

    @property
    def node(self) -> str:
        """The Node.js interpreter, empty when none is unpacked."""
        directory = installer.node_dir(self.module_dir)
        return installer.node_path(directory, "darwin") if directory else ""

    def apply(
        self, config, upstream_ports: dict, databases: "dict | None" = None
    ) -> list:
        """Install CloudCLI for each account, load one LaunchDaemon per instance, unload the rest.

        Args:
            config: The validated :class:`CloudcliConfig`.
            upstream_ports: Account to the loopback port its CloudCLI
                listens on.
            databases: Account to the database file its CloudCLI runs on;
                ``auth.db`` for an account not named.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``account_unknown`` for an account the Mac does
                not have, ``cloudcli_claude_missing`` for one whose login
                shell finds no ``claude``, ``cloudcli_node_download_failed``
                with no Node.js, and an install's
                ``cloudcli_npm_install_failed`` or
                ``cloudcli_native_module_failed``.
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When launchd refuses.
        """
        node = self.node
        if not node:
            raise ModuleApplyError("cloudcli_node_download_failed", {})
        entries = {}
        for instance in config.instances:
            try:
                entries[instance.account] = self._lookup_account(instance.account)
            except KeyError:
                raise ModuleApplyError(
                    "account_unknown", {"account": instance.account}
                ) from None
        claudes = {
            instance.account: self._find_claude(
                instance.account, entries[instance.account]
            )
            for instance in config.instances
        }
        notes = []
        for instance in config.instances:
            if self._install_app(
                instance.account,
                entries[instance.account],
                node,
                registry=config.npm_registry,
                extra=config.npm_environment,
            ):
                notes.append(f"installed CloudCLI for {instance.account}")
        os.makedirs(self._log_dir, mode=0o755, exist_ok=True)
        wanted = {instance.account for instance in config.instances}
        for account in self._held_accounts():
            if account not in wanted:
                self._retire(account)
                notes.append(f"stopped CloudCLI of {account}")
        for instance in config.instances:
            uid, gid, home, _shell = entries[instance.account]
            log_path = self.log_path(instance.account)
            self._prepare_log(log_path, uid, gid)
            label = CLOUDCLI_LAUNCHD_PREFIX + instance.account
            plist = render_plist(
                label=label,
                account=instance.account,
                node=node,
                server=installer.server_path(installer.app_dir(home, "darwin")),
                home=home,
                environment=installer.service_environment(
                    instance,
                    upstream_port=upstream_ports[instance.account],
                    database_name=(databases or {}).get(
                        instance.account, CLOUDCLI_DATABASE_NAME
                    ),
                    home=home,
                    os_name="darwin",
                    node_dir=os.path.dirname(node),
                    claude_path=claudes[instance.account],
                ),
                log_path=log_path,
            )
            is_changed = write_if_changed(
                self._plist_path(instance.account), plist.decode("utf-8"), 0o600
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
                notes.append(f"started CloudCLI of {instance.account}")
        return notes

    def stop(self) -> None:
        """Unload every instance's job; its plist loads it again at boot."""
        for account in self._held_accounts():
            self._run(
                ["launchctl", "bootout", f"system/{CLOUDCLI_LAUNCHD_PREFIX}{account}"],
                is_checked=False,
            )

    def remove(self) -> None:
        """Unload every instance and delete its plist and its log."""
        for account in self._held_accounts():
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
                "is_running": self._is_running(CLOUDCLI_LAUNCHD_PREFIX + account),
                "code": "",
            }
            for account in accounts
        }

    def units(self) -> list:
        """No journal: launchd keeps none."""
        return []

    def log_path(self, account: str) -> str:
        """The file one account's CloudCLI writes its output to.

        Args:
            account: The account.

        Returns:
            ``/Library/Logs/Neutrino/agent/cloudcli_<account>.log``.
        """
        return os.path.join(
            self._log_dir, CLOUDCLI_DARWIN_LOG_PREFIX + account + CLOUDCLI_LOG_SUFFIX
        )

    def log_paths(self, accounts: list) -> list:
        """Each instance's log file.

        Args:
            accounts: The accounts asked about.

        Returns:
            ``[(account, path)]``, in that order.
        """
        return [(account, self.log_path(account)) for account in accounts]

    def _find_claude(self, account: str, entry: tuple) -> str:
        """The ``claude`` the account's login shell finds, or ``cloudcli_claude_missing``."""
        _uid, _gid, home, shell = entry
        result = self._run_as(
            entry,
            [shell or "/bin/zsh", "-l", "-c", "command -v claude"],
            environment={
                "HOME": home,
                "USER": account,
                "LOGNAME": account,
                "SHELL": shell,
                "PATH": ACCOUNT_PATH,
            },
            timeout_s=CLOUDCLI_LOOKUP_TIMEOUT_S,
        )
        found = installer.claude_of(result.stdout) if result.is_success else ""
        if not found:
            raise ModuleApplyError("cloudcli_claude_missing", {"account": account})
        return found

    def _install_app(
        self,
        account: str,
        entry: tuple,
        node: str,
        *,
        registry: str = "",
        extra: "dict | None" = None,
    ) -> bool:
        """Install CloudCLI into the account's app directory unless it is there."""
        home = entry[2]
        app = installer.app_dir(home, "darwin")
        if installer.installed_version(app) == CLOUDCLI_VERSION:
            return False
        self.installing = frozenset({account})
        try:
            node_bin = os.path.dirname(node)
            environment = {
                "HOME": home,
                "USER": account,
                "LOGNAME": account,
                "PATH": f"{node_bin}:{ACCOUNT_PATH}",
                **installer.npm_environment(app, registry=registry, extra=extra),
            }
            npm = installer.npm_path(os.path.dirname(node_bin), "darwin")
            self._log(
                f"cloudcli: installing CloudCLI for {account} "
                f"from {installer.registry_host(registry)}"
            )
            result = self._run_as(
                entry,
                ["/bin/sh", "-c", INSTALL_SHELL, app, node, npm]
                + installer.npm_arguments(app),
                environment=environment,
                timeout_s=CLOUDCLI_INSTALL_TIMEOUT_S,
            )
            if not result.is_success:
                output = (result.stdout + "\n" + result.stderr).strip()
                self._log(f"cloudcli: npm for {account}: {output[-2000:]}")
                raise installer.npm_failure(output, account)
            check = self._run_as(
                entry,
                ["/bin/sh", "-c", CHECK_SHELL, app, node, "-e"]
                + [installer.NATIVE_CHECK_SCRIPT],
                environment=environment,
                timeout_s=CLOUDCLI_LOOKUP_TIMEOUT_S,
            )
            if check.exit_code == installer.NATIVE_CHECK_EXIT:
                raise ModuleApplyError(
                    "cloudcli_native_module_failed",
                    {
                        "account": account,
                        "module": check.stdout.strip(),
                        "detail": installer.failure_detail(check.stderr),
                    },
                )
            return True
        finally:
            self.installing = frozenset()

    def _held_accounts(self) -> list:
        try:
            names = os.listdir(self._launchd_dir)
        except OSError:
            return []
        return sorted(
            name[len(CLOUDCLI_LAUNCHD_PREFIX) : -len(PLIST_SUFFIX)]
            for name in names
            if name.startswith(CLOUDCLI_LAUNCHD_PREFIX) and name.endswith(PLIST_SUFFIX)
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
            ["launchctl", "bootout", f"system/{CLOUDCLI_LAUNCHD_PREFIX}{account}"],
            is_checked=False,
        )
        for path in (self._plist_path(account), self.log_path(account)):
            with contextlib.suppress(OSError):
                os.unlink(path)

    def _plist_path(self, account: str) -> str:
        return os.path.join(
            self._launchd_dir, CLOUDCLI_LAUNCHD_PREFIX + account + PLIST_SUFFIX
        )
