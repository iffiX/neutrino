"""The Terminal module: the enabled accounts a new shell runs as, with nothing to install.

The agent carries the module, so it is always there. Its apply holds the
enabled accounts the state names; a ``shell`` or an ``exec`` stream opened
afterwards reads them, and a shell already running keeps the account it
runs as. Until a state is applied after a start, the accounts are the ones
the kept desired state carries, so a restart changes nothing a new shell
runs. The module reads ``running`` once it holds them.

Not pure: reads the kept desired state.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import threading

from neutrino_agent.constants import AGENT_DESIRED_STATE_NAME
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.modules.terminal.config import TerminalConfig
from neutrino_agent.modules.terminal.constants import TERMINAL_NAME, TERMINAL_RUNNER


def kept_settings(path: str) -> dict:
    """The Terminal module's configuration in a kept desired state.

    Args:
        path: The kept state's file.

    Returns:
        ``{accounts}`` as the state carries it; empty when the file or the
        entry is not there.
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
    """Holds the enabled accounts a new shell or command runs as."""

    runner = TERMINAL_RUNNER
    name = TERMINAL_NAME

    def __init__(self, *, platform, log=print, publish=None, state_path: str = ""):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            state_path: The kept desired state the accounts start from;
                empty is the one beside the agent's configuration.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._state_path = state_path or os.path.join(
            platform.agent_data_dir(), AGENT_DESIRED_STATE_NAME
        )
        self._lock = threading.Lock()
        self._config: "TerminalConfig | None" = None

    def verify(self, recipe: dict) -> bool:
        """Whether the module is on the machine.

        Args:
            recipe: The module's recipe.

        Returns:
            True: the agent carries it.
        """
        return True

    def is_active(self) -> bool:
        """Whether the module serves.

        Returns:
            True: every new shell reads its accounts.
        """
        return True

    def validate(self, config: dict) -> None:
        """Check that a shell can run for every account a configuration enables.

        Args:
            config: ``{accounts: [{account, shell_path, password}]}``.

        Raises:
            ModuleApplyError: ``config_invalid {field}``,
                ``account_duplicate {account}``, ``account_unknown
                {account}``, ``shell_program_unusable {path}``, and on
                Windows ``credential_missing {account}``.
        """
        known = None
        if self._platform.os_name == "windows":
            try:
                known = self._platform.human_accounts()
            except PlatformUnsupportedError:
                known = None
        TerminalConfig.from_dict(config).validate(
            os_name=self._platform.os_name, known_accounts=known
        )

    def apply(self, config: dict) -> None:
        """Hold the accounts every shell opened from now on reads.

        Args:
            config: ``{accounts: [{account, shell_path, password}]}``.

        Raises:
            ModuleApplyError: ``config_invalid {field}`` or
                ``account_duplicate {account}`` for a list that does not
                read.
        """
        held = TerminalConfig.from_dict(config)
        with self._lock:
            self._config = held
        self._log(f"terminal: accounts={','.join(held.names()) or '-'}")

    def settings(self) -> TerminalConfig:
        """The accounts a shell opened now runs as.

        Returns:
            What the last apply held, or what the kept state carries before
            any apply since the agent started; a kept entry that cannot be
            read enables no account.
        """
        with self._lock:
            held = self._config
        if held is not None:
            return held
        try:
            return TerminalConfig.from_dict(kept_settings(self._state_path))
        except ModuleApplyError:
            return TerminalConfig()
