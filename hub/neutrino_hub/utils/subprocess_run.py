"""Running external commands.

Every system effect in the repo goes through here, so failures report the
command and its stderr instead of a bare exit code.
"""

import os
import subprocess
from dataclasses import dataclass

DEFAULT_TIMEOUT_S = 60


@dataclass
class CommandResult:
    """Outcome of one external command.

    Attributes:
        command: The argument vector that was run.
        exit_code: Process exit status.
        stdout: Captured standard output.
        stderr: Captured standard error.
    """

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def is_success(self) -> bool:
        """Whether the command exited zero."""
        return self.exit_code == 0


def run(
    command: list[str],
    *,
    input_text: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    is_checked: bool = True,
    environment: dict[str, str] | None = None,
) -> CommandResult:
    """Run a command and capture its output.

    Args:
        command: Argument vector; never a shell string.
        input_text: Text piped to standard input, if any.
        timeout_s: Seconds before the command is killed.
        is_checked: Raise on a non-zero exit instead of returning the result.
        environment: Variables added to this process's own, for a tool that
            is told where to look by the environment rather than by a flag.

    Returns:
        The captured result.

    Raises:
        subprocess.CalledProcessError: If the command exits non-zero and
            ``is_checked`` is set.
        subprocess.TimeoutExpired: If the command runs past ``timeout_s``.
        FileNotFoundError: If the tool is not installed and ``is_checked`` is
            set.
    """
    try:
        completed = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, **environment} if environment else None,
        )
    except FileNotFoundError:
        # An uninstalled tool is a failure like any other: callers that opted
        # out of checking want a failed result, not an exception, so the panel
        # still renders before the installer has run.
        if is_checked:
            raise
        return CommandResult(
            command=command,
            exit_code=127,
            stdout="",
            stderr=f"{command[0]} is not installed",
        )

    result = CommandResult(
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if is_checked and not result.is_success:
        raise subprocess.CalledProcessError(
            result.exit_code, command, output=result.stdout, stderr=result.stderr
        )
    return result


def command_failure_text(error: BaseException) -> str:
    """Word a command failure for a person reading it.

    Args:
        error: What ``run`` raised, or any other failure being reported
            beside one.

    Returns:
        The command, its exit status and what it printed for a
        ``subprocess.CalledProcessError``; the error's own text otherwise.
    """
    if not isinstance(error, subprocess.CalledProcessError):
        return str(error)
    command = error.cmd if isinstance(error.cmd, str) else " ".join(error.cmd)
    printed = ((error.stderr or "") or (error.output or "")).strip()
    if not printed:
        return f"{command} exited {error.returncode}"
    return f"{command} exited {error.returncode}: {printed}"
