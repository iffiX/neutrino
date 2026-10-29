"""Leaving the panel's sandbox to install something.

The panel's unit is root with `NoNewPrivileges` and systemd's sandboxing, and
under those the effective capability set loses `CAP_SETUID`. apt drops to the
`_apt` account to fetch and cannot, so every download dies with
`seteuid 42 failed`. On Rocky 9 with SELinux enforcing, systemd rejects the
pipes `systemd-run --pipe` passes, so the command's output comes back through
files systemd writes.
"""

import asyncio
import subprocess
from pathlib import Path

import pytest

from neutrino_hub.system import sandbox
from neutrino_hub.system.sandbox import (
    is_sandboxed,
    run_outside_sandbox,
    stream_outside_sandbox,
)
from neutrino_hub.utils.subprocess_run import CommandResult, command_failure_text

OUTPUT_PROPERTY = "--property=StandardOutput=file:"
ERROR_PROPERTY = "--property=StandardError="


@pytest.fixture
def in_a_unit(monkeypatch, tmp_path):
    """A process systemd started, its output directory under the test's own."""
    monkeypatch.setenv(sandbox.SYSTEM_SANDBOX_UNIT_MARKER, "b8f0b4c0")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")
    directory = tmp_path / "outside_sandbox"
    monkeypatch.setattr(sandbox, "SYSTEM_SANDBOX_OUTPUT_DIR", directory)
    monkeypatch.setattr(sandbox, "SYSTEM_SANDBOX_POLL_S", 0.01)
    return directory


class _SystemdRun:
    """``systemd-run`` as ``run`` starts it: systemd writes the command's streams."""

    def __init__(self, *, output="", errors="", exit_code=0, unit_errors=""):
        self.output = output
        self.errors = errors
        self.exit_code = exit_code
        self.unit_errors = unit_errors
        self.ran: list = []

    def __call__(self, command, **keywords):
        self.ran.append((command, keywords))
        if self.unit_errors:
            return CommandResult(command, self.exit_code, "", self.unit_errors)
        _property_path(command, OUTPUT_PROPERTY).write_text(self.output)
        _property_path(command, f"{ERROR_PROPERTY}file:").write_text(self.errors)
        return CommandResult(command, self.exit_code, "", "")


def _property_path(command, prefix):
    """The file one ``--property=`` of a ``systemd-run`` line names."""
    (value,) = [word[len(prefix) :] for word in command if word.startswith(prefix)]
    return Path(value)


# --- run_outside_sandbox ---


def test_a_command_inside_a_unit_is_handed_to_systemd_without_pipes(
    monkeypatch, in_a_unit
):
    """`--pipe` hands the panel's pipes to systemd, which SELinux on Rocky 9 rejects."""
    unit = _SystemdRun(output="Installed: podman\n")
    monkeypatch.setattr(sandbox, "run", unit)

    run_outside_sandbox(["apt-get", "install", "-y", "podman"], timeout_s=900)

    ((command, keywords),) = unit.ran
    assert command[:4] == ["systemd-run", "--quiet", "--wait", "--collect"]
    assert "--pipe" not in command
    assert command[command.index("--") :] == [
        "--",
        "apt-get",
        "install",
        "-y",
        "podman",
    ]
    assert keywords == {"timeout_s": 900, "is_checked": False}


def test_the_command_writes_its_streams_to_two_files_in_the_output_directory(
    monkeypatch, in_a_unit
):
    unit = _SystemdRun()
    monkeypatch.setattr(sandbox, "run", unit)

    run_outside_sandbox(["dnf", "-y", "makecache"], timeout_s=300)

    ((command, _),) = unit.ran
    output = _property_path(command, OUTPUT_PROPERTY)
    errors = _property_path(command, f"{ERROR_PROPERTY}file:")
    assert output.parent == errors.parent == in_a_unit
    assert output != errors


def test_the_result_is_the_commands_own(monkeypatch, in_a_unit):
    """A caller cannot tell it from having run the command itself."""
    unit = _SystemdRun(output="Complete!\n", errors="warning: cache\n")
    monkeypatch.setattr(sandbox, "run", unit)

    result = run_outside_sandbox(["dnf", "-y", "install", "a.rpm"], timeout_s=900)

    assert result.command == ["dnf", "-y", "install", "a.rpm"]
    assert (result.exit_code, result.stdout, result.stderr) == (
        0,
        "Complete!\n",
        "warning: cache\n",
    )


def test_the_output_files_are_deleted_when_the_command_ends(monkeypatch, in_a_unit):
    monkeypatch.setattr(sandbox, "run", _SystemdRun(output="done\n", errors="e\n"))

    run_outside_sandbox(["apt-get", "update"], timeout_s=300, is_checked=False)

    assert list(in_a_unit.iterdir()) == []


def test_the_output_directory_is_root_only(monkeypatch, in_a_unit):
    monkeypatch.setattr(sandbox, "run", _SystemdRun())

    run_outside_sandbox(["apt-get", "update"], timeout_s=300)

    assert in_a_unit.stat().st_mode & 0o777 == 0o700


def test_a_failed_command_is_raised_with_its_exit_code_and_errors(
    monkeypatch, in_a_unit
):
    """The panel's log line names the command, its exit code and its errors."""
    monkeypatch.setattr(
        sandbox,
        "run",
        _SystemdRun(errors="Error: Unable to find a match: nope\n", exit_code=1),
    )

    with pytest.raises(subprocess.CalledProcessError) as raised:
        run_outside_sandbox(["dnf", "-y", "install", "nope"], timeout_s=900)

    assert command_failure_text(raised.value) == (
        "dnf -y install nope exited 1: Error: Unable to find a match: nope"
    )
    assert list(in_a_unit.iterdir()) == []


def test_a_unit_that_never_started_reports_what_systemd_run_printed(
    monkeypatch, in_a_unit
):
    monkeypatch.setattr(
        sandbox,
        "run",
        _SystemdRun(exit_code=1, unit_errors="Failed to start transient service\n"),
    )

    result = run_outside_sandbox(["apt-get", "update"], timeout_s=300, is_checked=False)

    assert (result.exit_code, result.stdout) == (1, "")
    assert result.stderr == "Failed to start transient service\n"


def test_the_separator_keeps_a_command_from_being_read_as_options(
    monkeypatch, in_a_unit
):
    """Without `--`, `apt-get -q` is systemd-run's `-q` first."""
    unit = _SystemdRun()
    monkeypatch.setattr(sandbox, "run", unit)

    run_outside_sandbox(["apt-get", "-q", "update"], timeout_s=300)

    ((command, _),) = unit.ran
    assert command[command.index("--") + 1] == "apt-get"


def test_a_working_copy_runs_the_command_itself(monkeypatch):
    """`nhub run` from a shell is not inside a unit, so there is nothing to leave."""
    monkeypatch.delenv(sandbox.SYSTEM_SANDBOX_UNIT_MARKER, raising=False)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")
    ran: list = []

    def run_here(command, **keywords):
        ran.append(command)
        return CommandResult(command, 0, "", "")

    monkeypatch.setattr(sandbox, "run", run_here)

    run_outside_sandbox(["apt-get", "update"], timeout_s=300)

    assert ran == [["apt-get", "update"]]


def test_a_machine_without_systemd_run_has_no_sandbox_to_leave(monkeypatch):
    monkeypatch.setenv(sandbox.SYSTEM_SANDBOX_UNIT_MARKER, "b8f0b4c0")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)

    assert is_sandboxed() is False


def test_macos_and_windows_have_no_sandbox_to_leave(monkeypatch):
    """No unit narrows the hub there."""
    monkeypatch.setenv(sandbox.SYSTEM_SANDBOX_UNIT_MARKER, "b8f0b4c0")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")
    for system in ("darwin", "win32"):
        monkeypatch.setattr("neutrino_hub.platforms.detect.sys.platform", system)

        assert is_sandboxed() is False


# --- stream_outside_sandbox ---


class _StreamingUnit:
    """``systemd-run`` as asyncio starts it: the command writes to its file as it runs."""

    def __init__(self, path, lines, *, exit_code=0, unit_errors=b""):
        self.path = path
        self.lines = lines
        self.exit_code = exit_code
        self.unit_errors = unit_errors
        self.returncode = None
        self.first_line_read = asyncio.Event()

    async def communicate(self):
        for index, line in enumerate(self.lines):
            with open(self.path, "ab") as handle:
                handle.write(line)
            if index == 0:
                await self.first_line_read.wait()
        self.returncode = self.exit_code
        return None, self.unit_errors


def _start_streaming_unit(lines, **keywords):
    """A fake ``create_subprocess_exec`` and the list of command lines it started."""
    started: list = []

    async def create_subprocess_exec(*command, **options):
        unit = _StreamingUnit(
            _property_path(command, OUTPUT_PROPERTY), lines, **keywords
        )
        started.append((list(command), options, unit))
        return unit

    return create_subprocess_exec, started


async def _read_all(source, started=None):
    """Every line a stream yields, releasing the unit after its first line."""
    lines = []
    async for line in source:
        lines.append(line)
        if started:
            started[0][2].first_line_read.set()
    return lines


def test_a_streamed_command_writes_both_streams_to_one_file(monkeypatch, in_a_unit):
    exec_, started = _start_streaming_unit([b"rendered\n"])
    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", exec_)

    asyncio.run(_read_all(stream_outside_sandbox(["nhub", "apply"]), started))

    ((command, _, _),) = started
    assert "--pipe" not in command
    assert f"{ERROR_PROPERTY}inherit" in command
    assert command[command.index("--") :] == ["--", "nhub", "apply"]


def test_a_streamed_line_arrives_while_the_command_runs(monkeypatch, in_a_unit):
    """The unit writes its second line only once the first has been read."""
    exec_, started = _start_streaming_unit([b"one\n", b"two\n", b"three"])
    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", exec_)

    async def read():
        return await asyncio.wait_for(
            _read_all(stream_outside_sandbox(["nhub", "apply"]), started), 5
        )

    assert asyncio.run(read()) == ["one\n", "two\n", "three"]
    assert list(in_a_unit.iterdir()) == []


def test_a_streamed_command_gets_its_environment_from_the_unit(monkeypatch, in_a_unit):
    exec_, started = _start_streaming_unit([b"x\n"])
    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", exec_)

    asyncio.run(
        _read_all(
            stream_outside_sandbox(
                ["nhub", "apply"], environment={"PYTHONUNBUFFERED": "1"}
            ),
            started,
        )
    )

    ((command, _, _),) = started
    assert "--setenv=PYTHONUNBUFFERED=1" in command[: command.index("--")]


def test_a_failed_streamed_command_ends_with_what_systemd_run_printed(
    monkeypatch, in_a_unit
):
    exec_, started = _start_streaming_unit(
        [b"applying\n"], exit_code=1, unit_errors=b"Job failed\n"
    )
    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", exec_)
    lines: list = []

    async def read():
        async for line in stream_outside_sandbox(["nhub", "apply"]):
            lines.append(line)
            started[0][2].first_line_read.set()

    with pytest.raises(subprocess.CalledProcessError) as raised:
        asyncio.run(read())

    assert lines == ["applying\n", "Job failed\n"]
    assert raised.value.returncode == 1
    assert list(in_a_unit.iterdir()) == []


class _Child:
    """A command asyncio started as this process's child, already done."""

    def __init__(self, exit_code=0):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(b"rendered and applied\n")
        self.stdout.feed_eof()
        self.exit_code = exit_code

    async def wait(self) -> int:
        return self.exit_code


def test_a_streamed_command_outside_a_unit_runs_as_a_child(monkeypatch):
    monkeypatch.delenv(sandbox.SYSTEM_SANDBOX_UNIT_MARKER, raising=False)
    started: list = []

    async def create_subprocess_exec(*command, **options):
        started.append((list(command), options))
        return _Child()

    monkeypatch.setattr(
        sandbox.asyncio, "create_subprocess_exec", create_subprocess_exec
    )

    lines = asyncio.run(
        _read_all(
            stream_outside_sandbox(
                ["nhub", "apply"], environment={"PYTHONUNBUFFERED": "1"}
            )
        )
    )

    ((command, options),) = started
    assert command == ["nhub", "apply"]
    assert options["env"]["PYTHONUNBUFFERED"] == "1"
    assert lines == ["rendered and applied\n"]
