"""Carrying out the commands the hub sends.

Only the actions in :data:`SUPPORTED_ACTIONS` can run. The hub is trusted,
but an agent running as root should still not accept an arbitrary shell
string just because something sent one, so ``run_command`` is deliberately
absent from the set. A module's own commands are named by its prefix and
run by its runner.

Installing a module is not here. Software reaches a managed machine one way,
an order from the hub's module controller carrying bytes the hub's cache
fetched; ``reinstall`` only puts this agent's own package back.

The device verbs the hub's drawer runs are here too: ending one process,
and reading or setting up the user-tier remote desktops.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field

from neutrino_agent.constants import (
    AGENT_MODULE_COMMAND_SETTLE_S,
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_KILL_GRACE_S,
    AGENT_OUTPUT_LIMIT_BYTES,
)
from neutrino_agent.modules.remote_desktop import (
    SUPPORTED_PRODUCTS,
    RemoteDesktopReader,
)
from neutrino_agent.exceptions import PlatformUnsupportedError

POWER_ACTIONS = {"reboot": "reboot", "shutdown": "poweroff"}

ACTION_KILL_PROCESS = "kill_process"
ACTION_REMOTE_DESKTOP_STATUS = "remote_desktop_status"
ACTION_REMOTE_DESKTOP_PASSWORD = "remote_desktop_password"  # scan: allow
DEVICE_ACTIONS = (
    ACTION_KILL_PROCESS,
    ACTION_REMOTE_DESKTOP_STATUS,
    ACTION_REMOTE_DESKTOP_PASSWORD,
)
# How often a signalled process is looked in on while its grace runs.
KILL_POLL_S = 0.05

# What each module answers to, by the prefix its actions carry.
MODULE_ACTIONS = {
    "samba": ("samba_set_password",),
    "gitea": ("gitea_admin", "gitea_password"),
    "podman": ("podman_control", "podman_journal"),
    "zfs": ("zfs_op", "zfs_scan"),
}

SUPPORTED_ACTIONS = (
    ("reboot", "shutdown", "reinstall")
    + DEVICE_ACTIONS
    + tuple(action for actions in MODULE_ACTIONS.values() for action in actions)
)


@dataclass
class CommandOutcome:
    """Result of running one command.

    Attributes:
        exit_code: The command's exit status; 0 means success.
        output: Combined output, truncated to a size the hub will accept.
        code: Why it failed, typed; empty on success.
        params: What the wording names.
        result: What a reading command answers with, structured; empty
            for a command that only acts.
    """

    exit_code: int
    output: str
    code: str = ""
    params: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Whether the command succeeded."""
        return self.exit_code == 0


class DeviceOperator:
    """Runs the supported remote actions on this device."""

    def __init__(
        self,
        *,
        platform,
        reinstall=None,
        module_runners=None,
        remote_desktop=None,
        settle=None,
        on_module_changed=None,
    ):
        """
        Args:
            platform: The machine's platform, behind the contract.
            reinstall: Called for the ``reinstall`` action; returns empty
                when the install was launched, ``{"code", "params"}`` when
                not. None refuses the action as unsupported.
            settle: Called with a timeout before a module command runs, to
                let a pending desired state apply first; None waits for
                nothing.
            on_module_changed: Called with the module name after one of its
                commands succeeded, so its details are read again at once.
            module_runners: Module name to its runner, for the actions a
                module answers. None refuses every module action.
            remote_desktop: The reader the remote desktop actions run on.
                None reads this machine through the platform.
        """
        self._platform = platform
        self._settle = settle
        self._on_module_changed = on_module_changed
        self._reinstall = reinstall
        self._module_runners = dict(module_runners or {})
        self._remote_desktop = remote_desktop or RemoteDesktopReader(platform=platform)

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
        if action == ACTION_KILL_PROCESS:
            return self._kill_process(args)
        if action in (ACTION_REMOTE_DESKTOP_STATUS, ACTION_REMOTE_DESKTOP_PASSWORD):
            return self._remote_desktop_command(action, args)
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
        if self._settle is not None and not self._settle(AGENT_MODULE_COMMAND_SETTLE_S):
            return CommandOutcome(
                exit_code=1,
                output="",
                code="state_not_settled",
                params={"module": module},
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
        if int(outcome.get("exit_code", 1)) == 0 and self._on_module_changed:
            self._on_module_changed(module)
        return CommandOutcome(
            exit_code=int(outcome.get("exit_code", 1)),
            output=str(outcome.get("output", "") or "")[-AGENT_OUTPUT_LIMIT_BYTES:],
            code=str(outcome.get("code", "") or ""),
            params=dict(outcome.get("params") or {}),
        )

    def _kill_process(self, args: dict) -> CommandOutcome:
        """End one process: a term, then a kill once its grace has run."""
        try:
            pid = int(args.get("pid", 0))
        except (TypeError, ValueError):
            pid = 0
        if pid <= 1 or pid == os.getpid():
            return CommandOutcome(
                exit_code=1, output="", code="kill_failed", params={"pid": pid}
            )
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return CommandOutcome(
                exit_code=1, output="", code="process_missing", params={"pid": pid}
            )
        except OSError as error:
            return CommandOutcome(
                exit_code=1,
                output="",
                code="kill_failed",
                params={"pid": pid, "detail": str(error)[:200]},
            )
        deadline = time.monotonic() + AGENT_KILL_GRACE_S
        while time.monotonic() < deadline:
            if not _is_alive(pid):
                return CommandOutcome(exit_code=0, output=f"terminated {pid}\n")
            time.sleep(KILL_POLL_S)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return CommandOutcome(exit_code=0, output=f"terminated {pid}\n")
        except OSError as error:
            return CommandOutcome(
                exit_code=1,
                output="",
                code="kill_failed",
                params={"pid": pid, "detail": str(error)[:200]},
            )
        return CommandOutcome(exit_code=0, output=f"killed {pid}\n")

    def _remote_desktop_command(self, action: str, args: dict) -> CommandOutcome:
        product = str(args.get("product", ""))
        if product not in SUPPORTED_PRODUCTS:
            return CommandOutcome(
                exit_code=1,
                output="",
                code="product_unknown",
                params={"product": product},
            )
        try:
            if action == ACTION_REMOTE_DESKTOP_STATUS:
                status = self._remote_desktop.status(product)
                return CommandOutcome(exit_code=0, output="", result=status)
            outcome = self._remote_desktop.set_password(
                product, str(args.get("password", ""))
            )
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


def _is_alive(pid: int) -> bool:
    """Whether a process still exists; a zombie counts until it is reaped."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            state = handle.read().rsplit(") ", 1)[1].split()[0]
    except (OSError, IndexError):
        return True
    return state != "Z"


def _module_of(action: str) -> "str | None":
    """Which module answers one action, or None for the agent's own."""
    for module, actions in MODULE_ACTIONS.items():
        if action in actions:
            return module
    return None
