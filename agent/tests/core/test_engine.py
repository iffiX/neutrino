"""The module engine: observing against the state, and moving software.

The engine is handed the state's modules section, each entry carrying the
recipe resolved for this platform, ``{runner, method, params}``, and
observes every module it has a runner for, named or not. What is pinned
here is the runner the recipe's ``runner`` chooses, an unknown one reading
unsupported; the state derived from three facts (the software there by the
method's one presence check, the unit active, the configured mark on disk)
with the unit and the details read whenever that check passes, whatever the
runner's own check says; the five fields of every row; the mark written and
cleared by name; an install and an uninstall run in the caller's thread
with each output line handed on as it comes and the row transient
meanwhile; a ``hub`` recipe's system packages installed by name before its
artifacts, each artifact asked for as ``{module, artifact, digest}``,
checked against its digest and deleted afterwards, the hub's refusal
passed on as it came; a ``system`` recipe installed by name and its
uninstall's own packages and steps; results judged by the machine's own
state; one package operation at a time; a module whose own install runs
reading installing with the code its runner names for what holds it up;
the modules waiting behind the one being applied reading queued; a failed
install reading install_failed with its code whatever the machine has, any
other failed step reading failed while the software is there, both kept
root-only on disk and read the same by an engine that starts again, until
the next attempt replaces them or a state stops naming the module, and kept
off the row while the module's task runs; an uninstall of what a failed
install left judged by the check afterwards; the steps of the programs run
as an account, the file share and Gitea with their locks; and that nothing
in it ever retries anything.
"""

import os
import threading
import time

import pytest

import neutrino_agent.core.engine as engine_module
from neutrino_agent.core.desired_state import APPLY_ORDER
from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.core.tasks import run_step
from neutrino_agent.exceptions import (
    InstallError,
    ModuleApplyError,
    PlatformUnsupportedError,
)
from neutrino_agent.modules.podman.container_runner import (
    ContainerModuleRunner,
    recipe_images,
)
from neutrino_agent.modules.podman.machine_runner import PodmanMachineModuleRunner
from neutrino_agent.modules.podman.runner import PodmanModuleRunner
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.modules.shared.step_locks import is_in_order
from neutrino_agent.modules.shared.system_package import SystemPackageModuleRunner
from neutrino_agent.platforms.base import AgentPlatform

DIGEST = "ab" * 32
ARTIFACT = {"name": "app", "kind": "binary", "digest": "sha256:" + DIGEST}
HUB_RECIPE = {
    "runner": "fakedesk",
    "method": "hub",
    "params": {
        "version": "1.0",
        "artifacts": [dict(ARTIFACT)],
        "verify": "fakedesk --version",
        "uninstall": {"post_uninstall": [], "is_data_kept": True},
    },
}

WANTED = {"fakedesk": {"want": "installed", "config": {}, "install": HUB_RECIPE}}

ROW_FIELDS = {"state", "is_active", "code", "params", "details", "task"}
# A task's row as the applier publishes it.
TASK_ROW = {
    "steps": [{"name": "packages", "params": {}}, {"name": "verify", "params": {}}],
    "index": 1,
    "wait": {},
    "is_running": True,
}


class FakePlatform(AgentPlatform):
    """A platform whose package manager records what it is asked."""

    os_name = "linux"

    def __init__(self):
        self.installed: list = []

    def install_system_packages(self, names):
        self.installed.append(list(names))
        return ""


class HubRunner(ModuleRunner):
    """A ``hub`` module that records each artifact it is handed."""

    runner = "fakedesk"
    name = "fakedesk"

    def __init__(self, *, platform=None, install_error=None):
        super().__init__(
            platform=platform if platform is not None else FakePlatform(),
            log=lambda message: None,
        )
        self.install_error = install_error
        self.landed: list = []
        self.uninstalls = 0

    def install_artifact(self, recipe, artifact, path):
        self.landed.append((artifact["name"], os.path.exists(path)))
        if self.install_error is not None:
            raise self.install_error

    def uninstall(self, recipe):
        self.uninstalls += 1


def bare_engine(*, runner=None, verified=None, tmp_path=None):
    """An engine with no worker thread, driven a pass at a time.

    Args:
        runner: The one runner it has; a fresh :class:`HubRunner` by default.
        verified: Scripted answers for the presence check; the last one
            repeats. None leaves the engine's own check.
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
    engine._versions_dir = (
        str(tmp_path / "versions") if tmp_path else "/nowhere/versions"
    )
    engine._platform_tuple = {"os": "linux", "family": "debian", "arch": "amd64"}
    engine._lines = threading.local()
    engine._task_rows = {}
    engine._statuses = {}
    engine._signature = ""
    engine._checked_at = 0.0
    engine._log = lambda message: None
    engine._on_change = None
    engine._lock = threading.Lock()
    engine._wakeup = threading.Event()
    engine._failures = {}
    engine._verify_failures = {}
    engine._details_at = 0.0
    runner = runner if runner is not None else HubRunner()
    engine._module_runners = {runner.name: runner}
    engine._runners_by_name = {runner.runner: runner}
    engine._container_runners = {}
    engine._configure_asker = None
    engine._platform = None
    if verified is not None:
        answers = list(verified)

        def is_present(runner, recipe):
            return answers.pop(0) if len(answers) > 1 else answers[0]

        engine._is_present = is_present
    return engine


class StepContext:
    """What a step is handed here: its lines and the artifacts it receives."""

    def __init__(self, name, receive=None, on_line=None):
        self.name = name
        self._receive = receive
        self._on_line = on_line
        self.waits: list = []

    def log(self, line):
        if self._on_line is not None:
            self._on_line(line)

    def receive(self, artifact):
        return self._receive(self.name, artifact)

    def wait_for_containers(self):
        self.waits.append("wait_containers")

    def render_containers(self):
        self.waits.append("render")


def run_task(engine, name, steps, *, receive=None, on_line=None) -> dict:
    """Run steps as a task does, in this thread: the lines to ``on_line``,
    the failure kept, the row read again afterwards."""
    context = StepContext(name, receive, on_line)
    engine.set_line_sink(on_line)
    failure = None
    try:
        for step in steps:
            failure = run_step(step, context)
            if failure is not None:
                break
    finally:
        engine.set_line_sink(None)
    engine.record_failure(name, failure)
    engine.refresh_one(name)
    if failure is None:
        return {}
    return {"code": failure["code"], "params": failure["params"]}


def install(engine, name, *, receive, on_line=None) -> dict:
    """One module's install steps, run as its task runs them."""
    steps = engine.install_steps(name, engine._wanted[name])
    return run_task(engine, name, steps, receive=receive, on_line=on_line)


def uninstall(engine, name, *, on_line=None) -> dict:
    """One module's uninstall steps, run as its task runs them."""
    steps = engine.uninstall_steps(name, engine._wanted[name])
    return run_task(engine, name, steps, on_line=on_line)


def switch(engine, name, *, receive, on_line=None) -> dict:
    """One module's version switch, run as its task runs it."""
    steps = engine.switch_steps(name, engine._wanted[name])
    return run_task(engine, name, steps, receive=receive, on_line=on_line)


def landing_receive(received, tmp_path, sha256=DIGEST):
    """A receive that writes each artifact and records what was asked."""

    def receive(name, artifact):
        received.append((name, artifact["name"], artifact["digest"]))
        path = tmp_path / f"{artifact['name']}.bin"
        path.write_bytes(b"\x7fELF")
        return {"path": str(path), "sha256": sha256}

    return receive


# --- an install ---


def test_an_install_asks_for_each_artifact_checks_it_and_deletes_it_after(tmp_path):
    received: list = []
    runner = HubRunner()
    engine = bare_engine(runner=runner, verified=[True], tmp_path=tmp_path)

    refusal = install(engine, "fakedesk", receive=landing_receive(received, tmp_path))

    assert received == [("fakedesk", "app", "sha256:" + DIGEST)]
    # The file was there for the install and is gone after it.
    assert runner.landed == [("app", True)]
    assert not (tmp_path / "app.bin").exists()
    assert refusal == {}


def test_each_output_line_is_handed_on_as_it_comes(tmp_path):
    class LoggingRunner(HubRunner):
        def install_artifact(self, recipe, artifact, path):
            self._log(f"{self.name}: unpacking {artifact['name']}")
            super().install_artifact(recipe, artifact, path)

    runner = LoggingRunner()
    runner._log = None
    engine = bare_engine(runner=runner, verified=[True], tmp_path=tmp_path)
    runner._log = engine._collect
    lines: list = []

    install(
        engine, "fakedesk", receive=landing_receive([], tmp_path), on_line=lines.append
    )

    assert lines == ["fakedesk: unpacking app"]
    # The line sink is the task's; it does not outlive the task.
    assert getattr(engine._lines, "on_line", None) is None


def test_an_install_the_machine_cannot_confirm_is_failed_not_latched(tmp_path):
    engine = bare_engine(verified=[False], tmp_path=tmp_path)

    refusal = install(engine, "fakedesk", receive=landing_receive([], tmp_path))

    assert refusal == {"code": "install_unconfirmed", "params": {}}


def test_a_failed_install_hands_on_the_installers_own_words(tmp_path):
    runner = HubRunner(install_error=InstallError("msiexec exited 1603: held"))
    engine = bare_engine(runner=runner, verified=[False], tmp_path=tmp_path)
    lines: list = []

    refusal = install(
        engine, "fakedesk", receive=landing_receive([], tmp_path), on_line=lines.append
    )

    assert refusal["code"] == "install_failed"
    assert "msiexec exited 1603: held" in refusal["params"]["detail"]
    # The installer's own words, not only that something went wrong.
    assert any("msiexec exited 1603: held" in line for line in lines)


def test_a_refused_artifact_is_reported_with_the_hubs_own_code(tmp_path):
    refused = {
        "code": "download_failed",
        "params": {
            "file": "app",
            "sources": [{"source": "https://x", "reason": "timeout", "detail": ""}],
        },
    }
    runner = HubRunner()
    engine = bare_engine(runner=runner, verified=[False], tmp_path=tmp_path)

    refusal = install(engine, "fakedesk", receive=lambda name, artifact: dict(refused))

    assert refusal == refused
    assert runner.landed == []


def test_bytes_that_are_not_the_artifacts_are_refused_and_deleted(tmp_path):
    runner = HubRunner()
    engine = bare_engine(runner=runner, verified=[False], tmp_path=tmp_path)

    refusal = install(
        engine, "fakedesk", receive=landing_receive([], tmp_path, sha256="cd" * 32)
    )

    assert refusal == {
        "code": "package_digest_mismatch",
        "params": {"artifact": "app"},
    }
    assert runner.landed == []
    assert not (tmp_path / "app.bin").exists()


def test_an_install_that_names_its_step_is_reported_with_that_code(tmp_path):
    runner = HubRunner(
        install_error=ModuleApplyError("podman_install_failed", {"exit_code": 1})
    )
    engine = bare_engine(runner=runner, verified=[False], tmp_path=tmp_path)

    refusal = install(engine, "fakedesk", receive=landing_receive([], tmp_path))

    assert refusal == {"code": "podman_install_failed", "params": {"exit_code": 1}}


def test_a_hub_entrys_packages_install_by_name_before_any_artifact(tmp_path):
    platform = FakePlatform()
    order: list = []
    platform.install_system_packages = lambda names: order.append(names) or ""
    runner = HubRunner(platform=platform)
    engine = bare_engine(runner=runner, verified=[True], tmp_path=tmp_path)
    recipe = dict(HUB_RECIPE, params=dict(HUB_RECIPE["params"], packages=["git"]))
    engine._wanted = {"fakedesk": dict(WANTED["fakedesk"], install=recipe)}

    def receive(name, artifact):
        order.append(artifact["name"])
        return landing_receive([], tmp_path)(name, artifact)

    assert install(engine, "fakedesk", receive=receive) == {}
    assert order == [["git"], "app"]


def test_an_npm_artifact_is_not_received(tmp_path):
    received: list = []
    engine = bare_engine(verified=[True], tmp_path=tmp_path)
    npm = {"name": "cloudcli", "kind": "npm", "digest": "sha512-x", "sources": []}
    recipe = dict(
        HUB_RECIPE, params=dict(HUB_RECIPE["params"], artifacts=[ARTIFACT, npm])
    )
    engine._wanted = {"fakedesk": dict(WANTED["fakedesk"], install=recipe)}

    install(engine, "fakedesk", receive=landing_receive(received, tmp_path))

    assert received == [("fakedesk", "app", "sha256:" + DIGEST)]


def test_a_platform_that_installs_nothing_is_reported_not_raised(tmp_path):
    runner = HubRunner(platform=AgentPlatform())
    engine = bare_engine(runner=runner, verified=[False], tmp_path=tmp_path)
    recipe = dict(HUB_RECIPE, params=dict(HUB_RECIPE["params"], packages=["git"]))
    engine._wanted = {"fakedesk": dict(WANTED["fakedesk"], install=recipe)}

    refusal = install(engine, "fakedesk", receive=landing_receive([], tmp_path))

    assert refusal == {"code": "unsupported_platform", "params": {}}


def test_a_module_the_agent_carries_takes_no_operation(tmp_path):
    engine = bare_engine(tmp_path=tmp_path)
    engine._wanted = {
        "remote_desktop": {
            "want": "running",
            "config": {},
            "install": {"runner": "remote_desktop", "method": "agent", "params": {}},
        }
    }

    refusal = install(engine, "remote_desktop", receive=landing_receive([], tmp_path))

    assert refusal == {
        "code": "module_not_orderable",
        "params": {"module": "remote_desktop"},
    }
    assert uninstall(engine, "remote_desktop") == refusal


def test_a_recipe_naming_a_runner_this_agent_lacks_is_refused(tmp_path):
    engine = bare_engine(tmp_path=tmp_path)
    recipe = dict(HUB_RECIPE, runner="container")
    engine._wanted = {"fakedesk": dict(WANTED["fakedesk"], install=recipe)}

    assert install(engine, "fakedesk", receive=None) == {
        "code": "runner_unknown",
        "params": {"runner": "container"},
    }
    assert uninstall(engine, "fakedesk") == {
        "code": "runner_unknown",
        "params": {"runner": "container"},
    }


def test_a_method_this_agent_does_not_install_by_is_refused(tmp_path):
    engine = bare_engine(tmp_path=tmp_path)
    recipe = dict(HUB_RECIPE, method="flatpak")
    engine._wanted = {"fakedesk": dict(WANTED["fakedesk"], install=recipe)}

    assert install(engine, "fakedesk", receive=None) == {
        "code": "method_unknown",
        "params": {"method": "flatpak"},
    }


def test_an_idle_pass_reruns_nothing(tmp_path):
    received: list = []
    engine = bare_engine(verified=[False], tmp_path=tmp_path)

    install(engine, "fakedesk", receive=landing_receive(received, tmp_path))
    # Every idle pass after a failed install must run nothing: deciding to
    # try again is the applier's, under another state hash.
    for _ in range(5):
        engine._reconcile()

    assert len(received) == 1


# --- an uninstall ---


def test_an_uninstall_is_run_and_confirmed(tmp_path):
    runner = HubRunner()
    engine = bare_engine(runner=runner, verified=[False], tmp_path=tmp_path)
    engine.mark_configured("fakedesk")

    refusal = uninstall(engine, "fakedesk")

    assert runner.uninstalls == 1
    assert refusal == {}
    assert engine.is_configured("fakedesk") is False


def test_an_uninstall_that_did_not_take_is_reported_failed(tmp_path):
    engine = bare_engine(verified=[True], tmp_path=tmp_path)

    refusal = uninstall(engine, "fakedesk")

    assert refusal == {"code": "uninstall_unconfirmed", "params": {}}


class MountRunner(SystemPackageModuleRunner):
    """A module the machine's own package manager installs."""

    runner = "mount"
    name = "samba_mount"


SYSTEM_RECIPE = {
    "runner": "mount",
    "method": "system",
    "params": {
        "version": "system",
        "packages": ["cifs-utils"],
        "verify": "mount.cifs -V",
        "uninstall": {
            "packages": ["cifs-utils", "cifs-extra"],
            "post_uninstall": ["rm -f /etc/cifs.neutrino"],
        },
    },
}
SYSTEM_WANTED = {
    "samba_mount": {"want": "installed", "config": {}, "install": SYSTEM_RECIPE}
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


def system_engine(platform, tmp_path, verified):
    engine = bare_engine(verified=verified, tmp_path=tmp_path)
    runner = MountRunner(platform=platform, log=engine._collect)
    engine._module_runners = {runner.name: runner}
    engine._runners_by_name = {runner.runner: runner}
    engine._container_runners = {}
    engine._platform = None
    engine._wanted = {name: dict(entry) for name, entry in SYSTEM_WANTED.items()}
    return engine, runner


def test_the_uninstall_recipe_names_its_own_packages_and_steps(tmp_path, monkeypatch):
    ran: list = []
    monkeypatch.setattr(
        engine_module.installers,
        "run_shell",
        lambda command, **kwargs: ran.append(command) or "cleaned\n",
    )
    platform = SystemPackagePlatform()
    engine, _ = system_engine(platform, tmp_path, [False])
    lines: list = []

    refusal = uninstall(engine, "samba_mount", on_line=lines.append)

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
    runner = HubRunner()
    engine = bare_engine(runner=runner, verified=[False], tmp_path=tmp_path)
    params = dict(
        HUB_RECIPE["params"],
        uninstall={"post_uninstall": [], "is_data_kept": is_data_kept},
    )
    engine._wanted = {
        "fakedesk": dict(WANTED["fakedesk"], install=dict(HUB_RECIPE, params=params))
    }
    removed: list = []
    runner.remove_data = lambda: removed.append("data")
    lines: list = []

    assert uninstall(engine, "fakedesk", on_line=lines.append) == {}

    assert removed == ([] if is_data_kept else ["data"])
    assert ("fakedesk: removing its data" in lines) is not is_data_kept


def test_the_engine_runs_a_failed_install_again_never_by_itself(tmp_path):
    runner = HubRunner()
    engine = bare_engine(runner=runner, verified=[False], tmp_path=tmp_path)

    install(engine, "fakedesk", receive=landing_receive([], tmp_path))
    engine._refresh(is_forced=True)
    engine._refresh(is_forced=True)

    # The failure is kept for the row; there is no attempt count and no
    # second install here.
    assert len(runner.landed) == 1
    assert engine.report()["fakedesk"]["state"] == "install_failed"
    assert not hasattr(engine, "_attempts")


# --- the system method installs with the platform's own tooling ---


def test_a_system_install_runs_by_name_and_asks_for_no_bytes(tmp_path):
    platform = SystemPackagePlatform()
    received: list = []
    engine, _ = system_engine(platform, tmp_path, [True])
    lines: list = []

    refusal = install(
        engine,
        "samba_mount",
        receive=landing_receive(received, tmp_path),
        on_line=lines.append,
    )

    assert platform.installed == [["cifs-utils"]]
    assert received == []
    assert refusal == {}
    assert "Setting up cifs-utils" in lines


def test_an_absent_capability_reports_unsupported_platform(tmp_path):
    engine, _ = system_engine(AgentPlatform(), tmp_path, [False])

    refusal = install(engine, "samba_mount", receive=None)

    assert refusal == {"code": "unsupported_platform", "params": {}}


# --- the modules this agent applies, observed against the state ---


class ConfigurableRunner(ModuleRunner):
    """A module runner whose own check, unit and details a test scripts."""

    runner = "samba"
    name = "samba"

    def __init__(self, *, is_installed=True, is_active_now=False):
        super().__init__(platform=None, log=lambda message: None)
        self.is_installed = is_installed
        self.is_active_now = is_active_now
        self.detail_reads = 0
        self.verified: list = []
        self.stops = 0
        self.removals = 0

    def verify(self, recipe):
        self.verified.append(recipe)
        return self.is_installed

    def is_active(self):
        return self.is_active_now

    def details(self, recipe):
        self.detail_reads += 1
        return {"sessions": [self.detail_reads]}

    def stop(self):
        self.stops += 1

    def remove_configuration(self):
        self.removals += 1

    def uninstall(self, recipe):
        self.is_installed = False


def module_wanted(want: str, method: str = "builtin") -> dict:
    """The file share named with a recipe; ``builtin`` is judged by the runner."""
    params = {}
    if method == "system":
        params = {"packages": ["samba"], "verify": "smbd -V"}
    return {
        "samba": {
            "want": want,
            "config": {"shares": []},
            "install": {"runner": "samba", "method": method, "params": params},
        }
    }


def module_engine(runner, wanted=None, tmp_path=None):
    engine = bare_engine(runner=runner, tmp_path=tmp_path)
    engine._wanted = wanted if wanted is not None else module_wanted("running")
    return engine


def test_the_recipes_runner_chooses_the_runner():
    runner = ConfigurableRunner()
    engine = module_engine(runner)

    assert engine._runner_for("samba", {"runner": "samba"}) is runner
    assert engine._runner_for("samba", {"runner": "samba_native"}) is None
    assert engine._runner_for("samba", {}) is runner
    assert engine._runner_for("gitea", {}) is None


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
    params = {"artifact": "image"}
    engine = module_engine(
        WaitingRunner(
            is_installing_now=True, wait={"code": "install_waits", "params": params}
        ),
        module_wanted("running"),
        tmp_path,
    )

    engine._refresh(is_forced=True)
    params["artifact"] = "changed"

    assert engine.report()["samba"]["params"] == {"artifact": "image"}


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
        "task": None,
    }
    assert runner.detail_reads == 0


def test_an_absent_row_carries_the_kept_failure(tmp_path):
    engine = module_engine(
        ConfigurableRunner(is_installed=False), module_wanted("running"), tmp_path
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
    assert runner.verified == [{}]


# --- one presence check ---


def test_the_recipes_verify_decides_presence_and_no_runner_check_stands_before_it(
    monkeypatch, tmp_path
):
    """Containers on a machine with Docker CE: the runner's own check finds
    no ``podman-docker``, the recipe's ``verify`` finds Podman, and the row
    reads the unit and the details all the same."""
    runner = ConfigurableRunner(is_installed=False, is_active_now=True)
    engine = module_engine(runner, module_wanted("running", "system"), tmp_path)
    engine.mark_configured("samba")
    asked: list = []
    monkeypatch.setattr(
        engine_module, "verify_passes", lambda command: asked.append(command) or True
    )

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert asked == ["smbd -V"]
    assert (row["state"], row["is_active"]) == ("running", True)
    assert row["details"] == {"sessions": [1]}
    assert runner.verified == []
    assert engine.is_installed("samba") is True


def test_a_recipe_whose_verify_fails_is_absent_whatever_the_runner_says(
    monkeypatch, tmp_path
):
    runner = ConfigurableRunner(is_installed=True, is_active_now=True)
    engine = module_engine(runner, module_wanted("running", "system"), tmp_path)
    monkeypatch.setattr(engine_module, "verify_passes", lambda command: False)

    engine._refresh(is_forced=True)

    assert engine.report()["samba"]["state"] == "absent"
    assert runner.detail_reads == 0
    assert engine.is_installed("samba") is False


def test_a_module_the_agent_carries_is_there_without_any_check(monkeypatch):
    runner = ConfigurableRunner(is_installed=False, is_active_now=True)
    wanted = {
        "samba": {
            "want": "running",
            "config": {},
            "install": {"runner": "samba", "method": "agent", "params": {}},
        }
    }
    engine = module_engine(runner, wanted)
    monkeypatch.setattr(
        engine_module, "verify_passes", lambda command: pytest.fail("no verify")
    )

    assert engine.is_installed("samba") is True
    assert runner.verified == []


def test_is_installed_answers_from_the_runner_for_a_builtin_recipe():
    runner = ConfigurableRunner(is_installed=True)
    engine = module_engine(runner)

    assert engine.is_installed("samba") is True
    runner.is_installed = False
    assert engine.is_installed("samba") is False
    assert engine.is_installed("nothing") is False


def test_taking_a_state_wakes_the_worker_hands_each_runner_its_recipe_and_reports(
    tmp_path,
):
    runner = ConfigurableRunner(is_active_now=True)
    taken: list = []
    runner.take_recipe = taken.append
    engine = module_engine(runner, wanted={}, tmp_path=tmp_path)
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == "installed"
    engine.mark_configured("samba")

    engine.take_state(module_wanted("running"))

    assert engine._wakeup.is_set()
    assert taken == [{"runner": "samba", "method": "builtin", "params": {}}]
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


def test_a_module_that_cannot_be_read_is_logged_once_per_change():
    runner = ConfigurableRunner()
    errors = ["byte 0xff", "byte 0xff", "byte 0xfe", None, "byte 0xff"]

    def details(recipe):
        error = errors.pop(0)
        if error is not None:
            raise ValueError(error)
        return {}

    runner.details = details
    engine = module_engine(runner)
    lines: list = []
    engine._log = lines.append
    rows = []

    for _ in range(5):
        engine._refresh(is_forced=True)
        rows.append(engine.report()["samba"]["code"])

    assert rows == ["verify_failed"] * 3 + ["", "verify_failed"]
    assert lines == [
        "samba: verify_failed: byte 0xff",
        "samba: verify_failed: byte 0xfe",
        "samba: verify_failed: byte 0xff",
    ]


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
        failure("install_failed", "download_failed", file="release", sources=[]),
    )

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["code"], row["params"]) == (
        "install_failed",
        "download_failed",
        {"file": "release", "sources": []},
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

    def install(self, recipe):
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
    wanted = module_wanted("installed")
    wanted["samba"]["install"]["params"] = {"packages": ["samba"]}
    engine = module_engine(runner, wanted, tmp_path)

    refusal = install(engine, "samba", receive=lambda *names: {})

    assert refusal == {"code": "podman_install_failed", "params": {"exit_code": 1603}}
    row = engine.report()["samba"]
    assert (row["state"], row["code"], row["params"]) == (
        "install_failed",
        "podman_install_failed",
        {"exit_code": 1603},
    )

    runner.install_error = None
    assert install(engine, "samba", receive=lambda *names: {}) == {}
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
        def uninstall(self, recipe):
            raise ModuleApplyError("uninstall_failed", {"detail": "not installed"})

    engine = module_engine(
        LeftoverRunner(is_installed=False), module_wanted("absent"), tmp_path
    )
    engine.record_failure("samba", failure("install_failed", "install_failed"))
    lines: list = []

    refusal = uninstall(engine, "samba", on_line=lines.append)

    assert refusal == {}
    assert any("not installed" in line for line in lines)
    assert engine.report()["samba"]["state"] == "absent"
    assert engine.is_install_failed("samba") is False


def test_an_uninstall_step_that_fails_on_software_that_is_there_reads_failed(
    tmp_path,
):
    class StuckRunner(ConfigurableRunner):
        def uninstall(self, recipe):
            raise ModuleApplyError("uninstall_failed", {"detail": "held"})

    engine = module_engine(
        StuckRunner(is_installed=True), module_wanted("absent"), tmp_path
    )

    refusal = uninstall(engine, "samba")

    assert refusal == {"code": "uninstall_failed", "params": {"detail": "held"}}
    row = engine.report()["samba"]
    assert (row["state"], row["code"]) == ("failed", "uninstall_failed")


def test_an_install_s_row_stays_installing_when_a_read_begun_before_it_ends(
    tmp_path,
):
    """A read of every module takes seconds; one begun before a task started
    does not put what it read over the task's row."""
    reading = threading.Event()
    read_release = threading.Event()

    class SlowRunner(ConfigurableRunner):
        def details(self, recipe):
            reading.set()
            read_release.wait(5)
            return {}

    engine = module_engine(SlowRunner(), tmp_path=tmp_path)
    read = threading.Thread(target=engine._refresh, kwargs={"is_forced": True})
    read.start()
    assert reading.wait(5)

    engine.publish_task("samba", TASK_ROW, "installing", {})
    read_release.set()
    read.join(5)

    row = engine.report()["samba"]
    assert (row["state"], row["task"]) == ("installing", TASK_ROW)


def test_a_task_s_row_carries_its_steps_and_its_transient_state(tmp_path):
    engine = module_engine(ConfigurableRunner(is_installed=True), tmp_path=tmp_path)
    engine._refresh(is_forced=True)
    lock_wait = {
        "code": "waiting_for_lock",
        "params": {"lock": "package_manager", "module": "gitea"},
    }

    engine.publish_task("samba", TASK_ROW, "queued", lock_wait)
    queued = engine.report()["samba"]
    engine.publish_task("samba", TASK_ROW, "", {})
    observed = engine.report()["samba"]

    assert queued == {
        "state": "queued",
        "is_active": False,
        "code": "waiting_for_lock",
        "params": {"lock": "package_manager", "module": "gitea"},
        "details": {},
        "task": TASK_ROW,
    }
    # A configure task leaves the state the machine shows, with the task beside it.
    assert observed["state"] == "installed"
    assert observed["task"] == TASK_ROW


def test_a_kept_failure_stays_off_the_row_while_the_module_s_task_runs(tmp_path):
    engine = module_engine(ConfigurableRunner(is_active_now=True), tmp_path=tmp_path)
    engine.mark_configured("samba")
    engine.record_failure(
        "samba", failure("failed", "cloudcli_npm_install_failed", account="anna")
    )
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == "failed"

    engine.publish_task("samba", TASK_ROW, "", {})
    running = engine.report()["samba"]
    engine._refresh(is_forced=True)
    refreshed = engine.report()["samba"]
    engine.publish_task("samba", dict(TASK_ROW, is_running=False), "", {})
    engine._refresh(is_forced=True)
    ended = engine.report()["samba"]

    assert (running["state"], running["code"]) == ("running", "")
    assert (refreshed["state"], refreshed["code"]) == ("running", "")
    assert (ended["state"], ended["code"]) == ("failed", "cloudcli_npm_install_failed")


def test_a_retried_failed_install_reads_installing_from_its_task_s_start(tmp_path):
    engine = module_engine(ConfigurableRunner(is_installed=True), tmp_path=tmp_path)
    engine.record_failure(
        "samba", failure("install_failed", "download_failed", file="x", sources=[])
    )
    engine._refresh(is_forced=True)
    assert engine.report()["samba"]["state"] == "install_failed"

    engine.publish_task("samba", dict(TASK_ROW, index=0), "installing", {})
    engine._refresh(is_forced=True)

    assert engine.report()["samba"]["state"] == "installing"


def test_a_refresh_keeps_a_task_s_transient_row(tmp_path):
    engine = module_engine(ConfigurableRunner(is_installed=True), tmp_path=tmp_path)
    engine.publish_task("samba", TASK_ROW, "uninstalling", {})

    engine._refresh(is_forced=True)
    engine.refresh_one("samba")

    assert engine.report()["samba"]["state"] == "uninstalling"


def test_a_runner_that_cannot_read_the_machine_is_failed_typed():
    class BrokenRunner(ConfigurableRunner):
        def verify(self, recipe):
            raise PlatformUnsupportedError("no package database here")

    engine = module_engine(BrokenRunner())

    engine._refresh(is_forced=True)

    row = engine.report()["samba"]
    assert (row["state"], row["code"]) == ("failed", "unsupported_platform")


def test_a_module_this_agent_has_no_runner_for_is_reported_unsupported():
    """An older agent meeting a module a newer hub serves is a machine
    that cannot have it, not one that has not answered."""
    engine = bare_engine()
    engine._wanted = {
        "thing": {
            "want": "running",
            "install": {"runner": "container", "method": "container", "params": {}},
        }
    }

    engine._refresh(is_forced=True)

    assert engine.report()["thing"] == {
        "state": "unsupported",
        "is_active": False,
        "code": "",
        "params": {},
        "details": {},
        "task": None,
    }


def test_reporting_a_module_touches_nothing():
    runner = HubRunner()
    engine = bare_engine(runner=runner, verified=[True])

    engine._refresh(is_forced=True)

    assert runner.landed == []
    assert runner.uninstalls == 0
    assert engine.report()["fakedesk"]["state"] == "installed"


def test_uninstalling_a_configured_module_stops_it_and_drops_its_configuration(
    tmp_path,
):
    runner = ConfigurableRunner(is_active_now=True)
    engine = module_engine(runner, module_wanted("absent"), tmp_path)
    engine.mark_configured("samba")

    refusal = uninstall(engine, "samba")

    assert refusal == {}
    assert (runner.stops, runner.removals) == (1, 1)
    assert engine.is_configured("samba") is False
    assert engine.report()["samba"]["state"] == "absent"


def test_uninstalling_software_the_hub_never_configured_leaves_its_files(tmp_path):
    runner = ConfigurableRunner()
    engine = module_engine(runner, module_wanted("absent"), tmp_path)

    uninstall(engine, "samba")

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

    assert set(engine.module_runners) == {"terminal", "remote_desktop", "ssh_server"}
    assert set(engine.report()) == {"terminal", "remote_desktop", "ssh_server"}


def test_a_module_the_state_names_there_is_unsupported_never_failed(
    monkeypatch, tmp_path
):
    engine = ModuleEngine(
        platform=NoPackagesPlatform(), configured_dir=str(tmp_path / "configured")
    )
    samba = {
        "runner": "samba",
        "method": "system",
        "params": {"packages": ["samba"], "verify": "true"},
    }
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
    assert install(engine, "samba", receive=None) == {
        "code": "runner_unknown",
        "params": {"runner": "samba"},
    }


class SmbServerApplier:
    """A system SMB server that is there and running."""

    def read_status(self, record):
        return {"is_present": True, "is_running": True}


class SmbServerPlatform(AgentPlatform):
    """A platform that carries its own SMB server, the way Windows does."""

    os_name = "windows"
    capabilities = frozenset({"smb_server"})

    def smb_server_applier(self):
        return SmbServerApplier()


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
                "install": {
                    "runner": "samba_native",
                    "method": "builtin",
                    "params": {},
                },
            },
            "fakedesk": dict(WANTED["fakedesk"]),
        }
    )

    engine._refresh(is_forced=True)
    report = engine.report()

    assert set(engine.module_runners) == {
        "samba",
        "terminal",
        "remote_desktop",
        "ssh_server",
    }
    assert report["samba"]["state"] == "installed"
    assert report["fakedesk"]["state"] == "unsupported"
    assert install(engine, "samba", receive=None) == {}


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
    monkeypatch.setattr(engine_module, "verify_passes", lambda command: False)
    engine = ModuleEngine(
        platform=HubPackagesPlatform(str(tmp_path / "Neutrino")),
        configured_dir=str(tmp_path / "configured"),
    )
    cli = {"name": "cli", "kind": "zip", "digest": "sha256:" + DIGEST}
    engine.take_state(
        {
            "vscode": {
                "want": "installed",
                "config": {},
                "install": {
                    "runner": "vscode",
                    "method": "hub",
                    "params": {"artifacts": [cli], "verify": "code --version"},
                },
            }
        }
    )
    received = []

    def receive(name, artifact):
        received.append((name, artifact["name"]))
        return {"code": "hub_unreachable", "params": {}}

    engine._refresh(is_forced=True)

    assert set(engine.module_runners) == {
        "samba",
        "gitea",
        "podman",
        "vscode",
        "cloudcli",
        "codeg",
        "siyuan",
        "terminal",
        "remote_desktop",
        "ssh_server",
    }
    assert engine.module_runners["podman"].runner == "podman_machine"
    assert engine.report()["vscode"]["state"] == "absent"
    assert install(engine, "vscode", receive=receive) == {
        "code": "hub_unreachable",
        "params": {},
    }
    assert received == [("vscode", "cli")]


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
    assert "siyuan" in mac.module_runners
    assert "siyuan" in windows.module_runners


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
        assert runner.runner == "podman_machine"
    linux = ModuleEngine(
        platform=LinuxHubPackagesPlatform(str(tmp_path / "Neutrino")),
        configured_dir=str(tmp_path / "configured"),
    )
    assert "podman" not in linux.module_runners


def test_a_platform_with_packages_builds_every_runner_by_its_name(tmp_path):
    class PackagesPlatform(FakePlatform):
        capabilities = frozenset({"packages"})

    engine = ModuleEngine(
        platform=PackagesPlatform(), configured_dir=str(tmp_path / "configured")
    )

    assert set(engine.module_runners) == {
        "samba",
        "gitea",
        "podman",
        "vscode",
        "code_server",
        "cloudcli",
        "codeg",
        "siyuan",
        "terminal",
        "remote_desktop",
        "ssh_server",
    }
    assert type(engine.module_runners["podman"]) is PodmanModuleRunner
    assert set(engine._runners_by_name) == {
        "samba",
        "gitea",
        "podman",
        "vscode",
        "code_server",
        "cloudcli",
        "codeg",
        "siyuan",
        "terminal",
        "remote_desktop",
        "ssh_server",
    }


# --- several artifacts ---


def two_artifact_engine(runner, tmp_path):
    artifacts = [
        {
            "name": "server",
            "kind": "tar_gz",
            "directory": "server",
            "digest": "sha256:" + "a" * 64,
        },
        {
            "name": "node",
            "kind": "tar_gz",
            "directory": "node",
            "digest": "sha256:" + "b" * 64,
        },
    ]
    engine = bare_engine(runner=runner, verified=[True], tmp_path=tmp_path)
    recipe = dict(HUB_RECIPE, params=dict(HUB_RECIPE["params"], artifacts=artifacts))
    engine._wanted = {"fakedesk": dict(WANTED["fakedesk"], install=recipe)}
    return engine


def digest_receive(received, tmp_path, digests):
    def receive(name, artifact):
        received.append(artifact["name"])
        path = tmp_path / f"{artifact['name']}.tar"
        path.write_bytes(b"archive")
        return {"path": str(path), "sha256": digests[artifact["name"]]}

    return receive


def test_each_artifact_is_received_and_installed_in_the_recipes_order(tmp_path):
    runner = HubRunner()
    engine = two_artifact_engine(runner, tmp_path)
    received: list = []

    refusal = install(
        engine,
        "fakedesk",
        receive=digest_receive(
            received, tmp_path, {"server": "a" * 64, "node": "b" * 64}
        ),
    )

    assert refusal == {}
    assert received == ["server", "node"]
    assert runner.landed == [("server", True), ("node", True)]
    assert not (tmp_path / "server.tar").exists()
    assert not (tmp_path / "node.tar").exists()


def test_an_artifact_whose_digest_is_not_the_recipes_stops_the_install(tmp_path):
    runner = HubRunner()
    engine = two_artifact_engine(runner, tmp_path)

    refusal = install(
        engine,
        "fakedesk",
        receive=digest_receive([], tmp_path, {"server": "a" * 64, "node": "x" * 64}),
    )

    assert refusal == {
        "code": "package_digest_mismatch",
        "params": {"artifact": "node"},
    }
    assert runner.landed == [("server", True)]
    assert not (tmp_path / "node.tar").exists()


def test_an_artifact_of_a_kind_no_shared_path_takes_is_install_failed(tmp_path):
    class PlainRunner(ModuleRunner):
        runner = "fakedesk"
        name = "fakedesk"

    engine = bare_engine(
        runner=PlainRunner(platform=FakePlatform(), log=lambda line: None),
        verified=[False],
        tmp_path=tmp_path,
    )
    recipe = dict(
        HUB_RECIPE,
        params=dict(
            HUB_RECIPE["params"],
            artifacts=[{"name": "x", "kind": "rar", "digest": "sha256:" + DIGEST}],
        ),
    )
    engine._wanted = {"fakedesk": dict(WANTED["fakedesk"], install=recipe)}

    refusal = install(engine, "fakedesk", receive=landing_receive([], tmp_path))

    assert refusal["code"] == "install_failed"
    assert "rar" in refusal["params"]["detail"]


# --- container modules ---

CONTAINER_RECIPE = {
    "runner": "container",
    "method": "container",
    "params": {
        "version": "1.0",
        "artifacts": [
            {
                "name": "web",
                "kind": "image",
                "digest": "sha256:" + "c" * 64,
                "sources": ["ghcr.io/acme/web"],
            }
        ],
        "source_sets": ["pypi"],
    },
}
PYPI = {"pypi": {"probe": "/pip/", "sources": ["https://p.example"], "variables": []}}


class ContainersRunner(ModuleRunner):
    """The Containers runner as the engine hands it to a container module."""

    runner = "podman"
    name = "podman"

    def __init__(self):
        super().__init__(platform=FakePlatform(), log=lambda line: None)
        self.source_sets: dict = {}
        self.configs: list = []

    def take_source_sets(self, source_sets):
        self.source_sets = dict(source_sets)

    def take_config(self, config):
        self.configs.append(config)


def container_engine(tmp_path):
    """A bare engine with a Containers runner, the state naming one container module."""
    containers = ContainersRunner()
    engine = bare_engine(runner=containers, tmp_path=tmp_path)
    engine._platform = FakePlatform()
    engine._wanted = {}
    return engine, containers


def test_a_container_module_gets_its_runner_the_first_time_the_state_names_it(
    tmp_path,
):
    engine, containers = container_engine(tmp_path)

    engine.take_state(
        {
            "demo": {"want": "installed", "config": {}, "install": CONTAINER_RECIPE},
            "podman": {"want": "running", "config": {"mirrors": ["m"]}},
        },
        PYPI,
    )
    runner = engine.module_runners["demo"]
    engine.take_state(
        {"demo": {"want": "installed", "config": {}, "install": CONTAINER_RECIPE}}
    )

    assert isinstance(runner, ContainerModuleRunner)
    assert runner.name == "demo"
    assert runner._containers is containers
    assert engine.container_runners() == {"demo": runner}
    assert engine.module_runners["demo"] is runner
    assert containers.source_sets == {}
    assert containers.configs[0] == {"mirrors": ["m"]}


def test_every_runner_takes_the_state_s_source_sets(tmp_path):
    engine, containers = container_engine(tmp_path)

    engine.take_state({}, PYPI)

    assert containers.source_sets == PYPI


def test_a_container_module_is_present_by_its_runner_s_image_check(
    tmp_path, monkeypatch
):
    engine, _containers = container_engine(tmp_path)
    wanted = {"want": "installed", "config": {}, "install": CONTAINER_RECIPE}
    engine.take_state({"demo": wanted})
    answers = iter([False, True])
    monkeypatch.setattr(
        ContainerModuleRunner, "verify", lambda self, recipe: next(answers)
    )
    monkeypatch.setattr(ContainerModuleRunner, "is_active", lambda self: False)
    monkeypatch.setattr(ContainerModuleRunner, "details", lambda self, recipe: {})

    assert engine._read_one("demo", wanted)["state"] == "absent"
    assert engine._read_one("demo", wanted)["state"] == "installed"


def test_a_container_module_reads_unsupported_where_no_containers_runner_is(
    tmp_path,
):
    engine = bare_engine(tmp_path=tmp_path)
    engine._platform = FakePlatform()
    wanted = {"want": "installed", "config": {}, "install": CONTAINER_RECIPE}

    engine.take_state({"demo": wanted})

    assert engine.container_runners() == {}
    assert engine._read_one("demo", wanted)["state"] == "unsupported"


def test_a_container_install_runs_the_runner_s_install_and_checks_it_took(
    tmp_path, monkeypatch
):
    engine, _containers = container_engine(tmp_path)
    wanted = {"want": "installed", "config": {}, "install": CONTAINER_RECIPE}
    engine.take_state({"demo": wanted})
    engine._wanted = {"demo": wanted}
    pulled: list = []
    monkeypatch.setattr(
        ContainerModuleRunner,
        "pull_image",
        lambda self, image: pulled.append(image["name"]),
    )
    monkeypatch.setattr(ContainerModuleRunner, "verify", lambda self, recipe: True)
    steps = engine.install_steps("demo", wanted)

    assert install(engine, "demo", receive=None) == {}
    # It waits for Containers, pulls each image on it shared, checks, and has
    # Containers render its containers.
    assert [step.name for step in steps] == [
        "wait_containers",
        *["pull"] * len(pulled),
        "verify",
        "render",
    ]
    assert pulled == [image["name"] for image in recipe_images(CONTAINER_RECIPE)]
    assert {step.name: step.locks for step in steps}["pull"] == (
        ("containers", "shared"),
    )


class ContainerReads:
    """What a container module reads as, set by a test between passes."""

    def __init__(self, monkeypatch):
        self.is_present = False
        self.is_active = False
        self.is_installing = False
        monkeypatch.setattr(ContainerModuleRunner, "verify", self.verify)
        monkeypatch.setattr(ContainerModuleRunner, "is_active", self.active)
        monkeypatch.setattr(ContainerModuleRunner, "is_installing", self.installing)
        monkeypatch.setattr(ContainerModuleRunner, "details", self.details)

    def verify(self, recipe):
        return self.is_present

    def active(self):
        return self.is_active

    def installing(self):
        return self.is_installing

    def details(self, recipe):
        return {}


def held_engine(tmp_path, monkeypatch, want="running"):
    engine, _containers = container_engine(tmp_path)
    wanted = {"want": want, "config": {}, "install": CONTAINER_RECIPE}
    engine.take_state({"demo": wanted})
    engine._wanted = {"demo": wanted}
    return engine, ContainerReads(monkeypatch)


def test_the_containers_row_is_kept_while_a_container_module_pulls(
    tmp_path, monkeypatch
):
    """On Windows a read of the Podman machine failed during a 2.8 GB pull,
    and Containers read stopped."""
    engine, _reads = held_engine(tmp_path, monkeypatch)
    running = {
        "state": "running",
        "is_active": True,
        "code": "",
        "params": {},
        "details": {"containers": []},
    }
    engine._statuses["podman"] = dict(running)
    pulling = {
        "steps": [
            {"name": "wait_containers", "params": {}},
            {"name": "pull", "params": {"image": "app"}},
        ],
        "index": 2,
        "wait": {},
        "is_running": True,
    }
    engine.publish_task("demo", pulling, "installing", {})

    engine._refresh(is_forced=True)
    kept = engine.report()["podman"]
    engine.publish_task("demo", dict(pulling, index=1), "installing", {})
    engine._refresh(is_forced=True)

    assert kept == running
    assert engine.report()["podman"]["state"] != "running"


# --- the steps of Containers, Ayakaleaf and Hermes WebUI ---

CONTAINERS_ALONE = ("containers", "alone")
CONTAINERS_SHARED = ("containers", "shared")
PACKAGE_MANAGER = ("package_manager", "alone")


class StateRootPlatform(FakePlatform):
    """A Linux platform whose state roots are the test's directory."""

    capabilities = frozenset({"packages"})

    def __init__(self, root):
        super().__init__()
        self._root = root

    def agent_var_dir(self):
        return self._root

    def agent_data_dir(self):
        return self._root


class DarwinPackagesPlatform(HubPackagesPlatform):
    """A platform that unpacks the hub's software, the way macOS does."""

    os_name = "darwin"


def planned(steps) -> list:
    """Each step's name, params and locks."""
    return [(step.name, step.params, step.locks) for step in steps]


def podman_entry(engine, want="running") -> dict:
    """Containers' entry with the recipe its runner takes on the engine's system."""
    runner = engine.module_runners["podman"]
    if runner.runner == "podman":
        recipe = {
            "runner": "podman",
            "method": "system",
            "params": {"packages": ["podman", "runc"], "verify": "podman --version"},
        }
    else:
        recipe = {
            "runner": "podman_machine",
            "method": "hub",
            "params": {
                "version": "6.1.4",
                "artifacts": [
                    {"name": name, "kind": kind, "digest": "sha256:" + DIGEST}
                    for name, kind in (
                        ("wsl", "msi"),
                        ("podman", "msi"),
                        ("image", "tar_zst"),
                    )
                    if runner._system.has_windows_features or name != "wsl"
                ],
                "verify": "podman --version",
            },
        }
    return {"want": want, "config": {}, "install": recipe}


def test_containers_on_linux_plans_its_steps_under_containers_alone(tmp_path):
    engine = ModuleEngine(
        platform=StateRootPlatform(str(tmp_path)), configured_dir=str(tmp_path / "c")
    )
    entry = podman_entry(engine)

    steps = engine.install_steps("podman", entry) + engine.configure_steps(
        "podman", entry, "running"
    )

    assert planned(steps) == [
        ("packages", {}, (CONTAINERS_ALONE, PACKAGE_MANAGER)),
        ("verify", {}, (CONTAINERS_ALONE,)),
        ("configure", {}, (CONTAINERS_ALONE,)),
        ("start", {}, (CONTAINERS_ALONE,)),
    ]
    assert planned(engine.configure_steps("podman", entry, "stopped")) == [
        ("configure", {}, (CONTAINERS_ALONE,)),
        ("stop", {}, (CONTAINERS_ALONE,)),
    ]


def test_containers_on_windows_plans_the_features_and_the_restart_first(tmp_path):
    engine = ModuleEngine(
        platform=HubPackagesPlatform(str(tmp_path / "Neutrino")),
        configured_dir=str(tmp_path / "c"),
    )
    entry = podman_entry(engine)

    steps = engine.install_steps("podman", entry) + engine.configure_steps(
        "podman", entry, "running"
    )

    assert planned(steps) == [
        ("windows_features", {}, (CONTAINERS_ALONE, PACKAGE_MANAGER)),
        ("restart", {}, ()),
        ("artifact", {"name": "wsl"}, (CONTAINERS_ALONE, PACKAGE_MANAGER)),
        ("artifact", {"name": "podman"}, (CONTAINERS_ALONE, PACKAGE_MANAGER)),
        ("artifact", {"name": "image"}, (CONTAINERS_ALONE,)),
        ("verify", {}, (CONTAINERS_ALONE,)),
        ("machine", {}, (CONTAINERS_ALONE,)),
        ("configure", {}, (CONTAINERS_ALONE,)),
        ("start", {}, (CONTAINERS_ALONE,)),
    ]
    assert [
        step.name for step in engine.configure_steps("podman", entry, "stopped")
    ] == [
        "configure",
        "stop",
    ]


def test_containers_on_macos_plans_the_pkg_then_the_machine(tmp_path):
    engine = ModuleEngine(
        platform=DarwinPackagesPlatform(str(tmp_path / "Neutrino")),
        configured_dir=str(tmp_path / "c"),
    )
    entry = podman_entry(engine)
    entry["install"]["params"]["artifacts"][0]["kind"] = "pkg"

    steps = engine.install_steps("podman", entry) + engine.configure_steps(
        "podman", entry, "running"
    )

    assert planned(steps) == [
        ("artifact", {"name": "podman"}, (CONTAINERS_ALONE, PACKAGE_MANAGER)),
        ("artifact", {"name": "image"}, (CONTAINERS_ALONE,)),
        ("verify", {}, (CONTAINERS_ALONE,)),
        ("machine", {}, (CONTAINERS_ALONE,)),
        ("configure", {}, (CONTAINERS_ALONE,)),
        ("start", {}, (CONTAINERS_ALONE,)),
    ]


def image_recipe(*names) -> dict:
    """A ``container`` recipe pinning one image per name."""
    return {
        "runner": "container",
        "method": "container",
        "params": {
            "version": "1.0",
            "artifacts": [
                {
                    "name": name,
                    "kind": "image",
                    "digest": "sha256:" + DIGEST,
                    "sources": [f"ghcr.io/acme/{name}"],
                }
                for name in names
            ],
        },
    }


@pytest.mark.parametrize(
    "module, images, first_start",
    [
        (
            "ayakaleaf",
            ("app", "mongo", "redis"),
            [
                ("replica_set", {}, (CONTAINERS_SHARED,)),
                ("wait_app", {}, ()),
                ("admin", {}, ()),
                ("tex", {}, (CONTAINERS_SHARED,)),
            ],
        ),
        (
            "hermes_webui",
            ("webui", "agent"),
            [
                ("first_start", {}, (CONTAINERS_SHARED,)),
                ("update_check", {}, ()),
            ],
        ),
    ],
)
def test_a_container_module_plans_its_pulls_then_its_start_and_first_start(
    tmp_path, module, images, first_start
):
    engine = ModuleEngine(
        platform=StateRootPlatform(str(tmp_path)), configured_dir=str(tmp_path / "c")
    )
    entry = {"want": "running", "config": {}, "install": image_recipe(*images)}
    with engine._lock:
        engine._add_container_runner(module, entry["install"])
    engine.runner_of(module).take_recipe(entry["install"])

    install = engine.install_steps(module, entry)
    start = engine.configure_steps(module, entry, "running")
    stop = engine.configure_steps(module, entry, "stopped")

    assert planned(install) == [
        ("wait_containers", {}, ()),
        *[("pull", {"image": image}, (CONTAINERS_SHARED,)) for image in images],
        ("verify", {}, (CONTAINERS_SHARED,)),
        ("render", {}, ()),
    ]
    assert planned(start) == [
        ("wait_containers", {}, ()),
        ("start", {}, (CONTAINERS_SHARED,)),
        *first_start,
    ]
    assert planned(stop) == [
        ("wait_containers", {}, ()),
        ("stop", {}, (CONTAINERS_SHARED,)),
    ]
    assert planned(engine.uninstall_steps(module, entry)) == [
        ("uninstall", {}, (CONTAINERS_ALONE,))
    ]
    assert {step.failed_state for step in start[2:]} == {"install_failed"}


# --- another version ---


def tarball_bytes(members: dict) -> bytes:
    """A tar.gz with one top directory holding the members."""
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(f"top/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class SwitchPlatform(FakePlatform):
    """A platform whose state root is the test's."""

    def __init__(self, root):
        super().__init__()
        self.root = str(root)
        self.opened: list = []

    def agent_var_dir(self):
        return self.root

    def open_to_accounts(self, directory):
        self.opened.append(directory)


class SwitchRunner(HubRunner):
    """A hub module with a server under a directory and a program beside it."""

    def __init__(self, platform, journal):
        super().__init__(platform=platform)
        self.journal = journal

    def stop(self):
        self.journal.append("stop")

    def apply(self, config):
        self.journal.append("apply")

    def start(self):
        self.journal.append("start")


def switch_recipe(version, server_digest, cli_digest):
    return {
        "runner": "fakedesk",
        "method": "hub",
        "params": {
            "version": version,
            "artifacts": [
                {
                    "name": "server",
                    "kind": "tar_gz",
                    "directory": "server",
                    "digest": "sha256:" + server_digest,
                },
                {"name": "cli", "kind": "tar_gz", "digest": "sha256:" + cli_digest},
            ],
            "verify": "true",
        },
    }


@pytest.fixture
def switched(tmp_path, monkeypatch):
    """An engine whose fakedesk 1.0 is installed: server/ and a cli program."""
    import hashlib

    journal: list = []
    root = tmp_path / "state"
    module = root / "fakedesk"
    (module / "server").mkdir(parents=True)
    (module / "server" / "run").write_bytes(b"server 1.0")
    (module / "cli").write_bytes(b"cli 1.0")
    platform = SwitchPlatform(root)
    runner = SwitchRunner(platform, journal)
    engine = bare_engine(runner=runner, tmp_path=tmp_path)
    engine._platform = platform
    archives = {
        "server": tarball_bytes({"run": b"server 2.0"}),
        "cli": tarball_bytes({"cli": b"cli 2.0"}),
    }
    digests = {
        name: hashlib.sha256(data).hexdigest() for name, data in archives.items()
    }
    engine.take_state(
        {
            "fakedesk": {
                "want": "running",
                "config": {},
                "install": switch_recipe("1.0", "11" * 32, "22" * 32),
            }
        }
    )
    engine._keep_version("fakedesk", switch_recipe("1.0", "11" * 32, "22" * 32))
    engine.take_state(
        {
            "fakedesk": {
                "want": "running",
                "config": {},
                "install": switch_recipe("2.0", digests["server"], digests["cli"]),
            }
        }
    )
    asked: list = []

    def receive(name, artifact):
        asked.append(artifact["name"])
        path = tmp_path / f"{artifact['name']}.tar.gz"
        path.write_bytes(archives[artifact["name"]])
        return {"path": str(path), "sha256": digests[artifact["name"]]}

    detail = {"text": ""}
    monkeypatch.setattr(engine_module, "verify_detail", lambda command: detail["text"])
    return engine, module, journal, asked, receive, detail, digests


def test_another_version_is_staged_swapped_in_and_the_old_files_dropped(switched):
    engine, module, journal, asked, receive, _detail, digests = switched

    assert engine.take_version_switch("fakedesk", engine._wanted["fakedesk"]) is True
    refusal = switch(engine, "fakedesk", receive=receive)

    assert refusal == {}
    assert (module / "server" / "run").read_bytes() == b"server 2.0"
    assert (module / "cli").read_bytes() == b"cli 2.0"
    assert sorted(os.listdir(module)) == ["cli", "server"]
    assert journal == ["stop"]
    assert asked == ["server", "cli"]
    assert engine.installed_version("fakedesk") == {
        "version": "2.0",
        "digests": {
            "server": "sha256:" + digests["server"],
            "cli": "sha256:" + digests["cli"],
        },
    }
    assert engine.take_version_switch("fakedesk", engine._wanted["fakedesk"]) is False


def test_a_switch_that_does_not_verify_puts_the_old_version_back_and_starts_it(
    switched,
):
    engine, module, journal, _asked, receive, detail, _digests = switched
    detail["text"] = "code: version 2.0 cannot start"

    refusal = switch(engine, "fakedesk", receive=receive)

    assert refusal == {
        "code": "version_switch_failed",
        "params": {"version": "2.0", "detail": "code: version 2.0 cannot start"},
    }
    assert (module / "server" / "run").read_bytes() == b"server 1.0"
    assert (module / "cli").read_bytes() == b"cli 1.0"
    assert sorted(os.listdir(module)) == ["cli", "server"]
    assert journal == ["stop", "apply", "start"]
    assert engine.installed_version("fakedesk")["version"] == "1.0"
    assert engine.report()["fakedesk"]["state"] == "failed"


def test_a_failure_before_the_swap_leaves_the_old_version_and_no_new_file(
    switched,
):
    engine, module, journal, _asked, receive, _detail, digests = switched

    def short_receive(name, artifact):
        if artifact["name"] == "cli":
            return {"code": "download_failed", "params": {"file": "cli"}}
        return receive(name, artifact)

    refusal = switch(engine, "fakedesk", receive=short_receive)

    assert refusal == {"code": "download_failed", "params": {"file": "cli"}}
    assert (module / "server" / "run").read_bytes() == b"server 1.0"
    assert sorted(os.listdir(module)) == ["cli", "server"]
    assert journal == []
    assert engine.installed_version("fakedesk")["version"] == "1.0"


def test_an_artifact_whose_digest_is_unchanged_is_not_fetched_again(switched):
    engine, module, _journal, asked, receive, _detail, digests = switched
    engine._keep_version("fakedesk", switch_recipe("1.0", "11" * 32, digests["cli"]))

    assert switch(engine, "fakedesk", receive=receive) == {}

    assert asked == ["server"]
    assert (module / "cli").read_bytes() == b"cli 1.0"


def test_an_msi_is_switched_by_uninstalling_the_old_package_before_installing(
    tmp_path,
):
    import hashlib

    journal: list = []
    root = tmp_path / "state"
    (root / "fakedesk").mkdir(parents=True)
    platform = SwitchPlatform(root)
    runner = SwitchRunner(platform, journal)
    runner.uninstall_package = lambda recipe, artifact: journal.append(
        ("uninstall", artifact["name"])
    )
    runner.install_artifact = lambda recipe, artifact, path: journal.append(
        ("install", artifact["name"])
    )
    engine = bare_engine(runner=runner, tmp_path=tmp_path)
    engine._platform = platform
    data = b"an msi of 2.0"

    def msi_recipe(version, digest):
        return {
            "runner": "fakedesk",
            "method": "hub",
            "params": {
                "version": version,
                "artifacts": [
                    {
                        "name": "app",
                        "kind": "msi",
                        "directory": "app",
                        "digest": "sha256:" + digest,
                    }
                ],
                "verify": "true",
            },
        }

    engine._keep_version("fakedesk", msi_recipe("1.0", "11" * 32))
    digest = hashlib.sha256(data).hexdigest()
    engine.take_state(
        {
            "fakedesk": {
                "want": "running",
                "config": {},
                "install": msi_recipe("2.0", digest),
            }
        }
    )

    def receive(name, artifact):
        path = tmp_path / "app.msi"
        path.write_bytes(data)
        return {"path": str(path), "sha256": digest}

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(engine_module, "verify_detail", lambda command: "")
        assert switch(engine, "fakedesk", receive=receive) == {}

    assert journal == ["stop", ("uninstall", "app"), ("install", "app")]
    assert engine.installed_version("fakedesk")["version"] == "2.0"


def test_a_module_installed_before_versions_were_kept_takes_the_recipe_s(
    switched,
):
    engine, _module, _journal, _asked, _receive, _detail, _digests = switched
    engine._forget_version("fakedesk")

    assert engine.take_version_switch("fakedesk", engine._wanted["fakedesk"]) is False
    assert engine.installed_version("fakedesk")["version"] == "2.0"


def test_an_install_keeps_the_version_and_an_uninstall_forgets_it(tmp_path):
    engine = bare_engine(verified=[True, True, False], tmp_path=tmp_path)

    install(engine, "fakedesk", receive=landing_receive([], tmp_path))
    kept = engine.installed_version("fakedesk")
    uninstall(engine, "fakedesk")

    assert kept == {"version": "1.0", "digests": {"app": "sha256:" + DIGEST}}
    assert engine.installed_version("fakedesk") == {}


def test_every_module_runner_the_engine_builds_is_in_the_apply_order(tmp_path):
    for platform in (FakePlatform(), NoPackagesPlatform()):
        engine = ModuleEngine(platform=platform, configured_dir=str(tmp_path))
        assert set(engine.module_runners) <= set(APPLY_ORDER)


def test_a_runners_notice_is_the_steady_rows_code_and_nothing_else_changes():
    class Noticing:
        def notice(self):
            return {"code": "share_users_unknown", "params": {"shares": "a"}}

    class Quiet:
        def notice(self):
            return {}

    told = engine_module._with_notice(Noticing(), engine_module._typed("running"))
    quiet = engine_module._with_notice(Quiet(), engine_module._typed("running"))

    assert (told["state"], told["code"], told["params"]) == (
        "running",
        "share_users_unknown",
        {"shares": "a"},
    )
    assert (quiet["code"], quiet["params"]) == ("", {})


# --- the steps every runner's task is planned from ---

# The closed list of step names every surface words.
STEP_NAMES = {
    "packages",
    "artifact",
    "verify",
    "switch",
    "configure",
    "account",
    "npm",
    "start",
    "stop",
    "uninstall",
    "wait_containers",
    "pull",
    "render",
    "windows_features",
    "restart",
    "machine",
    "first_start",
    "update_check",
    "replica_set",
    "wait_app",
    "admin",
    "tex",
    "guests",
    "tools",
}


def every_step(engine) -> list:
    """Each step the engine plans for each of its runners, by every method."""
    steps = []
    artifacts = [
        {"name": "app", "kind": "tar_gz", "digest": "sha256:" + DIGEST},
        {"name": "setup", "kind": "msi", "digest": "sha256:" + DIGEST},
    ]
    for name, runner in engine.module_runners.items():
        for method in ("system", "hub", "builtin", "container"):
            entry = {
                "want": "running",
                "config": {},
                "install": {
                    "runner": runner.runner,
                    "method": method,
                    "params": {
                        "version": "1",
                        "packages": ["x"],
                        "artifacts": artifacts,
                    },
                },
            }
            engine._wanted[name] = entry
            steps += engine.install_steps(name, entry)
            steps += engine.switch_steps(name, entry)
            steps += engine.uninstall_steps(name, entry)
            for want in ("running", "stopped"):
                steps += engine.configure_steps(name, entry, want)
    return steps


def test_every_step_takes_its_locks_in_the_one_order_and_has_a_known_name(
    tmp_path,
):
    class PackagesPlatform(FakePlatform):
        capabilities = frozenset({"packages"})

    engines = [
        ModuleEngine(
            platform=PackagesPlatform(), configured_dir=str(tmp_path / "linux")
        ),
        ModuleEngine(
            platform=HubPackagesPlatform(str(tmp_path / "Neutrino")),
            configured_dir=str(tmp_path / "windows"),
        ),
    ]

    steps = [step for engine in engines for step in every_step(engine)]

    assert steps
    assert all(is_in_order(step.locks) for step in steps)
    assert {step.name for step in steps} <= STEP_NAMES


def test_a_package_step_takes_the_package_manager_and_containers_steps_its_lock(
    tmp_path,
):
    engine = bare_engine(tmp_path=tmp_path)
    recipe = dict(
        HUB_RECIPE,
        params=dict(
            HUB_RECIPE["params"],
            packages=["git"],
            artifacts=[
                dict(ARTIFACT),
                {"name": "setup", "kind": "msi", "digest": ARTIFACT["digest"]},
            ],
        ),
    )
    entry = dict(WANTED["fakedesk"], install=recipe)

    steps = engine.install_steps("fakedesk", entry)

    assert [(step.name, step.params, step.locks) for step in steps] == [
        ("packages", {}, (("package_manager", "alone"),)),
        ("artifact", {"name": "app"}, ()),
        ("artifact", {"name": "setup"}, (("package_manager", "alone"),)),
        ("verify", {}, ()),
    ]
    assert [step.failed_state for step in steps] == ["install_failed"] * 4


def test_every_runner_asks_for_a_configure_task_of_its_own_module(tmp_path):
    engine, _containers = container_engine(tmp_path)
    asked: list = []

    engine.set_configure_asker(asked.append)
    engine.take_state(
        {"demo": {"want": "running", "config": {}, "install": CONTAINER_RECIPE}}
    )

    assert engine.runner_of("podman").ask_configure() is True
    assert engine.runner_of("demo").ask_configure() is True
    assert asked == ["podman", "demo"]


def test_a_runner_with_nobody_to_ask_takes_no_ask():
    assert HubRunner().ask_configure() is False


# --- the steps of the programs run as an account, the file share and Gitea ---

# An SSH public key an account's SSH server instance admits.
PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPbg3nX0Oi4lmPN3XHwV4yl1/aAMviQsLSIiP50dOkkz"  # scan: allow
# One enabled account, with the field each module's configuration checks.
ACCOUNT_INSTANCE = {
    "account": "ann",
    "secret": "s",
    "token": "t",
    "token_secret": "ts",
    "web_password": "w",
    "access_code": "a",
    "password": "p",
    "authorized_key": PUBLIC_KEY,
}
ACCOUNT_MODULES = ("vscode", "code_server", "cloudcli", "codeg", "siyuan", "ssh_server")


def planned_accounts(steps) -> list:
    """Each step's name, account and locks."""
    return [(step.name, step.params.get("account", ""), step.locks) for step in steps]


class PackagesPlatform(FakePlatform):
    capabilities = frozenset({"packages"})


@pytest.mark.parametrize("module", ACCOUNT_MODULES)
def test_a_running_program_run_as_an_account_steps_through_each_account(
    tmp_path, module
):
    engine = ModuleEngine(platform=PackagesPlatform(), configured_dir=str(tmp_path))
    runner = engine.runner_of(module)
    entry = {
        "want": "running",
        "config": {"instances": [dict(ACCOUNT_INSTANCE)]},
        "install": {"runner": runner.runner, "method": "builtin", "params": {}},
    }

    running = engine.configure_steps(module, entry, "running")
    stopped = engine.configure_steps(module, entry, "stopped")

    npm = [("npm", "ann", ())] if module == "cloudcli" else []
    assert planned_accounts(running) == [
        ("configure", "", ()),
        *npm,
        ("account", "ann", ()),
        ("start", "", ()),
    ]
    assert planned_accounts(stopped) == [("configure", "", ()), ("stop", "", ())]
    assert {step.name for step in running + stopped} <= STEP_NAMES


def test_the_file_share_and_gitea_take_system_accounts_for_their_accounts(tmp_path):
    engine = ModuleEngine(platform=PackagesPlatform(), configured_dir=str(tmp_path))
    samba = {
        "want": "running",
        "config": {},
        "install": {
            "runner": "samba",
            "method": "system",
            "params": {"packages": ["samba"], "verify": "smbd -V"},
        },
    }
    gitea = {
        "want": "running",
        "config": {},
        "install": {
            "runner": "gitea",
            "method": "hub",
            "params": {
                "version": "1.27.3",
                "packages": ["git"],
                "artifacts": [
                    {"name": "gitea", "kind": "binary", "digest": "sha256:" + DIGEST}
                ],
            },
        },
    }
    manager = (("package_manager", "alone"),)
    accounts = (("system_accounts", "alone"),)

    file_share = engine.install_steps("samba", samba) + engine.configure_steps(
        "samba", samba, "running"
    )
    server = engine.install_steps("gitea", gitea) + engine.configure_steps(
        "gitea", gitea, "running"
    )

    assert planned_accounts(file_share) == [
        ("packages", "", manager),
        ("verify", "", ()),
        ("configure", "", accounts),
        ("start", "", ()),
    ]
    assert planned_accounts(server) == [
        ("packages", "", manager),
        ("artifact", "", ()),
        ("verify", "", ()),
        ("account", "git", accounts),
        ("configure", "", ()),
        ("start", "", ()),
    ]
    assert planned_accounts(engine.uninstall_steps("samba", samba)) == [
        ("uninstall", "", (*manager, *accounts))
    ]
    assert planned_accounts(engine.uninstall_steps("gitea", gitea)) == [
        ("uninstall", "", accounts)
    ]
