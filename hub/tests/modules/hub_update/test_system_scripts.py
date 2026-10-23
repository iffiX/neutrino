"""The macOS and Windows update scripts, rendered and run against stand-ins.

The macOS sh runs under ``sh`` with ``launchctl``, ``installer``, ``curl``,
``nhub`` and ``nagent`` as scripts on a PATH of the test's own. The Windows
PowerShell runs where ``pwsh`` is, dot-sourced after functions that stand in
for msiexec, the service and curl. Each installer stand-in writes down the
version it installed, and ``nhub`` and ``nagent`` say it back. Each script
leaves the state file the panel reads, and that is what is asserted.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from neutrino_hub.modules.hub_update import installer as installer_module
from neutrino_hub.modules.hub_update.installer import (
    HubUpdatePlan,
    install_commands,
    render_script,
)
from neutrino_hub.modules.hub_update.state import HubUpdateStateFile

STAGING = ["neutrino-hub-0.5.1 already here, checked"]
HANDED_OVER = [*STAGING, "installing; the panel restarts now"]


def stub(bin_dir: Path, name: str, *, body: str) -> None:
    program = bin_dir / name
    program.write_text("#!/bin/sh\n" + body + "\n")
    program.chmod(0o755)


def plan_for(directory: Path, family: str, *, rollback: bool = True) -> HubUpdatePlan:
    name = {"pkg": "macos-arm64.pkg", "msi": "windows-amd64.msi"}[family]
    return HubUpdatePlan(
        from_version="0.5.0",
        to_version="0.5.1",
        package=directory / f"neutrino-hub-0.5.1-{name}",
        rollback=directory / f"neutrino-hub-0.5.0-{name}" if rollback else None,
        family=family,
        port=8080,
        https_port=8443,
        units=(),
        started_at="2026-10-03T12:00:00Z",
        steps=tuple(STAGING),
    )


# --- what each family runs ---


def test_macos_installs_and_rolls_back_with_the_system_installer():
    assert install_commands("pkg", Path("/s/a b.pkg")) == (
        "installer -pkg '/s/a b.pkg' -target /",
        "installer -pkg '/s/a b.pkg' -target /",
    )


def test_windows_hands_msiexec_the_quoted_file():
    install, rollback = install_commands("msi", Path("C:/s/it's.msi"))

    assert install == """'/i "C:/s/it''s.msi" /qn /norestart'"""
    assert rollback == install


def test_each_system_names_its_script():
    assert installer_module.script_name("msi") == "update.ps1"
    assert installer_module.script_name("pkg") == "update.sh"
    assert installer_module.script_name("debian") == "update.sh"


def test_the_family_is_the_systems_outside_linux(monkeypatch):
    monkeypatch.setattr(installer_module, "hub_os", lambda: "darwin")
    assert installer_module.update_family() == "pkg"
    monkeypatch.setattr(installer_module, "hub_os", lambda: "windows")
    assert installer_module.update_family() == "msi"
    monkeypatch.setattr(installer_module, "hub_os", lambda: "linux")
    monkeypatch.setattr(installer_module, "distribution_family", lambda: "rhel")
    assert installer_module.update_family() == "rhel"


# --- the macOS script ---


def installer_stub(directory: Path, log: Path, *, failing: str = "") -> str:
    """macOS's installer, writing down each call and the version it put in."""
    failure = ""
    if failing:
        failure = (
            f'case "$*" in *hub-{failing}-*) echo "installer: failed"; exit 1;; esac\n'
        )
    return (
        f'echo "installer $*" >> {log}\n'
        + failure
        + f'case "$2" in *neutrino-hub-*) echo "$2" | sed -E "s/.*hub-([0-9.]+)-.*/\\1/" > {directory}/hub_version;;\n'
        + f'  *neutrino-agent-*) echo "$2" | sed -E "s/.*agent-([0-9.]+)-.*/\\1/" > {directory}/agent_version;; esac\n'
        + "echo installed"
    )


@pytest.fixture
def mac(tmp_path):
    """A directory for the job, and a PATH where everything passes."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    directory = tmp_path / "hub_update"
    directory.mkdir()
    cache = tmp_path / "agent_cache"
    cache.mkdir()
    log = tmp_path / "asked"
    (directory / "hub_version").write_text("0.5.0\n")
    (directory / "agent_version").write_text("0.5.0\n")
    stub(bin_dir, "installer", body=installer_stub(directory, log))
    stub(
        bin_dir,
        "launchctl",
        body=f'echo "launchctl $*" >> {log}\n'
        f'[ "$1" = remove ] && cp {directory}/state.json {directory}/at_remove.json\n'
        'case "$*" in "print system/com.neutrino.hub") echo "state = running" ;; esac',
    )
    stub(bin_dir, "curl", body="exit 0")
    stub(bin_dir, "nhub", body=f"cat {directory}/hub_version")
    stub(bin_dir, "nagent", body=f"cat {directory}/agent_version")
    return bin_dir, directory, cache, log


def run_mac(mac, *, rollback=True, agent_start_s=0, agent_wait_s=120, gate_timeout_s=1):
    bin_dir, directory, cache, log = mac
    text = render_script(
        plan_for(directory, "pkg", rollback=rollback),
        directory=directory,
        gate_timeout_s=gate_timeout_s,
        poll_s=0.2,
        agent_start_s=agent_start_s,
        agent_wait_s=agent_wait_s,
    )
    text = (
        text.replace("/usr/local/bin/nhub", str(bin_dir / "nhub"))
        .replace("/usr/local/bin/nagent", str(bin_dir / "nagent"))
        .replace(str(installer_module.AGENT_PACKAGE_CACHE_DIR), str(cache))
    )
    script = directory / "update.sh"
    script.write_text(text)
    result = subprocess.run(
        ["sh", str(script)],
        capture_output=True,
        text=True,
        env=dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}"),
    )
    raw = json.loads((directory / "state.json").read_text())
    asked = log.read_text().splitlines() if log.exists() else []
    return result.returncode, raw, asked


def test_a_mac_install_the_gate_passes_is_installed_and_the_agent_follows(mac):
    _bin_dir, _directory, cache, _log = mac
    (cache / "neutrino-agent-0.5.1-macos-arm64.pkg").write_bytes(b"agent")
    (cache / "neutrino-agent-0.5.0-macos-arm64.pkg").write_bytes(b"older")

    code, raw, asked = run_mac(mac)

    assert code == 0
    assert raw["stage"] == "installed"
    assert raw["reason"] == ""
    assert raw["steps"] == [
        *HANDED_OVER,
        "installed 0.5.1",
        "panel answers",
        "agent updated to 0.5.1",
        "done",
    ]
    installs = [line for line in asked if line.startswith("installer")]
    assert installs[0].endswith("neutrino-hub-0.5.1-macos-arm64.pkg -target /")
    assert installs[1] == (
        f"installer -pkg {cache}/neutrino-agent-0.5.1-macos-arm64.pkg -target /"
    )
    assert "launchctl kickstart system/com.neutrino.hub" in asked


def stub_failing_gate(mac) -> None:
    """A panel that answers only on 0.5.0."""
    bin_dir, directory, _cache, _log = mac
    stub(bin_dir, "curl", body=f"grep -q 0.5.0 {directory}/hub_version")


@pytest.mark.parametrize(
    "case, stage",
    [
        ("installed", "installed"),
        ("nothing changed", "rolled_back"),
        ("rolled back", "rolled_back"),
        ("failed", "failed"),
    ],
)
def test_every_mac_end_removes_its_job_after_the_record_is_final(mac, case, stage):
    """launchd runs a submitted job again whenever it exits."""
    bin_dir, directory, _cache, log = mac
    if case == "nothing changed":
        stub(bin_dir, "installer", body=installer_stub(directory, log, failing="0.5.1"))
    if case == "rolled back":
        stub_failing_gate(mac)
    if case == "failed":
        stub(bin_dir, "curl", body="exit 7")

    code, raw, asked = run_mac(mac)

    assert code == 0
    assert raw["stage"] == stage
    assert [line for line in asked if line.startswith("launchctl remove")] == [
        "launchctl remove neutrino_hub_update"
    ]
    assert asked[-1] == "launchctl remove neutrino_hub_update"
    at_remove = json.loads((directory / "at_remove.json").read_text())
    assert at_remove["stage"] == stage
    assert at_remove["steps"][-1] == "done"


def test_a_mac_install_that_changed_nothing_is_not_rolled_back(mac):
    bin_dir, directory, _cache, log = mac
    stub(bin_dir, "installer", body=installer_stub(directory, log, failing="0.5.1"))

    _code, raw, asked = run_mac(mac)

    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "package_install_failed"
    assert raw["steps"][len(HANDED_OVER) :] == [
        "install failed: installer exited 1",
        "nothing changed, still 0.5.0",
        "done",
    ]
    assert "installer: failed" in raw["output"]
    assert len([line for line in asked if line.startswith("installer")]) == 1


def test_a_mac_gate_that_fails_puts_the_older_package_back(mac):
    _bin_dir, directory, _cache, _log = mac
    stub_failing_gate(mac)

    _code, raw, asked = run_mac(mac)

    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "health_gate_failed"
    assert raw["steps"][len(HANDED_OVER) :] == [
        "installed 0.5.1",
        "panel did not answer in 1 s",
        "rolled back to 0.5.0",
        "done",
    ]
    assert (
        f"installer -pkg {directory}/neutrino-hub-0.5.0-macos-arm64.pkg -target /"
        in asked
    )
    record = HubUpdateStateFile(path=directory / "state.json").load()
    assert record.stage == "rolled_back"


def test_a_mac_gate_with_no_time_left_probes_once_before_it_looks_at_the_clock(mac):
    bin_dir, directory, _cache, _log = mac
    stub(bin_dir, "curl", body=f"echo probe >> {directory}/probes")

    _code, raw, _asked = run_mac(mac, gate_timeout_s=0)

    assert raw["stage"] == "installed"
    assert len((directory / "probes").read_text().splitlines()) == 1


def test_a_mac_gate_reports_a_stopped_service(mac):
    bin_dir, directory, _cache, log = mac
    stub(
        bin_dir,
        "launchctl",
        body=f'echo "launchctl $*" >> {log}\n'
        'case "$1" in print) echo "state = not running" ;; esac',
    )

    _code, raw, _asked = run_mac(mac, rollback=False)

    assert raw["stage"] == "failed"
    assert "service=stopped" in raw["output"]


def test_a_service_launchd_does_not_know_is_bootstrapped(mac):
    bin_dir, _directory, _cache, log = mac
    stub(
        bin_dir,
        "launchctl",
        body=f'echo "launchctl $*" >> {log}\n'
        f'case "$1" in print) [ "$2" = system/com.neutrino.hub ] && [ -e {log}.boot ]'
        ' && echo "state = running" && exit 0;'
        f" exit 113;; bootstrap) touch {log}.boot;; esac",
    )

    _code, raw, asked = run_mac(mac)

    assert raw["stage"] == "installed"
    assert (
        "launchctl bootstrap system /Library/LaunchDaemons/com.neutrino.hub.plist"
        in asked
    )


def test_a_mac_agent_updating_itself_is_waited_out(mac):
    bin_dir, directory, cache, log = mac
    (cache / "neutrino-agent-0.5.1-macos-arm64.pkg").write_bytes(b"agent")
    count = directory / "agent_asked"
    stub(
        bin_dir,
        "launchctl",
        body=f'echo "launchctl $*" >> {log}\n'
        'case "$*" in\n'
        '  "print system/com.neutrino.hub") echo "state = running" ;;\n'
        f'  "print system/neutrino_agent_update") echo x >> {count}\n'
        f'    if [ "$(wc -l < {count})" -le 2 ]; then echo "state = running";\n'
        f"    else echo 0.5.1 > {directory}/agent_version; fi ;;\n"
        "esac",
    )

    _code, raw, asked = run_mac(mac)

    assert raw["steps"][-2:] == ["agent already 0.5.1", "done"]
    assert len([line for line in asked if line.startswith("installer")]) == 1


def test_a_mac_agent_is_given_time_to_start_its_own_update(mac):
    """The agent logs its update a second before its job exists."""
    bin_dir, directory, cache, log = mac
    (cache / "neutrino-agent-0.5.1-macos-arm64.pkg").write_bytes(b"agent")
    count = directory / "agent_asked"
    stub(
        bin_dir,
        "launchctl",
        body=f'echo "launchctl $*" >> {log}\n'
        'case "$*" in\n'
        '  "print system/com.neutrino.hub") echo "state = running" ;;\n'
        f'  "print system/neutrino_agent_update") echo x >> {count}\n'
        f"    asked=$(wc -l < {count})\n"
        '    if [ "$asked" -le 2 ]; then exit 113;\n'
        '    elif [ "$asked" -le 4 ]; then echo "state = running";\n'
        f"    else echo 0.5.1 > {directory}/agent_version; fi ;;\n"
        "esac",
    )

    _code, raw, asked = run_mac(mac, agent_start_s=10)

    assert raw["steps"][-2:] == ["agent already 0.5.1", "done"]
    assert len([line for line in asked if line.startswith("installer")]) == 1


def test_a_mac_agent_install_that_failed_with_the_target_in_place_says_already(mac):
    bin_dir, directory, cache, log = mac
    (cache / "neutrino-agent-0.5.1-macos-arm64.pkg").write_bytes(b"agent")
    stub(
        bin_dir,
        "installer",
        body='case "$2" in *neutrino-agent-*) '
        f'echo 0.5.1 > {directory}/agent_version; echo "installer: failed"; exit 1;; esac\n'
        + installer_stub(directory, log),
    )

    _code, raw, _asked = run_mac(mac)

    assert raw["stage"] == "installed"
    assert raw["steps"][-2:] == ["agent already 0.5.1", "done"]


# --- the Windows script ---

pwsh = shutil.which("pwsh")

# Stand-ins defined before the script is dot-sourced, so its calls reach them.
WINDOWS_STAND_INS = """
function Start-Process {
    param([string]$FilePath, [switch]$Wait, [switch]$PassThru, [string]$WindowStyle,
          [string]$ArgumentList)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value "msiexec $ArgumentList"
    $code = 0
    if ($env:FAKE_BUSY -and $ArgumentList -like "*neutrino-agent-*" -and
        -not (Test-Path -LiteralPath "$env:FAKE_ASKED.busy")) {
        Set-Content -LiteralPath "$env:FAKE_ASKED.busy" -Value ''
        return [pscustomobject]@{ ExitCode = 1618 }
    }
    if ($env:FAKE_FAILING -and $ArgumentList -like "*$env:FAKE_FAILING*") {
        if ($env:FAKE_LEAVES_AGENT) {
            Set-Content -LiteralPath $env:FAKE_AGENT -Value $env:FAKE_LEAVES_AGENT
        }
        return [pscustomobject]@{ ExitCode = 1603 }
    }
    if ($ArgumentList -match '^/i .*neutrino-hub-([0-9.]+)-') {
        Set-Content -LiteralPath $env:FAKE_HUB -Value $Matches[1]
    }
    if ($ArgumentList -match '^/i .*neutrino-agent-([0-9.]+)-') {
        Set-Content -LiteralPath $env:FAKE_AGENT -Value $Matches[1]
    }
    return [pscustomobject]@{ ExitCode = $code }
}
function Start-Service {
    param([string]$Name, $ErrorAction)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value "start $Name"
}
function Get-Service {
    param([string]$Name, $ErrorAction)
    return [pscustomobject]@{ Status = $env:FAKE_SERVICE }
}
function curl.exe {
    $global:LASTEXITCODE = 0
    if ($env:FAKE_PANEL_ON -and
        (Get-Content -LiteralPath $env:FAKE_HUB) -ne $env:FAKE_PANEL_ON) {
        $global:LASTEXITCODE = 7
    }
}
"""


@pytest.fixture
def windows(tmp_path):
    if pwsh is None:
        pytest.skip("PowerShell is not installed")
    directory = tmp_path / "hub_update"
    directory.mkdir()
    (directory / "hub_version").write_text("0.5.0\n")
    (directory / "agent_version").write_text("0.5.0\n")
    stub(tmp_path, "nhub.exe", body=f"cat {directory}/hub_version")
    stub(tmp_path, "nagent.exe", body=f"cat {directory}/agent_version")
    cache = tmp_path / "agent_cache"
    cache.mkdir()
    return directory, tmp_path, tmp_path / "asked"


def run_windows(
    windows,
    *,
    service="Running",
    failing="",
    panel_on="",
    rollback=True,
    is_agent_here=False,
    is_busy=False,
    leaves_agent="",
    gate_timeout_s=1,
):
    directory, root, asked = windows
    text = render_script(
        plan_for(directory, "msi", rollback=rollback),
        directory=directory,
        gate_timeout_s=gate_timeout_s,
        poll_s=1,
        agent_start_s=0,
    )
    text = text.replace(
        f"'{installer_module.constants.UTILS_STATIC_ROOT / 'nhub.exe'}'",
        f"'{root / 'nhub.exe'}'",
    ).replace(
        f"'{installer_module.AGENT_PACKAGE_CACHE_DIR}'", f"'{root / 'agent_cache'}'"
    )
    if is_agent_here:
        text = text.replace(
            "'C:\\Program Files\\Neutrino\\agent\\nagent.exe'",
            f"'{root / 'nagent.exe'}'",
        )
    script = directory / "update.ps1"
    script.write_text(text)
    driver = directory / "driver.ps1"
    driver.write_text(WINDOWS_STAND_INS + f". '{script}'\n")
    subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(directory),
            "FAKE_ASKED": str(asked),
            "FAKE_SERVICE": service,
            "FAKE_FAILING": failing,
            "FAKE_PANEL_ON": panel_on,
            "FAKE_BUSY": "1" if is_busy else "",
            "FAKE_LEAVES_AGENT": leaves_agent,
            "FAKE_HUB": str(directory / "hub_version"),
            "FAKE_AGENT": str(directory / "agent_version"),
        },
    )
    raw = json.loads((directory / "state.json").read_text())
    lines = asked.read_text().splitlines() if asked.exists() else []
    return raw, lines


def test_a_windows_install_the_gate_passes_is_installed(windows):
    directory, _root, _asked = windows

    raw, asked = run_windows(windows)

    assert raw["stage"] == "installed"
    assert raw["from_version"] == "0.5.0"
    assert raw["steps"] == [
        *HANDED_OVER,
        "installed 0.5.1",
        "panel answers",
        "no agent on this machine",
        "done",
    ]
    assert raw["finished_at"].endswith("Z")
    assert raw["output"].startswith("msiexec /i ")
    assert asked[0] == (
        f'msiexec /i "{directory}/neutrino-hub-0.5.1-windows-amd64.msi" /qn /norestart'
    )
    assert "start neutrino_hub" in asked
    assert not (directory / "update.pid").exists()
    assert HubUpdateStateFile(path=directory / "state.json").load().stage == (
        "installed"
    )


def test_a_windows_gate_with_no_time_left_probes_once_before_it_looks_at_the_clock(
    windows,
):
    raw, _asked = run_windows(windows, gate_timeout_s=0)

    assert raw["stage"] == "installed"
    assert "panel answers" in raw["steps"]


def test_a_windows_install_msiexec_refused_changed_nothing(windows):
    """msiexec rolls a failed install back itself."""
    raw, asked = run_windows(windows, failing="0.5.1")

    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "package_install_failed"
    assert raw["steps"][len(HANDED_OVER) :] == [
        "install failed: msiexec exited 1603",
        "nothing changed, still 0.5.0",
        "done",
    ]
    assert len([line for line in asked if line.startswith("msiexec")]) == 1


def test_a_windows_rollback_takes_the_newer_version_away_first(windows):
    """msiexec refuses an older version over a newer one."""
    directory, _root, _asked = windows

    raw, asked = run_windows(windows, panel_on="0.5.0")

    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "health_gate_failed"
    assert raw["steps"][len(HANDED_OVER) :] == [
        "installed 0.5.1",
        "panel did not answer in 1 s",
        "rolled back to 0.5.0",
        "done",
    ]
    msiexec = [line for line in asked if line.startswith("msiexec")]
    assert msiexec == [
        f'msiexec /i "{directory}/neutrino-hub-0.5.1-windows-amd64.msi" /qn /norestart',
        f'msiexec /x "{directory}/neutrino-hub-0.5.1-windows-amd64.msi" /qn /norestart',
        f'msiexec /i "{directory}/neutrino-hub-0.5.0-windows-amd64.msi" /qn /norestart',
    ]


def test_a_windows_gate_says_which_check_failed(windows):
    raw, _asked = run_windows(windows, service="Stopped", rollback=False)

    assert raw["stage"] == "failed"
    assert raw["reason"] == "health_gate_failed"
    assert "service=stopped" in raw["output"]
    assert raw["steps"][-2:] == ["rollback failed: no package of 0.5.0", "done"]


def test_a_windows_agent_is_updated_from_the_cache(windows):
    _directory, root, _asked = windows
    (root / "agent_cache" / "neutrino-agent-0.5.1-windows-amd64.msi").write_text("")

    raw, asked = run_windows(windows, is_agent_here=True)

    assert raw["steps"][-2:] == ["agent updated to 0.5.1", "done"]
    assert asked[-1].startswith("msiexec /i ")
    assert asked[-1].endswith('neutrino-agent-0.5.1-windows-amd64.msi" /qn /norestart')


def test_a_windows_agent_install_another_install_held_off_is_tried_again(windows):
    """The agent's own update holds the Windows Installer: msiexec answers
    1618 until it is done."""
    _directory, root, _asked = windows
    (root / "agent_cache" / "neutrino-agent-0.5.1-windows-amd64.msi").write_text("")

    raw, asked = run_windows(windows, is_agent_here=True, is_busy=True)

    assert raw["steps"][-2:] == ["agent updated to 0.5.1", "done"]
    agent = [line for line in asked if "neutrino-agent" in line]
    assert len(agent) == 2


def test_a_windows_agent_install_that_failed_with_the_target_in_place_says_already(
    windows,
):
    _directory, root, _asked = windows
    (root / "agent_cache" / "neutrino-agent-0.5.1-windows-amd64.msi").write_text("")

    raw, _asked = run_windows(
        windows, is_agent_here=True, failing="neutrino-agent", leaves_agent="0.5.1"
    )

    assert raw["stage"] == "installed"
    assert raw["steps"][-2:] == ["agent already 0.5.1", "done"]


def test_a_windows_agent_is_given_time_to_start_its_own_update(tmp_path):
    text = render_script(
        plan_for(tmp_path, "msi"), directory=tmp_path, agent_start_s=20
    )

    assert "$AgentStart = 20\n" in text
    assert "while (((Get-Date) -lt $deadline) -and -not (Test-Installer)) {" in text
