"""VS Code's servers on Windows, with PowerShell faked.

What these pin: one script registers a task per instance, signed in with the
account's login, started at boot with no time limit and a limited token; the
login and the token travel in the script's document; the task's description
carries a digest that moves when what it runs or its login changes; a
refused login comes back as ``credential_invalid``, and a task whose last
start could not sign in reads it too.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.vscode.windows_applier import (
    APPLY_SCRIPT,
    STATUS_SCRIPT,
    WITHDRAW_SCRIPT,
    VscodeWindowsApplier,
)

ROOT = "C:\\ProgramData\\Neutrino"
CONFIG = VscodeConfig.from_dict(
    {
        "address": "192.168.1.9",
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
    assert document["program"] == "C:\\ProgramData\\Neutrino\\vscode\\code.exe"
    assert document["tasks"] == ["neutrino_vscode_hanha"]
    (instance,) = document["instances"]
    token_file = "C:\\ProgramData\\Neutrino\\vscode\\tokens\\hanha.token"
    assert instance["account"] == "hanha"
    assert instance["password"] == "pw"
    assert instance["token"] == "t-1"
    assert instance["token_file"] == token_file
    assert instance["arguments"] == (
        "serve-web --accept-server-license-terms --host 192.168.1.9 --port 8000 "
        f"--connection-token-file {token_file}"
    )
    assert instance["description"].startswith("neutrino:")
    assert "pw" not in instance["description"]
    assert "-User $i.account -Password $i.password -RunLevel Limited" in APPLY_SCRIPT
    assert "New-ScheduledTaskTrigger -AtStartup" in APPLY_SCRIPT
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in APPLY_SCRIPT


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
            "url": "http://192.168.1.9:8000/",
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
        "C:\\ProgramData\\Neutrino\\vscode\\tokens"
    )
