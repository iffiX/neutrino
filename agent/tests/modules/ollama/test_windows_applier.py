"""Ollama on Windows: the task of SYSTEM's, its script, the publisher's app.

What these pin: the script sets ``OLLAMA_HOST``, ``OLLAMA_MODELS`` and
``OLLAMA_NO_CLOUD`` and appends the server's output to its log; an apply
registers the task as SYSTEM under a digest of the script and starts it,
leaves a running task with the same script alone, registers a changed one
again after ending the old server, and under ``stopped`` disables a task it
registered; a stop ends the task and every process of the module's
program; an uninstall unregisters the task and deletes the program and
keeps the data. The settings' variables, the default context length among
them, are set in the script, and a change of them registers the task again
and restarts the server. The publisher's app of every profile is taken
over once: its Startup shortcut moved to ``kept/``, a junction refused, its
processes ended, at each report again; the uninstall moves each shortcut
back and opens the app again, once, as an account whose app ran.
"""

import ntpath
import os
from types import SimpleNamespace

from neutrino_agent.modules.ollama.config import OllamaConfig
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


class FakeCommands:
    def __init__(self):
        self.commands: list = []

    def run(self, command, *, is_checked=True, **kwargs):
        self.commands.append(list(command))
        return SimpleNamespace(exit_code=0, stdout="", stderr="", is_success=True)


def _profile(tmp_path, name, *, is_started=True):
    root = tmp_path / "Users" / name
    app = root / "AppData" / "Local" / "Programs" / "Ollama"
    app.mkdir(parents=True)
    (app / "ollama app.exe").write_text("")
    startup = (
        root
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )
    startup.mkdir(parents=True)
    if is_started:
        (startup / "Ollama.lnk").write_bytes(b"lnk of " + name.encode())
    return app, startup


def _taking_applier(tmp_path, processes, *, is_plain=None):
    commands = FakeCommands()
    applier = OllamaWindowsApplier(
        state_dir=str(tmp_path / "state"),
        powershell=FakeHost(),
        processes=processes,
        users_dir=str(tmp_path / "Users"),
        join=os.path.join,
        sleep=lambda seconds: None,
        run_command=commands.run,
        is_plain=is_plain or (lambda path: True),
    )
    return applier, commands


def test_the_app_of_every_profile_is_taken_over_once(tmp_path):
    app, startup = _profile(tmp_path, "ann")
    _profile(tmp_path, "bob", is_started=False)
    processes = FakeProcesses(
        {
            50: str(app / "ollama app.exe"),
            51: str(app / "ollama.exe"),
            52: "C:\\Windows\\explorer.exe",
        }
    )
    applier, _commands = _taking_applier(tmp_path, processes)
    assert applier.take_over_apps() == ["ann", "bob"]
    kept = tmp_path / "state" / "ollama" / "kept" / "ann" / "Ollama.lnk"
    assert kept.read_bytes() == b"lnk of ann"
    assert not (startup / "Ollama.lnk").exists()
    assert sorted(processes.ended) == [50, 51]
    (startup / "Ollama.lnk").write_bytes(b"made again")
    assert applier.take_over_apps() == []
    assert (startup / "Ollama.lnk").read_bytes() == b"made again"


def test_each_report_ends_an_app_opened_by_hand(tmp_path):
    app, _startup = _profile(tmp_path, "ann")
    processes = FakeProcesses({60: str(app / "ollama app.exe")})
    applier, _commands = _taking_applier(tmp_path, processes)
    assert applier.stop_apps() == [60]
    assert applier.stop_apps() == []


def test_a_startup_folder_that_is_a_junction_is_left(tmp_path):
    _app, startup = _profile(tmp_path, "ann")
    applier, _commands = _taking_applier(
        tmp_path, FakeProcesses({}), is_plain=lambda path: False
    )
    assert applier.take_over_apps() == ["ann"]
    assert (startup / "Ollama.lnk").exists()
    applier.give_back_apps()
    assert (startup / "Ollama.lnk").read_bytes() == b"lnk of ann"


def test_the_uninstall_gives_each_start_back_and_opens_the_app_again(tmp_path):
    app, startup = _profile(tmp_path, "ann")
    _profile(tmp_path, "bob")
    processes = FakeProcesses({70: str(app / "ollama app.exe")})
    applier, commands = _taking_applier(tmp_path, processes)
    applier.take_over_apps()
    applier.uninstall()
    assert (startup / "Ollama.lnk").read_bytes() == b"lnk of ann"
    assert not (tmp_path / "state" / "ollama").exists()
    opened = [command for command in commands.commands if "/create" in command]
    assert len(opened) == 1
    assert "/it" in opened[0] and opened[0][opened[0].index("/ru") + 1] == "ann"
    assert opened[0][opened[0].index("/tr") + 1] == (
        '"' + str(app / "ollama app.exe") + '"'
    )
    assert [command[1] for command in commands.commands] == [
        "/create",
        "/run",
        "/delete",
    ]


def test_the_settings_variables_are_set_in_the_script_and_restart_the_server(
    tmp_path,
):
    script = render_script(
        program="C:\\o\\ollama.exe",
        data_dir="C:\\d",
        log="C:\\d\\ollama.log",
        environment={"OLLAMA_KEEP_ALIVE": "4h", "CUDA_VISIBLE_DEVICES": "1"},
    )
    lines = script.split("\r\n")
    assert 'set "OLLAMA_KEEP_ALIVE=4h"' in lines
    assert 'set "CUDA_VISIBLE_DEVICES=1"' in lines
    assert lines.index('set "OLLAMA_KEEP_ALIVE=4h"') < len(lines) - 2
    host = FakeHost()
    applier = _applier(tmp_path, host)
    applier.apply(environment={"OLLAMA_KEEP_ALIVE": "30m"}, is_started=True)
    host.calls.clear()
    assert applier.apply(environment={"OLLAMA_KEEP_ALIVE": "30m"}) == "unchanged"
    assert applier.apply(environment={"OLLAMA_KEEP_ALIVE": "-1"}) == "restarted"
    with open(applier.script_path, encoding="utf-8") as stream:
        assert 'set "OLLAMA_KEEP_ALIVE=-1"' in stream.read()


def test_the_default_context_length_is_set_in_the_script():
    script = render_script(
        program="C:\\o\\ollama.exe",
        data_dir="C:\\d",
        log="C:\\d\\ollama.log",
        environment=OllamaConfig.from_dict({}).environment("windows"),
    )
    lines = script.split("\r\n")
    assert 'set "OLLAMA_CONTEXT_LENGTH=65536"' in lines
    assert lines.index('set "OLLAMA_CONTEXT_LENGTH=65536"') < len(lines) - 2


def test_the_person_s_app_takes_no_setting(tmp_path):
    host = FakeHost()
    applier = _applier(tmp_path, host)
    assert applier.apply_person(environment={"OLLAMA_KEEP_ALIVE": "5m"}) == ""
    assert applier.remove_person_settings() is False
    assert host.calls == []
