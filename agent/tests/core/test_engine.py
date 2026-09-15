"""The module engine: observing against the state, and holding no policy.

The engine is handed the state's modules section, each entry carrying the
recipe resolved for this platform, and observes every module it has a
runner for, named or not. What is pinned here is the state it derives from
three facts (the software there, the unit active, the hub's want), the
five fields of every row, orders run in the caller's thread with each
output line handed on as it comes, results judged by the machine's own
state, and that nothing in it ever retries anything.
"""

import threading

import pytest

import neutrino_agent.core.engine as engine_module
from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.exceptions import InstallError, PlatformUnsupportedError
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
        self.installs.append((package_kind, entry))
        if self._install_error is not None:
            raise self._install_error

    def uninstall_package(self, command):
        self.uninstalls.append(command)


def bare_engine(*, platform=None, fetch_artifact=None, verified=None):
    """An engine with no worker thread, driven a pass at a time.

    Args:
        platform: The machine's platform.
        fetch_artifact: What the hub hands down.
        verified: Scripted answers for verify; the last one repeats.

    Returns:
        The engine.
    """
    engine = ModuleEngine.__new__(ModuleEngine)
    engine._wanted = {name: dict(entry) for name, entry in WANTED.items()}
    engine._platform_tuple = {"os": "linux", "family": "debian", "arch": "amd64"}
    engine._output = []
    engine._on_line = None
    engine._order_lock = threading.Lock()
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
    engine._fetch_artifact = fetch_artifact
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


def landing_fetch(fetches):
    """A fetch that writes a package and records the key it was asked for."""

    def fetch(artifact_key, destination):
        fetches.append(artifact_key)
        with open(destination, "wb") as stream:
            stream.write(b"!<arch>package")
        return {}

    return fetch


INSTALL_ORDER = {
    "id": "order-1",
    "module": "fakedesk",
    "action": "install",
    "artifact_key": "key",
    "package_kind": "deb",
}


def test_an_order_installs_what_it_is_given_and_reports_done():
    fetches: list = []
    platform = FakePlatform()
    engine = bare_engine(
        platform=platform, fetch_artifact=landing_fetch(fetches), verified=[True]
    )

    result = engine.run_order(
        dict(INSTALL_ORDER, artifact_key="fakedesk-linux-debian-amd64-aaaa")
    )

    assert fetches == ["fakedesk-linux-debian-amd64-aaaa"]
    # The recipe's entry is what the platform installs by: the header
    # fields name the runner and the check, and are not part of it.
    assert platform.installs == [
        ("deb", {"package_kind": "deb", "uninstall": "apt-get remove -y fakedesk"})
    ]
    assert result["state"] == "done"
    assert result["code"] == ""
    # Success carries its output too: a person watching an install came to
    # read the log of something that worked.
    assert "fakedesk: installing" in result["output"]


def test_each_output_line_is_handed_on_as_it_comes():
    engine = bare_engine(fetch_artifact=landing_fetch([]), verified=[True])
    lines: list = []

    engine.run_order(INSTALL_ORDER, on_line=lines.append)

    assert lines[0] == "fakedesk: install"
    assert "fakedesk: installing" in lines
    # The line handler is the stream's; it does not outlive the order.
    assert engine._on_line is None


def test_an_install_the_machine_cannot_confirm_is_failed_not_latched():
    engine = bare_engine(fetch_artifact=landing_fetch([]), verified=[False])

    result = engine.run_order(INSTALL_ORDER)

    assert result["state"] == "failed"
    assert result["code"] == "install_unconfirmed"


def test_a_failed_install_reports_the_output_it_produced():
    platform = FakePlatform(install_error=InstallError("dpkg failed: held broken"))
    engine = bare_engine(
        platform=platform, fetch_artifact=landing_fetch([]), verified=[False]
    )

    result = engine.run_order(INSTALL_ORDER)

    assert result["state"] == "failed"
    assert result["code"] == "install_failed"
    # The vendor's own words, not only that something went wrong.
    assert "dpkg failed: held broken" in result["output"]


def test_a_refused_fetch_is_reported_with_the_hubs_own_code():
    def refuse(artifact_key, destination):
        return {"code": "module_fetch_failed", "params": {"detail": "refused"}}

    engine = bare_engine(fetch_artifact=refuse, verified=[False])

    result = engine.run_order(INSTALL_ORDER)

    assert result["code"] == "module_fetch_failed"
    assert result["params"] == {"detail": "refused"}


def test_an_uninstall_is_run_and_confirmed():
    platform = FakePlatform()
    engine = bare_engine(platform=platform, verified=[False])

    result = engine.run_order(
        {"id": "order-1", "module": "fakedesk", "action": "uninstall"}
    )

    assert platform.uninstalls == ["apt-get purge -y fakedesk"]
    assert result["state"] == "done"


def test_an_uninstall_that_did_not_take_is_reported_failed():
    engine = bare_engine(verified=[True])

    result = engine.run_order(
        {"id": "order-1", "module": "fakedesk", "action": "uninstall"}
    )

    assert result["code"] == "uninstall_unconfirmed"


def test_an_idle_pass_reruns_nothing():
    fetches: list = []
    engine = bare_engine(fetch_artifact=landing_fetch(fetches), verified=[False])

    engine.run_order(INSTALL_ORDER)
    # Every idle pass after a failed order must run nothing: deciding to
    # try again is the hub's, and it does so with a new order.
    for _ in range(5):
        engine._reconcile()

    assert fetches == ["key"]


def test_asking_again_is_a_new_order_and_runs():
    fetches: list = []
    engine = bare_engine(fetch_artifact=landing_fetch(fetches), verified=[False])

    engine.run_order(INSTALL_ORDER)
    engine.run_order(dict(INSTALL_ORDER, id="order-2"))

    assert fetches == ["key", "key"]


def test_an_order_for_a_module_the_state_does_not_name_is_refused_not_attempted():
    fetches: list = []
    engine = bare_engine(fetch_artifact=landing_fetch(fetches))
    engine._wanted = {}

    result = engine.run_order(INSTALL_ORDER)

    assert fetches == []
    assert result["code"] == "unknown_module"
    assert result["params"] == {"module": "fakedesk"}


def test_an_action_this_agent_does_not_know_is_typed_not_guessed():
    engine = bare_engine(verified=[False])

    result = engine.run_order(
        {"id": "order-1", "module": "fakedesk", "action": "reticulate"}
    )

    assert result["code"] == "unknown_action"
    assert result["params"] == {"action": "reticulate"}


def test_a_platform_that_installs_nothing_is_reported_not_raised():
    engine = bare_engine(
        platform=AgentPlatform(), fetch_artifact=landing_fetch([]), verified=[False]
    )

    result = engine.run_order(INSTALL_ORDER)

    assert result["code"] == "unsupported_platform"


def test_reporting_a_module_touches_nothing():
    platform = FakePlatform()
    engine = bare_engine(platform=platform, verified=[True])

    engine._refresh(is_forced=True)

    assert platform.installs == []
    assert platform.uninstalls == []
    assert engine.report()["fakedesk"]["state"] == "installed"


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


def test_an_absent_capability_reports_unsupported_platform():
    engine = bare_engine(platform=AgentPlatform())
    engine._wanted = dict(SYSTEM_WANTED)

    result = engine.run_order(
        {"id": "order-1", "module": "samba_mount", "action": "install"}
    )

    assert (result["state"], result["code"]) == ("failed", "unsupported_platform")


def test_the_engine_holds_no_failure_memory():
    engine = bare_engine(fetch_artifact=landing_fetch([]), verified=[False])

    engine.run_order(INSTALL_ORDER)

    # A result is the stream's answer, not a record of what failed: there
    # is no latch, no failure map and no attempt count here.
    assert not hasattr(engine, "_install_failed")
    assert not hasattr(engine, "_install_unconfirmed")
    assert not hasattr(engine, "_remove_unconfirmed")
    assert not hasattr(engine, "_results")


# --- the by-name kind rides the same order path ---

SYSTEM_WANTED = {
    "samba_mount": {
        "want": "installed",
        "config": {},
        "install": {"kind": "system_package", "packages": ["cifs-utils"]},
        "uninstall": {},
    }
}


class SystemPackagePlatform(AgentPlatform):
    """A platform whose own package manager is observable."""

    os_name = "linux"

    def __init__(self):
        self.installed: list = []
        self.removed: list = []

    def install_system_packages(self, names):
        self.installed.append(list(names))
        return "Setting up cifs-utils"

    def remove_system_packages(self, names):
        self.removed.append(list(names))
        return ""


def test_a_system_package_order_installs_by_name_and_fetches_nothing():
    platform = SystemPackagePlatform()
    fetches: list = []
    engine = bare_engine(platform=platform, fetch_artifact=landing_fetch(fetches))
    engine._wanted = dict(SYSTEM_WANTED)
    engine._system.verify = lambda resolved: True

    result = engine.run_order(
        {"id": "order-1", "module": "samba_mount", "action": "install"}
    )

    assert platform.installed == [["cifs-utils"]]
    assert fetches == []
    assert result["state"] == "done"
    assert "Setting up cifs-utils" in result["output"]


def test_a_system_package_uninstall_rides_the_package_manager_too():
    platform = SystemPackagePlatform()
    engine = bare_engine(platform=platform)
    engine._wanted = dict(SYSTEM_WANTED)
    engine._system.verify = lambda resolved: False

    result = engine.run_order(
        {"id": "order-1", "module": "samba_mount", "action": "uninstall"}
    )

    assert platform.removed == [["cifs-utils"]]
    assert result["state"] == "done"


# --- the modules this agent applies, observed against the state ---


class ConfigurableRunner:
    """A module runner whose presence, unit and details a test scripts."""

    kind = "system_package"
    name = "samba"

    def __init__(self, *, is_installed=True, is_active_now=False):
        self.is_installed = is_installed
        self.is_active_now = is_active_now
        self.detail_reads = 0
        self.verified: list = []

    def verify(self, resolved):
        self.verified.append(resolved)
        return self.is_installed

    def is_active(self):
        return self.is_active_now

    def details(self, resolved):
        self.detail_reads += 1
        return {"sessions": [self.detail_reads]}


def module_wanted(want: str) -> dict:
    return {
        "samba": {
            "want": want,
            "config": {"shares": []},
            "install": {"kind": "system_package", "packages": ["samba"]},
            "uninstall": {},
        }
    }


def module_engine(runner, wanted=None):
    engine = bare_engine()
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
    "want, is_active_now, state",
    [
        ("running", True, "running"),
        ("running", False, "stopped"),
        ("stopped", False, "stopped"),
        ("stopped", True, "running"),
        ("installed", True, "installed"),
        ("installed", False, "installed"),
        ("absent", True, "installed"),
    ],
)
def test_the_state_of_software_that_is_there_follows_the_unit_and_the_want(
    want, is_active_now, state
):
    """The hub has configured a module it wants running or stopped; the
    unit then tells the two apart. Any other want is software the hub has
    not configured, and ``is_active`` still says whether it runs."""
    runner = ConfigurableRunner(is_active_now=is_active_now)
    engine = module_engine(runner, module_wanted(want))

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert row["state"] == state
    assert row["is_active"] is is_active_now
    assert row["code"] == ""


def test_software_that_is_not_there_is_absent_whatever_the_want():
    runner = ConfigurableRunner(is_installed=False, is_active_now=True)
    engine = module_engine(runner, module_wanted("running"))

    engine._refresh(is_forced=True)

    assert engine.report()["samba"] == {
        "state": "absent",
        "is_active": False,
        "code": "",
        "params": {},
        "details": {},
    }
    assert runner.detail_reads == 0


def test_a_module_the_state_does_not_name_is_observed_by_its_own_check():
    """A hand-installed Samba shows as installed, its unit reported, from
    the runner's own check: there is no recipe to ask."""
    runner = ConfigurableRunner(is_active_now=True)
    engine = module_engine(runner, wanted={})

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["is_active"]) == ("installed", True)
    assert runner.verified == [{"kind": "", "entry": {}, "verify": "", "package": ""}]


def test_the_recipes_verify_command_decides_presence_over_the_runner(monkeypatch):
    runner = ConfigurableRunner(is_installed=False)
    wanted = module_wanted("running")
    wanted["samba"]["install"]["verify"] = "smbd -V"
    engine = module_engine(runner, wanted)
    asked: list = []
    monkeypatch.setattr(
        engine_module, "verify_passes", lambda command: asked.append(command) or True
    )

    engine._refresh(is_forced=True)

    assert asked == ["smbd -V"]
    assert runner.verified == []
    assert engine.report()["samba"]["state"] == "stopped"
    assert engine.is_installed("samba") is True


def test_is_installed_answers_from_the_runner_when_no_command_is_named():
    runner = ConfigurableRunner(is_installed=True)
    engine = module_engine(runner)

    assert engine.is_installed("samba") is True
    runner.is_installed = False
    assert engine.is_installed("samba") is False
    assert engine.is_installed("nothing") is False


def test_taking_a_state_wakes_the_worker_and_reports_against_it():
    runner = ConfigurableRunner(is_active_now=True)
    engine = module_engine(runner, wanted={})
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == "installed"

    engine.take_state(module_wanted("running"))

    assert engine._wakeup.is_set()
    engine._refresh(is_forced=False)
    assert engine.report()["samba"]["state"] == "running"


def test_an_installed_module_reports_its_details():
    engine = module_engine(ConfigurableRunner())

    engine._refresh(is_forced=True)

    assert engine.report()["samba"]["details"] == {"sessions": [1]}


def test_details_are_read_again_only_once_they_are_stale(monkeypatch):
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


def test_an_apply_failure_makes_the_row_failed_with_its_code():
    engine = module_engine(ConfigurableRunner(is_active_now=True))
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


def test_the_built_in_module_takes_no_order():
    engine = bare_engine()

    result = engine.run_order({"id": "o", "module": "rustdesk", "action": "install"})

    assert (result["state"], result["code"]) == ("failed", "module_not_orderable")
    assert result["params"] == {"module": "rustdesk"}
