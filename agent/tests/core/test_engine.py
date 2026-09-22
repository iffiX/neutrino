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
at a time, and that nothing in it ever retries anything.
"""

import os
import threading
import time

import pytest

import neutrino_agent.core.engine as engine_module
from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.exceptions import InstallError, PlatformUnsupportedError
from neutrino_agent.modules.base import ModuleRunner
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
    engine._platform_tuple = {"os": "linux", "family": "debian", "arch": "amd64"}
    engine._on_line = None
    engine._operation_lock = threading.Lock()
    engine._in_transit = set()
    engine._statuses = {}
    engine._signature = ""
    engine._checked_at = 0.0
    engine._log = lambda message: None
    engine._on_change = None
    engine._lock = threading.Lock()
    engine._wakeup = threading.Event()
    engine._apply_results = {}
    engine._details_at = 0.0
    engine._module_runners = {}

    from neutrino_agent.modules.package import PackageModuleRunner
    from neutrino_agent.modules.system_package import SystemPackageModuleRunner

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
    engine = bare_engine(verified=[False, True], tmp_path=tmp_path)
    seen: list = []

    def receive(name):
        seen.append(engine.report()["fakedesk"]["state"])
        # A refresh under way keeps the transient row.
        engine._refresh(is_forced=True)
        seen.append(engine.report()["fakedesk"]["state"])
        return landing_receive([], tmp_path)(name)

    engine.install("fakedesk", receive=receive)

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


def test_the_built_in_module_takes_no_operation(tmp_path):
    engine = bare_engine(tmp_path=tmp_path)

    refusal = engine.install("rustdesk", receive=landing_receive([], tmp_path))

    assert refusal == {"code": "module_not_orderable", "params": {"module": "rustdesk"}}
    assert engine.uninstall("rustdesk") == refusal


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


def test_the_engine_holds_no_failure_memory(tmp_path):
    engine = bare_engine(verified=[False], tmp_path=tmp_path)

    engine.install("fakedesk", receive=landing_receive([], tmp_path))

    # A result is the applier's answer, not a record of what failed: there
    # is no latch, no failure map and no attempt count here.
    assert not hasattr(engine, "_install_failed")
    assert not hasattr(engine, "_install_unconfirmed")
    assert not hasattr(engine, "_remove_unconfirmed")
    assert not hasattr(engine, "_results")


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


def test_an_apply_failure_makes_the_row_failed_with_its_code(tmp_path):
    engine = module_engine(ConfigurableRunner(is_active_now=True), tmp_path=tmp_path)
    engine.mark_configured("samba")
    engine.record_apply("samba", "samba_config_rejected", {"detail": "bad"})

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert row["state"] == "failed"
    assert row["is_active"] is True
    assert (row["code"], row["params"]) == ("samba_config_rejected", {"detail": "bad"})

    engine.record_apply("samba", "", {})
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == "running"
    assert engine.report()["samba"]["code"] == ""


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


def test_the_built_in_rustdesk_row_follows_the_agents_own_binary(monkeypatch, tmp_path):
    engine = bare_engine()
    engine._wanted = {}
    binary = tmp_path / "rustdesk"
    monkeypatch.setattr(
        "neutrino_agent.core.engine.AGENT_RUSTDESK_BINARY_PATH", str(binary)
    )

    engine._refresh(is_forced=True)
    assert engine.report()["rustdesk"]["state"] == "absent"

    binary.write_text("")
    engine._refresh(is_forced=True)
    assert engine.report()["rustdesk"]["state"] == "installed"
