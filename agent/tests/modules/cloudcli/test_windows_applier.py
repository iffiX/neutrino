"""CloudCLI on Windows, with PowerShell faked.

What these pin: an account whose app directory holds no CloudCLI is
installed once by a task with its login, and a failure names its step; each
instance is a task with its login running a script that sets the
instance's environment and keeps the account's ``PATH``; a refused login
is ``credential_invalid``; and a task Windows cannot sign in reads so.
"""

import ntpath

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli.config import CloudcliConfig
from neutrino_agent.modules.cloudcli.installer import NATIVE_CHECK_EXIT
from neutrino_agent.modules.cloudcli.windows_applier import (
    APPLY_SCRIPT,
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

    def __call__(self, script, document, timeout_s=120):
        self.calls.append((script, document, timeout_s))
        answer = self.answers.get(script, {})
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def powershell():
    return PowerShell()


@pytest.fixture
def applier(powershell, tmp_path):
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


def test_an_account_is_installed_by_a_task_with_its_login(applier, powershell):
    powershell.answers[INSTALL_SCRIPT] = {"exit_code": 0, "output": ""}
    powershell.answers[APPLY_SCRIPT] = {"notes": ["registered CloudCLI of ann"]}

    notes = applier.apply(CONFIG, {"ann": 41234})

    script, document, timeout_s = powershell.calls[0]
    assert script == INSTALL_SCRIPT
    assert document["account"] == "ann"
    assert document["password"] == "login-pw"
    assert document["task"] == "neutrino_cloudcli_install_ann"
    assert "@cloudcli-ai/cloudcli@1.37.3" in document["script_text"]
    assert timeout_s > 1800
    assert notes == ["installed CloudCLI for ann", "registered CloudCLI of ann"]


def test_an_instance_is_a_task_running_its_script(applier, powershell):
    powershell.answers[INSTALL_SCRIPT] = {"exit_code": 0, "output": ""}
    applier.apply(CONFIG, {"ann": 41234})

    _script, document, _timeout = powershell.calls[1]
    (instance,) = document["instances"]
    assert instance["task"] == "neutrino_cloudcli_ann"
    assert instance["password"] == "login-pw"
    assert instance["port"] == 3001
    assert instance["rule"] == "neutrino_cloudcli_port_ann"
    text = instance["script_text"]
    assert 'set "HOST=127.0.0.1"' in text
    assert 'set "SERVER_PORT=41234"' in text
    assert 'set "ANTHROPIC_AUTH_TOKEN=device-key"' in text
    node_dir = ntpath.dirname(applier.node)
    assert f'set "PATH={node_dir};%PATH%"' in text
    assert "node.exe" in text and "index.js" in text
    assert instance["arguments"].startswith("/s /c ")
    assert instance["description"].startswith("neutrino:")


@pytest.mark.parametrize(
    "answer, expected",
    [
        (
            {"exit_code": NATIVE_CHECK_EXIT, "output": "npm ok\nnode-pty\n"},
            ("cloudcli_native_module_failed", {"account": "ann", "module": "node-pty"}),
        ),
        (
            {"exit_code": 1, "output": "npm error network"},
            ("cloudcli_npm_install_failed", {"account": "ann"}),
        ),
    ],
)
def test_a_failed_install_names_its_step(applier, powershell, answer, expected):
    powershell.answers[INSTALL_SCRIPT] = answer

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG, {"ann": 41234})

    assert (caught.value.code, caught.value.params) == expected
    assert len(powershell.calls) == 1


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
