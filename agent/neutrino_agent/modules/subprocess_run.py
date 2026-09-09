"""Running one command for a module applier, with its output kept.

Every module applier drives the machine through ``systemctl``, ``smbpasswd``,
``zpool`` and the like. One helper runs them all: checked by default, so a
refusal raises with the command's own complaint, and unchecked where the
caller reads the exit status itself.

Not pure: runs commands.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from neutrino_agent.constants import AGENT_MODULE_OUTPUT_LIMIT_BYTES

RUN_TIMEOUT_S = 120


class CommandError(RuntimeError):
    """Raised when a checked command fails or cannot run.

    Attributes:
        command: The argument vector.
        detail: The command's own complaint, bounded.
    """

    def __init__(self, command: list, detail: str):
        super().__init__(f"{command[0]} failed: {detail}")
        self.command = list(command)
        self.detail = detail


@dataclass
class CommandResult:
    """What one command answered.

    Attributes:
        command: The argument vector.
        exit_code: Its exit status.
        stdout: Standard output.
        stderr: Standard error.
    """

    command: list
    exit_code: int
    stdout: str
    stderr: str

    @property
    def is_success(self) -> bool:
        """Whether the command exited zero."""
        return self.exit_code == 0


def run(
    command: list,
    *,
    is_checked: bool = True,
    input_text: "str | None" = None,
    timeout_s: int = RUN_TIMEOUT_S,
) -> CommandResult:
    """Run one command to completion.

    Args:
        command: The argument vector.
        is_checked: Whether a non-zero exit raises.
        input_text: Text for the command's standard input.
        timeout_s: How long to wait.

    Returns:
        The result.

    Raises:
        CommandError: When the command fails and ``is_checked`` is set, or
            when it cannot run at all.
    """
    try:
        completed = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CommandError(command, str(error)[:AGENT_MODULE_OUTPUT_LIMIT_BYTES])
    result = CommandResult(
        command=list(command),
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
    if is_checked and not result.is_success:
        detail = (result.stderr or result.stdout).strip()
        raise CommandError(command, detail[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:])
    return result


def unit_state(unit: str) -> str:
    """What systemd says one unit is doing.

    Args:
        unit: The unit name.

    Returns:
        ``systemctl is-active``'s word, empty when systemd cannot be asked.
    """
    try:
        return run(["systemctl", "is-active", unit], is_checked=False).stdout.strip()
    except CommandError:
        return ""
