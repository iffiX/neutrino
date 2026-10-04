"""code-server on Linux: one systemd unit per account.

The template unit ``neutrino_code_server@.service`` runs the release's
launcher as the account its instance names, listening on the socket in that
account's run directory, which the agent makes the account's own, mode
0700, before the unit starts.

Not pure: writes under ``/etc`` and the state root, and drives systemd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server import installer
from neutrino_agent.modules.code_server.constants import (
    CODE_SERVER_SYSTEMD_DIR,
    CODE_SERVER_UNIT_PREFIX,
    CODE_SERVER_UNIT_TEMPLATE,
)
from neutrino_agent.modules.subprocess_run import run as run_command
from neutrino_agent.modules.subprocess_run import unit_state
from neutrino_agent.modules.vscode.installer import write_if_changed

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

# The file beside each record that says the account's unit is enabled.
ENABLED_SUFFIX = ".enabled"


def render_unit(root: str) -> str:
    """The template unit every instance runs from.

    Args:
        root: The module's directory.

    Returns:
        The unit file's text, ``%i`` standing for the account.
    """
    arguments = " ".join(installer.server_arguments(root, "%i"))
    return (
        "[Unit]\n"
        "Description=code-server for %i\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=%i\n"
        "WorkingDirectory=~\n"
        f"ExecStart={arguments}\n"
        "Restart=always\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def instance_unit(account: str) -> str:
    """The unit one account's code-server runs as.

    Args:
        account: The account.

    Returns:
        ``neutrino_code_server@<account>.service``.
    """
    return f"{CODE_SERVER_UNIT_PREFIX}{account}.service"


def _account_entry(account: str) -> tuple:
    """One account's uid, gid and home.

    Raises:
        KeyError: When the account database has no such account.
    """
    if pwd is None:
        raise KeyError(account)
    entry = pwd.getpwnam(account)
    return entry.pw_uid, entry.pw_gid, entry.pw_dir


class CodeServerLinuxApplier:
    """Runs each instance as a systemd unit of its account."""

    os_name = "linux"

    def __init__(
        self,
        *,
        module_dir: str,
        record_dir: str,
        run=None,
        lookup_account=None,
        chown=None,
        systemd_dir: str = CODE_SERVER_SYSTEMD_DIR,
    ):
        """
        Args:
            module_dir: Where the release and the run directories are.
            record_dir: Where the records live, root-only.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            lookup_account: Returns an account's ``(uid, gid, home)`` or
                raises KeyError; None asks the account database.
            chown: Changes a file's owner as :func:`os.chown` does; None is
                that.
            systemd_dir: Where the template unit is written.
        """
        self.module_dir = module_dir
        self.record_dir = record_dir
        self._run = run if run is not None else run_command
        self._lookup_account = (
            lookup_account if lookup_account is not None else _account_entry
        )
        self._chown = chown if chown is not None else os.chown
        self._systemd_dir = systemd_dir

    def apply(self, config) -> list:
        """Run one unit per instance and stop the rest.

        Args:
            config: The validated :class:`CodeServerConfig`.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``account_unknown`` for an account the machine
                does not have, ``account_invalid`` for one whose socket path
                is too long, ``code_server_download_failed`` with no release.
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When systemd refuses.
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
            installer.check_socket_path(self.module_dir, instance.account, "linux")
        is_template_new = write_if_changed(
            os.path.join(self._systemd_dir, CODE_SERVER_UNIT_TEMPLATE),
            render_unit(self.module_dir),
            0o644,
        )
        if is_template_new:
            self._run(["systemctl", "daemon-reload"])
        notes = []
        wanted = {instance.account for instance in config.instances}
        for account in self.held_accounts():
            if account not in wanted:
                self._retire(account)
                notes.append(f"stopped code-server of {account}")
        os.makedirs(self.record_dir, mode=0o700, exist_ok=True)
        for instance in config.instances:
            uid, gid, _home = entries[instance.account]
            installer.prepare_run_dir(
                self.module_dir, instance.account, uid, gid, self._chown
            )
            unit = instance_unit(instance.account)
            is_new = not os.path.exists(self._enabled_path(instance.account))
            if is_new or is_template_new:
                self._run(["systemctl", "enable", unit])
                self._run(["systemctl", "restart", unit])
                with open(self._enabled_path(instance.account), "w"):
                    pass
                notes.append(f"started code-server of {instance.account}")
            else:
                self._run(["systemctl", "enable", "--now", unit])
        return notes

    def stop(self) -> None:
        """Stop every instance's unit; each stays enabled."""
        for account in self.held_accounts():
            self._run(["systemctl", "stop", instance_unit(account)], is_checked=False)

    def remove(self) -> None:
        """Stop and disable every instance, and delete the template."""
        for account in self.held_accounts():
            self._retire(account)
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(self._systemd_dir, CODE_SERVER_UNIT_TEMPLATE))
        self._run(["systemctl", "daemon-reload"], is_checked=False)

    def states(self, accounts: list) -> dict:
        """Whether each account's unit is active.

        Args:
            accounts: The accounts asked about.

        Returns:
            Account to ``{"is_running", "code"}``.
        """
        return {
            account: {
                "is_running": unit_state(instance_unit(account)) == "active",
                "code": "",
            }
            for account in accounts
        }

    def units(self) -> list:
        """Every instance's unit, for the journal."""
        return [instance_unit(account) for account in self.held_accounts()]

    def log_paths(self, accounts: list) -> list:
        """No log file: the journal keeps each unit's output.

        Args:
            accounts: The accounts asked about.

        Returns:
            Empty.
        """
        return []

    def held_accounts(self) -> list:
        """The accounts whose unit an apply enabled."""
        try:
            names = os.listdir(self.record_dir)
        except OSError:
            return []
        return sorted(
            name[: -len(ENABLED_SUFFIX)]
            for name in names
            if name.endswith(ENABLED_SUFFIX)
        )

    def _retire(self, account: str) -> None:
        self._run(
            ["systemctl", "disable", "--now", instance_unit(account)], is_checked=False
        )
        with contextlib.suppress(OSError):
            os.unlink(self._enabled_path(account))
        installer.remove_run_dir(self.module_dir, account)

    def _enabled_path(self, account: str) -> str:
        return os.path.join(self.record_dir, account + ENABLED_SUFFIX)
