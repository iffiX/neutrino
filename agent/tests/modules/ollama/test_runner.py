"""The Ollama runner: install from bytes, a person's own copy, apply, details.

What these pin: the runner's own check finds the module's program, a
person's unit on Linux and a person's app answering on its port on Windows
and macOS; an install beside a person's unit keeps its ``verify`` alone, and
one beside the publisher's app on Windows and macOS is planned whole, and
that app no presence of Ollama; the Linux ``tar_zst`` lands under
``ollama/`` through the system's ``zstd``; the server's account is a step of
its own before ``configure`` taking ``system_accounts``, none on Windows and
none on a person's unit; a configure that runs the server waits until
``/api/version`` answers and fails ``apply_failed`` when it never does; a
person's unit is kept as found at the first start, started and stopped, and
given back at the uninstall with nothing of it removed; the details name the
port, the version and whose copy it is. The settings are checked, and the
variables they give reach the module's own service and a person's unit,
whose drop-in an uninstall removes before it gives the unit back.
"""

import io
import os
import sys
import tarfile

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.ollama import runner as runner_module
from neutrino_agent.modules.ollama.runner import (
    OllamaModuleRunner,
    version_in,
)
from neutrino_agent.modules.shared import unpacked_tree
from neutrino_agent.modules.shared.base import ModuleStep
from neutrino_agent.platforms.base import AgentPlatform


class RecordingPlatform(AgentPlatform):
    def __init__(self, root, os_name="linux"):
        self.root = str(root)
        self.os_name = os_name
        self.labelled: list = []

    def agent_var_dir(self) -> str:
        return self.root

    def label_programs(self, path):
        self.labelled.append(path)

    def open_to_accounts(self, directory):
        os.chmod(directory, 0o755)


class FakeApplier:
    """An applier of one system, recording what the runner asks."""

    def __init__(self, root, *, account="neutrino_ollama"):
        self.program_path = os.path.join(str(root), "ollama", "ollama", "bin", "ollama")
        self.data_dir = os.path.join(str(root), "ollama_data")
        self.account = account
        self.unit = ""
        self.app = ""
        self.unit_state = {"is_enabled": False, "is_active": False}
        self.calls: list = []
        self.is_running = False

    def person_unit_path(self):
        return self.unit

    def person_unit_name(self):
        return "ollama.service"

    def person_unit_state(self):
        return dict(self.unit_state)

    def apply_person(self, *, environment=None, is_started=True):
        self.calls.append(("apply_person", dict(environment or {}), is_started))
        if is_started:
            self.unit_state = {"is_enabled": True, "is_active": True}
        return "started" if is_started else "written"

    def remove_person_settings(self):
        self.calls.append("remove_person_settings")
        return True

    def stop_person(self):
        self.calls.append("stop_person")
        self.unit_state = {"is_enabled": False, "is_active": False}

    def restore_person(self, found):
        self.calls.append(("restore_person", dict(found)))

    def take_over_apps(self):
        self.calls.append("take_over_apps")
        return []

    def stop_apps(self):
        self.calls.append("stop_apps")
        return []

    def ensure_account(self, *, log=None):
        self.calls.append("ensure_account")
        return False

    def apply(self, *, environment=None, is_started=True):
        self.calls.append(("apply", is_started))
        self.environment = dict(environment or {})
        if is_started:
            self.is_running = True
        return "started" if is_started else "written"

    def stop(self):
        self.calls.append("stop")
        self.is_running = False

    def is_active(self):
        return self.is_running

    def uninstall(self):
        self.calls.append("uninstall")
        return ""

    def journal_units(self):
        return ["neutrino_ollama.service"]

    def output_path(self):
        return ""


def _runner(tmp_path, applier, *, os_name="linux", answers=None, clock=None):
    platform = RecordingPlatform(tmp_path, os_name)
    answers = answers if answers is not None else {"version": None}
    ticks = clock if clock is not None else iter(range(0, 10**6))
    return OllamaModuleRunner(
        platform=platform,
        log=lambda line: None,
        applier=applier,
        read_version=lambda: answers["version"],
        is_listening=lambda: answers["version"] is not None,
        clock=lambda: next(ticks),
        sleep=lambda seconds: None,
    )


def _place_program(applier):
    os.makedirs(os.path.dirname(applier.program_path), exist_ok=True)
    with open(applier.program_path, "w", encoding="utf-8") as stream:
        stream.write("#!/bin/sh\necho 'ollama version is 0.40.16'\n")
    os.chmod(applier.program_path, 0o755)


def _step(name):
    return ModuleStep(name=name, run=lambda context: None)


def test_the_own_check_finds_the_program_and_a_unit_and_no_app(tmp_path):
    applier = FakeApplier(tmp_path)
    answers = {"version": None}
    runner = _runner(tmp_path, applier, answers=answers)
    assert runner.verify({}) is False
    applier.unit = "/etc/systemd/system/ollama.service"
    assert runner.verify({}) is True
    applier.unit = ""
    _place_program(applier)
    assert runner.verify({}) is True

    app = FakeApplier(tmp_path / "mac", account="neutrino_ollama")
    runner = _runner(tmp_path / "mac", app, os_name="darwin", answers=answers)
    answers["version"] = "0.40.16"
    assert runner.verify({}) is False
    assert runner.details({})["found"] == ""


def test_an_install_beside_a_person_s_unit_keeps_its_verify_alone(tmp_path):
    applier = FakeApplier(tmp_path)
    applier.unit = "/etc/systemd/system/ollama.service"
    runner = _runner(tmp_path, applier)
    steps = [_step("packages"), _step("artifact"), _step("verify")]
    assert [step.name for step in runner.install_steps({}, steps)] == ["verify"]


def test_an_install_beside_the_publisher_s_app_is_planned_whole(tmp_path):
    applier = FakeApplier(tmp_path, account="")
    runner = _runner(tmp_path, applier, os_name="windows")
    steps = [_step("artifact"), _step("verify")]
    assert runner.install_steps({}, steps) == steps


def test_a_configure_takes_the_app_over_before_the_server_starts(tmp_path):
    applier = FakeApplier(tmp_path, account="")
    runner = _runner(tmp_path, applier, os_name="windows", answers={"version": "1"})
    runner.apply({})
    assert applier.calls == ["take_over_apps", ("apply", True)]
    runner.apply_stopped({})
    assert applier.calls[-2:] == ["take_over_apps", ("apply", False)]


def test_each_report_ends_the_app_while_the_program_is_installed(tmp_path):
    applier = FakeApplier(tmp_path, account="")
    runner = _runner(tmp_path, applier, os_name="windows")
    runner.details({})
    assert "stop_apps" not in applier.calls
    _place_program(applier)
    runner.details({})
    assert applier.calls == ["stop_apps"]


def test_the_linux_archive_lands_under_ollama_through_zstd(tmp_path, monkeypatch):
    tar_path = tmp_path / "plain.tar"
    with tarfile.open(tar_path, "w") as archive:
        for name, data in (("bin/ollama", b"program"), ("lib/ollama/x.so", b"lib")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
    copy = "import shutil, sys; shutil.copyfileobj(open(sys.argv[1], 'rb'), sys.stdout.buffer)"
    monkeypatch.setattr(unpacked_tree, "ZSTD_COMMAND", (sys.executable, "-c", copy))
    state = tmp_path / "state"
    applier = FakeApplier(state)
    runner = _runner(state, applier)
    artifact = {"name": "ollama", "kind": "tar_zst", "directory": "ollama"}
    runner.install_artifact({}, artifact, str(tar_path))
    program = state / "ollama" / "ollama" / "bin" / "ollama"
    assert program.read_bytes() == b"program"
    assert (state / "ollama" / "ollama" / "lib" / "ollama" / "x.so").exists()
    assert not os.stat(program).st_mode & 0o222
    assert runner._platform.labelled == [str(state / "ollama" / "ollama")]


def test_a_failing_zstd_fails_the_install(tmp_path, monkeypatch):
    fail = "import sys; sys.stderr.write('bad magic'); sys.exit(1)"
    monkeypatch.setattr(unpacked_tree, "ZSTD_COMMAND", (sys.executable, "-c", fail))
    applier = FakeApplier(tmp_path)
    runner = _runner(tmp_path, applier)
    archive = tmp_path / "x.tar.zst"
    archive.write_bytes(b"")
    with pytest.raises(ModuleApplyError) as failed:
        runner.install_artifact(
            {},
            {"name": "ollama", "kind": "tar_zst", "directory": "ollama"},
            str(archive),
        )
    assert failed.value.code == "install_failed"


def test_the_account_comes_before_configure_and_takes_system_accounts(tmp_path):
    applier = FakeApplier(tmp_path)
    runner = _runner(tmp_path, applier)
    steps = runner.configure_steps({}, "running", [_step("configure"), _step("start")])
    assert [step.name for step in steps] == ["account", "configure", "start"]
    assert steps[0].params == {"account": "neutrino_ollama"}
    assert runner.step_locks("account") == (("system_accounts", "alone"),)
    assert runner.step_locks("uninstall") == (("system_accounts", "alone"),)
    assert runner.step_locks("configure") == ()

    windows = FakeApplier(tmp_path / "w", account="")
    runner = _runner(tmp_path / "w", windows, os_name="windows")
    steps = runner.configure_steps({}, "running", [_step("configure"), _step("start")])
    assert [step.name for step in steps] == ["configure", "start"]


def test_a_stopped_configure_writes_the_service_and_starts_nothing(tmp_path):
    applier = FakeApplier(tmp_path)
    runner = _runner(tmp_path, applier)
    steps = runner.configure_steps({}, "stopped", [_step("configure"), _step("stop")])
    steps[1].run(None)
    assert applier.calls == ["take_over_apps", ("apply", False)]


def test_a_configure_waits_for_the_server_and_fails_when_it_never_answers(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        runner_module, "units_journal", lambda units, lines: ["Error: listen tcp"]
    )
    applier = FakeApplier(tmp_path)
    answers = {"version": None}
    runner = _runner(
        tmp_path, applier, answers=answers, clock=iter(range(0, 10**6, 10))
    )
    with pytest.raises(ModuleApplyError) as failed:
        runner.apply({})
    assert failed.value.code == "apply_failed"
    assert failed.value.params["detail"] == (
        "ollama did not answer on 127.0.0.1:11434: Error: listen tcp"
    )

    answers["version"] = "0.40.16"
    runner.apply({})
    assert applier.calls[-1] == ("apply", True)


def test_a_person_s_unit_is_kept_started_stopped_and_given_back(tmp_path):
    applier = FakeApplier(tmp_path)
    applier.unit = "/etc/systemd/system/ollama.service"
    applier.unit_state = {"is_enabled": True, "is_active": False}
    answers = {"version": "0.40.16"}
    runner = _runner(tmp_path, applier, answers=answers)
    assert runner.is_software_kept() is True
    steps = runner.configure_steps({}, "running", [_step("configure"), _step("start")])
    assert [step.name for step in steps] == ["configure", "start"]

    runner.apply_stopped({})
    assert applier.calls == [
        ("apply_person", {"OLLAMA_KEEP_ALIVE": "30m"}, False),
    ]
    assert runner._found_unit() == {}
    applier.calls.clear()
    runner.apply({"keep_alive": "5m"})
    assert applier.calls == [("apply_person", {"OLLAMA_KEEP_ALIVE": "5m"}, True)]
    assert runner._found_unit() == {"is_enabled": True, "is_active": False}
    assert runner.is_active() is True
    assert runner.journal_units() == ["ollama.service"]

    runner.stop()
    assert applier.calls[-1] == "stop_person"
    assert runner._found_unit() == {"is_enabled": True, "is_active": False}

    runner.uninstall({})
    assert applier.calls[-2:] == [
        "remove_person_settings",
        ("restore_person", {"is_enabled": True, "is_active": False}),
    ]
    assert "uninstall" not in applier.calls
    assert runner._found_unit() == {}


def test_a_stop_of_a_person_s_unit_that_does_not_run_leaves_it(tmp_path):
    applier = FakeApplier(tmp_path)
    applier.unit = "/etc/systemd/system/ollama.service"
    runner = _runner(tmp_path, applier)
    runner.stop()
    assert applier.calls == []
    assert runner._found_unit() == {}


def test_the_module_s_own_uninstall_goes_through_its_applier(tmp_path):
    applier = FakeApplier(tmp_path)
    _place_program(applier)
    runner = _runner(tmp_path, applier)
    assert runner.is_software_kept() is False
    runner.uninstall({})
    assert applier.calls == ["uninstall"]


def test_the_details_name_the_port_the_version_and_whose_copy(tmp_path, monkeypatch):
    applier = FakeApplier(tmp_path)
    answers = {"version": None}
    runner = _runner(tmp_path, applier, answers=answers)
    _place_program(applier)
    seen = {}

    def version(command, **kwargs):
        seen["env"] = kwargs["env"]
        return type(
            "Result",
            (),
            {"stdout": "Warning: client version is 0.40.16\n", "stderr": ""},
        )()

    monkeypatch.setattr(runner_module, "run_program", version)
    assert runner.details({}) == {
        "is_running": False,
        "port": 11434,
        "version": "0.40.16",
        "found": "",
        "has_package_mark": True,
    }
    assert seen["env"]["OLLAMA_MODELS"] == os.path.join(
        str(tmp_path), "ollama_data", "models"
    )
    answers["version"] = "0.40.17"
    assert runner.details({})["version"] == "0.40.17"
    assert runner.details({})["is_running"] is True


def test_version_in_reads_both_lines():
    assert version_in("ollama version is 0.40.16\n") == "0.40.16"
    assert (
        version_in("Warning: could not connect\nWarning: client version is 0.40.16")
        == "0.40.16"
    )
    assert version_in("nothing") == ""


def test_a_report_asks_the_server_s_version_at_most_every_ten_minutes(tmp_path):
    asked = []
    clock = {"now": 0.0}
    applier = FakeApplier(tmp_path)
    _place_program(applier)
    runner = OllamaModuleRunner(
        platform=RecordingPlatform(tmp_path),
        log=lambda line: None,
        applier=applier,
        read_version=lambda: asked.append(1) or "0.40.16",
        is_listening=lambda: True,
        clock=lambda: clock["now"],
        sleep=lambda seconds: None,
    )
    for _turn in range(5):
        assert runner.details({})["version"] == "0.40.16"
    assert len(asked) == 1
    clock["now"] = 601.0
    runner.details({})
    assert len(asked) == 2


def test_the_verify_runs_with_the_module_s_models_folder(tmp_path):
    """Ollama's --version stops at a missing HOME unless OLLAMA_MODELS names its folder."""
    runner = _runner(tmp_path, FakeApplier(tmp_path))
    assert runner.verify_environment() == {
        "OLLAMA_MODELS": os.path.join(str(tmp_path), "ollama_data", "models")
    }


def test_the_settings_are_checked_and_reach_the_module_s_own_service(tmp_path):
    applier = FakeApplier(tmp_path)
    runner = _runner(tmp_path, applier, answers={"version": "0.40.16"})
    with pytest.raises(ModuleApplyError) as refused:
        runner.validate({"keep_alive": "2h"})
    assert refused.value.code == "config_invalid"
    assert refused.value.params == {"field": "keep_alive"}
    runner.validate(
        {"keep_alive": "4h", "gpus": [{"vendor": "nvidia", "is_used": True}]}
    )
    gpus = [
        {"vendor": "nvidia", "is_used": False},
        {"vendor": "nvidia", "is_used": True},
    ]
    runner.apply({"keep_alive": "4h", "gpus": gpus})
    assert applier.environment == {
        "OLLAMA_KEEP_ALIVE": "4h",
        "CUDA_VISIBLE_DEVICES": "1",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
    }
    runner.apply_stopped({})
    assert applier.calls[-1] == ("apply", False)
    assert applier.environment == {"OLLAMA_KEEP_ALIVE": "30m"}


def test_a_mac_s_service_takes_no_gpu_variable(tmp_path):
    applier = FakeApplier(tmp_path)
    runner = _runner(
        tmp_path, applier, os_name="darwin", answers={"version": "0.40.16"}
    )
    runner.apply({"keep_alive": "1h", "gpus": [{"vendor": "apple", "is_used": False}]})
    assert applier.environment == {"OLLAMA_KEEP_ALIVE": "1h"}


def test_an_uninstall_with_nothing_kept_still_removes_the_drop_in(tmp_path):
    applier = FakeApplier(tmp_path)
    applier.unit = "/etc/systemd/system/ollama.service"
    runner = _runner(tmp_path, applier)
    runner.uninstall({})
    assert applier.calls == ["remove_person_settings"]
