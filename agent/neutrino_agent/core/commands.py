"""Carrying out the commands the gateway sends.

Only the actions in :data:`SUPPORTED_ACTIONS` can run. The gateway is trusted,
but an agent running as root should still not accept an arbitrary shell string
just because something posted one, so ``run_command`` is deliberately absent
from the default set.

Installing is not here. Software reaches a managed machine one way — an
order from the hub's module controller, carrying bytes the hub's cache
fetched — and a command that downloaded and installed something of its own
would be a second way in.
"""

import subprocess
from dataclasses import dataclass

from neutrino_agent.constants import AGENT_COMMAND_TIMEOUT_S, AGENT_OUTPUT_LIMIT_BYTES
from neutrino_agent.platforms.base import PlatformUnsupportedError

SUPPORTED_ACTIONS = ("reboot", "shutdown")

POWER_ACTIONS = {"reboot": "reboot", "shutdown": "poweroff"}


@dataclass
class CommandOutcome:
    """Result of running one command.

    Attributes:
        exit_code: The command's exit status; 0 means success.
        output: Combined output, truncated to a size the gateway will accept.
    """

    exit_code: int
    output: str

    @property
    def is_success(self) -> bool:
        """Whether the command succeeded."""
        return self.exit_code == 0


class DeviceOperator:
    """Runs the supported remote actions on this device."""

    def __init__(self, *, platform):
        """
        Args:
            platform: The machine's platform, behind the contract.
        """
        self._platform = platform

    def run(self, action: str, args: dict) -> CommandOutcome:
        """Run one command by name.

        Args:
            action: One of :data:`SUPPORTED_ACTIONS`.
            args: Action-specific arguments.

        Returns:
            The outcome, including an explanatory message for an unsupported
            action rather than raising, so the gateway always gets a report.
        """
        if action not in SUPPORTED_ACTIONS:
            return CommandOutcome(
                exit_code=1, output=f"unsupported action {action!r}\n"
            )
        return self._power(POWER_ACTIONS[action])

    def _power(self, action: str) -> CommandOutcome:
        try:
            exit_code, output = self._platform.power(action)
        except PlatformUnsupportedError as error:
            return CommandOutcome(exit_code=1, output=f"{error.code}\n")
        except subprocess.TimeoutExpired:
            return CommandOutcome(
                exit_code=124, output=f"timed out after {AGENT_COMMAND_TIMEOUT_S}s\n"
            )
        except OSError as error:
            return CommandOutcome(exit_code=1, output=f"{error}\n")
        return CommandOutcome(
            exit_code=exit_code, output=output[-AGENT_OUTPUT_LIMIT_BYTES:]
        )
