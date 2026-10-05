"""The git server as a module: binary, configuration, verbs, details.

The binary is a hub-cached release that comes down a package stream. On
Linux git comes from the distribution; on macOS and Windows it is the
machine's own, and an install or an apply refuses ``gitea_git_missing``
while there is none. What makes the binary this hub's git server, the
rendered ``app.ini`` and the first administrator, is applied here through
the system's applier: a systemd unit on Linux, a LaunchDaemon of a hidden
account on macOS, a LocalSystem service on Windows. Only the hub's own
instance is served: one somebody installed by hand reports as running on
its port and nothing more.

Not pure: drives Gitea through its applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import subprocess
import time

from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.base import ModuleRunner, command_outcome
from neutrino_agent.modules.gitea.applier import (
    GiteaAdminManager,
    GiteaConfigApplier,
    GiteaInstaller,
    read_listen_port,
)
from neutrino_agent.modules.gitea.config import ADMIN_NAME_PATTERN, GiteaConfig
from neutrino_agent.modules.gitea.constants import (
    GITEA_BINARY_PATH,
    GITEA_CODE_GIT_MISSING,
    GITEA_COMMAND_ADMIN,
    GITEA_COMMAND_PASSWORD,
    GITEA_SURVEY_TTL_S,
    GITEA_UNIT,
)
from neutrino_agent.modules.gitea.darwin_applier import GiteaDarwinApplier
from neutrino_agent.modules.gitea.renderer import GiteaConfigRenderer, GiteaLayout
from neutrino_agent.modules.gitea.windows_applier import GiteaWindowsApplier
from neutrino_agent.modules.log_tail import file_tail
from neutrino_agent.modules.subprocess_run import command_detail, unit_state


class GiteaLinuxApplier:
    """The Linux server: the ``git`` account, the systemd unit, ``runuser``."""

    is_git_required = False

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
        """Install the binary, its account, its directories and its unit."""
        GiteaInstaller().install(binary_path)

    def uninstall(self) -> None:
        """Take the unit, the binary and ``app.ini`` off; keep the data."""
        GiteaInstaller().uninstall()

    def apply(self, rendered: str, *, git_path: str) -> str:
        """Install ``app.ini`` and run the unit on it."""
        return GiteaConfigApplier().apply(rendered)

    def stop(self) -> None:
        """Stop the unit."""
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

    kind = "gitea"
    name = "gitea"

    def __init__(self, *, platform, log=print, publish=None, applier=None):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            applier: The system's applier; None picks the platform's own.

        Raises:
            PlatformUnsupportedError: On a system with no applier.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._applier = applier if applier is not None else gitea_applier_for(platform)
        self._config: "GiteaConfig | None" = None
        self._survey = None
        self._surveyed_at = 0.0

    def verify(self, resolved: dict) -> bool:
        """Whether the binary is on the machine.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when the binary exists.
        """
        return os.path.isfile(self._applier.binary_path)

    def install(self, resolved: dict, package_path: str) -> None:
        """Install git, the binary the hub handed down, its user and its unit.

        Args:
            resolved: The module as the hub resolved it.
            package_path: The release binary on local disk.

        Raises:
            ModuleApplyError: ``gitea_git_missing`` on macOS or Windows with
                no git; ``user_create_failed`` when macOS will not make the
                server's account.
            InstallError: If the package manager refuses.
            subprocess.CalledProcessError: If a setup step refuses.
        """
        self._git_path()
        entry = resolved.get("entry") or {}
        packages = [str(name) for name in entry.get("packages") or []]
        if packages:
            output = self._platform.install_system_packages(packages)
            if output.strip():
                self._log(output.strip())
        self._applier.install(package_path)
        self._survey = None

    def uninstall(self, resolved: dict) -> None:
        """Take the service, the binary and the configuration off; keep the
        data and the account.

        Args:
            resolved: The module as the hub resolved it.
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
        GiteaConfigRenderer(config=parsed, layout=self._applier.layout("")).render()

    def apply(self, config: dict) -> None:
        """Render ``app.ini`` and run the server on it.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused, the
                machine has no git (``gitea_git_missing``), or the server
                will not come up.
        """
        parsed = GiteaConfig.from_dict(config)
        parsed.validate()
        git_path = self._git_path()
        rendered = GiteaConfigRenderer(
            config=parsed, layout=self._applier.layout(git_path)
        ).render()
        try:
            note = self._applier.apply(rendered, git_path=git_path)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        self._config = parsed
        self._log(f"gitea: {note}")

    def stop(self) -> None:
        """Take the server down, leaving the repositories in place."""
        self._applier.stop()

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

    def details(self, resolved: dict) -> dict:
        """Whether it runs, where it answers, and who administers it.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"is_running", "port", "url", "version", "admins"}``; the
            port is the held configuration's, else the installed
            ``app.ini``'s.
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
            "url": config.derived_root_url if config is not None else "",
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
