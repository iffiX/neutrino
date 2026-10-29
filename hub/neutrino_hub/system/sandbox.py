"""Running a command outside the panel's own sandbox.

A child of the panel's unit inherits its hardening, under which apt and a
vendor's installer cannot drop privileges. The command runs in a transient
unit of its own instead, and systemd writes its output and errors to files
the panel reads ([../../../skills/core-code-author/design/privilege.md](../../../skills/core-code-author/design/privilege.md)).
"""

import asyncio
import os
import shutil
import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from neutrino_hub.platforms.detect import is_linux
from neutrino_hub.system.constants import (
    SYSTEM_SANDBOX_OUTPUT_DIR,
    SYSTEM_SANDBOX_OUTPUT_DIR_MODE,
    SYSTEM_SANDBOX_POLL_S,
    SYSTEM_SANDBOX_SYSTEMD_RUN,
    SYSTEM_SANDBOX_UNIT_MARKER,
)
from neutrino_hub.utils.subprocess_run import CommandResult, run


def run_outside_sandbox(
    command: list, *, timeout_s: float, is_checked: bool = True
) -> CommandResult:
    """Run a command outside this unit's sandbox and capture its output.

    Args:
        command: The argument vector.
        timeout_s: Seconds before the wait for the command is killed.
        is_checked: Raise on a non-zero exit instead of returning the result.

    Returns:
        The command, its exit code, its output, and its errors followed by
        any error ``systemd-run`` printed.

    Raises:
        subprocess.CalledProcessError: If the command exits non-zero and
            ``is_checked`` is set.
        subprocess.TimeoutExpired: If the command runs past ``timeout_s``.
        FileNotFoundError: If no sandbox applies, the program is not
            installed, and ``is_checked`` is set.
        OSError: If the output directory cannot be made.
    """
    if not is_sandboxed():
        return run(list(command), timeout_s=timeout_s, is_checked=is_checked)
    output, errors = _output_paths()
    try:
        started = run(
            _unit_command(command, output=output, errors=errors),
            timeout_s=timeout_s,
            is_checked=False,
        )
        result = CommandResult(
            command=list(command),
            exit_code=started.exit_code,
            stdout=_read_output(output),
            stderr=_read_output(errors) + started.stderr,
        )
    finally:
        _remove_output(output, errors)
    if is_checked and not result.is_success:
        raise subprocess.CalledProcessError(
            result.exit_code, result.command, output=result.stdout, stderr=result.stderr
        )
    return result


async def stream_outside_sandbox(
    command: list, *, environment: dict | None = None
) -> AsyncIterator[str]:
    """Run a command outside this unit's sandbox and yield its output as it runs.

    Args:
        command: The argument vector.
        environment: Variables added to the command's environment.

    Yields:
        Each line of its output and errors in the order written, then any
        error ``systemd-run`` printed.

    Raises:
        subprocess.CalledProcessError: If the command exits non-zero.
        FileNotFoundError: If no sandbox applies and the program is not
            installed.
        OSError: If the output directory cannot be made.
    """
    if not is_sandboxed():
        async for line in _stream_here(command, environment=environment):
            yield line
        return
    output, _ = _output_paths()
    try:
        process = await asyncio.create_subprocess_exec(
            *_unit_command(command, output=output, environment=environment),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        ended = asyncio.ensure_future(process.communicate())
        try:
            offset = 0
            partial = b""
            is_ended = False
            while not is_ended:
                done, _ = await asyncio.wait({ended}, timeout=SYSTEM_SANDBOX_POLL_S)
                is_ended = bool(done)
                written = _read_from(output, offset)
                offset += len(written)
                *lines, partial = (partial + written).split(b"\n")
                for line in lines:
                    yield (line + b"\n").decode("utf-8", "replace")
        finally:
            ended.cancel()
        if partial:
            yield partial.decode("utf-8", "replace")
        unit_errors = ended.result()[1].decode("utf-8", "replace")
        if unit_errors:
            yield unit_errors
    finally:
        _remove_output(output)
    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            process.returncode, list(command), stderr=unit_errors
        )


def is_sandboxed() -> bool:
    """Whether this process is inside a unit whose sandbox can be left.

    Returns:
        True when systemd started this process and ``systemd-run`` is there
        to start another; False on macOS and Windows, which have no sandbox.
    """
    return (
        is_linux()
        and bool(os.environ.get(SYSTEM_SANDBOX_UNIT_MARKER))
        and bool(shutil.which("systemd-run"))
    )


async def _stream_here(
    command: list, *, environment: dict | None
) -> AsyncIterator[str]:
    """Run a command as a child of this process and yield its output lines."""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **environment} if environment else None,
    )
    assert process.stdout is not None
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        yield line.decode("utf-8", "replace")
    code = await process.wait()
    if code != 0:
        raise subprocess.CalledProcessError(code, list(command))


def _unit_command(
    command: list,
    *,
    output: Path,
    errors: Path | None = None,
    environment: dict | None = None,
) -> list:
    """The ``systemd-run`` line, its errors to ``errors`` or else to ``output``."""
    standard_error = f"file:{errors}" if errors is not None else "inherit"
    return [
        *SYSTEM_SANDBOX_SYSTEMD_RUN,
        f"--property=StandardOutput=file:{output}",
        f"--property=StandardError={standard_error}",
        *(f"--setenv={name}={value}" for name, value in (environment or {}).items()),
        "--",
        *command,
    ]


def _output_paths() -> tuple:
    """A new output file path and error file path in the output directory."""
    SYSTEM_SANDBOX_OUTPUT_DIR.mkdir(
        mode=SYSTEM_SANDBOX_OUTPUT_DIR_MODE, parents=True, exist_ok=True
    )
    name = uuid.uuid4().hex
    return (
        SYSTEM_SANDBOX_OUTPUT_DIR / f"{name}.out",
        SYSTEM_SANDBOX_OUTPUT_DIR / f"{name}.err",
    )


def _read_output(path: Path) -> str:
    """The text of an output file, empty when systemd never made it."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _read_from(path: Path, offset: int) -> bytes:
    """The bytes of an output file past ``offset``, empty before systemd makes it."""
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            return handle.read()
    except FileNotFoundError:
        return b""


def _remove_output(*paths: Path) -> None:
    """Delete output files, ignoring those systemd never made."""
    for path in paths:
        path.unlink(missing_ok=True)
