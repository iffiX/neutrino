"""Instances on Windows, with PowerShell faked.

What these pin: a register writes the account's files and its log,
reachable by the account, SYSTEM and the administrators alone, and
registers a task signed in with the account's login, started at boot with
no time limit and a limited token; a service with an environment or a
working directory runs a script, a bare one runs the program itself; the
task's description carries a digest that moves when what it runs, its
login or a file it reads changes; a stop ends the instance's whole process
tree, taken before the task stops; a start first ends what is left of the
instance; an instance whose service names a port runs only while its tree
listens on it, any other while its task runs; a task Windows cannot sign in
reads ``credential_invalid``; and a remove unregisters the task and deletes
what it ran from.
"""

import json

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.account_service import (
    AccountService,
    ServiceMachine,
)
from neutrino_agent.modules.shared.account_service.windows import (
    FORGET_SCRIPT,
    REGISTER_SCRIPT,
    REMOVE_SCRIPT,
    START_SCRIPT,
    STATUS_SCRIPT,
    STOP_SCRIPT,
    TREE_FUNCTIONS,
    render_script,
    task_arguments,
)

MODULE_DIR = "C:\\ProgramData\\Neutrino\\agent\\state\\demo"
LOG = MODULE_DIR + "\\hanha.log"


class FakePowerShell:
    def __init__(self, answers=None, error=None):
        self.runs: list = []
        self._answers = dict(answers or {})
        self._error = error

    def __call__(self, script, document, timeout_s=120):
        self.runs.append((script, json.loads(json.dumps(document))))
        if self._error is not None:
            raise self._error
        return dict(self._answers.get(script, {}))


def service_with(**changes) -> AccountService:
    fields = {
        "name": "demo",
        "title": "Demo",
        "account": "hanha",
        "command": (MODULE_DIR + "\\demo.exe", "--port", "8000"),
        "password": "pw",
    }
    fields.update(changes)
    return AccountService(**fields)


def machine_with(powershell) -> ServiceMachine:
    return ServiceMachine(
        os_name="windows",
        module_dir=MODULE_DIR,
        record_dir="C:\\ProgramData\\Neutrino\\agent\\config\\demo",
        lookup_account=lambda account: None,
        powershell=powershell,
    )


def test_a_bare_service_is_a_task_running_the_program_itself():
    powershell = FakePowerShell({REGISTER_SCRIPT: {"is_registered": True}})
    token = MODULE_DIR + "\\tokens\\hanha.token"
    service = service_with(files=((token, "t-1"),), listen_port=8000)

    assert account_service.write(service, machine_with(powershell)) is True

    ((script, document),) = powershell.runs
    assert script == REGISTER_SCRIPT
    assert document["account"] == "hanha"
    assert document["password"] == "pw"
    assert document["task"] == "neutrino_demo_hanha"
    assert document["program"] == "cmd.exe"
    assert document["arguments"] == (
        f'/s /c "{MODULE_DIR}\\demo.exe --port 8000 >> {LOG} 2>&1"'
    )
    assert document["files"] == [{"path": token, "text": "t-1"}]
    assert document["log_file"] == LOG and document["mark"] == LOG
    assert document["rule_prefix"] == "neutrino_demo_port_"
    assert document["description"].startswith("neutrino:")
    assert "pw" not in document["description"]


def test_a_service_with_an_environment_runs_a_script():
    powershell = FakePowerShell({REGISTER_SCRIPT: {"is_registered": False}})
    service = service_with(
        command=("C:\\node\\node.exe", "C:\\app\\index.js"),
        environment={"HOST": "127.0.0.1", "PATH": "C:\\node;%PATH%"},
        working_directory="~",
    )

    assert account_service.write(service, machine_with(powershell)) is False

    ((_script, document),) = powershell.runs
    script_path = MODULE_DIR + "\\run\\hanha.cmd"
    assert document["arguments"] == f'/s /c "{script_path} >> {LOG} 2>&1"'
    (file,) = document["files"]
    assert file["path"] == script_path
    assert file["text"] == (
        "@echo off\r\n"
        'set "HOST=127.0.0.1"\r\n'
        'set "PATH=C:\\node;%PATH%"\r\n'
        'cd /d "%USERPROFILE%"\r\n'
        "C:\\node\\node.exe C:\\app\\index.js\r\n"
    )


def test_a_script_without_a_working_directory_enters_none():
    text = render_script(service_with(environment={"A": "1"}))

    assert (
        text == "@echo off\r\n"
        'set "A=1"\r\n'
        f"{MODULE_DIR}\\demo.exe --port 8000\r\n"
    )


def test_the_registration_is_a_boot_task_under_the_login_with_no_time_limit():
    assert "-User $d.account -Password $d.password -RunLevel Limited" in REGISTER_SCRIPT
    assert "New-ScheduledTaskTrigger -AtStartup" in REGISTER_SCRIPT
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in REGISTER_SCRIPT
    assert '"$($d.account):R"' in REGISTER_SCRIPT
    assert '"$($d.account):M"' in REGISTER_SCRIPT
    assert "Send-Refusal 'credential_invalid'" in REGISTER_SCRIPT
    assert 'Get-NetFirewallRule -Name "$($d.rule_prefix)*"' in REGISTER_SCRIPT
    assert "$stale | Remove-NetFirewallRule" in REGISTER_SCRIPT
    assert "New-NetFirewallRule" not in REGISTER_SCRIPT


def test_the_digest_moves_with_the_login_the_command_and_a_file():
    def description(**changes):
        powershell = FakePowerShell()
        account_service.write(service_with(**changes), machine_with(powershell))
        return powershell.runs[0][1]["description"]

    assert description() == description()
    assert description(password="new") != description()
    assert description(command=(MODULE_DIR + "\\demo.exe", "--port", "8001")) != (
        description()
    )
    assert description(files=(("C:\\t", "a"),)) != description(files=(("C:\\t", "b"),))


def test_a_refused_login_is_credential_invalid():
    error = ModuleApplyError("credential_invalid", {"account": "hanha"})
    powershell = FakePowerShell(error=error)

    with pytest.raises(ModuleApplyError) as refused:
        account_service.write(service_with(), machine_with(powershell))

    assert refused.value.code == "credential_invalid"


def test_a_path_with_spaces_is_quoted_inside_the_command():
    arguments = task_arguments(
        "C:\\Program Data\\demo\\demo.exe",
        ["--port", "8000"],
        "C:\\Program Data\\demo\\ann.log",
    )

    assert arguments == (
        '/s /c ""C:\\Program Data\\demo\\demo.exe" --port 8000 '
        '>> "C:\\Program Data\\demo\\ann.log" 2>&1"'
    )


def test_start_stop_and_remove_name_the_task_and_its_mark():
    powershell = FakePowerShell()
    machine = machine_with(powershell)
    token = MODULE_DIR + "\\tokens\\hanha.token"
    service = service_with(files=((token, "t"),), directories=(MODULE_DIR + "\\d",))

    account_service.start(service, machine, is_restart=True)
    account_service.stop(service, machine)
    account_service.remove(service, machine)

    assert [script for script, _ in powershell.runs] == [
        START_SCRIPT,
        STOP_SCRIPT,
        REMOVE_SCRIPT,
    ]
    for _script, document in powershell.runs:
        assert document["task"] == "neutrino_demo_hanha"
        assert document["mark"] == LOG
    assert powershell.runs[2][1]["paths"] == [
        token,
        MODULE_DIR + "\\run\\hanha.cmd",
        LOG,
        MODULE_DIR + "\\d",
    ]
    assert "Unregister-ScheduledTask -TaskName $d.task" in REMOVE_SCRIPT


def test_the_states_read_each_task_its_port_and_its_last_result():
    read = {
        "tasks": [
            {
                "name": "neutrino_demo_hanha",
                "state": "Ready",
                "last_result": -2147023570,
                "is_listening": True,
            },
            {"name": "neutrino_demo_bob", "state": "Running", "last_result": 0},
        ]
    }
    powershell = FakePowerShell({STATUS_SCRIPT: read})
    services = [service_with(listen_port=8000), service_with(account="bob")]

    states = account_service.states(services, machine_with(powershell))

    assert states == {
        "hanha": {"is_running": True, "code": "credential_invalid"},
        "bob": {"is_running": True, "code": ""},
    }
    ((_script, document),) = powershell.runs
    assert document["prefix"] == "neutrino_demo_"
    assert document["ports"] == {"neutrino_demo_hanha": 8000}
    assert document["marks"] == {
        "neutrino_demo_hanha": LOG,
        "neutrino_demo_bob": MODULE_DIR + "\\bob.log",
    }


def test_an_instance_with_a_port_runs_only_while_its_tree_listens_on_it():
    def is_running(task_state, is_listening, listen_port):
        read = {
            "tasks": [
                {
                    "name": "neutrino_demo_hanha",
                    "state": task_state,
                    "last_result": 0,
                    "is_listening": is_listening,
                }
            ]
        }
        powershell = FakePowerShell({STATUS_SCRIPT: read})
        states = account_service.states(
            [service_with(listen_port=listen_port)], machine_with(powershell)
        )
        return states["hanha"]["is_running"]

    assert is_running("Running", True, 8000) is True
    assert is_running("Running", False, 8000) is False
    assert is_running("Ready", True, 8000) is True
    assert is_running("Running", False, 0) is True
    assert is_running("Ready", True, 0) is False
    assert "Test-InstanceListening $d.marks.($task.TaskName)" in STATUS_SCRIPT


def test_a_status_powershell_cannot_give_reads_as_nothing_running():
    powershell = FakePowerShell(error=OSError("gone"))

    states = account_service.states([service_with()], machine_with(powershell))

    assert states == {"hanha": {"is_running": False, "code": ""}}
    assert account_service.states([], machine_with(powershell)) == {}


def test_forget_removes_the_rules_an_older_build_opened():
    powershell = FakePowerShell()

    account_service.forget("demo", machine_with(powershell))

    assert powershell.runs == [(FORGET_SCRIPT, {"rule_prefix": "neutrino_demo_port_"})]
    assert 'Remove-NetFirewallRule -Name "$($d.rule_prefix)*"' in FORGET_SCRIPT


# --- the process tree ---


def test_the_tree_is_every_process_naming_the_mark_and_its_descendants():
    assert "Get-CimInstance Win32_Process" in TREE_FUNCTIONS
    assert '"$($_.CommandLine)".Contains($mark)' in TREE_FUNCTIONS
    assert "$child.ParentProcessId -eq $parent.ProcessId" in TREE_FUNCTIONS
    assert "$child.CreationDate -ge $parent.CreationDate" in TREE_FUNCTIONS
    stop = TREE_FUNCTIONS[TREE_FUNCTIONS.index("function Stop-Instance") :]
    assert stop.index("Get-InstanceTree $mark") < stop.index("Stop-ScheduledTask")
    assert stop.index("Stop-ScheduledTask") < stop.index("Stop-Process")
    assert "Stop-Process -Id $process.ProcessId -Force" in stop
    assert "Get-NetTCPConnection -State Listen -LocalPort $port" in TREE_FUNCTIONS


def test_every_stop_ends_the_whole_tree():
    for script in (REGISTER_SCRIPT, START_SCRIPT, STOP_SCRIPT, REMOVE_SCRIPT):
        assert script.startswith(TREE_FUNCTIONS)
        body = script[len(TREE_FUNCTIONS) :]
        assert "Stop-ScheduledTask" not in body
    assert "if ($task) { Stop-Instance $d.task $d.mark }" in REGISTER_SCRIPT
    assert (
        STOP_SCRIPT[len(TREE_FUNCTIONS) :]
        .strip()
        .startswith("Stop-Instance $d.task $d.mark")
    )


def test_a_start_first_ends_what_is_left_of_the_instance():
    body = START_SCRIPT[len(TREE_FUNCTIONS) :]

    assert body.index(".State -ne 'Running'") < body.index("Stop-Instance $d.task")
    assert body.index("Stop-Instance $d.task") < body.index("Start-ScheduledTask")
