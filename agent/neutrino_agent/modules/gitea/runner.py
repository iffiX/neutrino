"""The git server as a module: binary, configuration, commands, details.

The binary is a hub-cached release the order hands down; git itself comes
from the distribution. What makes the binary this hub's git server, the
rendered ``app.ini`` and the first administrator, is applied here.

Not pure: drives Gitea through its applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.base import ModuleRunner, command_outcome
from neutrino_agent.modules.gitea.applier import (
    GiteaAdminManager,
    GiteaConfigApplier,
    GiteaInstaller,
)
from neutrino_agent.modules.gitea.config import ADMIN_NAME_PATTERN, GiteaConfig
from neutrino_agent.modules.gitea.constants import (
    GITEA_BINARY_PATH,
    GITEA_COMMAND_ADMIN,
    GITEA_COMMAND_PASSWORD,
    GITEA_UNIT,
)
from neutrino_agent.modules.gitea.renderer import GiteaConfigRenderer
from neutrino_agent.modules.subprocess_run import command_detail, unit_state


class GiteaModuleRunner(ModuleRunner):
    """Installs Gitea from the hub's bytes and keeps it serving what the hub says."""

    kind = "gitea"
    name = "gitea"

    def __init__(self, *, platform, log=print, publish=None):
        super().__init__(platform=platform, log=log, publish=publish)
        self._config: "GiteaConfig | None" = None

    def verify(self, resolved: dict) -> bool:
        """Whether the binary is on the machine.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when the binary exists.
        """
        return os.path.isfile(GITEA_BINARY_PATH)

    def install(self, resolved: dict, package_path: str) -> None:
        """Install git, the binary the hub handed down, its user and its unit.

        Args:
            resolved: The module as the hub resolved it.
            package_path: The release binary on local disk.

        Raises:
            InstallError: If the package manager refuses.
            subprocess.CalledProcessError: If a setup step refuses.
        """
        entry = resolved.get("entry") or {}
        packages = [str(name) for name in entry.get("packages") or []]
        if packages:
            output = self._platform.install_system_packages(packages)
            if output.strip():
                self._log(output.strip())
        GiteaInstaller().install(package_path)

    def uninstall(self, resolved: dict) -> None:
        """Take the unit, the binary and the configuration off; keep the data.

        Args:
            resolved: The module as the hub resolved it.
        """
        GiteaInstaller().uninstall()

    def validate(self, config: dict) -> None:
        """Parse, check and render a configuration.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        parsed = GiteaConfig.from_dict(config)
        parsed.validate()
        GiteaConfigRenderer(config=parsed).render()

    def apply(self, config: dict) -> None:
        """Render ``app.ini`` and run the server on it.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or the
                server will not come up.
        """
        parsed = GiteaConfig.from_dict(config)
        parsed.validate()
        rendered = GiteaConfigRenderer(config=parsed).render()
        try:
            note = GiteaConfigApplier().apply(rendered)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        self._config = parsed
        self._log(f"gitea: {note}")

    def stop(self) -> None:
        """Take the server down, leaving the repositories in place."""
        GiteaConfigApplier().stop()

    def details(self, resolved: dict) -> dict:
        """Whether it runs, where it answers, and who administers it.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"is_running", "url", "version", "admins"}``.
        """
        try:
            state = GiteaAdminManager().survey()
        except (OSError, subprocess.SubprocessError):
            state = None
        config = self._config
        return {
            "is_running": unit_state(GITEA_UNIT) == "active",
            "url": config.derived_root_url if config is not None else "",
            "version": state.version if state is not None else "",
            "admins": list(state.admin_usernames) if state is not None else [],
        }

    def command(self, action: str, args: dict, on_line=None) -> dict:
        """Run one of the git server's commands.

        Args:
            action: ``gitea_admin`` or ``gitea_password``.
            args: ``{"username", "password", "email"}``.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        username = str(args.get("username", ""))
        password = str(args.get("password", ""))
        if action == GITEA_COMMAND_ADMIN:
            if not ADMIN_NAME_PATTERN.match(username):
                return command_outcome(1, "username_invalid", {"username": username})
            if GiteaAdminManager().survey().has_admin:
                return command_outcome(1, "admin_exists")
            return self._run_admin(
                username,
                GiteaAdminManager().create_admin,
                username=username,
                password=password,
                email=str(args.get("email", "")),
            )
        if action == GITEA_COMMAND_PASSWORD:
            if username not in GiteaAdminManager().survey().admin_usernames:
                return command_outcome(1, "admin_unknown", {"username": username})
            return self._run_admin(
                username,
                GiteaAdminManager().change_password,
                username=username,
                password=password,
            )
        return super().command(action, args, on_line)

    def _run_admin(self, subject: str, step, **fields) -> dict:
        try:
            step(**fields)
        except (OSError, subprocess.SubprocessError) as error:
            return command_outcome(
                1, "command_failed", {"detail": command_detail(error)[:500]}
            )
        return command_outcome(0, output=f"{subject}\n")
