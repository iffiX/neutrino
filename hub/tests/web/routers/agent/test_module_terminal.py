"""The Terminal block: the account and the shell program a terminal runs.

What these pin: the view reads the two settings and the machine's
accounts, and says whether an account can be set there, false on Windows;
a set is checked on the agent as the agent will receive it, a Windows
machine receiving no account, then stored and pushed; an account the
machine did not report and a shell program that is not an absolute path are
refused by code before the agent is asked, and the agent's own refusal is
the route's; the state sends the module to every device with ``want``
running.
"""

import json

import pytest

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.web.routers.agent import module_terminal
from tests.web.module_api_box import DEVICE, module_box

BASE = "/api/agent/module/terminal"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    client, runtime = module_box(monkeypatch, tmp_path, module_terminal.router)
    runtime.device_accounts[DEVICE] = ["alice", "bob"]
    with client:
        yield client, runtime, tmp_path


def stored(tmp_path) -> dict:
    return json.loads((tmp_path / "devices" / DEVICE / "terminal.json").read_text())


def test_the_view_reads_the_settings_and_the_accounts(api):
    client, runtime, _ = api
    runtime.device_platform[DEVICE] = LINUX
    DesiredStateStore().write(
        DEVICE, "terminal", {"account": "alice", "shell_path": "/bin/zsh"}
    )

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert (view["account"], view["shell_path"]) == ("alice", "/bin/zsh")
    assert view["accounts"] == ["alice", "bob"]
    assert view["is_account_settable"] is True


def test_a_set_is_checked_as_the_agent_receives_it_then_stored_and_pushed(api):
    client, runtime, tmp_path = api
    runtime.device_platform[DEVICE] = LINUX

    answer = client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "account": "bob", "shell_path": "/usr/bin/fish"},
    )

    assert answer.status_code == 200
    assert runtime.agent_sessions.validations == [
        (DEVICE, "terminal", {"account": "bob", "shell_path": "/usr/bin/fish"})
    ]
    assert stored(tmp_path) == {"account": "bob", "shell_path": "/usr/bin/fish"}
    assert len(runtime.agent_sessions.pushes) == 1


def test_a_windows_machine_takes_the_shell_program_alone(api):
    client, runtime, _ = api
    runtime.device_platform[DEVICE] = WINDOWS
    shell = "C:\\Program Files\\PowerShell\\7\\pwsh.exe"

    answer = client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "account": "anyone", "shell_path": shell},
    )
    desired, _ = DesiredStateStore().compose(DEVICE, WINDOWS)

    assert answer.json()["is_account_settable"] is False
    assert runtime.agent_sessions.validations[0][2] == {
        "account": "",
        "shell_path": shell,
    }
    assert desired["modules"]["terminal"] == {
        "want": "running",
        "config": {"account": "", "shell_path": shell},
    }


@pytest.mark.parametrize(
    "body, code",
    [
        ({"account": "mallory"}, ("account_unknown", {"account": "mallory"})),
        ({"shell_path": "bin/zsh"}, ("path_invalid", {"path": "bin/zsh"})),
    ],
)
def test_a_setting_the_machine_cannot_have_is_refused_before_the_agent(api, body, code):
    client, runtime, _ = api
    runtime.device_platform[DEVICE] = LINUX

    answer = client.post(f"{BASE}/set", json={"device_id": DEVICE, **body})

    assert answer.status_code == 400
    assert (answer.json()["detail"]["code"], answer.json()["detail"]["params"]) == code
    assert runtime.agent_sessions.validations == []


def test_the_agents_refusal_of_a_shell_program_is_the_routes(api):
    client, runtime, tmp_path = api
    runtime.device_platform[DEVICE] = LINUX
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "shell_program_unusable",
        "params": {"path": "/bin/none"},
    }

    answer = client.post(
        f"{BASE}/set", json={"device_id": DEVICE, "shell_path": "/bin/none"}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "shell_program_unusable"
    assert not (tmp_path / "devices" / DEVICE / "terminal.json").exists()


def test_every_device_is_sent_the_module_with_its_default(api):
    _, _, _ = api

    desired, _ = DesiredStateStore().compose(DEVICE, LINUX)

    assert desired["modules"]["terminal"] == {
        "want": "running",
        "config": {"account": "", "shell_path": ""},
    }
