"""VS Code's servers on Linux: one systemd unit per account.

The template unit ``neutrino_vscode@.service`` runs the CLI as the account
its instance names, with the address, the port and the token file read from
a per-account environment file. The token file belongs to the account, mode
0600, so only that account and root read it.

Not pure: writes under the agent's state root and ``/etc``, and drives
systemd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.subprocess_run import run as run_command
from neutrino_agent.modules.subprocess_run import unit_state
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.vscode.constants import (
    VSCODE_CLI_NAMES,
    VSCODE_LINUX_SYSCTL_FLOORS,
    VSCODE_LINUX_SYSCTL_PATH,
    VSCODE_LINUX_SYSCTL_PROC_DIR,
    VSCODE_SERVE_ARGUMENTS,
    VSCODE_SYSTEMD_DIR,
    VSCODE_UNIT_PREFIX,
    VSCODE_UNIT_TEMPLATE,
)
from neutrino_agent.modules.vscode.installer import write_if_changed

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

ENVIRONMENT_SUFFIX = ".env"
TOKEN_SUFFIX = ".token"


def render_unit(cli_path: str, token_dir: str) -> str:
    """The template unit every instance runs from.

    Args:
        cli_path: Where the CLI is.
        token_dir: Where each account's environment and token files are.

    Returns:
        The unit file's text.
    """
    arguments = " ".join(VSCODE_SERVE_ARGUMENTS)
    return (
        "[Unit]\n"
        "Description=VS Code server for %i\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=%i\n"
        f"EnvironmentFile={token_dir}/%i{ENVIRONMENT_SUFFIX}\n"
        f"ExecStart={cli_path} {arguments} --host ${{VSCODE_HOST}} "
        "--port ${VSCODE_PORT} --connection-token-file ${VSCODE_TOKEN_FILE}\n"
        "Restart=always\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def render_environment(host: str, port: int, token_path: str) -> str:
    """One account's environment file.

    Args:
        host: The address the server listens on.
        port: The port.
        token_path: The account's token file.

    Returns:
        The file's text.
    """
    return (
        f"VSCODE_HOST={host}\n"
        f"VSCODE_PORT={port}\n"
        f"VSCODE_TOKEN_FILE={token_path}\n"
    )


def instance_unit(account: str) -> str:
    """The unit one account's server runs as.

    Args:
        account: The account.

    Returns:
        ``neutrino_vscode@<account>.service``.
    """
    return f"{VSCODE_UNIT_PREFIX}{account}.service"


def _account_ids(account: str) -> tuple:
    """One account's uid and gid.

    Raises:
        KeyError: When the account database has no such account.
    """
    if pwd is None:
        raise KeyError(account)
    entry = pwd.getpwnam(account)
    return entry.pw_uid, entry.pw_gid


class VscodeLinuxApplier:
    """Runs each instance as a systemd unit of its account."""

    def __init__(
        self,
        *,
        run=None,
        lookup_account=None,
        chown=None,
        cli_dir: str,
        token_dir: str,
        systemd_dir: str = VSCODE_SYSTEMD_DIR,
        sysctl_path: str = VSCODE_LINUX_SYSCTL_PATH,
        proc_dir: str = VSCODE_LINUX_SYSCTL_PROC_DIR,
    ):
        """
        Args:
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            lookup_account: Returns an account's ``(uid, gid)`` or raises
                KeyError; None asks the account database.
            chown: Changes a file's owner as :func:`os.chown` does; None is
                that.
            cli_dir: Where the CLI is unpacked.
            token_dir: Where the environment and token files live.
            systemd_dir: Where the template unit is written.
            sysctl_path: The drop-in that raises the inotify limits.
            proc_dir: Where the kernel shows the limits in force.
        """
        self._run = run if run is not None else run_command
        self._lookup_account = (
            lookup_account if lookup_account is not None else _account_ids
        )
        self._chown = chown if chown is not None else os.chown
        self.cli_dir = cli_dir
        self._token_dir = token_dir
        self._systemd_dir = systemd_dir
        self._sysctl_path = sysctl_path
        self._proc_dir = proc_dir

    @property
    def cli_path(self) -> str:
        """Where the CLI is."""
        return os.path.join(self.cli_dir, VSCODE_CLI_NAMES["linux"])

    def apply(self, config: VscodeConfig) -> list:
        """Run one unit per instance and stop the units of instances gone.

        Args:
            config: The validated configuration.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``account_unknown`` for an account the
                machine does not have.
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When systemd refuses.
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
        notes = []
        if self._raise_watch_limits():
            notes.append("raised the inotify limits")
        is_template_new = write_if_changed(
            os.path.join(self._systemd_dir, VSCODE_UNIT_TEMPLATE),
            render_unit(self.cli_path, self._token_dir),
            0o644,
        )
        if is_template_new:
            self._run(["systemctl", "daemon-reload"])
        wanted = {instance.account for instance in config.instances}
        for account in self._held_accounts():
            if account not in wanted:
                self._retire(account)
                notes.append(f"stopped the server of {account}")
        for instance in config.instances:
            token_path = self._path(instance.account, TOKEN_SUFFIX)
            is_changed = write_if_changed(token_path, instance.token, 0o600)
            uid, gid = owners[instance.account]
            self._chown(token_path, uid, gid)
            is_changed |= write_if_changed(
                self._path(instance.account, ENVIRONMENT_SUFFIX),
                render_environment(config.host, instance.port, token_path),
                0o644,
            )
            unit = instance_unit(instance.account)
            if is_changed or is_template_new:
                self._run(["systemctl", "enable", unit])
                self._run(["systemctl", "restart", unit])
                notes.append(f"started the server of {instance.account}")
            else:
                self._run(["systemctl", "enable", "--now", unit])
        return notes

    def stop(self) -> None:
        """Stop every instance's unit; each stays enabled."""
        for account in self._held_accounts():
            self._run(["systemctl", "stop", instance_unit(account)], is_checked=False)

    def remove(self) -> None:
        """Stop and disable every instance, and delete its files and the template."""
        for account in self._held_accounts():
            self._retire(account)
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(self._systemd_dir, VSCODE_UNIT_TEMPLATE))
        with contextlib.suppress(OSError):
            os.unlink(self._sysctl_path)
        self._run(["systemctl", "daemon-reload"], is_checked=False)

    def _raise_watch_limits(self) -> bool:
        """Lift the inotify limits to the module's floors, never lower them.

        A limit the kernel does not report is left alone.

        Returns:
            Whether a drop-in was written and loaded.
        """
        wanted = {}
        for key, floor in VSCODE_LINUX_SYSCTL_FLOORS.items():
            current = self._read_limit(key)
            if current is not None and current < floor:
                wanted[key] = floor
        if not wanted:
            return False
        text = "".join(f"{key} = {value}\n" for key, value in wanted.items())
        os.makedirs(os.path.dirname(self._sysctl_path), exist_ok=True)
        if not write_if_changed(self._sysctl_path, text, 0o644):
            return False
        self._run(["sysctl", "-p", self._sysctl_path], is_checked=False)
        return True

    def _read_limit(self, key: str) -> "int | None":
        path = os.path.join(self._proc_dir, *key.split("."))
        try:
            with open(path, encoding="utf-8") as handle:
                return int(handle.read().strip())
        except (OSError, ValueError):
            return None

    def states(self, config: "VscodeConfig | None") -> list:
        """Each instance and whether its unit is active.

        Args:
            config: The applied configuration; None reads the instances
                from their environment files.

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
                "is_running": unit_state(instance_unit(account)) == "active",
                "code": "",
            }
            for account, port in held
        ]

    def units(self) -> list:
        """Every instance's unit, for the journal."""
        return [instance_unit(account) for account in self._held_accounts()]

    def log_paths(self, config: "VscodeConfig | None") -> list:
        """No log file: the journal keeps each unit's output.

        Args:
            config: The applied configuration.

        Returns:
            Empty.
        """
        return []

    def _held_accounts(self) -> list:
        """The accounts an environment file names a server for."""
        try:
            names = os.listdir(self._token_dir)
        except OSError:
            return []
        return sorted(
            name[: -len(ENVIRONMENT_SUFFIX)]
            for name in names
            if name.endswith(ENVIRONMENT_SUFFIX)
        )

    def _held_port(self, account: str) -> int:
        try:
            with open(
                self._path(account, ENVIRONMENT_SUFFIX), "r", encoding="utf-8"
            ) as stream:
                for line in stream:
                    key, _, value = line.strip().partition("=")
                    if key == "VSCODE_PORT":
                        return int(value)
        except (OSError, ValueError):
            return 0
        return 0

    def _retire(self, account: str) -> None:
        self._run(
            ["systemctl", "disable", "--now", instance_unit(account)], is_checked=False
        )
        for suffix in (ENVIRONMENT_SUFFIX, TOKEN_SUFFIX):
            with contextlib.suppress(OSError):
                os.unlink(self._path(account, suffix))

    def _path(self, account: str, suffix: str) -> str:
        return os.path.join(self._token_dir, account + suffix)
