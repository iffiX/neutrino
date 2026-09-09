"""Carrying out the commands the hub sends.

Only the actions in :data:`SUPPORTED_ACTIONS` can run. The hub is trusted,
but an agent running as root should still not accept an arbitrary shell
string just because something sent one, so ``run_command`` is deliberately
absent from the set. A module's own commands are named by its prefix and
run by its runner.

Installing a module is not here. Software reaches a managed machine one way,
an order from the hub's module controller carrying bytes the hub's cache
fetched; ``reinstall`` only puts this agent's own package back.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from neutrino_agent.constants import AGENT_COMMAND_TIMEOUT_S, AGENT_OUTPUT_LIMIT_BYTES
from neutrino_agent.platforms.base import PlatformUnsupportedError

POWER_ACTIONS = {"reboot": "reboot", "shutdown": "poweroff"}

# What each module answers to, by the prefix its actions carry.
MODULE_ACTIONS = {
    "samba": ("samba_set_password",),
    "gitea": ("gitea_admin", "gitea_password"),
    "podman": ("podman_control", "podman_journal"),
    "zfs": ("zfs_op", "zfs_scan"),
}

SUPPORTED_ACTIONS = ("reboot", "shutdown", "reinstall") + tuple(
    action for actions in MODULE_ACTIONS.values() for action in actions
)


@dataclass
class CommandOutcome:
    """Result of running one command.

    Attributes:
        exit_code: The command's exit status; 0 means success.
        output: Combined output, truncated to a size the hub will accept.
        code: Why it failed, typed; empty on success.
        params: What the wording names.
    """

    exit_code: int
    output: str
    code: str = ""
    params: dict = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Whether the command succeeded."""
        return self.exit_code == 0


class DeviceOperator:
    """Runs the supported remote actions on this device."""

    def __init__(self, *, platform, reinstall=None, module_runners=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            reinstall: Called for the ``reinstall`` action; returns empty
                when the install was launched, ``{"code", "params"}`` when
                not. None refuses the action as unsupported.
            module_runners: Module name to its runner, for the actions a
                module answers. None refuses every module action.
        """
        self._platform = platform
        self._reinstall = reinstall
        self._module_runners = dict(module_runners or {})

    def run(self, action: str, args: dict, on_line=None) -> CommandOutcome:
        """Run one command by name.

        Args:
            action: One of :data:`SUPPORTED_ACTIONS`.
            args: Action-specific arguments.
            on_line: Called with each output line a module command produces.

        Returns:
            The outcome; an unsupported action is a typed refusal rather
            than an exception, so the hub always gets a report.
        """
        if action == "reinstall" and self._reinstall is not None:
            refusal = self._reinstall()
            if refusal:
                return CommandOutcome(
                    exit_code=1,
                    output="",
                    code=str(refusal.get("code", "")),
                    params=dict(refusal.get("params") or {}),
                )
            return CommandOutcome(exit_code=0, output="reinstall launched\n")
        module = _module_of(action)
        if module is not None:
            return self._module_command(module, action, args, on_line)
        if action not in POWER_ACTIONS:
            return CommandOutcome(
                exit_code=1,
                output="",
                code="unsupported_action",
                params={"action": action},
            )
        return self._power(POWER_ACTIONS[action])

    def _module_command(
        self, module: str, action: str, args: dict, on_line
    ) -> CommandOutcome:
        runner = self._module_runners.get(module)
        if runner is None:
            return CommandOutcome(
                exit_code=1,
                output="",
                code="unsupported_action",
                params={"action": action},
            )
        try:
            outcome = runner.command(action, dict(args), on_line)
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return CommandOutcome(
                exit_code=1,
                output="",
                code="agent_internal",
                params={"error": type(error).__name__},
            )
        return CommandOutcome(
            exit_code=int(outcome.get("exit_code", 1)),
            output=str(outcome.get("output", "") or "")[-AGENT_OUTPUT_LIMIT_BYTES:],
            code=str(outcome.get("code", "") or ""),
            params=dict(outcome.get("params") or {}),
        )

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


def _module_of(action: str) -> "str | None":
    """Which module answers one action, or None for the agent's own."""
    for module, actions in MODULE_ACTIONS.items():
        if action in actions:
            return module
    return None
