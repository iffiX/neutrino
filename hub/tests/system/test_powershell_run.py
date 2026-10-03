"""One PowerShell script on a Windows hub, with PowerShell faked.

What these pin: the script travels encoded with the prologue in front, the
document on standard input, and the answer is the last JSON object printed.
"""

import base64
import json

import pytest

from neutrino_hub.system import powershell_run
from neutrino_hub.system.powershell_run import (
    POWERSHELL_PROLOGUE,
    listed,
    run_powershell,
)
from neutrino_hub.utils.subprocess_run import CommandResult


class FakeShell:
    def __init__(self, stdout="", exit_code=0):
        self.calls = []
        self._stdout = stdout
        self._exit_code = exit_code

    def __call__(self, command, **keywords):
        self.calls.append((command, keywords))
        return CommandResult(command, self._exit_code, self._stdout, "denied")


def test_the_script_is_encoded_and_the_document_goes_on_standard_input(
    monkeypatch,
):
    shell = FakeShell('noise\n{"first": 1}\n{"ok": true}\n')
    monkeypatch.setattr(powershell_run, "run", shell)

    assert run_powershell("Write-Output 1", {"port": 8080}) == {"ok": True}

    ((command, keywords),) = shell.calls
    assert command[:6] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
    ]
    script = base64.b64decode(command[6]).decode("utf-16-le")
    assert script == POWERSHELL_PROLOGUE + "Write-Output 1"
    assert json.loads(keywords["input_text"]) == {"port": 8080}


def test_a_failed_script_is_an_os_error(monkeypatch):
    monkeypatch.setattr(powershell_run, "run", FakeShell(exit_code=1))

    with pytest.raises(OSError, match="powershell exited 1: denied"):
        run_powershell("exit 1", {})


def test_a_script_that_prints_no_object_is_an_os_error(monkeypatch):
    monkeypatch.setattr(powershell_run, "run", FakeShell("[1, 2]\n"))

    with pytest.raises(OSError, match="no JSON object"):
        run_powershell("", {})


def test_one_member_comes_back_as_a_list():
    assert listed(None) == []
    assert listed({"a": 1}) == [{"a": 1}]
    assert listed([1, 2]) == [1, 2]
