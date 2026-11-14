"""Ollama on macOS: the LaunchDaemon, the hidden account, the publisher's app.

What these pin: the LaunchDaemon runs ``ollama serve`` as
``neutrino_ollama`` with the module's environment and its output in the
agent's log folder; an apply loads it and reloads it only on a change, and
under ``stopped`` writes it alone; a stop disables and unloads it; an
uninstall deletes the plist and the program and keeps the data directory
and the account; the publisher's app is found in ``/Applications``.
"""

import os
import plistlib

from neutrino_agent.modules.ollama.darwin_applier import (
    OllamaDarwinApplier,
    render_plist,
)


class Result:
    def __init__(self, exit_code=0, stdout=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = ""

    @property
    def is_success(self):
        return self.exit_code == 0


class FakeLaunchd:
    def __init__(self):
        self.commands: list = []
        self.is_loaded = False

    def run(self, command, *, is_checked=True, **kwargs):
        self.commands.append(list(command))
        if command[:2] == ["dscl", "."] and command[2] == "-read":
            keys = "".join(f"{key}: x\n" for key in command[4:])
            return Result(0, keys)
        if command[:2] == ["launchctl", "print"]:
            return Result(0 if self.is_loaded else 113, "state = running\n")
        if command[:2] == ["launchctl", "bootstrap"]:
            self.is_loaded = True
        if command[:2] == ["launchctl", "bootout"]:
            self.is_loaded = False
        return Result(0)


def _applier(tmp_path, launchd):
    applier = OllamaDarwinApplier(
        state_dir=str(tmp_path / "state"),
        run=launchd.run,
        lookup_account=lambda account: (os.getuid(), os.getgid()),
        chown=lambda path, uid, gid: None,
        launchd_dir=str(tmp_path / "LaunchDaemons"),
        output_path=str(tmp_path / "Logs" / "ollama.log"),
        app_paths=(str(tmp_path / "Applications" / "Ollama.app"),),
        sleep=lambda seconds: None,
    )
    (tmp_path / "LaunchDaemons").mkdir()
    applier._prepare_data = lambda uid, gid: None
    return applier


def test_the_job_runs_ollama_serve_as_the_account_with_the_environment():
    job = plistlib.loads(render_plist(program="/s/ollama/ollama/ollama", data_dir="/d"))
    assert job["Label"] == "com.neutrino.ollama"
    assert job["UserName"] == "neutrino_ollama"
    assert job["ProgramArguments"] == ["/s/ollama/ollama/ollama", "serve"]
    assert job["EnvironmentVariables"]["OLLAMA_HOST"] == "127.0.0.1:11434"
    assert job["EnvironmentVariables"]["OLLAMA_MODELS"] == "/d/models"
    assert job["EnvironmentVariables"]["OLLAMA_NO_CLOUD"] == "1"
    assert job["EnvironmentVariables"]["HOME"] == "/d"
    assert job["StandardOutPath"] == "/Library/Logs/Neutrino/agent/ollama.log"


def test_an_apply_loads_the_job_and_reloads_it_only_on_a_change(tmp_path):
    launchd = FakeLaunchd()
    applier = _applier(tmp_path, launchd)
    assert applier.apply(is_started=False) == "written"
    assert not launchd.is_loaded
    assert applier.apply(is_started=True) == "started"
    assert ["launchctl", "enable", "system/com.neutrino.ollama"] in launchd.commands
    assert applier.apply(is_started=True) == "unchanged"
    (tmp_path / "LaunchDaemons" / "com.neutrino.ollama.plist").write_text("old")
    assert applier.apply(is_started=True) == "restarted"
    assert applier.is_active() is True


def test_a_stop_disables_and_an_uninstall_keeps_the_data_and_the_account(tmp_path):
    launchd = FakeLaunchd()
    applier = _applier(tmp_path, launchd)
    applier.apply(is_started=True)
    applier.stop()
    assert ["launchctl", "disable", "system/com.neutrino.ollama"] in launchd.commands
    assert not launchd.is_loaded
    os.makedirs(os.path.dirname(applier.program_path))
    open(applier.program_path, "w").close()
    os.makedirs(os.path.join(applier.data_dir, "models"))
    applier.uninstall()
    assert not (tmp_path / "LaunchDaemons" / "com.neutrino.ollama.plist").exists()
    assert not os.path.exists(applier.module_dir)
    assert os.path.isdir(os.path.join(applier.data_dir, "models"))
    assert not any(
        command[:3] == ["dscl", ".", "-delete"] for command in launchd.commands
    )


def test_the_publisher_s_app_is_found_in_applications(tmp_path):
    applier = _applier(tmp_path, FakeLaunchd())
    assert applier.app_path() == ""
    (tmp_path / "Applications" / "Ollama.app").mkdir(parents=True)
    assert applier.app_path() == str(tmp_path / "Applications" / "Ollama.app")
    assert applier.person_unit_path() == ""
