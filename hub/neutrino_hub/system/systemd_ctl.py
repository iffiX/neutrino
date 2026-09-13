"""Inspecting and controlling systemd units.

The panel's Services tab and the installer both drive systemd through this one
class, so the set of units either can touch is exactly
:data:`neutrino_hub.system.constants.SYSTEM_MANAGED_UNITS`.
"""

import os
import socket
from dataclasses import dataclass

from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.system.constants import (
    SYSTEM_MANAGED_UNITS,
    SYSTEM_NOTIFY_READY,
    SYSTEM_NOTIFY_SOCKET_ENV,
    SYSTEM_UNIT_STATE_FAILED,
    SYSTEM_UNIT_STATE_INACTIVE,
)

ALLOWED_ACTIONS = ("start", "stop", "restart", "enable", "disable")


def unit_state(unit: str) -> str:
    """What systemd says one unit is doing now.

    Args:
        unit: The unit's name.

    Returns:
        ``active``, ``activating``, ``inactive``, ``failed`` or another word
        systemd prints; ``inactive`` for a unit it does not know.
    """
    result = run(["systemctl", "is-active", unit], is_checked=False)
    return result.stdout.strip() or SYSTEM_UNIT_STATE_INACTIVE


def is_unit_startable(state: str, *, is_failed_restarted: bool) -> bool:
    """Whether a unit in this state is one to start.

    A unit systemd is starting or restarting is systemd's to finish.

    Args:
        state: What :func:`unit_state` answered.
        is_failed_restarted: Whether a failed unit counts. A person's apply
            restarts one; an event leaves it.

    Returns:
        True for an inactive unit, and for a failed one when asked.
    """
    if state == SYSTEM_UNIT_STATE_INACTIVE:
        return True
    return is_failed_restarted and state == SYSTEM_UNIT_STATE_FAILED


def take_notify_address() -> str:
    """Take systemd's notify socket out of this process's environment.

    Under `NotifyAccess=main` systemd refuses a message from a child, and
    every child started afterwards no longer inherits the socket.

    Returns:
        The socket's address; empty when no unit started this process.
    """
    return os.environ.pop(SYSTEM_NOTIFY_SOCKET_ENV, "")


def notify_ready(address: str) -> bool:
    """Tell systemd this unit is ready, when a unit started it.

    Args:
        address: The socket `take_notify_address` returned.

    Returns:
        True when systemd was told; False with no unit to tell.

    Raises:
        OSError: When the socket systemd named cannot be reached.
    """
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
        connection.connect(address)
        connection.sendall(SYSTEM_NOTIFY_READY)
    return True


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
        # Properties rather than the words `is-enabled` prints: what it says
        # about a unit that does not exist is a systemd version's wording, and
        # matching on it reads a missing unit as an installed one on any
        # release that phrases it differently. Debian 12 says "Failed to get
        # unit file state for x.service: No such file or directory" where
        # Ubuntu 25 says "not-found"; `LoadState` says `not-found` on both.
        properties = self._properties(
            unit, ("LoadState", "ActiveState", "UnitFileState")
        )
        return ServiceStatus(
            name=name,
            unit=unit,
            is_installed=properties.get("LoadState", "not-found") != "not-found",
            is_active=properties.get("ActiveState") == "active",
            is_enabled=properties.get("UnitFileState")
            in ("enabled", "enabled-runtime", "static"),
        )

    def _properties(self, unit: str, names: tuple) -> dict:
        """Read systemd's own answers for one unit.

        Args:
            unit: The systemd unit name.
            names: The properties to ask for.

        Returns:
            Property name to value. A unit systemd does not know still answers,
            with the values it has for one that is not there.
        """
        asked = []
        for name in names:
            asked += ["-p", name]
        result = run(["systemctl", "show", unit, *asked], is_checked=False)
        answers = {}
        for line in result.stdout.splitlines():
            key, _, value = line.partition("=")
            if key:
                answers[key] = value.strip()
        return answers

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
            subprocess.CalledProcessError: If systemd rejects the request.
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
            subprocess.CalledProcessError: If systemd fails to reload.
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
