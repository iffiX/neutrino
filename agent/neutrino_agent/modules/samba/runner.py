"""The file share as a module: package, configuration, commands, details.

The package comes from the distribution, so orders ride the system-package
runner. What makes the package this hub's file share, the rendered
``smb.conf``, the accounts and the share directories, is applied here from
the hub's desired configuration.

Not pure: drives Samba through its applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.base import command_outcome
from neutrino_agent.modules.samba.applier import (
    SambaConfigApplier,
    SambaStatusReader,
    SambaUserManager,
    ensure_share_group,
    testparm,
)
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_COMMAND_SET_PASSWORD,
    samba_unit,
)
from neutrino_agent.modules.samba.renderer import SambaConfigRenderer
from neutrino_agent.modules.subprocess_run import command_detail, unit_state
from neutrino_agent.modules.system_package import SystemPackageModuleRunner
from neutrino_agent.platforms.detect import platform_tuple


class SambaModuleRunner(SystemPackageModuleRunner):
    """Installs Samba by package and keeps it serving what the hub says."""

    name = "samba"

    def __init__(self, *, platform, log=print, publish=None, family: str = ""):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            family: The distribution family; detected when empty.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._unit = samba_unit(family or platform_tuple().get("family", ""))
        self._config: "SambaConfig | None" = None

    @property
    def unit(self) -> str:
        """The unit this machine's Samba runs as."""
        return self._unit

    def install(self, resolved: dict) -> None:
        """Install the package and the group every share account joins.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the package manager refuses.
            PlatformUnsupportedError: If this platform installs nothing.
        """
        super().install(resolved)
        ensure_share_group()

    def validate(self, config: dict) -> None:
        """Parse, check and render a configuration, then have Samba check it.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        parsed = SambaConfig.from_dict(config)
        parsed.validate()
        testparm(SambaConfigRenderer(config=parsed).render())

    def apply(self, config: dict) -> None:
        """Render the configuration, converge accounts, and load it.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or Samba
                will not take it.
        """
        parsed = SambaConfig.from_dict(config)
        parsed.validate()
        ensure_share_group()
        rendered = SambaConfigRenderer(config=parsed).render()
        try:
            note = SambaConfigApplier(unit=self._unit).apply(rendered, config=parsed)
            changes = SambaUserManager().converge(parsed.users)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        self._config = parsed
        self._log("samba: " + "; ".join([note] + changes))

    def stop(self) -> None:
        """Take the server down, leaving the shares' files in place."""
        SambaConfigApplier(unit=self._unit).stop()

    def details(self, resolved: dict) -> dict:
        """Who is connected, how full each share is, and each user's state.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"is_active", "sessions", "disk_usage", "users"}``.
        """
        config = self._config or SambaConfig()
        reader = SambaStatusReader()
        try:
            users = SambaUserManager().survey(config.users)
        except (OSError, subprocess.SubprocessError):
            users = []
        return {
            "is_active": unit_state(self._unit) == "active",
            "sessions": reader.sessions(),
            "disk_usage": reader.disk_usage(config),
            "users": [vars(state) for state in users],
        }

    def command(self, action: str, args: dict, on_line=None) -> dict:
        """Run one of the file share's commands.

        Args:
            action: ``samba_set_password``.
            args: ``{"name", "password"}``.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        if action != SAMBA_COMMAND_SET_PASSWORD:
            return super().command(action, args, on_line)
        name = str(args.get("name", ""))
        config = self._config or SambaConfig()
        if name not in config.users:
            return command_outcome(1, "user_unknown", {"user": name})
        try:
            SambaUserManager().set_password(name, str(args.get("password", "")))
        except (OSError, subprocess.SubprocessError) as error:
            return command_outcome(
                1, "command_failed", {"detail": command_detail(error)[:500]}
            )
        return command_outcome(0, output=f"password set for {name}\n")
