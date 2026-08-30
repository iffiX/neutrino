"""Inspecting and controlling systemd units.

The panel's Services tab and the installer both drive systemd through this one
class, so the set of units either can touch is exactly
:data:`neutrino_hub.system.constants.SYSTEM_MANAGED_UNITS`.
"""

from dataclasses import dataclass

from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.system.constants import SYSTEM_MANAGED_UNITS

ALLOWED_ACTIONS = ("start", "stop", "restart", "enable", "disable")


@dataclass
class ServiceStatus:
    """State of one managed unit.

    Attributes:
        name: Panel-facing name, for example ``xray``.
        unit: The systemd unit behind it.
        is_installed: Whether systemd knows the unit at all.
        is_active: Whether it is running now.
        is_enabled: Whether it starts at boot.
    """

    name: str
    unit: str
    is_installed: bool
    is_active: bool
    is_enabled: bool


class SystemdServiceController:
    """Reads and changes the state of the managed units."""

    def status(self, name: str) -> ServiceStatus:
        """Read one unit's state.

        Args:
            name: Panel-facing service name.

        Returns:
            The unit's current state.

        Raises:
            KeyError: If the name is not a managed unit.
        """
        unit = self._unit_for(name)
        active = run(["systemctl", "is-active", unit], is_checked=False)
        enabled = run(["systemctl", "is-enabled", unit], is_checked=False)
        # systemd reports an unknown unit as "not-found" on stdout from
        # is-enabled, while is-active just says "inactive", so a missing unit is
        # indistinguishable from a stopped one unless both streams are read.
        enabled_output = (enabled.stdout + enabled.stderr).strip()
        is_installed = "not-found" not in enabled_output
        return ServiceStatus(
            name=name,
            unit=unit,
            is_installed=is_installed,
            is_active=active.stdout.strip() == "active",
            is_enabled=enabled.stdout.strip()
            in ("enabled", "enabled-runtime", "static"),
        )

    def status_all(self) -> list[ServiceStatus]:
        """Read every managed unit's state.

        Returns:
            One entry per managed unit, in the declared order.
        """
        return [self.status(name) for name in SYSTEM_MANAGED_UNITS]

    def control(self, name: str, action: str) -> None:
        """Start, stop, restart, enable, or disable a unit.

        Args:
            name: Panel-facing service name.
            action: One of :data:`ALLOWED_ACTIONS`.

        Raises:
            KeyError: If the name is not a managed unit.
            ValueError: If the action is not allowed. Anything outside the list
                would let a panel request run arbitrary systemd verbs.
            CommandError: If systemd rejects the request.
        """
        if action not in ALLOWED_ACTIONS:
            raise ValueError(
                f"unsupported action {action!r}; "
                f"expected one of {', '.join(ALLOWED_ACTIONS)}"
            )
        run(["systemctl", action, self._unit_for(name)])

    def journal(self, name: str, *, line_count: int = 100) -> str:
        """Read the tail of a unit's journal.

        Args:
            name: Panel-facing service name.
            line_count: How many lines to return.

        Returns:
            The journal text, or the error output when the journal is
            unreadable.

        Raises:
            KeyError: If the name is not a managed unit.
        """
        result = run(
            [
                "journalctl",
                "-u",
                self._unit_for(name),
                "-n",
                str(line_count),
                "--no-pager",
                "--output",
                "short-iso",
            ],
            is_checked=False,
        )
        return result.stdout or result.stderr

    def daemon_reload(self) -> None:
        """Reload unit files after installing or editing one.

        Raises:
            CommandError: If systemd fails to reload.
        """
        run(["systemctl", "daemon-reload"])

    def _unit_for(self, name: str) -> str:
        try:
            return SYSTEM_MANAGED_UNITS[name]
        except KeyError as error:
            raise KeyError(
                f"{name!r} is not a managed service; "
                f"expected one of {', '.join(SYSTEM_MANAGED_UNITS)}"
            ) from error
