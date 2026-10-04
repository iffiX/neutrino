"""CloudCLI on Linux: one systemd unit per account.

The template unit ``neutrino_cloudcli@.service`` runs the Node.js the agent
unpacked with the server script of the account's own app directory, as the
account its instance names, from a per-account environment file the
agent writes from scratch, root-only. Before an instance first runs, the
account installs CloudCLI into its app directory with that Node.js, and
the service's ``PATH`` holds that Node.js's directory and then the
``claude`` its login shell finds.

Not pure: writes under ``/etc``, runs commands as an account and drives
systemd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli import installer
from neutrino_agent.modules.cloudcli.constants import (
    CLOUDCLI_INSTALL_TIMEOUT_S,
    CLOUDCLI_LOOKUP_TIMEOUT_S,
    CLOUDCLI_SYSTEMD_DIR,
    CLOUDCLI_UNIT_PREFIX,
    CLOUDCLI_UNIT_TEMPLATE,
    CLOUDCLI_VERSION,
)
from neutrino_agent.modules.subprocess_run import run as run_command
from neutrino_agent.modules.subprocess_run import unit_state
from neutrino_agent.modules.vscode.installer import write_if_changed

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

ENVIRONMENT_SUFFIX = ".env"
# The variable the unit's command line reads the server script from.
SERVER_VARIABLE = "CLOUDCLI_SERVER"
# What an account's install runs under ``sh``: the app directory and the
# empty npm configuration made as the account, then npm.
INSTALL_SHELL = 'mkdir -p "$0" && : > "$0/.npmrc" && exec "$@"'
CHECK_SHELL = 'cd "$0" && exec "$@"'


def render_unit(node: str, etc_dir: str) -> str:
    """The template unit every instance runs from.

    Args:
        node: The Node.js interpreter.
        etc_dir: Where each account's environment file is.

    Returns:
        The unit file's text.
    """
    return (
        "[Unit]\n"
        "Description=CloudCLI for %i\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=%i\n"
        f"EnvironmentFile={etc_dir}/%i{ENVIRONMENT_SUFFIX}\n"
        "WorkingDirectory=~\n"
        f"ExecStart={node} ${{{SERVER_VARIABLE}}}\n"
        "Restart=always\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def render_environment(environment: dict) -> str:
    """One account's environment file, every value quoted.

    Args:
        environment: Name to value.

    Returns:
        The file's text.
    """
    lines = []
    for name, value in environment.items():
        quoted = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{name}="{quoted}"\n')
    return "".join(lines)


def instance_unit(account: str) -> str:
    """The unit one account's CloudCLI runs as.

    Args:
        account: The account.

    Returns:
        ``neutrino_cloudcli@<account>.service``.
    """
    return f"{CLOUDCLI_UNIT_PREFIX}{account}.service"


def _account_entry(account: str) -> tuple:
    """One account's uid, gid and home.

    Raises:
        KeyError: When the account database has no such account.
    """
    if pwd is None:
        raise KeyError(account)
    entry = pwd.getpwnam(account)
    return entry.pw_uid, entry.pw_gid, entry.pw_dir


class CloudcliLinuxApplier:
    """Runs each instance as a systemd unit of its account."""

    def __init__(
        self,
        *,
        module_dir: str,
        etc_dir: str,
        run=None,
        lookup_account=None,
        systemd_dir: str = CLOUDCLI_SYSTEMD_DIR,
        log=print,
    ):
        """
        Args:
            module_dir: Where Node.js is unpacked.
            etc_dir: Where the environment files and the records live.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
            lookup_account: Returns an account's ``(uid, gid, home)`` or
                raises KeyError; None asks the account database.
            systemd_dir: Where the template unit is written.
            log: Callable used for progress messages.
        """
        self.module_dir = module_dir
        self.record_dir = etc_dir
        self._run = run if run is not None else run_command
        self._lookup_account = (
            lookup_account if lookup_account is not None else _account_entry
        )
        self._etc_dir = etc_dir
        self._systemd_dir = systemd_dir
        self._log = log
        # The account whose install the running apply waits on, if any.
        self.installing: frozenset = frozenset()

    @property
    def node(self) -> str:
        """The Node.js interpreter, empty when none is unpacked."""
        directory = installer.node_dir(self.module_dir)
        return installer.node_path(directory, "linux") if directory else ""

    def apply(self, config, upstream_ports: dict) -> list:
        """Install CloudCLI for each account, run one unit per instance, stop the rest.

        Args:
            config: The validated :class:`CloudcliConfig`.
            upstream_ports: Account to the loopback port its CloudCLI
                listens on.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``account_unknown`` for an account the machine
                does not have, ``cloudcli_claude_missing`` for one whose
                login shell finds no ``claude``,
                ``cloudcli_node_download_failed`` with no Node.js, and an
                install's ``cloudcli_npm_install_failed`` or
                ``cloudcli_native_module_failed``.
            OSError: When a file cannot be written.
            subprocess.CalledProcessError: When systemd refuses.
        """
        node = self.node
        if not node:
            raise ModuleApplyError("cloudcli_node_download_failed", {})
        homes = {}
        for instance in config.instances:
            try:
                homes[instance.account] = self._lookup_account(instance.account)[2]
            except KeyError:
                raise ModuleApplyError(
                    "account_unknown", {"account": instance.account}
                ) from None
        claudes = {}
        for instance in config.instances:
            claudes[instance.account] = self._find_claude(instance.account)
        notes = []
        for instance in config.instances:
            if self._install_app(
                instance.account,
                homes[instance.account],
                node,
                registry=config.npm_registry,
            ):
                notes.append(f"installed CloudCLI for {instance.account}")
        os.makedirs(self._etc_dir, mode=0o700, exist_ok=True)
        is_template_new = write_if_changed(
            os.path.join(self._systemd_dir, CLOUDCLI_UNIT_TEMPLATE),
            render_unit(node, self._etc_dir),
            0o644,
        )
        if is_template_new:
            self._run(["systemctl", "daemon-reload"])
        wanted = {instance.account for instance in config.instances}
        for account in self._held_accounts():
            if account not in wanted:
                self._retire(account)
                notes.append(f"stopped CloudCLI of {account}")
        for instance in config.instances:
            home = homes[instance.account]
            environment = installer.service_environment(
                config,
                instance,
                upstream_port=upstream_ports[instance.account],
                home=home,
                os_name="linux",
                node_dir=os.path.dirname(node),
                claude_path=claudes[instance.account],
            )
            environment[SERVER_VARIABLE] = installer.server_path(
                installer.app_dir(home, "linux")
            )
            is_changed = write_if_changed(
                self._environment_path(instance.account),
                render_environment(environment),
                0o600,
            )
            unit = instance_unit(instance.account)
            if is_changed or is_template_new:
                self._run(["systemctl", "enable", unit])
                self._run(["systemctl", "restart", unit])
                notes.append(f"started CloudCLI of {instance.account}")
            else:
                self._run(["systemctl", "enable", "--now", unit])
        return notes

    def stop(self) -> None:
        """Stop every instance's unit; each stays enabled."""
        for account in self._held_accounts():
            self._run(["systemctl", "stop", instance_unit(account)], is_checked=False)

    def remove(self) -> None:
        """Stop and disable every instance, and delete its file and the template."""
        for account in self._held_accounts():
            self._retire(account)
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(self._systemd_dir, CLOUDCLI_UNIT_TEMPLATE))
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
        return [instance_unit(account) for account in self._held_accounts()]

    def log_paths(self, accounts: list) -> list:
        """No log file: the journal keeps each unit's output.

        Args:
            accounts: The accounts asked about.

        Returns:
            Empty.
        """
        return []

    def _find_claude(self, account: str) -> str:
        """The ``claude`` the account's login shell finds, or ``cloudcli_claude_missing``."""
        result = self._run(
            ["runuser", "-l", account, "-c", "command -v claude"],
            is_checked=False,
            timeout_s=CLOUDCLI_LOOKUP_TIMEOUT_S,
        )
        found = installer.claude_of(result.stdout) if result.is_success else ""
        if not found:
            raise ModuleApplyError("cloudcli_claude_missing", {"account": account})
        return found

    def _install_app(
        self, account: str, home: str, node: str, *, registry: str = ""
    ) -> bool:
        """Install CloudCLI into the account's app directory unless it is there."""
        app = installer.app_dir(home, "linux")
        if installer.installed_version(app) == CLOUDCLI_VERSION:
            return False
        self.installing = frozenset({account})
        try:
            node_bin = os.path.dirname(node)
            environment = {
                "HOME": home,
                "USER": account,
                "LOGNAME": account,
                "PATH": f"{node_bin}:/usr/bin:/bin",
                **installer.npm_environment(app, registry=registry),
            }
            prefix = ["runuser", "-u", account, "--", "env", "-i"] + [
                f"{name}={value}" for name, value in environment.items()
            ]
            npm = installer.npm_path(os.path.dirname(node_bin), "linux")
            self._log(f"cloudcli: installing CloudCLI for {account}")
            result = self._run(
                prefix
                + ["sh", "-c", INSTALL_SHELL, app, node, npm]
                + installer.npm_arguments(app),
                is_checked=False,
                timeout_s=CLOUDCLI_INSTALL_TIMEOUT_S,
            )
            if not result.is_success:
                output = (result.stdout + "\n" + result.stderr).strip()
                self._log(f"cloudcli: npm for {account}: {output[-2000:]}")
                raise installer.npm_failure(output, account)
            check = self._run(
                prefix
                + [
                    "sh",
                    "-c",
                    CHECK_SHELL,
                    app,
                    node,
                    "-e",
                    installer.NATIVE_CHECK_SCRIPT,
                ],
                is_checked=False,
                timeout_s=CLOUDCLI_LOOKUP_TIMEOUT_S,
            )
            if check.exit_code == installer.NATIVE_CHECK_EXIT:
                raise ModuleApplyError(
                    "cloudcli_native_module_failed",
                    {"account": account, "module": check.stdout.strip()},
                )
            return True
        finally:
            self.installing = frozenset()

    def _held_accounts(self) -> list:
        """The accounts an environment file names an instance for."""
        try:
            names = os.listdir(self._etc_dir)
        except OSError:
            return []
        return sorted(
            name[: -len(ENVIRONMENT_SUFFIX)]
            for name in names
            if name.endswith(ENVIRONMENT_SUFFIX)
        )

    def _retire(self, account: str) -> None:
        self._run(
            ["systemctl", "disable", "--now", instance_unit(account)], is_checked=False
        )
        with contextlib.suppress(OSError):
            os.unlink(self._environment_path(account))

    def _environment_path(self, account: str) -> str:
        return os.path.join(self._etc_dir, account + ENVIRONMENT_SUFFIX)
