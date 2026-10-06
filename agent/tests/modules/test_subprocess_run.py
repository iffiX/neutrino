"""The module appliers' one command helper."""

import subprocess

import pytest

from neutrino_agent.modules import subprocess_run
from neutrino_agent.modules.subprocess_run import command_detail, run, unit_state


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

    with pytest.raises(subprocess.CalledProcessError) as refused:
        run(["zpool", "destroy", "tank"])

    assert command_detail(refused.value) == "no such pool"
    assert refused.value.cmd == ["zpool", "destroy", "tank"]
    assert refused.value.returncode == 1


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

    with pytest.raises(type(error)):
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


def test_a_blank_standard_error_does_not_hide_the_words_on_standard_output():
    error = subprocess.CalledProcessError(
        56, ["dscl", ".", "-passwd"], output="DS Error: -14136\n", stderr="\n"
    )

    assert command_detail(error) == "DS Error: -14136"


def test_a_command_that_said_nothing_is_named_with_its_exit_status():
    error = subprocess.CalledProcessError(
        1, ["pwpolicy", "-u", "ann"], output="", stderr=" \n"
    )

    assert command_detail(error) == "pwpolicy exited 1"


def test_output_a_byte_the_encoding_cannot_read_is_replaced_not_lost():
    import sys

    from neutrino_agent.modules.subprocess_run import run

    result = run(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'{\\x90}')"],
        is_checked=False,
        encoding="cp1252",
    )

    assert result.stdout == "{\ufffd}"
