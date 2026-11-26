"""Ollama on macOS: the LaunchDaemon, the hidden account, the publisher's app.

What these pin: the LaunchDaemon runs ``ollama serve`` as
``neutrino_ollama`` with the module's environment and its output in the
agent's log folder; an apply loads it and reloads it only on a change, and
under ``stopped`` writes it alone; a stop disables and unloads it; an
uninstall deletes the plist and the program and keeps the data directory
and the account. The settings' variables join the job's environment, the
default context length among them, and a change of them reloads it. The
publisher's app is taken over once per account: its login job
``com.ollama.ollama`` disabled, whether it was disabled before kept, its
processes ended, at each report again; the uninstall enables what was
enabled and opens the app again for the account at the console whose app
ran.
"""

import os
import plistlib

from neutrino_agent.modules.ollama.config import OllamaConfig
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


class AppLaunchd(FakeLaunchd):
    """launchd, ps and the console as the take-over of the app reads them."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.disabled = {"501": False, "502": True}
        self.processes = {}
        self.console = "501"

    def run(self, command, *, is_checked=True, **kwargs):
        if command[:2] == ["launchctl", "print-disabled"]:
            self.commands.append(list(command))
            uid = command[2].split("/")[1]
            word = "disabled" if self.disabled.get(uid) else "enabled"
            return Result(
                0, f'disabled services = {{\n\t"com.ollama.ollama" => {word}\n}}\n'
            )
        if command[:2] in (
            ["launchctl", "disable"],
            ["launchctl", "enable"],
        ) and command[2].startswith("gui/"):
            self.commands.append(list(command))
            self.disabled[command[2].split("/")[1]] = command[1] == "disable"
            return Result(0)
        if command[0] == "ps":
            self.commands.append(list(command))
            lines = "".join(
                f"{pid} {uid} {path}\n" for pid, (uid, path) in self.processes.items()
            )
            return Result(0, lines)
        if command[:3] == ["stat", "-f", "%u"]:
            return Result(0, self.console + "\n")
        return super().run(command, is_checked=is_checked, **kwargs)


def _taking_applier(tmp_path):
    app = tmp_path / "Applications" / "Ollama.app"
    app.mkdir(parents=True)
    launchd = AppLaunchd(str(app))
    ended = []
    applier = OllamaDarwinApplier(
        state_dir=str(tmp_path / "state"),
        run=launchd.run,
        lookup_account=lambda account: (os.getuid(), os.getgid()),
        chown=lambda path, uid, gid: None,
        launchd_dir=str(tmp_path / "LaunchDaemons"),
        output_path=str(tmp_path / "Logs" / "ollama.log"),
        app_paths=(str(app),),
        sleep=lambda seconds: None,
        accounts=lambda: [("ann", 501), ("bob", 502)],
        kill=lambda pid: ended.append(pid),
    )
    (tmp_path / "LaunchDaemons").mkdir()
    applier._prepare_data = lambda uid, gid: None
    return applier, launchd, ended


def test_the_app_of_every_account_is_taken_over_once(tmp_path):
    applier, launchd, ended = _taking_applier(tmp_path)
    launchd.processes = {
        80: (501, launchd.app + "/Contents/MacOS/Ollama"),
        81: (501, launchd.app + "/Contents/Resources/ollama"),
        82: (501, "/usr/bin/top"),
    }
    assert applier.take_over_apps() == ["ann", "bob"]
    assert ["launchctl", "disable", "gui/501/com.ollama.ollama"] in launchd.commands
    assert ended == []
    assert sorted(applier.stop_apps()) == [80, 81]
    launchd.commands.clear()
    assert applier.take_over_apps() == []
    assert not any(
        command[1] == "disable"
        for command in launchd.commands
        if command[0] == "launchctl"
    )


def test_each_report_ends_an_app_opened_by_hand_on_the_mac(tmp_path):
    applier, launchd, ended = _taking_applier(tmp_path)
    launchd.processes = {90: (502, launchd.app + "/Contents/MacOS/Ollama")}
    assert applier.stop_apps() == [90]


def test_the_uninstall_enables_what_was_enabled_and_opens_the_app_again(tmp_path):
    applier, launchd, _ended = _taking_applier(tmp_path)
    launchd.processes = {80: (501, launchd.app + "/Contents/MacOS/Ollama")}
    applier.take_over_apps()
    launchd.processes = {}
    applier.uninstall()
    assert launchd.disabled == {"501": False, "502": True}
    assert ["launchctl", "enable", "gui/501/com.ollama.ollama"] in launchd.commands
    assert ["launchctl", "enable", "gui/502/com.ollama.ollama"] not in launchd.commands
    assert [
        "launchctl",
        "asuser",
        "501",
        "/usr/bin/open",
        "-a",
        launchd.app,
    ] in launchd.commands
    assert not os.path.exists(applier.module_dir)


def test_the_default_context_length_joins_the_job():
    job = plistlib.loads(
        render_plist(
            program="/s/ollama",
            data_dir="/d",
            environment=OllamaConfig.from_dict({}).environment("darwin"),
        )
    )
    assert job["EnvironmentVariables"]["OLLAMA_CONTEXT_LENGTH"] == "65536"
    assert job["EnvironmentVariables"]["OLLAMA_KEEP_ALIVE"] == "30m"


def test_the_settings_variables_join_the_job_and_reload_it(tmp_path):
    job = plistlib.loads(
        render_plist(
            program="/s/ollama",
            data_dir="/d",
            environment={"OLLAMA_KEEP_ALIVE": "1h"},
        )
    )
    assert job["EnvironmentVariables"]["OLLAMA_KEEP_ALIVE"] == "1h"
    assert job["EnvironmentVariables"]["OLLAMA_HOST"] == "127.0.0.1:11434"
    launchd = FakeLaunchd()
    applier = _applier(tmp_path, launchd)
    applier.apply(environment={"OLLAMA_KEEP_ALIVE": "30m"}, is_started=True)
    assert applier.apply(environment={"OLLAMA_KEEP_ALIVE": "30m"}) == "unchanged"
    assert applier.apply(environment={"OLLAMA_KEEP_ALIVE": "5m"}) == "restarted"
    assert applier.apply_person(environment={"OLLAMA_KEEP_ALIVE": "5m"}) == ""
    assert applier.remove_person_settings() is False
