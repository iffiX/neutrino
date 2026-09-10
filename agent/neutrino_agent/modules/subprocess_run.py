"""Running one command for a module applier, with its output kept.

Every module applier drives the machine through ``systemctl``, ``smbpasswd``,
``zpool`` and the like. One helper runs them all: checked by default, so a
non-zero exit raises ``subprocess.CalledProcessError`` carrying the
command's own complaint, and unchecked where the caller reads the exit
status itself.

Not pure: runs commands.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from neutrino_agent.constants import AGENT_MODULE_OUTPUT_LIMIT_BYTES

RUN_TIMEOUT_S = 120


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
        subprocess.CalledProcessError: When the command exits non-zero and
            ``is_checked`` is set.
        subprocess.SubprocessError: When the command does not finish, a
            timeout included.
        OSError: When the command cannot be started at all.
    """
    completed = subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    result = CommandResult(
        command=list(command),
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
    if is_checked and not result.is_success:
        raise subprocess.CalledProcessError(
            result.exit_code,
            list(command),
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def command_detail(error: BaseException) -> str:
    """The bounded complaint one failed command left.

    Args:
        error: What running the command raised.

    Returns:
        The command's own words for a non-zero exit, its failure to start
        otherwise.
    """
    if isinstance(error, subprocess.CalledProcessError):
        text = (error.stderr or error.output or "").strip()
        return text[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]
    return str(error)[:AGENT_MODULE_OUTPUT_LIMIT_BYTES]


def unit_state(unit: str) -> str:
    """What systemd says one unit is doing.

    Args:
        unit: The unit name.

    Returns:
        ``systemctl is-active``'s word, empty when systemd cannot be asked.
    """
    try:
        return run(["systemctl", "is-active", unit], is_checked=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
