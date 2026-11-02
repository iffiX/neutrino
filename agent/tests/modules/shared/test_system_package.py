"""The system-package runner: packages by name, steps before them, and the one
helper every package run goes through, waiting for the system's own lock."""

import os
import pathlib

import pytest

from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared import system_package as system_package_module
from neutrino_agent.exceptions import InstallError, ModuleApplyError
from neutrino_agent.modules.shared.system_package import SystemPackageModuleRunner
from neutrino_agent.platforms.base import AgentPlatform

DNF_LOCK_PATHS = system_package_module.DNF_LOCK_PATHS


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
    """apt-get, dpkg, dnf and pacman on PATH under tmp_path, each answering
    from a script of turns and recording its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for program in ("apt-get", "dpkg", "dnf", "pacman"):
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
            '  alpm) echo "error: failed to init transaction'
            ' (unable to lock database)"; exit 1 ;;\n'
            '  noname) echo "error: target not found: nothing"; exit 1 ;;\n'
            '  fail) echo "E: Unable to locate package nothing"; exit 100 ;;\n'
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setattr(system_package_module, "AGENT_PACKAGE_LOCK_RETRY_S", 0)
    monkeypatch.setattr(system_package_module, "PROC_DIR", str(tmp_path / "proc"))
    dnf_lock = tmp_path / "rpmdb_lock.pid"
    monkeypatch.setattr(system_package_module, "DNF_LOCK_PATHS", (str(dnf_lock),))
    repo_lock = tmp_path / "system-repo.lock"
    monkeypatch.setattr(
        system_package_module, "DNF_SYSTEM_REPO_LOCK_PATHS", (str(repo_lock),)
    )
    proc_locks = tmp_path / "locks"
    monkeypatch.setattr(system_package_module, "PROC_LOCKS_PATH", str(proc_locks))
    alpm_lock = tmp_path / "db.lck"
    monkeypatch.setattr(system_package_module, "AGENT_PACMAN_LOCK_PATH", str(alpm_lock))

    class Fakes:
        lock = dnf_lock
        system_repo_lock = repo_lock
        kernel_locks = proc_locks
        pacman_lock = alpm_lock

        def turns(self, program, *turns):
            (tmp_path / f"{program}.turns").write_text("\n".join(turns) + "\n")

        def args(self, program):
            path = tmp_path / f"{program}.args"
            return path.read_text().splitlines() if path.exists() else []

        def process(self, pid, comm, *words):
            """One process as the kernel shows it: its cut name and its command line."""
            directory = tmp_path / "proc" / str(pid)
            directory.mkdir(parents=True)
            (directory / "comm").write_text(comm + "\n")
            (directory / "cmdline").write_bytes(b"\0".join(words) + b"\0")

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


def test_apt_s_holder_is_named_whole_from_its_command_line(fakes):
    waits: list = []
    fakes.process(
        2345,
        "unattended-upgr",
        b"/usr/bin/python3",
        b"/usr/bin/unattended-upgrade",
        b"--download-only",
    )
    system_package_module.set_wait_sink(waits.append)
    fakes.turns("apt-get", "wait")
    try:
        system_package_module.run_package_manager(["apt-get", "install", "-y", "x"])
    finally:
        system_package_module.set_wait_sink(None)

    assert waits[0]["params"] == {"holder": "unattended-upgrade"}


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


def test_dnf_waits_while_another_dnf_holds_its_lock_and_names_it(fakes):
    """dnf 4 waits for its own lock without a word; the step names the
    holder from the lock's file and runs dnf once the lock is free."""
    fakes.process(
        4321,
        "dnf-automatic",
        b"/usr/bin/python3",
        b"-s",
        b"/usr/bin/dnf-automatic",
        b"--timer",
    )
    fakes.lock.write_text("4321")
    waits: list = []

    def told(wait):
        waits.append((wait, len(fakes.args("dnf"))))
        fakes.lock.unlink(missing_ok=True)

    system_package_module.set_wait_sink(told)
    try:
        system_package_module.run_package_manager(["dnf", "install", "-y", "x"])
    finally:
        system_package_module.set_wait_sink(None)

    # The wait ends before dnf runs.
    assert waits == [
        (
            {
                "code": "waiting_for_package_manager",
                "params": {"holder": "dnf-automatic"},
            },
            0,
        ),
        ({}, 0),
    ]
    assert len(fakes.args("dnf")) == 1


def kernel_lock_line(pid: int, path) -> str:
    """One line of ``/proc/locks`` for a lock on a file."""
    inode = os.stat(path).st_ino
    return f"1: POSIX  ADVISORY  WRITE {pid} 00:2b:{inode} 0 EOF\n"


def test_dnf_5_4_waits_while_the_kernel_lists_a_holder_of_its_lock_and_names_it(fakes):
    """dnf 5.4 waits inside its own run with no word the row can show, for as
    long as another dnf downloads. The row names the holder, and dnf runs once
    the kernel lists no holder."""
    fakes.process(1507, "dnf", b"/usr/bin/dnf", b"-y", b"upgrade")
    fakes.system_repo_lock.write_text("")
    fakes.kernel_locks.write_text(kernel_lock_line(1507, fakes.system_repo_lock))
    waits: list = []

    def told(wait):
        waits.append((wait, len(fakes.args("dnf"))))
        fakes.kernel_locks.write_text("")

    system_package_module.set_wait_sink(told)
    try:
        system_package_module.run_package_manager(["dnf", "install", "-y", "x"])
    finally:
        system_package_module.set_wait_sink(None)

    assert waits == [
        (
            {"code": "waiting_for_package_manager", "params": {"holder": "dnf"}},
            0,
        ),
        ({}, 0),
    ]
    assert len(fakes.args("dnf")) == 1


def test_dnf_5_4_s_lock_held_past_the_wait_fails_package_manager_busy(
    fakes, monkeypatch
):
    monkeypatch.setattr(system_package_module, "AGENT_PACKAGE_LOCK_RETRY_S", 150)
    monkeypatch.setattr(system_package_module.time, "sleep", lambda seconds: None)
    fakes.process(1507, "dnf", b"/usr/bin/dnf", b"-y", b"upgrade")
    fakes.system_repo_lock.write_text("")
    fakes.kernel_locks.write_text(kernel_lock_line(1507, fakes.system_repo_lock))

    with pytest.raises(ModuleApplyError) as refused:
        system_package_module.run_package_manager(["dnf", "install", "-y", "x"])

    assert refused.value.code == "package_manager_busy"
    assert refused.value.params == {"holder": "dnf"}
    assert fakes.args("dnf") == []


def test_dnf_5_4_finds_its_lock_on_either_path(fakes, monkeypatch, tmp_path):
    """The file sits under /var/lib/dnf where that directory exists, and under
    /usr/lib/sysimage/libdnf5 where it does not."""
    other = tmp_path / "libdnf5" / "system-repo.lock"
    other.parent.mkdir()
    other.write_text("")
    monkeypatch.setattr(
        system_package_module,
        "DNF_SYSTEM_REPO_LOCK_PATHS",
        (str(fakes.system_repo_lock), str(other)),
    )
    fakes.kernel_locks.write_text(kernel_lock_line(1507, other))

    assert system_package_module._dnf_lock_pid() == 1507


@pytest.mark.parametrize(
    "line",
    [
        "",
        "1: POSIX  ADVISORY  WRITE 1507 00:2b:0 0 EOF\n",
        "1: OFDLCK ADVISORY  WRITE -1 00:2b:{inode} 0 EOF\n",
        "1: -> POSIX  ADVISORY  WRITE 1508 00:2b:{inode} 0 EOF\n",
    ],
    ids=["no lock", "another file", "a lock with no process", "a process waiting"],
)
def test_dnf_runs_at_once_while_no_process_holds_dnf_5_4_s_lock(fakes, line):
    fakes.system_repo_lock.write_text("")
    inode = os.stat(fakes.system_repo_lock).st_ino
    fakes.kernel_locks.write_text(line.format(inode=inode))
    waits: list = []

    system_package_module.set_wait_sink(waits.append)
    try:
        system_package_module.run_package_manager(["dnf", "install", "-y", "x"])
    finally:
        system_package_module.set_wait_sink(None)

    assert waits == []
    assert len(fakes.args("dnf")) == 1


def test_a_dnf_with_no_system_repo_lock_file_runs_as_before(fakes):
    """dnf 4 and dnf 5.2 make no such file."""
    fakes.kernel_locks.write_text("1: POSIX  ADVISORY  WRITE 1507 00:2b:99 0 EOF\n")

    system_package_module.run_package_manager(["dnf", "install", "-y", "x"])

    assert len(fakes.args("dnf")) == 1


@pytest.mark.parametrize(
    "path",
    [
        "/var/lib/dnf/rpmdb_lock.pid",
        "/var/cache/dnf/metadata_lock.pid",
        "/var/cache/dnf/download_lock.pid",
    ],
)
def test_each_lock_of_dnf_4_names_its_holder(fakes, monkeypatch, tmp_path, path):
    root = tmp_path / "root"
    monkeypatch.setattr(
        system_package_module,
        "DNF_LOCK_PATHS",
        tuple(f"{root}{named}" for named in DNF_LOCK_PATHS),
    )
    held = pathlib.Path(f"{root}{path}")
    held.parent.mkdir(parents=True)
    held.write_text("4321")
    fakes.process(4321, "dnf", b"/usr/bin/python3", b"/usr/bin/dnf", b"upgrade")
    waits: list = []

    def told(wait):
        waits.append(wait)
        held.unlink(missing_ok=True)

    system_package_module.set_wait_sink(told)
    try:
        system_package_module.run_package_manager(["dnf", "install", "-y", "x"])
    finally:
        system_package_module.set_wait_sink(None)

    assert waits == [
        {"code": "waiting_for_package_manager", "params": {"holder": "dnf"}},
        {},
    ]


def test_a_dnf_lock_held_past_the_wait_fails_naming_its_holder(fakes, monkeypatch):
    monkeypatch.setattr(system_package_module, "AGENT_UPDATE_LOCK_TIMEOUT_S", 0)
    fakes.process(4321, "dnf", b"/usr/bin/python3", b"/usr/bin/dnf", b"makecache")
    fakes.lock.write_text("4321")

    with pytest.raises(ModuleApplyError) as caught:
        system_package_module.run_package_manager(["dnf", "install", "-y", "x"])

    assert (caught.value.code, caught.value.params) == (
        "package_manager_busy",
        {"holder": "dnf"},
    )
    assert fakes.args("dnf") == []


def test_a_dnf_lock_file_of_an_ended_process_holds_nothing(fakes):
    fakes.lock.write_text("4321")

    system_package_module.run_package_manager(["dnf", "install", "-y", "x"])

    assert len(fakes.args("dnf")) == 1


PACMAN = ["pacman", "-Sy", "--needed", "--noconfirm", "x"]


def test_pacman_runs_at_once_while_its_lock_file_is_not_there(fakes):
    system_package_module.run_package_manager(PACMAN)

    assert fakes.args("pacman") == ["-Sy --needed --noconfirm x"]


def test_pacman_waits_while_a_process_holds_its_lock_file_and_names_it(
    fakes, monkeypatch
):
    fakes.pacman_lock.write_text("")
    fakes.process(4321, "packagekitd", b"/usr/lib/packagekitd")
    waits: list = []

    def release(seconds):
        fakes.pacman_lock.unlink()

    monkeypatch.setattr(system_package_module.time, "sleep", release)
    system_package_module.set_wait_sink(waits.append)
    try:
        system_package_module.run_package_manager(PACMAN)
    finally:
        system_package_module.set_wait_sink(None)

    assert waits == [
        {"code": "waiting_for_package_manager", "params": {"holder": "packagekitd"}},
        {},
    ]
    assert len(fakes.args("pacman")) == 1


def test_a_pacman_lock_held_past_the_wait_fails_naming_its_holder(fakes, monkeypatch):
    monkeypatch.setattr(system_package_module, "AGENT_UPDATE_LOCK_TIMEOUT_S", 0)
    fakes.pacman_lock.write_text("")
    fakes.process(4321, "pacman", b"/usr/bin/pacman", b"-Syu")

    with pytest.raises(ModuleApplyError) as refused:
        system_package_module.run_package_manager(PACMAN)

    assert (refused.value.code, refused.value.params) == (
        "package_manager_busy",
        {"holder": "pacman"},
    )
    assert fakes.args("pacman") == []
    assert fakes.pacman_lock.exists()


def test_a_pacman_lock_file_no_process_holds_is_removed(fakes):
    """A pacman the agent's stop ended leaves its lock file behind."""
    fakes.pacman_lock.write_text("")
    fakes.process(4321, "bash", b"/bin/bash")

    system_package_module.run_package_manager(PACMAN)

    assert not fakes.pacman_lock.exists()
    assert len(fakes.args("pacman")) == 1


def test_pacman_runs_again_while_it_refuses_on_its_lock(fakes):
    fakes.turns("pacman", "alpm", "ok")

    system_package_module.run_package_manager(PACMAN)

    assert len(fakes.args("pacman")) == 2


def test_pacman_s_own_refusal_is_an_install_error_with_its_words(fakes):
    fakes.turns("pacman", "noname")

    with pytest.raises(InstallError) as refused:
        system_package_module.run_package_manager(PACMAN)

    assert "target not found" in str(refused.value)
