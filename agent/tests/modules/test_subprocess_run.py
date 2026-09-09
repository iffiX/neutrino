"""The module appliers' one command helper."""

import subprocess

import pytest

from neutrino_agent.modules import subprocess_run
from neutrino_agent.modules.subprocess_run import CommandError, run, unit_state


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_a_command_answers_its_output_and_exit(monkeypatch):
    seen: dict = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["input"] = kwargs.get("input")
        return Completed(0, "out", "")

    monkeypatch.setattr(subprocess_run.subprocess, "run", fake_run)

    result = run(["smbpasswd", "-s", "-a", "ann"], input_text="pw\npw\n")

    assert result.is_success
    assert result.stdout == "out"
    assert seen["command"] == ["smbpasswd", "-s", "-a", "ann"]
    assert seen["input"] == "pw\npw\n"


def test_a_checked_failure_raises_with_the_commands_own_words(monkeypatch):
    monkeypatch.setattr(
        subprocess_run.subprocess,
        "run",
        lambda command, **kwargs: Completed(1, "", "no such pool"),
    )

    with pytest.raises(CommandError) as refused:
        run(["zpool", "destroy", "tank"])

    assert refused.value.detail == "no such pool"
    assert refused.value.command == ["zpool", "destroy", "tank"]


def test_an_unchecked_failure_is_answered_not_raised(monkeypatch):
    monkeypatch.setattr(
        subprocess_run.subprocess,
        "run",
        lambda command, **kwargs: Completed(3, "inactive\n", ""),
    )

    result = run(["systemctl", "is-active", "smbd"], is_checked=False)

    assert not result.is_success
    assert result.stdout == "inactive\n"


@pytest.mark.parametrize(
    "error", [OSError("no such file"), subprocess.TimeoutExpired("x", 1)]
)
def test_a_command_that_cannot_run_raises(monkeypatch, error):
    def fake_run(command, **kwargs):
        raise error

    monkeypatch.setattr(subprocess_run.subprocess, "run", fake_run)

    with pytest.raises(CommandError):
        run(["missing"])


def test_unit_state_reads_systemds_word_and_survives_no_systemd(monkeypatch):
    monkeypatch.setattr(
        subprocess_run.subprocess,
        "run",
        lambda command, **kwargs: Completed(0, "active\n", ""),
    )
    assert unit_state("smbd.service") == "active"

    def broken(command, **kwargs):
        raise OSError("no systemctl")

    monkeypatch.setattr(subprocess_run.subprocess, "run", broken)
    assert unit_state("smbd.service") == ""
