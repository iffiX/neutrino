"""Ollama on Windows: the task of SYSTEM's, its script, the publisher's app.

What these pin: the script sets ``OLLAMA_HOST``, ``OLLAMA_MODELS`` and
``OLLAMA_NO_CLOUD`` and appends the server's output to its log; an apply
registers the task as SYSTEM under a digest of the script and starts it,
leaves a running task with the same script alone, registers a changed one
again after ending the old server, and under ``stopped`` disables a task it
registered; a stop ends the task and every process of the module's
program; an uninstall unregisters the task and deletes the program and
keeps the data; the publisher's app is found in any profile.
"""

import ntpath
import os
from types import SimpleNamespace

from neutrino_agent.modules.ollama.windows_applier import (
    OllamaWindowsApplier,
    render_script,
    task_description,
)

STATE = "C:\\ProgramData\\Neutrino\\agent\\state"


class FakeHost:
    def __init__(self):
        self.calls: list = []
        self.task = {"is_present": False, "description": "", "state": ""}

    def call(self, op, request):
        self.calls.append((op, dict(request)))
        if op == "task_read":
            return dict(self.task)
        if op == "task_write_system":
            self.task = {
                "is_present": True,
                "description": request["description"],
                "state": "Ready",
            }
        if op == "task_start":
            self.task["state"] = "Running"
        if op == "task_stop":
            self.task["state"] = "Disabled"
        return {}


class FakeProcesses:
    def __init__(self, images):
        self.images = dict(images)
        self.ended: list = []

    def entries(self):
        return [SimpleNamespace(pid=pid) for pid in self.images]

    def image_path(self, pid):
        return self.images.get(pid, "")

    def end(self, pids):
        self.ended += pids
        for pid in pids:
            self.images.pop(pid, None)


def _applier(tmp_path, host, processes=None, monkeypatch=None):
    applier = OllamaWindowsApplier(
        state_dir=str(tmp_path),
        powershell=host,
        processes=processes or FakeProcesses({}),
        users_dir=str(tmp_path / "Users"),
        join=os.path.join,
        sleep=lambda seconds: None,
    )
    return applier


def test_the_script_sets_the_environment_and_appends_the_output():
    script = render_script(
        program=STATE + "\\ollama\\ollama\\ollama.exe",
        data_dir=STATE + "\\ollama_data",
        log=STATE + "\\ollama_data\\ollama.log",
    )
    lines = script.split("\r\n")
    assert lines[0] == "@echo off"
    assert 'set "OLLAMA_HOST=127.0.0.1:11434"' in lines
    assert 'set "OLLAMA_MODELS=' + STATE + '\\ollama_data\\models"' in lines
    assert 'set "OLLAMA_NO_CLOUD=1"' in lines
    assert lines[-2] == (
        STATE
        + '\\ollama\\ollama\\ollama.exe serve >> "'
        + STATE
        + '\\ollama_data\\ollama.log" 2>&1'
    )
    assert task_description(script).startswith("neutrino:")


def test_an_apply_registers_the_task_as_system_and_starts_it(tmp_path):
    host = FakeHost()
    applier = _applier(tmp_path, host)
    assert applier.apply(is_started=True) == "started"
    written = [request for op, request in host.calls if op == "task_write_system"][0]
    assert written["task"] == "neutrino_ollama"
    assert written["program"] == "cmd.exe"
    assert written["arguments"].endswith("serve.cmd")
    assert host.calls[-1] == ("task_start", {"task": "neutrino_ollama"})
    host.calls.clear()
    assert applier.apply(is_started=True) == "unchanged"
    assert [op for op, _request in host.calls] == ["task_read"]


def test_a_changed_script_ends_the_old_server_and_registers_again(tmp_path):
    host = FakeHost()
    own = os.path.join(str(tmp_path), "ollama", "ollama", "ollama.exe")
    processes = FakeProcesses({41: own, 42: "C:\\Windows\\explorer.exe"})
    applier = _applier(tmp_path, host, processes)
    host.task = {"is_present": True, "description": "neutrino:old", "state": "Running"}
    assert applier.apply(is_started=True) == "restarted"
    ops = [op for op, _request in host.calls]
    assert ops == ["task_read", "task_stop", "task_write_system", "task_start"]
    assert processes.ended == [41]


def test_a_stopped_apply_disables_the_task_it_registers(tmp_path):
    host = FakeHost()
    applier = _applier(tmp_path, host)
    assert applier.apply(is_started=False) == "written"
    assert host.calls[-1] == ("task_stop", {"task": "neutrino_ollama"})
    assert host.task["state"] == "Disabled"


def test_an_uninstall_unregisters_the_task_and_keeps_the_data(tmp_path):
    host = FakeHost()
    applier = _applier(tmp_path, host)
    applier.apply(is_started=True)
    (tmp_path / "ollama_data" / "models" / "blob").write_text("x")
    applier.uninstall()
    assert host.calls[-1] == ("task_remove", {"task": "neutrino_ollama"})
    assert not (tmp_path / "ollama").exists()
    assert (tmp_path / "ollama_data" / "models" / "blob").exists()


def test_the_publisher_s_app_is_found_in_any_profile(tmp_path):
    applier = _applier(tmp_path, FakeHost())
    assert applier.app_path() == ""
    app = tmp_path / "Users" / "ann" / "AppData" / "Local" / "Programs" / "Ollama"
    app.mkdir(parents=True)
    (app / "ollama.exe").write_text("")
    assert applier.app_path() == str(app / "ollama.exe")
