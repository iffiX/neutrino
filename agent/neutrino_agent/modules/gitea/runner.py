"""The git server as a module: binary, configuration, verbs, details.

The binary is a hub-cached release that comes down a package stream. On
Linux git comes from the distribution; on macOS and Windows it is the
machine's own, and an install or an apply refuses ``gitea_git_missing``
while there is none. What makes the binary this hub's git server, the
rendered ``app.ini`` and the first administrator, is applied here through
the system's applier: a systemd unit on Linux, a LaunchDaemon of a hidden
account on macOS, a LocalSystem service on Windows. Gitea's own SSH server
listens on loopback at a port the agent takes from 2222 up at the first
apply and keeps in the module's root-only record. Only the hub's own
instance is served: one somebody installed by hand reports as running on
its port and nothing more.

Not pure: drives Gitea through its applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import dataclasses
import functools
import os
import subprocess
import time

from neutrino_agent.constants import (
    AGENT_STEP_ACCOUNT,
    AGENT_STEP_CONFIGURE,
    AGENT_STEP_UNINSTALL,
    AGENT_WANT_STOPPED,
)
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.shared.base import (
    ModuleRunner,
    ModuleStep,
    command_outcome,
)
from neutrino_agent.modules.gitea.applier import (
    GiteaAdminManager,
    GiteaConfigApplier,
    GiteaInstaller,
    read_listen_port,
    read_root_url,
)
from neutrino_agent.modules.gitea.config import ADMIN_NAME_PATTERN, GiteaConfig
from neutrino_agent.modules.gitea.constants import (
    GITEA_BINARY_PATH,
    GITEA_CODE_GIT_MISSING,
    GITEA_COMMAND_ADMIN,
    GITEA_COMMAND_PASSWORD,
    GITEA_RECORD_FIELDS,
    GITEA_RECORD_NAME,
    GITEA_SSH_BASE_PORT,
    GITEA_SURVEY_TTL_S,
    GITEA_UNIT,
    GITEA_USER,
)
from neutrino_agent.modules.gitea.darwin_applier import GiteaDarwinApplier
from neutrino_agent.modules.gitea.renderer import GiteaConfigRenderer, GiteaLayout
from neutrino_agent.modules.gitea.windows_applier import GiteaWindowsApplier
from neutrino_agent.modules.shared.log_tail import file_tail
from neutrino_agent.modules.shared.loopback_port import is_port_free, pick_port
from neutrino_agent.modules.shared.record_store import InstanceRecordStore
from neutrino_agent.modules.shared.step_locks import SYSTEM_ACCOUNTS_LOCKS
from neutrino_agent.modules.shared.subprocess_run import command_detail, unit_state


class GiteaLinuxApplier:
    """The Linux server: the ``git`` account, the systemd unit, ``runuser``.

    Attributes:
        account: The system account the server runs as.
    """

    is_git_required = False
    account = GITEA_USER

    @property
    def binary_path(self) -> str:
        """Where the binary is installed."""
        return GITEA_BINARY_PATH

    def find_git(self) -> str:
        """Empty: the distribution's git is on ``PATH``."""
        return ""

    def layout(self, git_path: str) -> GiteaLayout:
        """The Linux layout, whatever git was found."""
        return GiteaLayout()

    def install(self, binary_path: str) -> None:
        """Install the binary and its unit."""
        GiteaInstaller().install(binary_path)

    def ensure_account(self) -> None:
        """Make the ``git`` account when it is missing, and its directories."""
        GiteaInstaller().ensure_account()

    def uninstall(self) -> None:
        """Take the unit, the binary and ``app.ini`` off; keep the data."""
        GiteaInstaller().uninstall()

    def apply(self, rendered: str, *, git_path: str, is_started: bool = True) -> str:
        """Install ``app.ini`` and run the unit on it; with ``is_started`` false, write it alone."""
        return GiteaConfigApplier().apply(rendered, is_started=is_started)

    def stop(self) -> None:
        """Stop the unit and disable it."""
        GiteaConfigApplier().stop()

    def is_active(self) -> bool:
        """Whether the unit is active."""
        return unit_state(GITEA_UNIT) == "active"

    def survey(self):
        """The binary, its version and the administrators."""
        return GiteaAdminManager().survey()

    def create_admin(self, **fields) -> None:
        """Create an administrator through the CLI."""
        GiteaAdminManager().create_admin(**fields)

    def change_password(self, **fields) -> None:
        """Reset an administrator's password through the CLI."""
        GiteaAdminManager().change_password(**fields)

    def read_listen_port(self) -> int:
        """The port ``/etc/gitea/app.ini`` names."""
        return read_listen_port()

    def read_root_url(self) -> str:
        """The root URL ``/etc/gitea/app.ini`` names."""
        return read_root_url()

    def journal_units(self) -> list:
        """The unit, whose journal is the server's log."""
        return [GITEA_UNIT]

    def log_path(self) -> str:
        """Empty: the journal holds the log."""
        return ""


def gitea_applier_for(platform):
    """The applier that runs the git server on this system.

    Args:
        platform: The machine's platform.

    Returns:
        The Linux, macOS or Windows applier.

    Raises:
        PlatformUnsupportedError: On a system with none.
    """
    if platform.os_name == "linux":
        return GiteaLinuxApplier()
    if platform.os_name == "darwin":
        return GiteaDarwinApplier(state_dir=platform.agent_var_dir())
    if platform.os_name == "windows":
        return GiteaWindowsApplier(state_dir=platform.agent_var_dir())
    raise PlatformUnsupportedError("no git server here")


class GiteaModuleRunner(ModuleRunner):
    """Installs Gitea from the hub's bytes and keeps it serving what the hub says."""

    runner = "gitea"
    name = "gitea"

    def __init__(
        self,
        *,
        platform,
        log=print,
        publish=None,
        applier=None,
        record_dir: str = "",
        is_port_free=is_port_free,
    ):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            applier: The system's applier; None picks the platform's own.
            record_dir: Where the module's record lives; empty is
                ``gitea`` under ``platform.agent_var_dir()``.
            is_port_free: Answers whether a loopback port can be bound now.

        Raises:
            PlatformUnsupportedError: On a system with no applier.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._applier = applier if applier is not None else gitea_applier_for(platform)
        self._records = InstanceRecordStore(
            directory=record_dir
            or os.path.join(platform.agent_var_dir(), GITEA_RECORD_NAME),
            fields=GITEA_RECORD_FIELDS,
        )
        self._is_port_free = is_port_free
        self._config: "GiteaConfig | None" = None
        self._survey = None
        self._surveyed_at = 0.0

    def verify(self, recipe: dict) -> bool:
        """Whether the binary is on the machine.

        Args:
            recipe: The module's recipe.

        Returns:
            True when the binary exists.
        """
        return os.path.isfile(self._applier.binary_path)

    def install_artifact(self, recipe: dict, artifact: dict, path: str) -> None:
        """Put the release binary the hub handed down in place, with its user and its unit.

        Args:
            recipe: The module's recipe.
            artifact: The ``binary`` artifact.
            path: The release binary on local disk.

        Raises:
            ModuleApplyError: ``gitea_git_missing`` on macOS or Windows with
                no git; ``user_create_failed`` when macOS will not make the
                server's account.
            subprocess.CalledProcessError: If a setup step refuses.
            OSError: If a file cannot be written.
        """
        self._git_path()
        self._applier.install(path)
        self._survey = None

    def binary_path(self, recipe: dict, artifact: dict) -> str:
        """Where the release binary is kept, which a version switch replaces.

        Args:
            recipe: The module's recipe.
            artifact: The ``binary`` artifact.

        Returns:
            The program's path on this system.
        """
        return self._applier.binary_path

    def uninstall(self, recipe: dict) -> None:
        """Take the service, the binary and the configuration off; keep the
        data and the account.

        Args:
            recipe: The module's recipe.
        """
        self._applier.uninstall()

    def validate(self, config: dict) -> None:
        """Parse, check and render a configuration.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        parsed = GiteaConfig.from_dict(config)
        parsed.validate()
        GiteaConfigRenderer(
            config=parsed,
            layout=self._applier.layout(""),
            ssh_listen_port=self._kept_ssh_port() or GITEA_SSH_BASE_PORT,
        ).render()

    def apply(self, config: dict) -> None:
        """Render ``app.ini`` and run the server on it.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused, the
                machine has no git (``gitea_git_missing``), no port from
                2222 up is free for its SSH server, or the server will not
                come up.
        """
        self._apply(config, is_started=True)

    def apply_stopped(self, config: dict) -> None:
        """Render ``app.ini`` under ``stopped``, the server neither enabled nor started.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: As :meth:`apply` does.
        """
        self._apply(config, is_started=False)

    def _apply(self, config: dict, *, is_started: bool) -> None:
        """Render and write ``app.ini``. With ``is_started`` false the server is left as it is."""
        parsed = GiteaConfig.from_dict(config)
        parsed.validate()
        git_path = self._git_path()
        rendered = GiteaConfigRenderer(
            config=parsed,
            layout=self._applier.layout(git_path),
            ssh_listen_port=self._take_ssh_port(),
        ).render()
        try:
            note = self._applier.apply(
                rendered, git_path=git_path, is_started=is_started
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        self._config = parsed
        self._log(f"gitea: {note}")

    def stop(self) -> None:
        """Take the server down and keep it from starting at boot, leaving the repositories in place."""
        self._applier.stop()

    def step_locks(self, step: str) -> tuple:
        """``system_accounts`` for ``account`` and ``uninstall``.

        Args:
            step: The step's name.

        Returns:
            The step locks the module adds to the step.
        """
        if step in (AGENT_STEP_ACCOUNT, AGENT_STEP_UNINSTALL):
            return SYSTEM_ACCOUNTS_LOCKS
        return ()

    def configure_steps(self, config: dict, want: str, steps: list) -> list:
        """The server's ``account {account}`` before the core's steps, where it runs as an account of its own.

        Under ``stopped`` the ``configure`` writes ``app.ini`` and starts nothing.

        Args:
            config: The configuration the task's entry carries.
            want: ``running`` or ``stopped``.
            steps: ``configure``, then ``start`` or ``stop``, as the core
                plans them.

        Returns:
            The steps; no ``account`` step on Windows, where the server runs
            as LocalSystem.
        """
        if want == AGENT_WANT_STOPPED:
            steps = [
                (
                    dataclasses.replace(
                        step,
                        run=functools.partial(self._run_apply_stopped, dict(config)),
                    )
                    if step.name == AGENT_STEP_CONFIGURE
                    else step
                )
                for step in steps
            ]
        account = self._applier.account
        if not account:
            return steps
        return [
            ModuleStep(
                name=AGENT_STEP_ACCOUNT,
                params={"account": account},
                run=self._run_account,
            ),
            *steps,
        ]

    def is_active(self) -> bool:
        """Whether the git server's unit, job or service runs."""
        return self._applier.is_active()

    def journal_units(self) -> list:
        """The git server's unit on Linux; none elsewhere."""
        return self._applier.journal_units()

    def journal_text(self, lines: int) -> list:
        """The unit's journal on Linux; elsewhere the end of the server's
        own log, then the agent's lines that name the module.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first.
        """
        path = self._applier.log_path()
        if not path:
            return super().journal_text(lines)
        own = self._read_source(path, lambda: file_tail(path, lines))
        return self._with_agent_lines(own, lines)

    def details(self, recipe: dict) -> dict:
        """Whether it runs, where it answers, and who administers it.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"is_running", "port", "ssh_listen_port", "url", "version",
            "admins"}``; the port is the held configuration's, else the
            installed ``app.ini``'s, the url likewise, and
            ``ssh_listen_port`` the one the agent took for Gitea's own SSH
            server, 0 before the first apply.
        """
        state = self._surveyed()
        config = self._config
        return {
            "is_running": self._applier.is_active(),
            "port": (
                config.listen_port
                if config is not None
                else self._applier.read_listen_port()
            ),
            "ssh_listen_port": self._kept_ssh_port(),
            "url": (
                config.derived_root_url
                if config is not None
                else self._applier.read_root_url()
            ),
            "version": state.version if state is not None else "",
            "admins": list(state.admin_usernames) if state is not None else [],
        }

    def command(self, verb: str, args: dict, on_line=None) -> dict:
        """Run one of the git server's verbs.

        Args:
            verb: ``admin``, ``password``, or ``validate``.
            args: ``{"username", "password", "email"}``.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        username = str(args.get("username", ""))
        password = str(args.get("password", ""))
        if verb == GITEA_COMMAND_ADMIN:
            if not ADMIN_NAME_PATTERN.match(username):
                return command_outcome(1, "username_invalid", {"username": username})
            if self._applier.survey().has_admin:
                return command_outcome(1, "admin_exists")
            return self._run_admin(
                username,
                self._applier.create_admin,
                username=username,
                password=password,
                email=str(args.get("email", "")),
            )
        if verb == GITEA_COMMAND_PASSWORD:
            if username not in self._applier.survey().admin_usernames:
                return command_outcome(1, "admin_unknown", {"username": username})
            return self._run_admin(
                username,
                self._applier.change_password,
                username=username,
                password=password,
            )
        return super().command(verb, args, on_line)

    def _run_admin(self, subject: str, step, **fields) -> dict:
        try:
            step(**fields)
        except (OSError, subprocess.SubprocessError, KeyError) as error:
            return command_outcome(
                1, "command_failed", {"detail": command_detail(error)[:500]}
            )
        self._survey = None
        return command_outcome(0, output=f"{subject}\n")

    def _run_apply_stopped(self, config: dict, context) -> None:
        """The ``configure`` step under ``stopped``."""
        self.apply_stopped(config)

    def _run_account(self, context) -> None:
        """The ``account`` step: the server's account made when it is missing, and its directories."""
        self._applier.ensure_account()

    def _kept_ssh_port(self) -> int:
        """The port the record keeps for Gitea's own SSH server, 0 when none."""
        record = self._records.read(GITEA_RECORD_NAME)
        try:
            return int(record.get("ssh_listen_port") or 0)
        except (TypeError, ValueError):
            return 0

    def _take_ssh_port(self) -> int:
        """The port Gitea's own SSH server listens on: the kept one, else the first free from 2222.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` when no port is free
                or the record cannot be written.
        """
        kept = self._kept_ssh_port()
        if kept:
            return kept
        try:
            port = pick_port(GITEA_SSH_BASE_PORT, is_free=self._is_port_free)
            self._records.write({"account": GITEA_RECORD_NAME, "ssh_listen_port": port})
        except OSError as error:
            raise ModuleApplyError("apply_failed", {"detail": str(error)[:500]})
        self._log(f"gitea: its SSH server takes port {port}")
        return port

    def _git_path(self) -> str:
        """The git the server runs, where the module needs to find one.

        Returns:
            The git found; empty on Linux, whose git is on ``PATH``.

        Raises:
            ModuleApplyError: ``gitea_git_missing`` when the system needs
                one and has none.
        """
        if not self._applier.is_git_required:
            return ""
        git_path = self._applier.find_git()
        if not git_path:
            raise ModuleApplyError(GITEA_CODE_GIT_MISSING)
        return git_path

    def _surveyed(self):
        """The version and the administrators, read at most once a minute.

        Returns:
            The last survey while it stands, a fresh one past that, None
            when the read fails.
        """
        now = time.monotonic()
        if self._survey is not None and now - self._surveyed_at < GITEA_SURVEY_TTL_S:
            return self._survey
        try:
            self._survey = self._applier.survey()
        except (OSError, subprocess.SubprocessError):
            self._survey = None
            return None
        self._surveyed_at = now
        return self._survey
