"""The Terminal module: settings a new shell reads, with nothing to install.

The agent carries the module, so it is always there and always running.
Its apply holds the account and the shell program the state names; a
``shell`` stream opened afterwards reads them, and a shell already running
keeps what it runs. Until a state is applied after a start, the settings
are the ones the kept desired state carries, so a restart changes nothing a
new shell runs.

Not pure: reads the kept desired state.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import threading

from neutrino_agent.constants import AGENT_DESIRED_STATE_NAME
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.modules.terminal.config import TerminalConfig
from neutrino_agent.modules.terminal.constants import TERMINAL_KIND, TERMINAL_NAME


def kept_settings(path: str) -> dict:
    """The Terminal module's configuration in a kept desired state.

    Args:
        path: The kept state's file.

    Returns:
        ``{account, shell_path}`` as the state carries it; empty when the
        file or the entry is not there.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, ValueError):
        return {}
    modules = document.get("modules") if isinstance(document, dict) else None
    entry = modules.get(TERMINAL_NAME) if isinstance(modules, dict) else None
    config = entry.get("config") if isinstance(entry, dict) else None
    return dict(config) if isinstance(config, dict) else {}


class TerminalModuleRunner(ModuleRunner):
    """Holds the account and the shell program a new shell runs."""

    kind = TERMINAL_KIND
    name = TERMINAL_NAME

    def __init__(self, *, platform, log=print, publish=None, state_path: str = ""):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            state_path: The kept desired state the settings start from;
                empty is the one beside the agent's configuration.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._state_path = state_path or os.path.join(
            platform.agent_data_dir(), AGENT_DESIRED_STATE_NAME
        )
        self._lock = threading.Lock()
        self._config: "TerminalConfig | None" = None

    def verify(self, resolved: dict) -> bool:
        """Whether the module is on the machine.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True: the agent carries it.
        """
        return True

    def is_active(self) -> bool:
        """Whether the module serves.

        Returns:
            True: every new shell reads its settings.
        """
        return True

    def validate(self, config: dict) -> None:
        """Check that a shell can run as a configuration says.

        Args:
            config: ``{account, shell_path}``.

        Raises:
            ModuleApplyError: ``config_invalid {field}``,
                ``account_unknown {account}`` or ``shell_program_unusable
                {path}``.
        """
        TerminalConfig.from_dict(config, os_name=self._platform.os_name).validate()

    def apply(self, config: dict) -> None:
        """Hold the settings every shell opened from now on reads.

        Args:
            config: ``{account, shell_path}``.

        Raises:
            ModuleApplyError: ``config_invalid {field}`` for a setting that
                is not a string.
        """
        held = TerminalConfig.from_dict(config, os_name=self._platform.os_name)
        with self._lock:
            self._config = held
        self._log(
            f"terminal: account={held.account or '-'} "
            f"shell_path={held.shell_path or '-'}"
        )

    def settings(self) -> TerminalConfig:
        """The settings a shell opened now runs with.

        Returns:
            What the last apply held, or what the kept state carries before
            any apply since the agent started; a kept entry that cannot be
            read is the defaults.
        """
        with self._lock:
            held = self._config
        if held is not None:
            return held
        try:
            return TerminalConfig.from_dict(
                kept_settings(self._state_path), os_name=self._platform.os_name
            )
        except ModuleApplyError:
            return TerminalConfig()
