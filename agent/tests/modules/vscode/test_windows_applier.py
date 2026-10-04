"""VS Code's servers on Windows, with PowerShell faked.

What these pin: one script registers a task per instance, signed in with the
account's login, started at boot with no time limit and a limited token; the
task runs the CLI through ``cmd.exe`` with its output appended to the
account's log file, reachable by the account, SYSTEM and the administrators
alone; the login and the token travel in the script's document; the task's
description
carries a digest that moves when what it runs or its login changes; a
refused login comes back as ``credential_invalid``, and a task whose last
start could not sign in reads it too. A stop ends the instance's whole
process tree, taken before the task stops, and an instance runs only while
its tree listens on its port, whatever its task's state says.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.vscode.windows_applier import (
    APPLY_SCRIPT,
    STATUS_SCRIPT,
    TREE_FUNCTIONS,
    WITHDRAW_SCRIPT,
    VscodeWindowsApplier,
    task_arguments,
)

ROOT = "C:\\ProgramData\\Neutrino\\agent\\state"
CONFIG = VscodeConfig.from_dict(
    {
        "address": "",
        "instances": [
            {"account": "hanha", "port": 8000, "token": "t-1", "password": "pw"}
        ],
    }
)


class FakePowerShell:
    def __init__(self, answers=None, error=None):
        self.runs: list = []
        self._answers = dict(answers or {})
        self._error = error

    def __call__(self, script, document):
        self.runs.append((script, document))
        if self._error is not None:
            raise self._error
        return dict(self._answers.get(script, {}))


def test_an_instance_is_a_task_signed_in_with_its_login():
    powershell = FakePowerShell({APPLY_SCRIPT: {"notes": ["registered"]}})
    applier = VscodeWindowsApplier(root=ROOT, powershell=powershell)

    assert applier.apply(CONFIG) == ["registered"]

    ((script, document),) = powershell.runs
    assert document["program"] == "cmd.exe"
    assert document["tasks"] == ["neutrino_vscode_hanha"]
    (instance,) = document["instances"]
    cli = "C:\\ProgramData\\Neutrino\\agent\\state\\vscode\\code.exe"
    token_file = "C:\\ProgramData\\Neutrino\\agent\\state\\vscode\\tokens\\hanha.token"
    log_file = "C:\\ProgramData\\Neutrino\\agent\\state\\vscode\\hanha.log"
    assert instance["account"] == "hanha"
    assert instance["password"] == "pw"
    assert instance["token"] == "t-1"
    assert instance["token_file"] == token_file
    assert instance["log_file"] == log_file
    assert instance["arguments"] == (
        f'/s /c "{cli} serve-web --accept-server-license-terms --host 0.0.0.0 '
        f'--port 8000 --connection-token-file {token_file} >> {log_file} 2>&1"'
    )
    assert '"$($i.account):M"' in APPLY_SCRIPT
    assert instance["description"].startswith("neutrino:")
    assert "pw" not in instance["description"]
    assert "-User $i.account -Password $i.password -RunLevel Limited" in APPLY_SCRIPT
    assert "New-ScheduledTaskTrigger -AtStartup" in APPLY_SCRIPT
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in APPLY_SCRIPT


def test_an_instance_opens_its_port_in_the_firewall_and_a_removal_closes_it():
    powershell = FakePowerShell({APPLY_SCRIPT: {"notes": []}})
    applier = VscodeWindowsApplier(root=ROOT, powershell=powershell)

    applier.apply(CONFIG)
    applier.remove()

    apply_run, withdraw_run = powershell.runs
    (instance,) = apply_run[1]["instances"]
    assert instance["port"] == 8000
    assert instance["rule"] == "neutrino_vscode_port_hanha"
    assert instance["rule_title"] == "Neutrino VS Code (hanha)"
    assert apply_run[1]["rule_prefix"] == "neutrino_vscode_port_"
    assert (
        "New-NetFirewallRule -Name $i.rule -DisplayName $i.rule_title" in APPLY_SCRIPT
    )
    assert "-Direction Inbound -Action Allow -Protocol TCP -LocalPort $i.port" in (
        APPLY_SCRIPT
    )
    assert 'Remove-NetFirewallRule -Name "$($d.rule_prefix)$account"' in APPLY_SCRIPT
    assert withdraw_run[1]["rule_prefix"] == "neutrino_vscode_port_"
    assert withdraw_run[1]["is_removed"] is True
    assert 'Remove-NetFirewallRule -Name "$($d.rule_prefix)*"' in WITHDRAW_SCRIPT


def test_the_digest_moves_with_the_login_and_the_port():
    def description(**changes):
        instance = {
            "account": "hanha",
            "port": 8000,
            "token": "t-1",
            "password": "pw",
            **changes,
        }
        powershell = FakePowerShell()
        VscodeWindowsApplier(root=ROOT, powershell=powershell).apply(
            VscodeConfig.from_dict({"instances": [instance]})
        )
        return powershell.runs[0][1]["instances"][0]["description"]

    assert description() == description()
    assert description(password="new") != description()
    assert description(port=8001) != description()


def test_a_path_with_spaces_is_quoted_inside_the_command():
    arguments = task_arguments(
        "C:\\Program Data\\vscode\\code.exe",
        ["serve-web", "--port", "8000"],
        "C:\\Program Data\\vscode\\ann.log",
    )

    assert arguments == (
        '/s /c ""C:\\Program Data\\vscode\\code.exe" serve-web --port 8000 '
        '>> "C:\\Program Data\\vscode\\ann.log" 2>&1"'
    )


def test_the_log_paths_name_each_instance_with_or_without_a_config():
    read = {"tasks": [{"name": "neutrino_vscode_ann", "state": "Running"}]}
    applier = VscodeWindowsApplier(
        root=ROOT, powershell=FakePowerShell({STATUS_SCRIPT: read})
    )

    assert applier.log_paths(CONFIG) == [
        ("hanha", "C:\\ProgramData\\Neutrino\\agent\\state\\vscode\\hanha.log")
    ]
    assert applier.log_paths(None) == [
        ("ann", "C:\\ProgramData\\Neutrino\\agent\\state\\vscode\\ann.log")
    ]


def test_a_refused_login_is_credential_invalid():
    error = ModuleApplyError("credential_invalid", {"account": "hanha"})
    applier = VscodeWindowsApplier(root=ROOT, powershell=FakePowerShell(error=error))

    with pytest.raises(ModuleApplyError) as refused:
        applier.apply(CONFIG)

    assert refused.value.code == "credential_invalid"
    assert "Send-Refusal 'credential_invalid'" in APPLY_SCRIPT


def test_the_states_read_each_task_and_its_last_result():
    read = {
        "tasks": [
            {
                "name": "neutrino_vscode_hanha",
                "state": "Ready",
                "last_result": -2147023570,
                "arguments": "serve-web --port 8000",
            }
        ]
    }
    applier = VscodeWindowsApplier(
        root=ROOT, powershell=FakePowerShell({STATUS_SCRIPT: read})
    )

    assert applier.states(CONFIG) == [
        {
            "account": "hanha",
            "port": 8000,
            "url": "http://127.0.0.1:8000/",
            "is_running": False,
            "code": "credential_invalid",
        }
    ]
    assert applier.states(None)[0]["port"] == 8000


def test_a_status_powershell_cannot_give_reads_as_nothing_running():
    applier = VscodeWindowsApplier(
        root=ROOT, powershell=FakePowerShell(error=OSError("gone"))
    )

    assert applier.states(CONFIG)[0]["is_running"] is False


def test_stop_stops_and_remove_unregisters():
    powershell = FakePowerShell()
    applier = VscodeWindowsApplier(root=ROOT, powershell=powershell)

    applier.stop()
    applier.remove()

    assert [
        (script, document["is_removed"]) for script, document in powershell.runs
    ] == [
        (WITHDRAW_SCRIPT, False),
        (WITHDRAW_SCRIPT, True),
    ]
    assert powershell.runs[1][1]["token_dir"] == (
        "C:\\ProgramData\\Neutrino\\agent\\state\\vscode\\tokens"
    )


# --- the process tree ---

TOKEN_DIR = "C:\\ProgramData\\Neutrino\\agent\\state\\vscode\\tokens"


def test_the_tree_is_every_process_naming_the_token_file_and_its_descendants():
    assert "Get-CimInstance Win32_Process" in TREE_FUNCTIONS
    assert '"$($_.CommandLine)".Contains($mark)' in TREE_FUNCTIONS
    assert "$child.ParentProcessId -eq $parent.ProcessId" in TREE_FUNCTIONS
    assert "$child.CreationDate -ge $parent.CreationDate" in TREE_FUNCTIONS
    stop = TREE_FUNCTIONS[TREE_FUNCTIONS.index("function Stop-Instance") :]
    assert stop.index("Get-InstanceTree $mark") < stop.index("Stop-ScheduledTask")
    assert stop.index("Stop-ScheduledTask") < stop.index("Stop-Process")
    assert "Stop-Process -Id $process.ProcessId -Force" in stop


def test_every_stop_ends_the_whole_tree():
    for script in (APPLY_SCRIPT, WITHDRAW_SCRIPT, STATUS_SCRIPT):
        assert script.startswith(TREE_FUNCTIONS)
    for script in (APPLY_SCRIPT, WITHDRAW_SCRIPT):
        body = script[len(TREE_FUNCTIONS) :]
        assert "Stop-ScheduledTask" not in body
    assert "Stop-Instance $task.TaskName (Get-TokenFile $task.TaskName)" in (
        WITHDRAW_SCRIPT
    )
    assert "if ($task) { Stop-Instance $i.task $i.token_file }" in APPLY_SCRIPT


def test_a_start_first_ends_what_is_left_of_the_instance():
    body = APPLY_SCRIPT[len(TREE_FUNCTIONS) :]
    start = body.index("Start-ScheduledTask -TaskName $i.task")
    assert body.rindex("Stop-Instance $i.task $i.token_file", 0, start) > body.index(
        ".State -ne 'Running'"
    )


def test_each_script_is_given_the_token_directory():
    powershell = FakePowerShell()
    applier = VscodeWindowsApplier(root=ROOT, powershell=powershell)

    applier.apply(CONFIG)
    applier.stop()
    applier.states(CONFIG)

    assert [document["token_dir"] for _, document in powershell.runs] == [TOKEN_DIR] * 3


def test_an_instance_runs_only_while_its_tree_listens_on_its_port():
    def states(task_state, is_listening):
        read = {
            "tasks": [
                {
                    "name": "neutrino_vscode_hanha",
                    "state": task_state,
                    "last_result": 0,
                    "arguments": "serve-web --port 8000",
                    "is_listening": is_listening,
                }
            ]
        }
        applier = VscodeWindowsApplier(
            root=ROOT, powershell=FakePowerShell({STATUS_SCRIPT: read})
        )
        return applier.states(CONFIG)[0]["is_running"]

    assert states("Running", True) is True
    assert states("Running", False) is False
    assert states("Ready", True) is True
    assert "Test-InstanceListening (Get-TokenFile $task.TaskName)" in STATUS_SCRIPT
    assert "Get-NetTCPConnection -State Listen -LocalPort $port" in TREE_FUNCTIONS
