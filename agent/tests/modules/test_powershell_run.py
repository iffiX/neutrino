"""One PowerShell script per operation, with the command runner faked.

What these pin: the script travels encoded after the prologue that reads
its document, the document, a password included, travels on standard input
and never on the command line, a refusal the script prints comes back as
its code, and a script that fails or prints no JSON object is an OS error.
"""

import base64
import json

import pytest

import neutrino_agent.modules.powershell_run as powershell_module
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.powershell_run import listed, run_powershell
from neutrino_agent.modules.subprocess_run import CommandResult

SCRIPT = "Set-LocalUser -Name $d.name\n'{}'\n"


def fake_run(result: CommandResult, calls: list):
    """A stand-in for the module runner's ``run`` answering one result."""

    def run(command, *, is_checked=True, input_text=None, timeout_s=0, encoding=None):
        calls.append(
            {"command": list(command), "input": input_text, "encoding": encoding}
        )
        return result

    return run


def decoded_script(command: list) -> str:
    encoded = command[command.index("-EncodedCommand") + 1]
    return base64.b64decode(encoded).decode("utf-16-le")


def test_a_script_runs_encoded_with_its_document_on_standard_input(monkeypatch):
    calls = []
    monkeypatch.setattr(
        powershell_module,
        "run",
        fake_run(CommandResult([], 0, 'noise\n{"notes": ["x"]}\n', ""), calls),
    )

    answer = run_powershell(SCRIPT, {"name": "ann", "password": "s3cret"})

    assert answer == {"notes": ["x"]}
    ((call,),) = [calls]
    command = call["command"]
    assert command[:3] == ["powershell.exe", "-NoProfile", "-NonInteractive"]
    assert decoded_script(command).endswith(SCRIPT)
    assert "[Console]::In.ReadToEnd()" in decoded_script(command)
    assert all("s3cret" not in part for part in command)
    assert json.loads(call["input"]) == {"name": "ann", "password": "s3cret"}


def test_a_refusal_the_script_prints_is_raised_with_its_code(monkeypatch):
    refusal = '{"code": "share_name_taken", "params": {"name": "media"}}'
    monkeypatch.setattr(
        powershell_module, "run", fake_run(CommandResult([], 3, refusal, ""), [])
    )

    with pytest.raises(ModuleApplyError) as caught:
        run_powershell(SCRIPT, {})

    assert caught.value.code == "share_name_taken"
    assert caught.value.params == {"name": "media"}


@pytest.mark.parametrize(
    "result",
    [
        CommandResult([], 1, "", "New-SmbShare : Access is denied."),
        CommandResult([], 0, "not json", ""),
    ],
)
def test_a_failed_or_silent_script_is_an_os_error(monkeypatch, result):
    monkeypatch.setattr(powershell_module, "run", fake_run(result, []))

    with pytest.raises(OSError):
        run_powershell(SCRIPT, {})


def test_one_object_comes_back_as_a_list_of_one():
    assert listed({"a": 1}) == [{"a": 1}]
    assert listed([1, 2]) == [1, 2]
    assert listed(None) == []


def test_powershell_output_is_read_as_the_utf_8_the_prologue_makes_it_write(
    monkeypatch,
):
    calls: list = []
    monkeypatch.setattr(
        powershell_module,
        "run",
        fake_run(CommandResult(["powershell.exe"], 0, '{"ok": true}', ""), calls),
    )

    run_powershell("'x'", {})

    assert calls[0]["encoding"] == "utf-8"


def test_a_refused_login_is_found_in_the_error_s_id_and_hresult_too():
    prologue = powershell_module.POWERSHELL_PROLOGUE

    assert "function Test-LogonRefused" in prologue
    assert "FullyQualifiedErrorId" in prologue
    assert "Exception.HResult" in prologue
    assert "8007052E" in prologue
