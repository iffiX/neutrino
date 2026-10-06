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
    encoding: "str | None" = None,
) -> CommandResult:
    """Run one command to completion.

    Its output is read in the encoding named, the system's own when none
    is, and a byte that encoding cannot read becomes a replacement
    character rather than an error: on Windows a decode error is raised in
    the thread that reads the pipe and would leave the output empty.

    Args:
        command: The argument vector.
        is_checked: Whether a non-zero exit raises.
        input_text: Text for the command's standard input.
        timeout_s: How long to wait.
        encoding: The encoding the command writes; None is the system's.

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
        encoding=encoding,
        errors="replace",
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
        The command's own words for a non-zero exit, standard error first
        and standard output when it is blank, else the command's name and
        exit status; its failure to start otherwise.
    """
    if isinstance(error, subprocess.CalledProcessError):
        for text in (error.stderr, error.output):
            if (text or "").strip():
                return text.strip()[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]
        command = error.cmd[0] if isinstance(error.cmd, list) else str(error.cmd)
        return f"{command} exited {error.returncode}"
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


def units_journal(units: list, lines: int) -> list:
    """The tail of the journal of one or more units, oldest line first.

    Args:
        units: The unit names; journald merges them by time.
        lines: How many lines to read at most.

    Returns:
        The lines, empty when there is no unit to ask or journald cannot be
        asked.
    """
    if not units:
        return []
    command = ["journalctl"]
    for unit in units:
        command += ["-u", unit]
    command += ["-n", str(lines), "--no-pager", "--output", "short-iso"]
    try:
        result = run(command, is_checked=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if not result.is_success:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]
