"""ComfyUI on Windows: the task registered as LOCAL SERVICE under a digest of its script and left running while the script is the same; a command as LOCAL SERVICE run in a one-shot task of LOCAL SERVICE's whose script sets ``UV_STACK_SIZE`` and writes its output to a file in the data directory, its last result and output read back and the task removed; the shared folders' rights set on each handle, the account's and LOCAL SERVICE's on every file and folder under them."""

import os
import types

from neutrino_agent.modules.comfyui.server import ComfyuiServer
from neutrino_agent.modules.comfyui.windows_applier import (
    ComfyuiWindowsApplier,
    render_script,
    task_description,
)

SERVER = ComfyuiServer(port=15000, index_url="https://pypi.org/simple", is_cpu=True)


class Host:
    def __init__(self):
        self.calls = []
        self.task = {"is_present": False, "description": "", "state": ""}
        self.step_states = []

    def call(self, op, request):
        self.calls.append((op, dict(request)))
        if op == "task_read":
            return dict(self.task)
        if op == "task_write_service":
            self.task = {
                "is_present": True,
                "description": request["description"],
                "state": "Ready",
            }
        if op == "task_start":
            self.task["state"] = "Running"
        if op == "task_states":
            state = self.step_states.pop(0) if self.step_states else ("Ready", 0)
            return {
                "tasks": [
                    {
                        "name": request["prefix"],
                        "state": state[0],
                        "last_result": state[1],
                    }
                ]
            }
        return {}


def windows(tmp_path, host, access=None):
    return ComfyuiWindowsApplier(
        state_dir=str(tmp_path),
        powershell=host,
        processes=None,
        folder_access=access,
        account_sid={"anna": "S-1-5-21-1-1001"}.get,
        join=os.path.join,
        sleep=lambda seconds: None,
        run_command=lambda argv, is_checked=True: types.SimpleNamespace(exit_code=0),
    )


def test_the_windows_task_runs_as_local_service_and_stays_while_its_script_is_the_same(
    tmp_path,
):
    host = Host()
    applier = windows(tmp_path, host)
    assert applier.apply(SERVER) == "started"
    written = [request for op, request in host.calls if op == "task_write_service"]
    assert written[0]["account"] == "S-1-5-19"
    assert written[0]["program"] == "cmd.exe"
    script = open(applier.script_path, newline="").read()
    assert written[0]["description"] == task_description(script)
    assert 'set "UV_STACK_SIZE=16777216"' in script
    assert script.rstrip().endswith(f">> {applier.log_path} 2>&1")
    host.calls.clear()
    assert applier.apply(SERVER) == "unchanged"
    assert not [op for op, _request in host.calls if op == "task_write_service"]


def test_a_command_as_local_service_runs_in_a_one_shot_task(tmp_path):
    host = Host()
    host.step_states = [("Ready", 0x41303), ("Running", 0x41301), ("Ready", 0)]
    applier = windows(tmp_path, host)
    os.makedirs(applier.data_dir)
    output = os.path.join(applier.data_dir, "step.log")
    open(output, "w").write("Installed 98 packages\n")
    code, words = applier.run_as_service(
        ["C:\\m\\uv\\uv.exe", "pip", "check"], {"UV_STACK_SIZE": "16777216"}, 600
    )
    assert code == 0 and "Installed 98 packages" in words
    run = [request for op, request in host.calls if op == "task_run_service"][0]
    assert run["account"] == "S-1-5-19"
    assert run["task"] == "neutrino_comfyui_step"
    assert run["timeout_s"] == 600
    script = open(
        os.path.join(applier.module_dir, "run", "step.cmd"), newline=""
    ).read()
    assert 'set "UV_STACK_SIZE=16777216"' in script
    assert f"> {output} 2>&1" in script
    assert script.rstrip().endswith("exit /b %ERRORLEVEL%")
    assert host.calls[-1] == ("task_remove", {"task": "neutrino_comfyui_step"})


class Access:
    def __init__(self, held=None):
        self.grants = []
        self.revoked = []
        self.held = held or {}

    def grant_rights(self, path, rights, *, is_folder, is_inherited):
        self.grants.append((path, list(rights), is_folder, is_inherited))

    def allowed_sids(self, path, *, is_folder=True):
        return list(self.held.get(path, ["S-1-5-18", "S-1-5-19"]))

    def revoke_sids(self, path, sids):
        if sids:
            self.revoked.append((path, list(sids)))


def test_the_windows_shared_folders_take_the_accounts_rights_on_each_handle(tmp_path):
    access = Access()
    applier = windows(tmp_path, Host(), access)
    for name in ("models", "input", "output", "user", "custom_nodes"):
        os.makedirs(os.path.join(applier.base_dir, name))
    os.makedirs(os.path.join(applier.base_dir, "models", "checkpoints"))
    open(
        os.path.join(applier.base_dir, "models", "checkpoints", "m.safetensors"), "w"
    ).close()
    open(os.path.join(applier.base_dir, "user", "comfyui.db"), "w").close()
    assert applier.write_access("anna") == []
    grants = {
        path: (rights, is_folder, is_inherited)
        for path, rights, is_folder, is_inherited in access.grants
    }
    assert grants[applier.base_dir] == ([("anna", "RX")], True, False)
    assert grants[os.path.join(applier.base_dir, "models")] == (
        [("anna", "M")],
        True,
        True,
    )
    assert grants[os.path.join(applier.base_dir, "user")] == (
        [("anna", "RX")],
        True,
        True,
    )
    assert grants[
        os.path.join(applier.base_dir, "models", "checkpoints", "m.safetensors")
    ] == (
        [("anna", "M"), ("*S-1-5-19", "M")],
        False,
        False,
    )
    assert grants[os.path.join(applier.base_dir, "user", "comfyui.db")][0] == [
        ("anna", "RX"),
        ("*S-1-5-19", "M"),
    ]
    assert windows(tmp_path / "x", Host(), Access()).write_access("") == []


def test_the_script_sets_its_environment_first():
    assert render_script(["run"], {"B": "2", "A": "1"}) == (
        '@echo off\r\nset "A=1"\r\nset "B=2"\r\nrun\r\n'
    )


def test_another_accounts_own_entries_go_from_the_shared_folders(tmp_path):
    applier = windows(tmp_path, Host())
    models = os.path.join(applier.base_dir, "models")
    for name in ("models", "input", "output", "user", "custom_nodes"):
        os.makedirs(os.path.join(applier.base_dir, name))
    access = Access(
        {
            applier.base_dir: ["S-1-5-21-1-1001", "S-1-5-21-1-1002", "S-1-5-18"],
            models: ["S-1-5-21-1-1002", "S-1-5-19"],
        }
    )
    applier._folder_access = access
    applier.write_access("anna")
    assert access.revoked == [
        (applier.base_dir, ["S-1-5-21-1-1002"]),
        (models, ["S-1-5-21-1-1002"]),
    ]
    access.revoked.clear()
    access.grants.clear()
    applier.write_access("")
    assert (applier.base_dir, ["S-1-5-21-1-1001", "S-1-5-21-1-1002"]) in access.revoked
    assert access.grants == []


def test_the_uninstall_deletes_the_steps_output_and_keeps_the_servers_log(tmp_path):
    applier = windows(tmp_path, Host())
    os.makedirs(os.path.join(applier.data_dir, "data", "models"))
    os.makedirs(applier.module_dir)
    open(os.path.join(applier.data_dir, "step.log"), "w").write("uv")
    open(applier.log_path, "w").write("comfyui")
    applier.uninstall()
    assert sorted(os.listdir(applier.data_dir)) == ["comfyui.log", "data"]
    assert not os.path.exists(applier.module_dir)
    applier.uninstall()


def test_a_service_task_names_its_account_by_its_sid_in_the_systems_language():
    from pathlib import Path

    import neutrino_agent

    library = (
        Path(neutrino_agent.__file__).parent
        / "data"
        / "windows"
        / "powershell_host.ps1"
    ).read_text(encoding="utf-8")
    for function in (
        "Register-NeutrinoServiceTask",
        "Invoke-NeutrinoServiceOneShotTask",
    ):
        body = library.split(f"function {function}(", 1)[1].split("\nfunction ", 1)[0]
        assert "-UserId (Get-NeutrinoSidName $Request.account)" in body
    assert "Translate([Security.Principal.NTAccount])" in library
