"""The PowerShell host's task reads, run in PowerShell where there is one.

What these pin: with the library's own loop answering, a task read the task
service failed is tried again and answers the tasks; a read that keeps failing
is an error and never no task; no match reads empty with no second try, by
a wildcard and by a whole name, whichever way the cmdlet says it; and each of
the three operations that read tasks does all of it.
"""

import json
import os
import shutil
import subprocess

import pytest

from neutrino_agent.platforms.powershell_host import library_path

pwsh = shutil.which("pwsh")

# Stands in for the task cmdlets: each read takes the next word of FAKE_READS,
# ``tasks`` the install task, ``none`` no output, ``missing`` the cmdlet's own
# error for a name with no match, and ``failed`` the error another process
# removing a task gives. Every read is a line in FAKE_ASKED.
TASK_STAND_INS = """
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value $TaskName
    $turn = @(Get-Content -LiteralPath $env:FAKE_ASKED).Count
    $word = $env:FAKE_READS.Split(',')[$turn - 1]
    if ($word -eq 'failed') {
        Write-Error -Message 'The system cannot find the file specified.' `
            -ErrorId 'HRESULT 0x80070002' -Category ObjectNotFound
    } elseif ($word -eq 'missing') {
        Write-Error -Message 'No MSFT_ScheduledTask objects found.' `
            -ErrorId 'CmdletizationQuery_NotFound_TaskName' -Category ObjectNotFound
    } elseif ($word -eq 'tasks') {
        [pscustomobject]@{
            TaskName = 'neutrino_cloudcli_install_ann'
            State = 'Running'
            Description = 'the install'
        }
    }
}
function Get-ScheduledTaskInfo {
    param([string]$TaskName)
    return [pscustomobject]@{ LastTaskResult = 267009 }
}
function Get-Service { param($Name, $ErrorAction) }
function Get-NetFirewallRule { param($Name, $ErrorAction) }
"""

STATES = {"op": "task_states", "args": {"prefix": "neutrino_cloudcli_install_"}}
READ = {"op": "task_read", "args": {"task": "neutrino_cloudcli_install_ann"}}
ADDED = {"op": "added_list", "args": {"prefix": "neutrino_"}}
RUNNING_TASK = {
    "name": "neutrino_cloudcli_install_ann",
    "state": "Running",
    "last_result": 267009,
}


def asked_of(tmp_path, request: dict, *, reads: str) -> tuple:
    """Ask the library's own loop one request.

    Returns:
        The answer, and how many task reads it took.
    """
    if pwsh is None:
        pytest.skip("PowerShell is not installed")
    driver = tmp_path / "driver.ps1"
    driver.write_text(f"{TASK_STAND_INS}\n. '{library_path()}'\n")
    asked = tmp_path / "asked"
    done = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
        input=json.dumps({"id": 1, **request}) + "\n",
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "FAKE_ASKED": str(asked),
            "FAKE_READS": reads,
        },
        timeout=60,
    )
    answer = json.loads(done.stdout.strip().splitlines()[-1])
    return answer, len(asked.read_text().splitlines()) if asked.exists() else 0


def test_a_read_another_process_failed_is_tried_again_and_answers_the_tasks(tmp_path):
    answer, reads = asked_of(tmp_path, STATES, reads="failed,failed,tasks")

    assert answer["ok"] is True
    assert answer["value"]["tasks"] == [RUNNING_TASK]
    assert reads == 3


def test_a_read_that_keeps_failing_is_an_error(tmp_path):
    answer, reads = asked_of(
        tmp_path, STATES, reads="failed,failed,failed,failed,failed"
    )

    assert answer["ok"] is False
    assert answer["kind"] == "error"
    assert "The system cannot find the file specified." in answer["message"]
    assert reads == 5


def test_a_wildcard_with_no_match_reads_empty_at_the_first_try(tmp_path):
    answer, reads = asked_of(tmp_path, STATES, reads="none")

    assert answer["ok"] is True
    assert answer["value"]["tasks"] == []
    assert reads == 1


def test_a_whole_name_with_no_match_reads_absent_at_the_first_try(tmp_path):
    answer, reads = asked_of(tmp_path, READ, reads="missing")

    assert answer["ok"] is True
    assert answer["value"]["is_present"] is False
    assert reads == 1


def test_one_task_read_by_its_name_is_tried_again_and_reads_present(tmp_path):
    answer, reads = asked_of(tmp_path, READ, reads="failed,tasks")

    assert answer["value"]["is_present"] is True
    assert answer["value"]["state"] == "Running"
    assert reads == 2


def test_one_task_read_that_keeps_failing_is_an_error(tmp_path):
    answer, _ = asked_of(tmp_path, READ, reads="failed,failed,failed,failed,failed")

    assert answer["ok"] is False
    assert answer["kind"] == "error"


def test_the_agent_s_additions_read_is_tried_again(tmp_path):
    answer, _ = asked_of(tmp_path, ADDED, reads="failed,tasks")
    assert answer["value"]["tasks"] == ["neutrino_cloudcli_install_ann"]


def test_the_agent_s_additions_read_that_keeps_failing_is_an_error(tmp_path):
    answer, _ = asked_of(tmp_path, ADDED, reads="failed,failed,failed,failed,failed")

    assert answer["ok"] is False
