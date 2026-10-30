"""The system-package runner: packages by name, steps before them, and the one
helper every package run goes through, waiting for the system's own lock."""

import pytest

from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared import system_package as system_package_module
from neutrino_agent.exceptions import InstallError, ModuleApplyError
from neutrino_agent.modules.shared.system_package import SystemPackageModuleRunner
from neutrino_agent.platforms.base import AgentPlatform


class RecordingPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self):
        self.installed: list = []
        self.removed: list = []

    def install_system_packages(self, names):
        self.installed.append(list(names))
        return ""

    def remove_system_packages(self, names):
        self.removed.append(list(names))
        return ""


@pytest.fixture
def steps(monkeypatch):
    ran: list = []

    def run_shell(command, *, timeout_s=installers.INSTALL_TIMEOUT_S):
        ran.append(command)
        if "fail" in command:
            raise InstallError("step failed: no")
        return "stepped\n"

    monkeypatch.setattr(system_package_module.installers, "run_shell", run_shell)
    return ran


def test_pre_install_steps_run_before_the_packages(steps):
    platform = RecordingPlatform()
    logged: list = []
    runner = SystemPackageModuleRunner(platform=platform, log=logged.append)

    runner.install(
        {
            "runner": "podman",
            "method": "system",
            "params": {
                "pre_install": ["enable contrib", "apt-get update"],
                "packages": ["podman"],
            },
        }
    )

    assert steps == ["enable contrib", "apt-get update"]
    assert platform.installed == [["podman"]]
    assert "stepped" in logged


def test_a_failing_step_stops_the_install_before_any_package(steps):
    platform = RecordingPlatform()
    runner = SystemPackageModuleRunner(platform=platform, log=lambda m: None)

    with pytest.raises(InstallError):
        runner.install({"params": {"pre_install": ["fail"], "packages": ["x"]}})

    assert platform.installed == []


def test_an_entry_without_steps_installs_its_packages_only(steps):
    platform = RecordingPlatform()
    runner = SystemPackageModuleRunner(platform=platform, log=lambda m: None)

    runner.install({"params": {"packages": ["samba"]}})

    assert steps == []
    assert platform.installed == [["samba"]]


def test_the_runners_own_check_looks_for_its_binary(monkeypatch):
    """The runner's own check, which answers for a module the state does
    not name: its binary on the path, and no for a runner with none."""
    found: list = []
    monkeypatch.setattr(
        system_package_module.shutil,
        "which",
        lambda name: found.append(name) or ("/usr/sbin/" + name),
    )

    class NamedRunner(SystemPackageModuleRunner):
        binary = "smbd"

    assert NamedRunner(platform=RecordingPlatform()).verify({}) is True
    assert SystemPackageModuleRunner(platform=RecordingPlatform()).verify({}) is False
    assert found == ["smbd"]


def test_an_uninstall_removes_the_packages_its_uninstall_names():
    platform = RecordingPlatform()
    runner = SystemPackageModuleRunner(platform=platform, log=lambda m: None)

    runner.uninstall(
        {
            "params": {
                "packages": ["podman"],
                "uninstall": {"packages": ["podman", "podman-plugins"]},
            }
        }
    )

    assert platform.removed == [["podman", "podman-plugins"]]


# --- the one helper and the system's own lock ---

LOCK_LINE = (
    "Waiting for cache lock: Could not get lock /var/lib/dpkg/lock-frontend. "
    "It is held by process 2345 (unattended-upgr)... 1s"
)
BUSY_LINE = (
    "E: Could not get lock /var/lib/dpkg/lock-frontend. "
    "It is held by process 2345 (unattended-upgr)"
)
INTERRUPTED_LINE = (
    "E: dpkg was interrupted, you must manually run 'dpkg --configure -a' "
    "to correct the problem."
)


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    """apt-get, dpkg and dnf on PATH under tmp_path, each answering from a
    script of turns and recording its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for program in ("apt-get", "dpkg", "dnf"):
        path = bin_dir / program
        path.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> "{tmp_path}/{program}.args"\n'
            f'turns="{tmp_path}/{program}.turns"\n'
            '[ -f "$turns" ] || exit 0\n'
            'turn=$(head -n 1 "$turns"); tail -n +2 "$turns" > "$turns.next"\n'
            'mv "$turns.next" "$turns"\n'
            'case "$turn" in\n'
            f'  wait) echo "{LOCK_LINE}"; sleep 0.2; echo "Reading package lists..."'
            "; exit 0 ;;\n"
            f'  busy) echo "{BUSY_LINE}"; exit 100 ;;\n'
            f'  interrupted) echo "{INTERRUPTED_LINE}"; exit 100 ;;\n'
            '  rpm) echo "Error: waiting for the rpm transaction lock"; exit 1 ;;\n'
            '  fail) echo "E: Unable to locate package nothing"; exit 100 ;;\n'
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setattr(system_package_module, "AGENT_PACKAGE_LOCK_RETRY_S", 0)

    class Fakes:
        def turns(self, program, *turns):
            (tmp_path / f"{program}.turns").write_text("\n".join(turns) + "\n")

        def args(self, program):
            path = tmp_path / f"{program}.args"
            return path.read_text().splitlines() if path.exists() else []

    return Fakes()


def test_apt_waits_for_dpkg_s_lock_and_names_its_holder(fakes):
    waits: list = []
    system_package_module.set_wait_sink(waits.append)
    fakes.turns("apt-get", "wait")
    try:
        output = system_package_module.run_package_manager(
            ["apt-get", "install", "-y", "samba"]
        )
    finally:
        system_package_module.set_wait_sink(None)

    assert "Reading package lists..." in output
    assert fakes.args("apt-get") == ["-o DPkg::Lock::Timeout=300 install -y samba"]
    assert waits == [
        {
            "code": "waiting_for_package_manager",
            "params": {"holder": "unattended-upgr"},
        },
        {},
    ]


def test_a_lock_held_past_the_wait_fails_package_manager_busy(fakes):
    fakes.turns("apt-get", "busy")

    with pytest.raises(ModuleApplyError) as caught:
        system_package_module.run_package_manager(["apt-get", "install", "-y", "x"])

    assert (caught.value.code, caught.value.params) == (
        "package_manager_busy",
        {"holder": "unattended-upgr"},
    )


def test_a_cut_dpkg_run_is_repaired_once_and_apt_runs_again(fakes):
    fakes.turns("apt-get", "interrupted", "ok")

    system_package_module.run_package_manager(["apt-get", "install", "-y", "x"])

    assert fakes.args("dpkg") == ["--configure -a"]
    assert len(fakes.args("apt-get")) == 2


def test_apt_s_own_refusal_is_an_install_error_with_its_words(fakes):
    fakes.turns("apt-get", "fail")

    with pytest.raises(InstallError) as caught:
        system_package_module.run_package_manager(["apt-get", "install", "-y", "x"])

    assert "Unable to locate package" in str(caught.value)
    assert fakes.args("dpkg") == []


def test_dnf_runs_again_while_another_run_holds_the_rpm_lock(fakes):
    waits: list = []
    system_package_module.set_wait_sink(waits.append)
    fakes.turns("dnf", "rpm", "rpm", "ok")
    try:
        system_package_module.run_package_manager(["dnf", "install", "-y", "x"])
    finally:
        system_package_module.set_wait_sink(None)

    assert len(fakes.args("dnf")) == 3
    assert waits[0] == {"code": "waiting_for_package_manager", "params": {"holder": ""}}
    assert waits[-1] == {}


def test_dnf_still_locked_past_the_wait_fails_package_manager_busy(fakes, monkeypatch):
    monkeypatch.setattr(system_package_module, "AGENT_UPDATE_LOCK_TIMEOUT_S", 0)
    fakes.turns("dnf", "rpm", "rpm")

    with pytest.raises(ModuleApplyError) as caught:
        system_package_module.run_package_manager(["dnf", "install", "-y", "x"])

    assert caught.value.code == "package_manager_busy"
