"""Running external commands.

Every system effect in the repo goes through here, so failures report the
command and its stderr instead of a bare exit code.
"""

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


class CommandError(RuntimeError):
    """Raised when a checked command fails."""


def run(
    command: list[str],
    *,
    input_text: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    is_checked: bool = True,
) -> CommandResult:
    """Run a command and capture its output.

    Args:
        command: Argument vector; never a shell string.
        input_text: Text piped to standard input, if any.
        timeout_s: Seconds before the command is killed.
        is_checked: Raise on a non-zero exit instead of returning the result.

    Returns:
        The captured result.

    Raises:
        CommandError: If the command fails and ``is_checked`` is set, or if it
            times out.
    """
    try:
        completed = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as error:
        raise CommandError(
            f"{' '.join(command)} timed out after {timeout_s}s"
        ) from error
    except FileNotFoundError as error:
        # An uninstalled tool is a failure like any other: callers that opted
        # out of checking want a failed result, not an exception, so the panel
        # still renders before the installer has run.
        if is_checked:
            raise CommandError(f"{command[0]} is not installed") from error
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
        raise CommandError(
            f"{' '.join(command)} exited {result.exit_code}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result
