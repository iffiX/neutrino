"""The install of the hub machine's own agent at the hub package's version.

The panel side runs against a fake runner. Each family's script runs for
real against stand-ins: on Linux the package manager, systemctl, nhub and
nagent are scripts on a PATH of the test's own; on macOS launchctl,
installer and pgrep join them; the Windows PowerShell runs where ``pwsh``
is, dot-sourced after a function that stands in for msiexec. Each installer
stand-in writes down the version it installed, and nagent says it back.
"""

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.hub_update import installer as installer_module
from neutrino_hub.modules.hub_update import local_agent as local_agent_module
from neutrino_hub.modules.hub_update.local_agent import (
    HubLocalAgentInstaller,
    local_agent_script_name,
    package_version,
    render_local_agent_script,
)

HUB = "0.6.0"
DEB = Path("/cache/neutrino-agent_0.6.0_amd64.deb")
RPM = Path("/cache/neutrino-agent-0.6.0-1.x86_64.rpm")
PKG = Path("/cache/neutrino-agent-0.6.0-macos-arm64.pkg")
MSI = Path("C:/cache/neutrino-agent-0.6.0-windows-amd64.msi")


def stub(bin_dir: Path, name: str, *, body: str) -> None:
    """One program on PATH, doing what a test wants."""
    program = bin_dir / name
    program.write_text("#!/bin/sh\n" + body + "\n")
    program.chmod(0o755)


# --- the package's version and this machine's package ---


@pytest.mark.parametrize("path", [DEB, RPM, PKG, MSI])
def test_every_familys_file_names_its_version(path):
    assert package_version(path.name) == "0.6.0"


def test_a_file_of_no_agent_package_names_no_version():
    assert package_version("neutrino-hub_0.6.0_amd64.deb") == ""


class FakeAgentCache:
    """Serves every family and machine, recording what it was asked."""

    asked = []

    def serves(self, *, family, architecture):
        self.asked.append((family, architecture))
        return True

    def package(self, *, family, architecture):
        return Path(f"/cache/{family}-{architecture}")


def test_the_local_agent_is_the_systems_own_family_outside_linux(monkeypatch):
    FakeAgentCache.asked = []
    monkeypatch.setattr(local_agent_module, "AgentPackageCache", FakeAgentCache)
    monkeypatch.setattr(local_agent_module, "machine_architecture", lambda: "arm64")
    monkeypatch.setattr(local_agent_module, "hub_os", lambda: "darwin")

    assert local_agent_module.local_agent_package() == "/cache/pkg-arm64"

    monkeypatch.setattr(local_agent_module, "hub_os", lambda: "linux")
    monkeypatch.setattr(local_agent_module, "distribution_family", lambda: "debian")

    assert local_agent_module.local_agent_package() == "/cache/deb-arm64"
    assert FakeAgentCache.asked == [("pkg", "arm64"), ("deb", "arm64")]


def test_each_system_names_its_script():
    assert local_agent_script_name("msi") == "local_agent.ps1"
    assert local_agent_script_name("pkg") == "local_agent.sh"
    assert local_agent_script_name("rhel") == "local_agent.sh"


def test_a_family_with_no_package_manager_is_refused(tmp_path):
    with pytest.raises(ValueError):
        render_local_agent_script(
            family="gentoo",
            hub_version=HUB,
            wanted=HUB,
            package=DEB,
            directory=tmp_path,
            agent_command="nagent",
        )


# --- the panel's start ---


class FakeRunner:
    """Answers the agent's --version and records every command."""

    def __init__(self, version: str):
        self.version = version
        self.ran = []

    def __call__(self, command, **_):
        self.ran.append(list(command))
        if command[-1] == "--version":
            return SimpleNamespace(stdout=f"{self.version}\n" if self.version else "")
        return SimpleNamespace(stdout="")


def follower(
    tmp_path,
    *,
    version="0.5.2",
    family="debian",
    package=str(DEB),
    state="inactive",
    is_agent_here=True,
):
    """An installer whose agent, cache, runner and job state are the test's."""
    agent = tmp_path / "nagent"
    if is_agent_here:
        agent.write_text("")
    runner = FakeRunner(version)
    started = []
    installer = HubLocalAgentInstaller(
        directory=tmp_path / "hub_update",
        family=family,
        hub_version=HUB,
        agent_command=str(agent),
        package_of=lambda: package,
        run_command=runner,
        job_state_of=lambda: state,
        start_detached=lambda command: started.append(command) or 4242,
    )
    return installer, runner, started


def test_a_machine_with_no_agent_gets_none(tmp_path):
    installer, runner, _ = follower(tmp_path, is_agent_here=False)

    assert installer.follow() == ""
    assert runner.ran == []
    assert not (tmp_path / "hub_update").exists()


def test_an_agent_at_the_hubs_version_is_left_alone(tmp_path):
    installer, runner, _ = follower(tmp_path, version=HUB)

    assert installer.follow() == ""
    assert runner.ran == [[str(tmp_path / "nagent"), "--version"]]


def test_an_older_agent_is_installed_by_a_transient_unit(tmp_path):
    installer, runner, _ = follower(tmp_path)

    note = installer.follow()

    assert note == "agent 0.5.2 goes to 0.6.0: neutrino_hub_local_agent started"
    script = tmp_path / "hub_update" / "local_agent.sh"
    assert runner.ran[-1] == [
        "systemd-run",
        "--unit",
        "neutrino_hub_local_agent",
        "--collect",
        "--property=MemoryHigh=384M",
        "--setenv=DEBIAN_FRONTEND=noninteractive",
        "--setenv=DPKG_DEB_THREADS_MAX=1",
        "/bin/sh",
        str(script),
    ]
    text = script.read_text()
    assert "HUB=0.6.0\n" in text
    assert "WANTED=0.6.0\n" in text
    assert f"AGENT={DEB}\n" in text
    assert script.stat().st_mode & 0o777 == 0o700


def test_an_agent_that_prints_no_version_is_installed(tmp_path):
    installer, runner, _ = follower(tmp_path, version="")

    assert installer.follow().startswith("agent unknown goes to 0.6.0")
    assert runner.ran[-1][0] == "systemd-run"


def test_the_wanted_version_is_the_packages_own(tmp_path):
    """A build pinned by hand names its own version."""
    pinned = "/pinned/neutrino-agent_0.5.2_amd64.deb"
    installer, runner, _ = follower(tmp_path, package=pinned)

    assert installer.follow() == ""
    assert runner.ran == [[str(tmp_path / "nagent"), "--version"]]


def test_a_hub_with_no_package_for_its_machine_starts_nothing(tmp_path):
    installer, runner, _ = follower(tmp_path, package="")

    assert installer.follow() == "agent 0.5.2: no agent package for this machine"
    assert len(runner.ran) == 1


def test_a_script_already_running_is_left_to_run(tmp_path):
    installer, runner, _ = follower(tmp_path, state="active")

    assert installer.follow() == "agent 0.5.2: neutrino_hub_local_agent runs"
    assert len(runner.ran) == 1
    assert not (tmp_path / "hub_update" / "local_agent.sh").exists()


def test_a_mac_submits_the_script_as_a_launchd_job(tmp_path):
    installer, runner, _ = follower(tmp_path, family="pkg", package=str(PKG))

    installer.follow()

    script = tmp_path / "hub_update" / "local_agent.sh"
    assert runner.ran[-2:] == [
        ["launchctl", "remove", "neutrino_hub_local_agent"],
        ["launchctl", "submit", "-l", "neutrino_hub_local_agent", "--", "/bin/sh"]
        + [str(script)],
    ]


def test_windows_starts_the_script_apart_and_keeps_its_process_id(tmp_path):
    installer, runner, started = follower(tmp_path, family="msi", package=str(MSI))

    installer.follow()

    script = tmp_path / "hub_update" / "local_agent.ps1"
    assert started == [
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]
    ]
    assert (tmp_path / "hub_update" / "local_agent.pid").read_text() == "4242"
    assert script.read_bytes().startswith(b"\xef\xbb\xbf")
    assert len(runner.ran) == 1


# --- the Linux script ---


def recording_manager(directory: Path, *, failing: bool = False) -> str:
    """A package manager that writes down each call and the agent it put in."""
    failure = 'echo "dpkg: error"; exit 100\n' if failing else ""
    return (
        f'echo "$(basename "$0") $*" >> {directory / "calls"}\n'
        + failure
        + 'for word in "$@"; do\n'
        + '  case "$word" in *neutrino-agent*) echo "$word" | '
        + f'sed -E "s/.*agent[_-]([0-9.]+)[_-].*/\\1/" > {directory / "agent_version"};; esac\n'
        + "done\n"
        + 'echo "Setting up $*"'
    )


def busy_systemctl(directory: Path, unit: str, *, times: int, then: str = ":") -> str:
    """systemctl naming a unit active for its first answers, and running
    ``then`` at each answer after them."""
    count = directory / "asked"
    return (
        f'case "$*" in *"{unit}.service"*) echo x >> {count}\n'
        f'  if [ "$(wc -l < {count})" -le {times} ]; then\n'
        f'    echo "{unit}.service loaded active running a unit"\n'
        f"  else {then}; fi ;; esac\n"
        "exit 0"
    )


@pytest.fixture
def box(tmp_path):
    """A directory for the script, and a PATH where everything passes."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    directory = tmp_path / "hub_update"
    directory.mkdir()
    (directory / "hub_version").write_text(f"{HUB}\n")
    (directory / "agent_version").write_text("0.5.2\n")
    for manager in ("apt-get", "dnf", "pacman"):
        stub(bin_dir, manager, body=recording_manager(directory))
    stub(bin_dir, "systemctl", body="exit 0")
    stub(bin_dir, "nhub", body=f"cat {directory / 'hub_version'}")
    stub(bin_dir, "nagent", body=f"cat {directory / 'agent_version'}")
    return bin_dir, directory


def run_linux(box, *, family="debian", package=DEB, wait_s=10) -> tuple:
    """Run the rendered script; its exit, its log's lines without the time,
    and the package manager's calls."""
    bin_dir, directory = box
    script = directory / "local_agent.sh"
    script.write_text(
        render_local_agent_script(
            family=family,
            hub_version=HUB,
            wanted=HUB,
            package=package,
            directory=directory,
            agent_command=str(bin_dir / "nagent"),
            wait_s=wait_s,
            poll_s=0.2,
        )
    )
    result = subprocess.run(
        ["sh", str(script)],
        capture_output=True,
        text=True,
        env=dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}"),
    )
    return result.returncode, log_lines(directory), calls(directory)


def log_lines(directory: Path) -> list:
    """The script's turns, each without its time."""
    lines = (directory / "local_agent.log").read_text().splitlines()
    return [line.split(" ", 1)[1] for line in lines if line[:4].isdigit()]


def calls(directory: Path) -> list:
    path = directory / "calls"
    return path.read_text().splitlines() if path.exists() else []


def test_a_debian_agent_is_installed_with_apt_get(box):
    code, steps, ran = run_linux(box)

    assert code == 0
    assert steps == [
        "agent 0.5.2, package 0.6.0, hub 0.6.0",
        f"installing {DEB}",
        "agent updated to 0.6.0",
    ]
    assert ran == [
        "apt-get install -y --reinstall --allow-downgrades "
        f"-o DPkg::Lock::Timeout=300 {DEB}"
    ]


def test_a_rhel_agent_is_installed_with_dnf(box):
    code, steps, ran = run_linux(box, family="rhel", package=RPM)

    assert code == 0
    assert steps[-1] == "agent updated to 0.6.0"
    assert ran == [f"dnf install -y {RPM}"]


def test_an_arch_agent_waits_for_pacmans_lock_and_says_so(box, monkeypatch):
    _, directory = box
    lock = directory / "db.lck"
    lock.write_text("")
    subprocess.Popen(["sh", "-c", f"sleep 1; rm {lock}"])
    monkeypatch.setattr(installer_module, "HUB_UPDATE_PACMAN_LOCK_PATH", str(lock))

    code, steps, ran = run_linux(box, family="arch")

    assert code == 0
    assert steps[1:] == [
        f"installing {DEB}",
        "waiting for the package manager",
        "agent updated to 0.6.0",
    ]
    assert ran == [f"pacman -U --noconfirm {DEB}"]


def test_the_hubs_own_update_is_waited_out_first(box):
    bin_dir, directory = box
    stub(
        bin_dir,
        "systemctl",
        body=busy_systemctl(directory, "neutrino_hub_update", times=3),
    )

    code, steps, ran = run_linux(box)

    assert code == 0
    assert len((directory / "asked").read_text().splitlines()) == 4
    assert steps[-1] == "agent updated to 0.6.0"
    assert len(ran) == 1


def test_a_hub_rolled_back_meanwhile_installs_nothing(box):
    bin_dir, directory = box
    stub(
        bin_dir,
        "systemctl",
        body=busy_systemctl(
            directory,
            "neutrino_hub_update",
            times=2,
            then=f"echo 0.5.2 > {directory / 'hub_version'}",
        ),
    )

    code, steps, ran = run_linux(box)

    assert code == 0
    assert steps[-1] == "hub 0.5.2 now; nothing installed"
    assert ran == []


def test_an_agent_at_the_version_when_the_update_ends_is_left_alone(box):
    bin_dir, directory = box
    stub(
        bin_dir,
        "systemctl",
        body=busy_systemctl(
            directory,
            "neutrino_hub_update",
            times=2,
            then=f"echo {HUB} > {directory / 'agent_version'}",
        ),
    )

    code, steps, ran = run_linux(box)

    assert code == 0
    assert steps[-1] == "agent already 0.6.0"
    assert ran == []


def test_an_install_that_never_ends_is_waited_out_only_so_long(box):
    bin_dir, directory = box
    stub(
        bin_dir,
        "systemctl",
        body=busy_systemctl(directory, "neutrino_hub_update", times=1000),
    )

    code, steps, ran = run_linux(box, wait_s=1)

    assert code == 0
    assert steps[-1] == "agent updated to 0.6.0"
    assert len(ran) == 1


def test_an_agent_removed_meanwhile_gets_none(box):
    bin_dir, _directory = box
    (bin_dir / "nagent").unlink()

    code, steps, ran = run_linux(box)

    assert code == 0
    assert steps == [
        "agent none, package 0.6.0, hub 0.6.0",
        "no agent on this machine",
    ]
    assert ran == []


def test_a_failed_install_says_why_and_fails(box):
    bin_dir, directory = box
    stub(bin_dir, "apt-get", body=recording_manager(directory, failing=True))

    code, steps, _ran = run_linux(box)

    assert code == 1
    assert steps[-1] == ("agent update failed: apt-get exited 100, found version 0.5.2")
    assert "dpkg: error" in (directory / "local_agent.log").read_text()


# --- the macOS script ---


@pytest.fixture
def mac(tmp_path):
    """A directory for the job, and a PATH where nothing else installs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    directory = tmp_path / "hub_update"
    directory.mkdir()
    (directory / "hub_version").write_text(f"{HUB}\n")
    (directory / "agent_version").write_text("0.5.2\n")
    stub(
        bin_dir,
        "installer",
        body=f'echo "installer $*" >> {directory / "calls"}\n'
        f'echo "$2" | sed -E "s/.*agent-([0-9.]+)-.*/\\1/" > '
        f"{directory / 'agent_version'}",
    )
    stub(bin_dir, "launchctl", body=f'echo "launchctl $*" >> {directory / "calls"}')
    stub(bin_dir, "pgrep", body="exit 1")
    stub(bin_dir, "nhub", body=f"cat {directory / 'hub_version'}")
    stub(bin_dir, "nagent", body=f"cat {directory / 'agent_version'}")
    return bin_dir, directory


def run_mac(mac, *, wait_s=10) -> tuple:
    bin_dir, directory = mac
    text = render_local_agent_script(
        family="pkg",
        hub_version=HUB,
        wanted=HUB,
        package=PKG,
        directory=directory,
        agent_command=str(bin_dir / "nagent"),
        wait_s=wait_s,
        poll_s=0.2,
    ).replace("/usr/local/bin/nhub", str(bin_dir / "nhub"))
    script = directory / "local_agent.sh"
    script.write_text(text)
    result = subprocess.run(
        ["sh", str(script)],
        capture_output=True,
        text=True,
        env=dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}"),
    )
    return result.returncode, log_lines(directory), calls(directory)


def test_a_mac_agent_is_installed_and_the_job_removes_itself(mac):
    code, steps, ran = run_mac(mac)

    assert code == 0
    assert steps[-1] == "agent updated to 0.6.0"
    assert [line for line in ran if " print " not in line] == [
        f"installer -pkg {PKG} -target /",
        "launchctl remove neutrino_hub_local_agent",
    ]


def test_a_mac_job_waits_for_the_hubs_update_and_for_another_installer(mac):
    bin_dir, directory = mac
    count = directory / "asked"
    stub(
        bin_dir,
        "launchctl",
        body=f'echo "launchctl $*" >> {directory / "calls"}\n'
        f'case "$*" in "print system/neutrino_hub_update") echo x >> {count}\n'
        f'  [ "$(wc -l < {count})" -le 2 ] && echo "state = running" ;; esac\n'
        "exit 0",
    )
    seen = directory / "pgrep_asked"
    stub(
        bin_dir,
        "pgrep",
        body=f'echo x >> {seen}; [ "$(wc -l < {seen})" -le 2 ]',
    )

    code, steps, ran = run_mac(mac)

    assert code == 0
    assert steps[-1] == "agent updated to 0.6.0"
    assert len(count.read_text().splitlines()) == 5
    assert len(seen.read_text().splitlines()) == 3
    assert ran[-2:] == [
        f"installer -pkg {PKG} -target /",
        "launchctl remove neutrino_hub_local_agent",
    ]


def test_a_mac_hub_rolled_back_installs_nothing_and_removes_the_job(mac):
    _bin_dir, directory = mac
    (directory / "hub_version").write_text("0.5.2\n")

    code, steps, ran = run_mac(mac)

    assert code == 0
    assert steps[-1] == "hub 0.5.2 now; nothing installed"
    assert [line for line in ran if " print " not in line] == [
        "launchctl remove neutrino_hub_local_agent"
    ]


# --- the Windows script ---

pwsh = shutil.which("pwsh")

# The stand-in defined before the script is dot-sourced, so its calls reach it.
WINDOWS_STAND_INS = """
function Start-Process {
    param([string]$FilePath, [switch]$Wait, [switch]$PassThru, [string]$WindowStyle,
          [string]$ArgumentList)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value "msiexec $ArgumentList"
    if ($env:FAKE_BUSY -and -not (Test-Path -LiteralPath "$env:FAKE_ASKED.busy")) {
        Set-Content -LiteralPath "$env:FAKE_ASKED.busy" -Value ''
        return [pscustomobject]@{ ExitCode = 1618 }
    }
    if ($env:FAKE_FAILING) {
        return [pscustomobject]@{ ExitCode = 1603 }
    }
    if ($ArgumentList -match '^/i .*neutrino-agent-([0-9.]+)-') {
        Set-Content -LiteralPath $env:FAKE_AGENT -Value $Matches[1]
    }
    return [pscustomobject]@{ ExitCode = 0 }
}
"""


@pytest.fixture
def windows(tmp_path):
    if pwsh is None:
        pytest.skip("PowerShell is not installed")
    directory = tmp_path / "hub_update"
    directory.mkdir()
    (directory / "hub_version").write_text(f"{HUB}\n")
    (directory / "agent_version").write_text("0.5.2\n")
    stub(tmp_path, "nhub.exe", body=f"cat {directory}/hub_version")
    stub(tmp_path, "nagent.exe", body=f"cat {directory}/agent_version")
    return directory, tmp_path


def run_windows(windows, *, is_busy=False, is_failing=False) -> tuple:
    """Run the rendered script; its log's lines without the time, and the
    msiexec calls."""
    directory, root = windows
    text = render_local_agent_script(
        family="msi",
        hub_version=HUB,
        wanted=HUB,
        package=MSI,
        directory=directory,
        agent_command=str(root / "nagent.exe"),
        wait_s=10,
        poll_s=1,
    ).replace(
        f"'{local_agent_module.constants.UTILS_STATIC_ROOT / 'nhub.exe'}'",
        f"'{root / 'nhub.exe'}'",
    )
    script = directory / "local_agent.ps1"
    script.write_text(text)
    driver = directory / "driver.ps1"
    driver.write_text(WINDOWS_STAND_INS + f". '{script}'\n")
    asked = root / "asked"
    subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(directory),
            "FAKE_ASKED": str(asked),
            "FAKE_BUSY": "1" if is_busy else "",
            "FAKE_FAILING": "1" if is_failing else "",
            "FAKE_AGENT": str(directory / "agent_version"),
        },
    )
    lines = asked.read_text().splitlines() if asked.exists() else []
    return log_lines(directory), lines


def test_a_windows_agent_is_installed_with_msiexec(windows):
    steps, asked = run_windows(windows)

    assert steps == [
        "agent 0.5.2, package 0.6.0, hub 0.6.0",
        f"installing {MSI}",
        "agent updated to 0.6.0",
    ]
    assert asked == [f'msiexec /i "{MSI}" /qn /norestart']


def test_a_windows_install_another_install_held_off_is_tried_again(windows):
    steps, asked = run_windows(windows, is_busy=True)

    assert steps[-1] == "agent updated to 0.6.0"
    assert len(asked) == 2


def test_a_windows_install_that_failed_says_why(windows):
    steps, _asked = run_windows(windows, is_failing=True)

    assert steps[-1] == "agent update failed: msiexec exited 1603, found version 0.5.2"


def test_a_windows_hub_rolled_back_installs_nothing(windows):
    directory, _root = windows
    (directory / "hub_version").write_text("0.5.2\n")

    steps, asked = run_windows(windows)

    assert steps[-1] == "hub 0.5.2 now; nothing installed"
    assert asked == []


def test_a_windows_script_waits_for_the_updates_powershell(tmp_path):
    text = render_local_agent_script(
        family="msi",
        hub_version=HUB,
        wanted=HUB,
        package=MSI,
        directory=tmp_path,
        agent_command="C:\\Program Files\\Neutrino\\agent\\nagent.exe",
    )

    assert f"$UpdatePid = '{tmp_path / 'update.pid'}'\n" in text
    assert "$Wait = 1800\n" in text
    assert "if ($id -eq $PID) { return $false }" in text
