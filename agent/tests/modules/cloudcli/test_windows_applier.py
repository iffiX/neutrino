"""CloudCLI on Windows, with PowerShell faked.

What these pin: an account whose app directory holds no CloudCLI gets an
install task with its login that is started and left to run; while the
task runs the apply waits on it, starts no instance, and the account's log
is the install's; an ended task is unregistered and judged by its result
and by the app directory, a failure naming its step; each instance is a
task with its login running a script that sets the instance's environment
and keeps the account's ``PATH``; a refused login is
``credential_invalid``; and a task Windows cannot sign in reads so.
"""

import ntpath

import pytest

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.cloudcli import installer
from neutrino_agent.modules.cloudcli.config import CloudcliConfig
from neutrino_agent.modules.cloudcli.installer import NATIVE_CHECK_EXIT
from neutrino_agent.modules.cloudcli.windows_applier import (
    APPLY_SCRIPT,
    FINISH_INSTALL_SCRIPT,
    INSTALL_SCRIPT,
    STATUS_SCRIPT,
    CloudcliWindowsApplier,
    render_install_script,
)

CONFIG = CloudcliConfig.from_dict(
    {
        "gateway_url": "http://10.0.0.1:8317",
        "gateway_key": "device-key",
        "instances": [
            {
                "account": "ann",
                "port": 3001,
                "web_password": "p",
                "token_secret": "s",
                "password": "login-pw",
            }
        ],
    }
)


class PowerShell:
    def __init__(self):
        self.calls: list = []
        self.answers: dict = {}
        self.install_tasks: list = []

    def __call__(self, script, document, timeout_s=120):
        self.calls.append((script, document, timeout_s))
        if script == STATUS_SCRIPT and document["prefix"].endswith("install_"):
            return {"tasks": list(self.install_tasks)}
        answer = self.answers.get(script, {})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def scripts(self) -> list:
        return [
            "install status" if script == STATUS_SCRIPT else script
            for script, _document, _timeout in self.calls
        ]


def install_task(state, last_result=0):
    return {
        "name": "neutrino_cloudcli_install_ann",
        "state": state,
        "last_result": last_result,
    }


@pytest.fixture
def powershell():
    return PowerShell()


@pytest.fixture
def ready(monkeypatch):
    """Whether the app directory holds CloudCLI and its native modules."""
    held = {"is_ready": False}
    monkeypatch.setattr(installer, "is_app_ready", lambda app: held["is_ready"])
    return held


@pytest.fixture
def applier(powershell, tmp_path, ready):
    module_dir = tmp_path / "Neutrino" / "cloudcli"
    (module_dir / "node-v22.23.3-win-x64").mkdir(parents=True)

    def home(account):
        if account != "ann":
            raise KeyError(account)
        return "C:\\Users\\ann"

    return CloudcliWindowsApplier(
        module_dir=str(module_dir),
        record_dir="C:\\ProgramData\\Neutrino\\agent\\config\\cloudcli",
        account_home=home,
        powershell=powershell,
    )


def test_an_install_is_started_and_left_to_run(applier, powershell):
    with pytest.raises(ModuleInstallPending):
        applier.apply(CONFIG, {"ann": 41234})

    assert powershell.scripts() == ["install status", INSTALL_SCRIPT]
    _script, document, _timeout = powershell.calls[1]
    assert document["account"] == "ann"
    assert document["password"] == "login-pw"
    assert document["task"] == "neutrino_cloudcli_install_ann"
    assert "@cloudcli-ai/cloudcli@1.37.3" in document["script_text"]
    assert document["timeout_s"] > 1800
    assert "Start-ScheduledTask" in INSTALL_SCRIPT
    assert "Unregister-ScheduledTask" not in INSTALL_SCRIPT
    assert applier.installing == {"ann"}
    assert applier.log_paths(["ann"]) == [("ann", applier.install_log_path("ann"))]


@pytest.mark.parametrize("state", ["Running", "Queued"])
def test_a_running_install_starts_nothing_and_keeps_waiting(applier, powershell, state):
    powershell.install_tasks = [install_task(state, 0x41301)]

    with pytest.raises(ModuleInstallPending):
        applier.apply(CONFIG, {"ann": 41234})

    assert powershell.scripts() == ["install status"]
    assert applier.installing == {"ann"}


def test_an_ended_install_is_unregistered_and_the_instance_starts(
    applier, powershell, ready
):
    powershell.install_tasks = [install_task("Ready", 0)]
    powershell.answers[APPLY_SCRIPT] = {"notes": ["registered CloudCLI of ann"]}
    ready["is_ready"] = True

    notes = applier.apply(CONFIG, {"ann": 41234})

    assert powershell.scripts() == [
        "install status",
        FINISH_INSTALL_SCRIPT,
        APPLY_SCRIPT,
    ]
    assert powershell.calls[1][1]["task"] == "neutrino_cloudcli_install_ann"
    assert notes == ["installed CloudCLI for ann", "registered CloudCLI of ann"]
    assert applier.installing == frozenset()
    assert applier.log_paths(["ann"]) == [("ann", applier.log_path("ann"))]


def test_an_app_already_there_starts_the_instance_at_once(applier, powershell, ready):
    ready["is_ready"] = True

    assert applier.apply(CONFIG, {"ann": 41234}) == []
    assert powershell.scripts() == ["install status", APPLY_SCRIPT]


def test_an_instance_is_a_task_running_its_script(applier, powershell, ready):
    ready["is_ready"] = True
    applier.apply(CONFIG, {"ann": 41234})

    _script, document, _timeout = powershell.calls[1]
    (instance,) = document["instances"]
    assert instance["task"] == "neutrino_cloudcli_ann"
    assert instance["password"] == "login-pw"
    assert instance["port"] == 3001
    assert "rule" not in instance
    assert "New-NetFirewallRule" not in APPLY_SCRIPT
    assert document["rule_prefix"] == "neutrino_cloudcli_port_"
    assert 'Get-NetFirewallRule -Name "$($d.rule_prefix)*"' in APPLY_SCRIPT
    assert "$stale | Remove-NetFirewallRule" in APPLY_SCRIPT
    text = instance["script_text"]
    assert 'set "HOST=127.0.0.1"' in text
    assert 'set "SERVER_PORT=41234"' in text
    assert "ANTHROPIC" not in text and "OPENAI" not in text
    node_dir = ntpath.dirname(applier.node)
    assert f'set "PATH={node_dir};%PATH%"' in text
    assert "node.exe" in text and "index.js" in text
    assert instance["arguments"].startswith("/s /c ")
    assert instance["description"].startswith("neutrino:")


@pytest.mark.parametrize(
    "result, output, is_ready, expected",
    [
        (
            NATIVE_CHECK_EXIT,
            "npm ok\nnode-pty\n",
            False,
            (
                "cloudcli_native_module_failed",
                {"account": "ann", "module": "node-pty", "detail": "node-pty"},
            ),
        ),
        (
            1,
            "npm error network",
            False,
            (
                "cloudcli_npm_install_failed",
                {"account": "ann", "detail": "npm error network"},
            ),
        ),
        (
            0,
            "",
            False,
            ("cloudcli_npm_install_failed", {"account": "ann", "detail": ""}),
        ),
        (0x8007052E, "", False, ("credential_invalid", {"account": "ann"})),
    ],
)
def test_a_failed_install_names_its_step(
    applier, powershell, ready, result, output, is_ready, expected
):
    powershell.install_tasks = [install_task("Ready", result)]
    powershell.answers[FINISH_INSTALL_SCRIPT] = {"output": output}
    ready["is_ready"] = is_ready

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG, {"ann": 41234})

    assert (caught.value.code, caught.value.params) == expected
    assert powershell.scripts() == ["install status", FINISH_INSTALL_SCRIPT]
    assert applier.installing == frozenset()


def test_a_refused_login_is_credential_invalid(applier, powershell):
    powershell.answers[INSTALL_SCRIPT] = ModuleApplyError(
        "credential_invalid", {"account": "ann"}
    )

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG, {"ann": 41234})

    assert caught.value.code == "credential_invalid"


def test_an_account_without_a_profile_is_unknown(applier, powershell):
    config = CloudcliConfig.from_dict(
        {
            "instances": [
                {
                    "account": "ghost",
                    "port": 3001,
                    "web_password": "p",
                    "token_secret": "s",
                    "password": "x",
                }
            ]
        }
    )

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(config, {"ghost": 41234})

    assert caught.value.code == "account_unknown"
    assert powershell.calls == []


def test_a_task_windows_cannot_sign_in_reads_so(applier, powershell):
    powershell.answers[STATUS_SCRIPT] = {
        "tasks": [
            {
                "name": "neutrino_cloudcli_ann",
                "state": "Ready",
                "last_result": -2147023570,
            }
        ]
    }

    assert applier.states(["ann"]) == {
        "ann": {"is_running": False, "code": "credential_invalid"}
    }


def test_the_install_script_names_the_registry_the_state_names():
    text = render_install_script(
        app="C:\\Users\\ann\\AppData\\Local\\Neutrino\\agent\\cloudcli\\app",
        node="C:\\ProgramData\\Neutrino\\agent\\state\\cloudcli\\n\\node.exe",
        npm="C:\\ProgramData\\Neutrino\\agent\\state\\cloudcli\\n\\npm-cli.js",
        registry="https://registry.npmmirror.com",
    )

    assert 'set "npm_config_registry=https://registry.npmmirror.com"' in text.split(
        "\r\n"
    )


def test_the_install_script_checks_the_native_modules_after_npm():
    text = render_install_script(
        app="C:\\Users\\ann\\AppData\\Local\\Neutrino\\agent\\cloudcli\\app",
        node="C:\\ProgramData\\Neutrino\\agent\\state\\cloudcli\\n\\node.exe",
        npm="C:\\ProgramData\\Neutrino\\agent\\state\\cloudcli\\n\\node_modules\\npm\\bin\\npm-cli.js",
    )

    lines = text.split("\r\n")
    assert (
        'type nul > "C:\\Users\\ann\\AppData\\Local\\Neutrino\\agent\\cloudcli\\app\\.npmrc"'
        in lines
    )
    assert any(line.endswith("|| exit /b 1") for line in lines)
    path_line = (
        'set "PATH=C:\\ProgramData\\Neutrino\\agent\\state\\cloudcli\\n;'
        '%SystemRoot%\\System32;%SystemRoot%;%PATH%"'
    )
    npm_line = next(index for index, line in enumerate(lines) if "npm-cli" in line)
    assert lines.index(path_line) < npm_line
    assert "createRequire" in lines[-2]
