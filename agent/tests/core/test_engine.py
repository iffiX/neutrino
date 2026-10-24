"""The module engine: observing against the state, and moving software.

The engine is handed the state's modules section, each entry carrying the
recipes resolved for this platform, and observes every module it has a
runner for, named or not. What is pinned here is the state it derives from
three facts (the software there, the unit active, the configured mark on
disk), the five fields of every row, the mark written and cleared by
name, an install and an uninstall run in the caller's thread with each
output line handed on as it comes and the row transient meanwhile, a
package's bytes asked for only by the kinds that install from bytes and
the file deleted afterwards, the uninstall recipe's own packages and
steps, results judged by the machine's own state, one package operation
at a time, a module whose own install runs reading installing with the
code its runner names for what holds it up, the modules
waiting behind the one being applied reading queued, a failed install
reading install_failed with its code whatever the machine has, any other
failed step reading failed while the software is there, both kept
root-only on disk and read the same by an engine that starts again, until
the next attempt replaces them or a state stops naming the module, an
uninstall of what a failed install left judged by the check afterwards,
and that nothing in it ever retries anything.
"""

import os
import subprocess
import threading
import time

import pytest

import neutrino_agent.core.engine as engine_module
from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.exceptions import (
    InstallError,
    ModuleApplyError,
    PlatformUnsupportedError,
)
from neutrino_agent.modules.podman.machine_runner import PodmanMachineModuleRunner
from neutrino_agent.modules.podman.runner import PodmanModuleRunner
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.platforms.base import AgentPlatform

DEB_RECIPE = {
    "kind": "package",
    "package_kind": "deb",
    "package": "fakedesk",
    "uninstall": "apt-get remove -y fakedesk",
}

WANTED = {
    "fakedesk": {
        "want": "installed",
        "config": {},
        "install": dict(DEB_RECIPE),
        "uninstall": {},
    }
}

ROW_FIELDS = {"state", "is_active", "code", "params", "details"}


class FakePlatform(AgentPlatform):
    """A platform that records installs and refuses nothing else."""

    os_name = "linux"

    def __init__(self, *, install_error=None):
        self.installs: list = []
        self.uninstalls: list = []
        self._install_error = install_error

    def install_package(self, path, *, package_kind, entry):
        self.installs.append((package_kind, entry, os.path.exists(path)))
        if self._install_error is not None:
            raise self._install_error

    def uninstall_package(self, command):
        self.uninstalls.append(command)


def bare_engine(*, platform=None, verified=None, tmp_path=None):
    """An engine with no worker thread, driven a pass at a time.

    Args:
        platform: The machine's platform.
        verified: Scripted answers for the package runner's verify; the
            last one repeats.
        tmp_path: Where the configured marks live.

    Returns:
        The engine.
    """
    engine = ModuleEngine.__new__(ModuleEngine)
    engine._wanted = {name: dict(entry) for name, entry in WANTED.items()}
    engine._configured_dir = str(tmp_path / "configured") if tmp_path else "/nowhere"
    engine._failures_dir = (
        str(tmp_path / "failures") if tmp_path else "/nowhere/failures"
    )
    engine._platform_tuple = {"os": "linux", "family": "debian", "arch": "amd64"}
    engine._on_line = None
    engine._operation_lock = threading.Lock()
    engine._in_transit = set()
    engine._queued = set()
    engine._statuses = {}
    engine._signature = ""
    engine._checked_at = 0.0
    engine._log = lambda message: None
    engine._on_change = None
    engine._lock = threading.Lock()
    engine._wakeup = threading.Event()
    engine._failures = {}
    engine._details_at = 0.0
    engine._module_runners = {}

    from neutrino_agent.modules.shared.package import PackageModuleRunner
    from neutrino_agent.modules.shared.system_package import SystemPackageModuleRunner

    platform = platform if platform is not None else FakePlatform()
    engine._package = PackageModuleRunner(
        platform=platform, log=engine._collect, publish=engine._publish
    )
    engine._system = SystemPackageModuleRunner(
        platform=platform, log=engine._collect, publish=engine._publish
    )
    answers = list(verified or [])

    def verify(resolved):
        return (
            answers.pop(0) if len(answers) > 1 else (answers[0] if answers else False)
        )

    engine._package.verify = verify
    return engine


def landing_receive(received, tmp_path):
    """A receive that writes a package and records the module it was asked for."""

    def receive(name):
        received.append(name)
        path = tmp_path / f"{name}.deb"
        path.write_bytes(b"!<arch>package")
        return {"path": str(path)}

    return receive


# --- an install ---


def test_an_install_from_bytes_asks_for_the_package_and_deletes_it_after(tmp_path):
    received: list = []
    platform = FakePlatform()
    engine = bare_engine(platform=platform, verified=[True], tmp_path=tmp_path)

    refusal = engine.install("fakedesk", receive=landing_receive(received, tmp_path))

    assert received == ["fakedesk"]
    # The recipe's entry is what the platform installs by: the header
    # fields name the runner and the check, and are not part of it. The
    # file was there for the install and is gone after it.
    assert platform.installs == [
        (
            "deb",
            {"package_kind": "deb", "uninstall": "apt-get remove -y fakedesk"},
            True,
        )
    ]
    assert not (tmp_path / "fakedesk.deb").exists()
    assert refusal == {}


def test_each_output_line_is_handed_on_as_it_comes(tmp_path):
    engine = bare_engine(verified=[True], tmp_path=tmp_path)
    lines: list = []

    engine.install(
        "fakedesk", receive=landing_receive([], tmp_path), on_line=lines.append
    )

    assert lines == ["fakedesk: installing"]
    # The line handler is the stream's; it does not outlive the operation.
    assert engine._on_line is None


def test_the_row_is_installing_while_the_install_runs_and_read_again_after(
    tmp_path,
):
    engine = bare_engine(verified=[True], tmp_path=tmp_path)
    seen: list = []

    def receive(name):
        seen.append(engine.report()["fakedesk"]["state"])
        # A refresh under way keeps the transient row.
        engine._refresh(is_forced=True)
        seen.append(engine.report()["fakedesk"]["state"])
        return landing_receive([], tmp_path)(name)

    assert engine.install("fakedesk", receive=receive) == {}

    assert seen == ["installing", "installing"]
    assert engine.report()["fakedesk"]["state"] == "installed"


def test_an_install_the_machine_cannot_confirm_is_failed_not_latched(tmp_path):
    engine = bare_engine(verified=[False], tmp_path=tmp_path)

    refusal = engine.install("fakedesk", receive=landing_receive([], tmp_path))

    assert refusal == {"code": "install_unconfirmed", "params": {}}


def test_a_failed_install_hands_on_the_installers_own_words(tmp_path):
    platform = FakePlatform(install_error=InstallError("dpkg failed: held broken"))
    engine = bare_engine(platform=platform, verified=[False], tmp_path=tmp_path)
    lines: list = []

    refusal = engine.install(
        "fakedesk", receive=landing_receive([], tmp_path), on_line=lines.append
    )

    assert refusal["code"] == "install_failed"
    assert "dpkg failed: held broken" in refusal["params"]["detail"]
    # The vendor's own words, not only that something went wrong.
    assert "dpkg failed: held broken" in lines


def test_a_refused_package_is_reported_with_the_hubs_own_code(tmp_path):
    def refuse(name):
        return {"code": "module_artifact_unknown", "params": {"detail": "refused"}}

    engine = bare_engine(verified=[False], tmp_path=tmp_path)
    platform = engine._package._platform

    refusal = engine.install("fakedesk", receive=refuse)

    assert refusal == {
        "code": "module_artifact_unknown",
        "params": {"detail": "refused"},
    }
    assert platform.installs == []


def test_an_install_that_names_its_step_is_reported_with_that_code(tmp_path):
    platform = FakePlatform(
        install_error=ModuleApplyError("cloudcli_node_download_failed", {"x": 1})
    )
    engine = bare_engine(platform=platform, verified=[False], tmp_path=tmp_path)

    refusal = engine.install("fakedesk", receive=landing_receive([], tmp_path))

    assert refusal == {"code": "cloudcli_node_download_failed", "params": {"x": 1}}


def test_a_platform_that_installs_nothing_is_reported_not_raised(tmp_path):
    engine = bare_engine(platform=AgentPlatform(), verified=[False], tmp_path=tmp_path)

    refusal = engine.install("fakedesk", receive=landing_receive([], tmp_path))

    assert refusal == {"code": "unsupported_platform", "params": {}}


def test_a_module_the_state_does_not_name_is_refused_not_attempted(tmp_path):
    received: list = []
    engine = bare_engine(tmp_path=tmp_path)
    engine._wanted = {}

    refusal = engine.install("fakedesk", receive=landing_receive(received, tmp_path))

    assert received == []
    assert refusal == {"code": "unknown_module", "params": {"module": "fakedesk"}}


def test_the_module_the_agent_carries_takes_no_operation(tmp_path):
    engine = bare_engine(tmp_path=tmp_path)

    refusal = engine.install("remote_desktop", receive=landing_receive([], tmp_path))

    assert refusal == {
        "code": "module_not_orderable",
        "params": {"module": "remote_desktop"},
    }
    assert engine.uninstall("remote_desktop") == refusal


def test_an_idle_pass_reruns_nothing(tmp_path):
    received: list = []
    engine = bare_engine(verified=[False], tmp_path=tmp_path)

    engine.install("fakedesk", receive=landing_receive(received, tmp_path))
    # Every idle pass after a failed install must run nothing: deciding to
    # try again is the applier's, under another state hash.
    for _ in range(5):
        engine._reconcile()

    assert received == ["fakedesk"]


# --- an uninstall ---


def test_an_uninstall_is_run_and_confirmed(tmp_path):
    platform = FakePlatform()
    engine = bare_engine(platform=platform, verified=[False], tmp_path=tmp_path)
    engine.mark_configured("fakedesk")

    refusal = engine.uninstall("fakedesk")

    assert platform.uninstalls == ["apt-get purge -y fakedesk"]
    assert refusal == {}
    assert engine.is_configured("fakedesk") is False


def test_an_uninstall_that_did_not_take_is_reported_failed(tmp_path):
    engine = bare_engine(verified=[True], tmp_path=tmp_path)

    refusal = engine.uninstall("fakedesk")

    assert refusal == {"code": "uninstall_unconfirmed", "params": {}}


def test_the_uninstall_recipe_names_its_own_packages_and_steps(tmp_path, monkeypatch):
    ran: list = []
    monkeypatch.setattr(
        engine_module.installers,
        "run_shell",
        lambda command, **kwargs: ran.append(command) or "cleaned\n",
    )
    platform = SystemPackagePlatform()
    engine = bare_engine(platform=platform, tmp_path=tmp_path)
    engine._wanted = {
        "samba_mount": {
            "want": "absent",
            "config": {},
            "install": {"kind": "system_package", "packages": ["cifs-utils"]},
            "uninstall": {
                "packages": ["cifs-utils", "cifs-extra"],
                "post_uninstall": ["rm -f /etc/cifs.neutrino"],
                "is_data_kept": True,
            },
        }
    }
    engine._system.verify = lambda resolved: False
    lines: list = []

    refusal = engine.uninstall("samba_mount", on_line=lines.append)

    assert refusal == {}
    assert platform.removed == [["cifs-utils", "cifs-extra"]]
    assert ran == ["rm -f /etc/cifs.neutrino"]
    assert "cleaned" in lines


@pytest.mark.parametrize("is_data_kept", [True, False])
def test_the_data_goes_only_when_the_recipe_says_so(
    tmp_path, monkeypatch, is_data_kept
):
    """``is_data_kept`` is the hub's word; the runner's ``remove_data`` is
    the hook it reaches, and nothing reaches it otherwise."""
    monkeypatch.setattr(
        engine_module.installers, "run_shell", lambda command, **kwargs: ""
    )
    platform = SystemPackagePlatform()
    engine = bare_engine(platform=platform, tmp_path=tmp_path)
    engine._wanted = {
        "samba_mount": {
            "want": "absent",
            "config": {},
            "install": {"kind": "system_package", "packages": ["cifs-utils"]},
            "uninstall": {
                "packages": ["cifs-utils"],
                "post_uninstall": [],
                "is_data_kept": is_data_kept,
            },
        }
    }
    engine._system.verify = lambda resolved: False
    removed: list = []
    engine._system.remove_data = lambda: removed.append("data")
    lines: list = []

    assert engine.uninstall("samba_mount", on_line=lines.append) == {}

    assert removed == ([] if is_data_kept else ["data"])
    assert ("samba_mount: removing its data" in lines) is not is_data_kept


def test_a_second_package_operation_waits_for_the_first(tmp_path):
    platform = SystemPackagePlatform(delay_s=0.3)
    engine = bare_engine(platform=platform, tmp_path=tmp_path)
    engine._wanted = dict(SYSTEM_WANTED)
    engine._system.verify = lambda resolved: True
    journal: list = []

    def first():
        engine.install("samba_mount", receive=None)
        journal.append(("first", time.monotonic()))

    def second():
        engine.uninstall("samba_mount")
        journal.append(("second", time.monotonic()))

    one = threading.Thread(target=first)
    one.start()
    time.sleep(0.05)
    two = threading.Thread(target=second)
    two.start()
    one.join(timeout=5)
    two.join(timeout=5)

    assert [entry[0] for entry in journal] == ["first", "second"]
    assert platform.journal == ["install", "remove"]


def test_the_engine_runs_a_failed_install_again_never_by_itself(tmp_path):
    platform = FakePlatform()
    engine = bare_engine(platform=platform, verified=[False], tmp_path=tmp_path)

    engine.install("fakedesk", receive=landing_receive([], tmp_path))
    engine._refresh(is_forced=True)
    engine._refresh(is_forced=True)

    # The failure is kept for the row; there is no attempt count and no
    # second install here.
    assert len(platform.installs) == 1
    assert engine.report()["fakedesk"]["state"] == "install_failed"
    assert not hasattr(engine, "_attempts")


# --- the by-name kind installs with the platform's own tooling ---

SYSTEM_WANTED = {
    "samba_mount": {
        "want": "installed",
        "config": {},
        "install": {"kind": "system_package", "packages": ["cifs-utils"]},
        "uninstall": {"packages": ["cifs-utils"]},
    }
}


class SystemPackagePlatform(AgentPlatform):
    """A platform whose own package manager is observable."""

    os_name = "linux"

    def __init__(self, delay_s: float = 0.0):
        self.installed: list = []
        self.removed: list = []
        self.journal: list = []
        self._delay_s = delay_s

    def install_system_packages(self, names):
        self.journal.append("install")
        time.sleep(self._delay_s)
        self.installed.append(list(names))
        return "Setting up cifs-utils"

    def remove_system_packages(self, names):
        self.journal.append("remove")
        self.removed.append(list(names))
        return ""


def test_a_system_package_install_runs_by_name_and_asks_for_no_bytes(tmp_path):
    platform = SystemPackagePlatform()
    received: list = []
    engine = bare_engine(platform=platform, tmp_path=tmp_path)
    engine._wanted = dict(SYSTEM_WANTED)
    engine._system.verify = lambda resolved: True
    lines: list = []

    refusal = engine.install(
        "samba_mount",
        receive=landing_receive(received, tmp_path),
        on_line=lines.append,
    )

    assert platform.installed == [["cifs-utils"]]
    assert received == []
    assert refusal == {}
    assert "Setting up cifs-utils" in lines


def test_a_system_package_uninstall_rides_the_package_manager_too(tmp_path):
    platform = SystemPackagePlatform()
    engine = bare_engine(platform=platform, tmp_path=tmp_path)
    engine._wanted = dict(SYSTEM_WANTED)
    engine._system.verify = lambda resolved: False

    refusal = engine.uninstall("samba_mount")

    assert platform.removed == [["cifs-utils"]]
    assert refusal == {}


def test_an_absent_capability_reports_unsupported_platform(tmp_path):
    engine = bare_engine(platform=AgentPlatform(), tmp_path=tmp_path)
    engine._wanted = dict(SYSTEM_WANTED)

    refusal = engine.install("samba_mount", receive=None)

    assert refusal == {"code": "unsupported_platform", "params": {}}


# --- the modules this agent applies, observed against the state ---


class ConfigurableRunner(ModuleRunner):
    """A module runner whose presence, unit and details a test scripts."""

    kind = "system_package"
    name = "samba"

    def __init__(self, *, is_installed=True, is_active_now=False):
        super().__init__(platform=None, log=lambda message: None)
        self.is_installed = is_installed
        self.is_active_now = is_active_now
        self.detail_reads = 0
        self.verified: list = []
        self.stops = 0
        self.removals = 0

    def verify(self, resolved):
        self.verified.append(resolved)
        return self.is_installed

    def is_active(self):
        return self.is_active_now

    def details(self, resolved):
        self.detail_reads += 1
        return {"sessions": [self.detail_reads]}

    def stop(self):
        self.stops += 1

    def remove_configuration(self):
        self.removals += 1

    def uninstall(self, resolved):
        self.is_installed = False


def module_wanted(want: str) -> dict:
    return {
        "samba": {
            "want": want,
            "config": {"shares": []},
            "install": {"kind": "system_package", "packages": ["samba"]},
            "uninstall": {"packages": ["samba"]},
        }
    }


def module_engine(runner, wanted=None, tmp_path=None):
    engine = bare_engine(tmp_path=tmp_path)
    engine._wanted = wanted if wanted is not None else module_wanted("running")
    engine._module_runners = {"samba": runner}
    return engine


def test_a_module_runner_is_found_by_name_before_its_kind():
    runner = ConfigurableRunner()
    engine = module_engine(runner)

    assert engine._runner_for("system_package", "samba") is runner
    assert engine._runner_for("system_package", "samba_mount") is engine._system


def test_every_row_has_the_five_fields():
    engine = module_engine(ConfigurableRunner())

    engine._refresh(is_forced=True)

    for name, row in engine.report().items():
        assert set(row) == ROW_FIELDS, name


@pytest.mark.parametrize(
    "is_marked, is_active_now, state",
    [
        (True, True, "running"),
        (True, False, "stopped"),
        (False, True, "installed"),
        (False, False, "installed"),
    ],
)
def test_the_state_of_software_that_is_there_follows_the_unit_and_the_mark(
    tmp_path, is_marked, is_active_now, state
):
    """The mark says the hub configured the module; the unit then tells the
    two apart. Without the mark it is software the hub never configured,
    whatever the state wants, and ``is_active`` still says whether it runs."""
    runner = ConfigurableRunner(is_active_now=is_active_now)
    engine = module_engine(runner, module_wanted("running"), tmp_path)
    if is_marked:
        engine.mark_configured("samba")

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert row["state"] == state
    assert row["is_active"] is is_active_now
    assert row["code"] == ""


@pytest.mark.parametrize("is_marked", [True, False])
def test_an_install_of_the_module_s_own_reads_installing(tmp_path, is_marked):
    runner = ConfigurableRunner(is_active_now=True)
    runner.is_installing = lambda: True
    engine = module_engine(runner, module_wanted("running"), tmp_path)
    if is_marked:
        engine.mark_configured("samba")

    engine._refresh(is_forced=True)

    assert engine.report()["samba"]["state"] == "installing"


class WaitingRunner(ConfigurableRunner):
    """A runner whose own install runs, or not, and names what holds it up."""

    def __init__(self, *, is_installing_now, wait):
        super().__init__(is_active_now=True)
        self.is_installing_now = is_installing_now
        self.wait = wait

    def is_installing(self):
        return self.is_installing_now

    def install_wait(self):
        return self.wait


def test_an_installing_row_carries_what_holds_the_install_up(tmp_path):
    engine = module_engine(
        WaitingRunner(is_installing_now=True, wait={"code": "reboot_required"}),
        module_wanted("running"),
        tmp_path,
    )

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["code"], row["params"]) == (
        "installing",
        "reboot_required",
        {},
    )


def test_the_wait_s_params_are_copied_onto_the_row(tmp_path):
    params = {"component": "image"}
    engine = module_engine(
        WaitingRunner(
            is_installing_now=True, wait={"code": "install_waits", "params": params}
        ),
        module_wanted("running"),
        tmp_path,
    )

    engine._refresh(is_forced=True)
    params["component"] = "changed"

    assert engine.report()["samba"]["params"] == {"component": "image"}


def test_an_install_waiting_on_nothing_named_reads_installing_with_no_code(tmp_path):
    engine = module_engine(
        WaitingRunner(is_installing_now=True, wait={}),
        module_wanted("running"),
        tmp_path,
    )

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["code"], row["params"]) == ("installing", "", {})


def test_a_module_not_installing_takes_no_code_from_its_install_wait(tmp_path):
    engine = module_engine(
        WaitingRunner(is_installing_now=False, wait={"code": "reboot_required"}),
        module_wanted("running"),
        tmp_path,
    )
    engine.mark_configured("samba")

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["code"]) == ("running", "")


def test_the_mark_is_a_root_only_file_named_after_the_module(tmp_path):
    engine = module_engine(ConfigurableRunner(), tmp_path=tmp_path)

    engine.mark_configured("samba")

    path = tmp_path / "configured" / "samba"
    assert path.is_file()
    assert (os.stat(path).st_mode & 0o777) == 0o600
    assert (os.stat(path.parent).st_mode & 0o777) == 0o700
    assert engine.is_configured("samba") is True
    engine.clear_configured("samba")
    engine.clear_configured("samba")
    assert engine.is_configured("samba") is False


def test_software_that_is_not_there_is_absent_whatever_the_mark(tmp_path):
    runner = ConfigurableRunner(is_installed=False, is_active_now=True)
    engine = module_engine(runner, module_wanted("running"), tmp_path)
    engine.mark_configured("samba")

    engine._refresh(is_forced=True)

    assert engine.report()["samba"] == {
        "state": "absent",
        "is_active": False,
        "code": "",
        "params": {},
        "details": {},
    }


class PartlyThereRunner(ConfigurableRunner):
    """A runner whose check fails and which names the part that is missing."""

    def absent_reason(self, resolved):
        return {"code": "zfs_kernel_module_missing", "params": {"kernel": "6.1.0"}}


def test_an_absent_row_carries_the_part_its_runner_names_missing(tmp_path):
    engine = module_engine(
        PartlyThereRunner(is_installed=False), module_wanted("running"), tmp_path
    )

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["code"], row["params"]) == (
        "absent",
        "zfs_kernel_module_missing",
        {"kernel": "6.1.0"},
    )


def test_a_kept_failure_takes_the_place_of_the_missing_part(tmp_path):
    engine = module_engine(
        PartlyThereRunner(is_installed=False), module_wanted("running"), tmp_path
    )
    engine.record_failure(
        "samba", {"state": "failed", "code": "uninstall_unconfirmed", "params": {}}
    )

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["code"], row["params"]) == (
        "absent",
        "uninstall_unconfirmed",
        {},
    )


def test_a_module_the_state_does_not_name_is_observed_by_its_own_check():
    """A hand-installed Samba shows as installed, its unit reported, from
    the runner's own check: there is no recipe to ask."""
    runner = ConfigurableRunner(is_active_now=True)
    engine = module_engine(runner, wanted={})

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["is_active"]) == ("installed", True)
    assert runner.verified == [{"kind": "", "entry": {}, "verify": "", "package": ""}]


def test_the_recipes_verify_command_decides_presence_over_the_runner(
    monkeypatch, tmp_path
):
    runner = ConfigurableRunner(is_installed=False)
    wanted = module_wanted("running")
    wanted["samba"]["install"]["verify"] = "smbd -V"
    engine = module_engine(runner, wanted, tmp_path)
    engine.mark_configured("samba")
    asked: list = []
    monkeypatch.setattr(
        engine_module, "verify_passes", lambda command: asked.append(command) or True
    )

    engine._refresh(is_forced=True)

    assert asked == ["smbd -V"]
    assert engine.report()["samba"]["state"] == "stopped"
    assert engine.is_installed("samba") is True


def test_is_installed_answers_from_the_runner_when_no_command_is_named():
    runner = ConfigurableRunner(is_installed=True)
    engine = module_engine(runner)

    assert engine.is_installed("samba") is True
    runner.is_installed = False
    assert engine.is_installed("samba") is False
    assert engine.is_installed("nothing") is False


def test_taking_a_state_wakes_the_worker_and_reports_against_it(tmp_path):
    runner = ConfigurableRunner(is_active_now=True)
    engine = module_engine(runner, wanted={}, tmp_path=tmp_path)
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == "installed"
    engine.mark_configured("samba")

    engine.take_state(module_wanted("running"))

    assert engine._wakeup.is_set()
    engine._refresh(is_forced=False)
    assert engine.report()["samba"]["state"] == "running"


def test_an_installed_module_reports_what_it_observes_as_details():
    engine = module_engine(ConfigurableRunner())

    engine._refresh(is_forced=True)

    assert engine.report()["samba"]["details"] == {"sessions": [1]}


def test_modules_are_observed_again_only_once_the_details_are_stale(monkeypatch):
    runner = ConfigurableRunner()
    engine = module_engine(runner)
    engine._refresh(is_forced=True)
    assert runner.detail_reads == 1

    engine._refresh(is_forced=False)
    assert runner.detail_reads == 1

    monkeypatch.setattr("neutrino_agent.core.engine.AGENT_MODULE_DETAILS_TTL_S", 0.0)
    engine._refresh(is_forced=False)
    assert runner.detail_reads == 2
    assert engine.report()["samba"]["details"] == {"sessions": [2]}


def test_report_wakes_the_worker_for_stale_details_and_never_waits():
    engine = module_engine(ConfigurableRunner())
    engine._refresh(is_forced=True)
    engine._details_at = 0.0

    engine.report()

    assert engine._wakeup.is_set()


def failure(state: str, code: str, **params) -> dict:
    return {"state": state, "code": code, "params": params}


def test_an_apply_failure_makes_the_row_failed_with_its_code(tmp_path):
    engine = module_engine(ConfigurableRunner(is_active_now=True), tmp_path=tmp_path)
    engine.mark_configured("samba")
    engine.record_failure(
        "samba", failure("failed", "samba_config_rejected", detail="bad")
    )

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert row["state"] == "failed"
    assert row["is_active"] is True
    assert (row["code"], row["params"]) == ("samba_config_rejected", {"detail": "bad"})

    engine.record_failure("samba", None)
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == "running"
    assert engine.report()["samba"]["code"] == ""


@pytest.mark.parametrize("is_installed", [False, True])
def test_a_failed_install_reads_install_failed_whatever_the_machine_has(
    tmp_path, is_installed
):
    """Nothing left behind, or software the check finds: the row is the
    install's failure, never ``absent`` or ``installed``."""
    engine = module_engine(
        ConfigurableRunner(is_installed=is_installed), tmp_path=tmp_path
    )
    engine.record_failure(
        "samba",
        failure("install_failed", "code_server_download_failed", detail="refused"),
    )

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["code"], row["params"]) == (
        "install_failed",
        "code_server_download_failed",
        {"detail": "refused"},
    )
    assert engine.is_install_failed("samba") is True

    engine.record_failure("samba", None)
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == (
        "installed" if is_installed else "absent"
    )
    assert engine.report()["samba"]["code"] == ""
    assert engine.is_install_failed("samba") is False


def test_a_failed_step_on_software_that_is_there_reads_failed(tmp_path):
    engine = module_engine(ConfigurableRunner(is_installed=True), tmp_path=tmp_path)
    engine.record_failure("samba", failure("failed", "uninstall_unconfirmed"))

    engine._refresh(is_forced=True)

    assert engine.report()["samba"]["state"] == "failed"
    assert engine.report()["samba"]["code"] == "uninstall_unconfirmed"
    assert engine.is_install_failed("samba") is False


class InstallingRunner(ConfigurableRunner):
    """A runner whose install by name succeeds or raises, as a test scripts."""

    def __init__(self, *, is_installed=False, install_error=None):
        super().__init__(is_installed=is_installed)
        self.install_error = install_error
        self.installs = 0

    def install(self, resolved):
        self.installs += 1
        if self.install_error is not None:
            raise self.install_error
        self.is_installed = True


@pytest.mark.parametrize("is_installed", [False, True])
def test_an_install_that_fails_reads_install_failed_and_one_that_takes_clears_it(
    tmp_path, is_installed
):
    runner = InstallingRunner(
        is_installed=is_installed,
        install_error=ModuleApplyError("podman_install_failed", {"exit_code": 1603}),
    )
    engine = module_engine(runner, module_wanted("installed"), tmp_path)

    refusal = engine.install("samba", receive=lambda *names: {})

    assert refusal == {"code": "podman_install_failed", "params": {"exit_code": 1603}}
    row = engine.report()["samba"]
    assert (row["state"], row["code"], row["params"]) == (
        "install_failed",
        "podman_install_failed",
        {"exit_code": 1603},
    )

    runner.install_error = None
    assert engine.install("samba", receive=lambda *names: {}) == {}
    assert engine.report()["samba"]["state"] == "installed"
    assert not (tmp_path / "failures" / "samba.json").exists()


def test_a_kept_failure_reads_the_same_after_the_agent_starts_again(tmp_path):
    """The record is a root-only file under the state root; a new engine on
    the same directory reports it before any state arrives."""
    configured_dir = str(tmp_path / "configured")
    first = ModuleEngine(platform=NoPackagesPlatform(), configured_dir=configured_dir)
    first.record_failure(
        "terminal", failure("install_failed", "install_failed", detail="dpkg")
    )

    path = tmp_path / "failures" / "terminal.json"
    assert (os.stat(path).st_mode & 0o777) == 0o600
    assert (os.stat(path.parent).st_mode & 0o777) == 0o700

    second = ModuleEngine(platform=NoPackagesPlatform(), configured_dir=configured_dir)
    second.refresh_now()

    row = second.report()["terminal"]
    assert (row["state"], row["code"], row["params"]) == (
        "install_failed",
        "install_failed",
        {"detail": "dpkg"},
    )


def test_a_kept_apply_failure_reads_failed_after_the_agent_starts_again(tmp_path):
    configured_dir = str(tmp_path / "configured")
    first = ModuleEngine(platform=NoPackagesPlatform(), configured_dir=configured_dir)
    first.record_failure(
        "terminal", failure("failed", "shell_program_unusable", path="/bin/nope")
    )

    second = ModuleEngine(platform=NoPackagesPlatform(), configured_dir=configured_dir)
    second.refresh_now()

    row = second.report()["terminal"]
    assert (row["state"], row["code"], row["params"]) == (
        "failed",
        "shell_program_unusable",
        {"path": "/bin/nope"},
    )


def test_a_state_that_no_longer_names_the_module_deletes_its_failure(tmp_path):
    engine = module_engine(ConfigurableRunner(is_installed=False), tmp_path=tmp_path)
    engine.record_failure("samba", failure("install_failed", "install_failed"))
    path = tmp_path / "failures" / "samba.json"
    assert path.is_file()

    engine.take_state(module_wanted("installed"))
    assert path.is_file()

    engine.take_state({})

    assert not path.exists()
    assert engine.is_install_failed("samba") is False


@pytest.mark.parametrize(
    "held",
    [
        "not json",
        '{"state": "running", "code": "x", "params": {}}',
        '{"state": "failed", "code": "", "params": {}}',
        "[]",
    ],
)
def test_a_kept_failure_of_another_shape_is_read_as_none(tmp_path, held):
    (tmp_path / "failures").mkdir()
    (tmp_path / "failures" / "terminal.json").write_text(held)

    engine = ModuleEngine(
        platform=NoPackagesPlatform(), configured_dir=str(tmp_path / "configured")
    )

    assert engine._failures == {}


def test_a_module_name_that_is_not_a_plain_file_name_keeps_nothing(tmp_path):
    engine = module_engine(ConfigurableRunner(), tmp_path=tmp_path)

    for name in ("../samba", ".samba", "a/b", "a\\b", ""):
        engine.record_failure(name, failure("failed", "apply_failed"))

    assert engine._failures == {}
    assert not (tmp_path / "failures").exists()


def test_an_uninstall_cleans_up_what_a_failed_install_left(tmp_path):
    """On software the check does not find, a step that fails is a line in
    the log, and the check afterwards is the outcome."""

    class LeftoverRunner(ConfigurableRunner):
        def uninstall(self, resolved):
            raise ModuleApplyError("uninstall_failed", {"detail": "not installed"})

    engine = module_engine(
        LeftoverRunner(is_installed=False), module_wanted("absent"), tmp_path
    )
    engine.record_failure("samba", failure("install_failed", "install_failed"))
    lines: list = []

    refusal = engine.uninstall("samba", on_line=lines.append)

    assert refusal == {}
    assert any("not installed" in line for line in lines)
    assert engine.report()["samba"]["state"] == "absent"
    assert engine.is_install_failed("samba") is False


def test_an_uninstall_step_that_fails_on_software_that_is_there_reads_failed(
    tmp_path,
):
    class StuckRunner(ConfigurableRunner):
        def uninstall(self, resolved):
            raise ModuleApplyError("uninstall_failed", {"detail": "held"})

    engine = module_engine(
        StuckRunner(is_installed=True), module_wanted("absent"), tmp_path
    )

    refusal = engine.uninstall("samba")

    assert refusal == {"code": "uninstall_failed", "params": {"detail": "held"}}
    row = engine.report()["samba"]
    assert (row["state"], row["code"]) == ("failed", "uninstall_failed")


def test_a_queued_module_reads_queued_until_it_leaves_the_set(tmp_path):
    engine = module_engine(ConfigurableRunner(), tmp_path=tmp_path)
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == "installed"

    engine.set_queued(["samba"])
    assert engine.report()["samba"]["state"] == "queued"
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == "queued"

    engine.set_queued(())
    assert engine.report()["samba"]["state"] == "installed"


def test_a_module_mid_operation_keeps_its_transient_row_when_queued(tmp_path):
    engine = module_engine(ConfigurableRunner(), tmp_path=tmp_path)
    engine._in_transit.add("samba")
    engine._publish("samba", engine_module._typed("installing"))

    engine.set_queued(["samba"])

    assert engine.report()["samba"]["state"] == "installing"


def test_a_runner_that_cannot_read_the_machine_is_failed_typed():
    class BrokenRunner(ConfigurableRunner):
        def verify(self, resolved):
            raise PlatformUnsupportedError("no package database here")

    engine = module_engine(BrokenRunner())

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["code"]) == ("failed", "unsupported_platform")


def test_a_module_this_agent_has_no_runner_for_is_reported_unsupported():
    """An older agent meeting a module a newer hub serves is a machine
    that cannot have it, not one that has not answered."""
    engine = bare_engine()
    engine._wanted = {"thing": {"want": "running", "install": {"kind": "ai_tools"}}}

    engine._refresh(is_forced=True)

    assert engine.report()["thing"] == {
        "state": "unsupported",
        "is_active": False,
        "code": "",
        "params": {},
        "details": {},
    }


def test_reporting_a_module_touches_nothing():
    platform = FakePlatform()
    engine = bare_engine(platform=platform, verified=[True])

    engine._refresh(is_forced=True)

    assert platform.installs == []
    assert platform.uninstalls == []
    assert engine.report()["fakedesk"]["state"] == "installed"


def test_uninstalling_a_configured_module_stops_it_and_drops_its_configuration(
    tmp_path,
):
    runner = ConfigurableRunner(is_active_now=True)
    engine = module_engine(runner, module_wanted("absent"), tmp_path)
    engine.mark_configured("samba")

    refusal = engine.uninstall("samba")

    assert refusal == {}
    assert (runner.stops, runner.removals) == (1, 1)
    assert engine.is_configured("samba") is False
    assert engine.report()["samba"]["state"] == "absent"


def test_uninstalling_software_the_hub_never_configured_leaves_its_files(tmp_path):
    runner = ConfigurableRunner()
    engine = module_engine(runner, module_wanted("absent"), tmp_path)

    engine.uninstall("samba")

    assert (runner.stops, runner.removals) == (0, 0)


def test_the_old_rustdesk_row_is_gone_and_remote_desktop_is_reported(tmp_path):
    engine = ModuleEngine(
        platform=NoPackagesPlatform(), configured_dir=str(tmp_path / "configured")
    )

    engine._refresh(is_forced=True)

    assert "rustdesk" not in engine.report()
    assert engine.report()["remote_desktop"]["state"] == "installed"


class NoPackagesPlatform(AgentPlatform):
    """A platform that installs nothing, the way Windows and macOS are."""

    os_name = "windows"
    capabilities = frozenset({"metrics", "power"})


def test_a_platform_without_packages_reports_only_what_the_agent_carries(
    monkeypatch, tmp_path
):
    engine = ModuleEngine(
        platform=NoPackagesPlatform(), configured_dir=str(tmp_path / "configured")
    )

    engine._refresh(is_forced=True)

    assert set(engine.module_runners) == {"terminal", "remote_desktop"}
    assert set(engine.report()) == {"terminal", "remote_desktop"}


def test_a_module_the_state_names_there_is_unsupported_never_failed(
    monkeypatch, tmp_path
):
    engine = ModuleEngine(
        platform=NoPackagesPlatform(), configured_dir=str(tmp_path / "configured")
    )
    samba = {"kind": "system_package", "package": "samba", "verify": "true"}
    engine.take_state(
        {
            "samba": {"want": "running", "config": {}, "install": samba},
            "fakedesk": dict(WANTED["fakedesk"]),
        }
    )

    engine._refresh(is_forced=True)
    report = engine.report()

    assert report["samba"]["state"] == "unsupported"
    assert report["fakedesk"]["state"] == "unsupported"
    assert engine.install("samba", receive=None) == {
        "code": "unknown_kind",
        "params": {"kind": "system_package"},
    }


class SmbServerApplier:
    """A system SMB server that is there and running."""

    def read_status(self, record):
        return {"is_present": True, "is_running": True}

    def reload_fence(self):
        """Nothing kept to load."""


class SmbServerPlatform(AgentPlatform):
    """A platform that carries its own SMB server, the way Windows does."""

    os_name = "windows"
    capabilities = frozenset({"smb_server"})

    def smb_server_applier(self):
        return SmbServerApplier()


class FenceRefusingApplier(SmbServerApplier):
    """An SMB applier whose kept fence pf refuses to load."""

    def reload_fence(self):
        raise subprocess.CalledProcessError(1, ["pfctl"])


class FenceRefusingPlatform(SmbServerPlatform):
    def smb_server_applier(self):
        return FenceRefusingApplier()


def test_a_fence_that_does_not_load_is_logged_while_the_engine_is_made(tmp_path):
    lines = []

    engine = ModuleEngine(
        platform=FenceRefusingPlatform(),
        log=lines.append,
        configured_dir=str(tmp_path / "configured"),
    )

    assert "samba" in engine.module_runners
    assert any(line.startswith("samba: the fence did not load") for line in lines)


def test_a_system_with_its_own_smb_server_runs_the_file_share_alone(
    monkeypatch, tmp_path
):
    engine = ModuleEngine(
        platform=SmbServerPlatform(), configured_dir=str(tmp_path / "configured")
    )
    engine.take_state(
        {
            "samba": {
                "want": "running",
                "config": {},
                "install": {"kind": "system_package"},
            },
            "fakedesk": dict(WANTED["fakedesk"]),
        }
    )

    engine._refresh(is_forced=True)
    report = engine.report()

    assert set(engine.module_runners) == {"samba", "terminal", "remote_desktop"}
    assert report["samba"]["state"] == "installed"
    assert report["fakedesk"]["state"] == "unsupported"
    assert engine.install("samba", receive=None) == {}


class HubPackagesPlatform(SmbServerPlatform):
    """A platform that also unpacks the hub's software, the way Windows does."""

    capabilities = frozenset({"smb_server", "hub_packages"})

    def __init__(self, root):
        self._root = root

    def hub_package_root(self):
        return self._root


def test_a_system_that_unpacks_the_hub_s_software_runs_vs_code_from_its_bytes(
    monkeypatch, tmp_path
):
    engine = ModuleEngine(
        platform=HubPackagesPlatform(str(tmp_path / "Neutrino")),
        configured_dir=str(tmp_path / "configured"),
    )
    engine.take_state(
        {
            "vscode": {
                "want": "installed",
                "config": {},
                "install": {"kind": "vscode", "package_kind": "zip"},
            }
        }
    )
    received = []

    def receive(name):
        received.append(name)
        return {"code": "hub_unreachable", "params": {}}

    engine._refresh(is_forced=True)

    assert set(engine.module_runners) == {
        "samba",
        "gitea",
        "podman",
        "vscode",
        "cloudcli",
        "codeg",
        "terminal",
        "remote_desktop",
    }
    assert engine.module_runners["podman"].kind == "podman_machine"
    assert engine.report()["vscode"]["state"] == "absent"
    assert engine.install("vscode", receive=receive) == {
        "code": "hub_unreachable",
        "params": {},
    }
    assert received == ["vscode"]


def test_code_server_runs_on_a_mac_beside_vs_code_and_not_on_windows(tmp_path):
    class MacHubPackagesPlatform(HubPackagesPlatform):
        os_name = "darwin"

    mac = ModuleEngine(
        platform=MacHubPackagesPlatform(str(tmp_path / "Neutrino")),
        configured_dir=str(tmp_path / "configured"),
    )
    windows = ModuleEngine(
        platform=HubPackagesPlatform(str(tmp_path / "Neutrino")),
        configured_dir=str(tmp_path / "configured"),
    )

    assert "code_server" in mac.module_runners
    assert "code_server" not in windows.module_runners
    assert "codeg" in mac.module_runners
    assert "codeg" in windows.module_runners


def test_containers_run_in_a_podman_machine_on_windows_and_macos_alone(tmp_path):
    class MacHubPackagesPlatform(HubPackagesPlatform):
        os_name = "darwin"

    class LinuxHubPackagesPlatform(HubPackagesPlatform):
        os_name = "linux"

    for platform_class in (HubPackagesPlatform, MacHubPackagesPlatform):
        engine = ModuleEngine(
            platform=platform_class(str(tmp_path / "Neutrino")),
            configured_dir=str(tmp_path / "configured"),
        )
        runner = engine.module_runners["podman"]
        assert isinstance(runner, PodmanMachineModuleRunner)
        assert runner.kind == "podman_machine"
    linux = ModuleEngine(
        platform=LinuxHubPackagesPlatform(str(tmp_path / "Neutrino")),
        configured_dir=str(tmp_path / "configured"),
    )
    assert "podman" not in linux.module_runners


def test_a_platform_with_packages_builds_the_vs_code_runner(tmp_path):
    class PackagesPlatform(FakePlatform):
        capabilities = frozenset({"packages"})

    engine = ModuleEngine(
        platform=PackagesPlatform(), configured_dir=str(tmp_path / "configured")
    )

    assert set(engine.module_runners) == {
        "samba",
        "gitea",
        "podman",
        "zfs",
        "vscode",
        "code_server",
        "cloudcli",
        "codeg",
        "terminal",
        "remote_desktop",
    }
    assert type(engine.module_runners["podman"]) is PodmanModuleRunner


# --- components ---


class ComponentRunner(ModuleRunner):
    """A module whose software comes as components, recorded as they land."""

    kind = "demo"
    name = "demo"
    download_failure_code = "demo_download_failed"

    def __init__(self):
        super().__init__(platform=AgentPlatform(), log=lambda line: None)
        self.landed: list = []
        self.installed: list = []

    def verify(self, resolved):
        return bool(self.landed)

    def install(self, resolved, package_path):
        self.installed.append(package_path)
        self.landed.append(("one", "", True))

    def install_component(self, resolved, component, package_path):
        self.landed.append(
            (component["name"], component["directory"], os.path.exists(package_path))
        )


COMPONENT_RECIPE = {
    "kind": "demo",
    "verify": "",
    "components": [
        {
            "name": "server",
            "package_kind": "tar",
            "directory": "server",
            "sha256": "a" * 64,
        },
        {
            "name": "node",
            "package_kind": "tar",
            "directory": "node",
            "sha256": "b" * 64,
        },
    ],
}
COMPONENT_DIGESTS = {"server": "a" * 64, "node": "b" * 64}


def component_engine(runner, recipe, tmp_path):
    engine = bare_engine(tmp_path=tmp_path)
    engine._wanted = {
        "demo": {
            "want": "installed",
            "config": {},
            "install": dict(recipe),
            "uninstall": {},
        }
    }
    engine._module_runners = {"demo": runner}
    return engine


def component_receive(received, tmp_path, digests):
    """A receive that writes each component's archive and records what was asked."""

    def receive(name, component=""):
        received.append((name, component))
        path = tmp_path / f"{component or name}.tar"
        path.write_bytes(b"archive")
        return {"path": str(path), "sha256": digests.get(component, "")}

    return receive


def test_a_recipe_with_components_receives_each_and_unpacks_it_under_its_directory(
    tmp_path,
):
    runner = ComponentRunner()
    engine = component_engine(runner, COMPONENT_RECIPE, tmp_path)
    received: list = []

    refusal = engine.install(
        "demo", receive=component_receive(received, tmp_path, COMPONENT_DIGESTS)
    )

    assert refusal == {}
    assert received == [("demo", "server"), ("demo", "node")]
    assert runner.landed == [("server", "server", True), ("node", "node", True)]
    assert runner.installed == []
    assert not (tmp_path / "server.tar").exists()
    assert not (tmp_path / "node.tar").exists()


def test_a_component_whose_digest_is_not_the_recipes_is_refused_and_deleted(tmp_path):
    runner = ComponentRunner()
    engine = component_engine(runner, COMPONENT_RECIPE, tmp_path)
    digests = dict(COMPONENT_DIGESTS, node="x" * 64)

    refusal = engine.install("demo", receive=component_receive([], tmp_path, digests))

    assert refusal == {
        "code": "package_digest_mismatch",
        "params": {"component": "node"},
    }
    assert runner.landed == [("server", "server", True)]
    assert not (tmp_path / "node.tar").exists()


def test_a_component_the_hub_could_not_hand_down_is_the_modules_own_code(tmp_path):
    runner = ComponentRunner()
    engine = component_engine(runner, COMPONENT_RECIPE, tmp_path)

    def refuse(name, component=""):
        return {"code": "module_fetch_failed", "params": {}}

    refusal = engine.install("demo", receive=refuse)

    assert refusal == {
        "code": "demo_download_failed",
        "params": {"detail": "module_fetch_failed"},
    }
    assert runner.landed == []


def test_a_recipe_with_one_archive_asks_with_the_module_name_alone(tmp_path):
    runner = ComponentRunner()
    recipe = {"kind": "demo", "verify": "", "package_kind": "tar"}
    engine = component_engine(runner, recipe, tmp_path)
    received: list = []

    def receive(name):
        received.append(name)
        path = tmp_path / "one.tar"
        path.write_bytes(b"archive")
        return {"path": str(path), "sha256": "c" * 64}

    assert engine.install("demo", receive=receive) == {}
    assert received == ["demo"]
    assert runner.installed == [str(tmp_path / "one.tar")]


def test_a_runner_that_unpacks_no_component_is_install_failed(tmp_path):
    class BareRunner(ComponentRunner):
        def install_component(self, resolved, component, package_path):
            ModuleRunner.install_component(self, resolved, component, package_path)

    engine = component_engine(BareRunner(), COMPONENT_RECIPE, tmp_path)

    refusal = engine.install(
        "demo", receive=component_receive([], tmp_path, COMPONENT_DIGESTS)
    )

    assert refusal["code"] == "install_failed"
    assert "installs no component" in refusal["params"]["detail"]
