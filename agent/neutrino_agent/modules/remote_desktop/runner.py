"""The Remote desktop module: one switch, made true by the desktop host.

Nothing is installed: the agent's package carries its copy of RustDesk. The
module reads ``running`` while the agent's RustDesk service runs, whoever
sits at the screen, and ``stopped`` otherwise. Applying the configuration hands the switch to the
:class:`~neutrino_agent.rdp.host.RdpShareHost`, which takes RustDesk over
or gives it back.

Not pure: drives the desktop host.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.modules.remote_desktop.config import RemoteDesktopConfig
from neutrino_agent.modules.remote_desktop.constants import (
    REMOTE_DESKTOP_KIND,
    REMOTE_DESKTOP_LINUX_UNIT,
    REMOTE_DESKTOP_NAME,
)


class RemoteDesktopModuleRunner(ModuleRunner):
    """Applies the hub's desktop switch and reports whether the copy listens."""

    kind = REMOTE_DESKTOP_KIND
    name = REMOTE_DESKTOP_NAME

    def __init__(self, *, platform, log=print, publish=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._host = None

    def bind_host(self, host) -> None:
        """Say which desktop host makes the switch true.

        Args:
            host: The :class:`~neutrino_agent.rdp.host.RdpShareHost`.
        """
        self._host = host

    def verify(self, resolved: dict) -> bool:
        """Always there: the agent's package carries it."""
        return True

    def is_active(self) -> bool:
        """Whether the agent's RustDesk service runs, with nobody at the
        screen too."""
        return self._host is not None and self._host.is_service_running()

    def apply(self, config: dict) -> None:
        """Turn the share on or off as the switch says.

        Args:
            config: ``{is_enabled}``.

        Raises:
            ModuleApplyError: ``rdp_takeover_failed`` or
                ``rdp_restore_failed {step, detail}``.
        """
        if self._host is None:
            raise ModuleApplyError(
                "rdp_takeover_failed", {"step": "host", "detail": "not ready"}
            )
        self._host.set_switch(RemoteDesktopConfig.from_dict(config).is_enabled)

    def journal_units(self) -> list:
        """RustDesk's unit on Linux; nothing elsewhere."""
        if self._platform.os_name == "linux":
            return [REMOTE_DESKTOP_LINUX_UNIT]
        return []

    def journal_text(self, lines: int) -> list:
        """The unit's journal on Linux, then the agent's lines that name the
        module.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first.
        """
        return self._with_agent_lines(super().journal_text(lines), lines)
