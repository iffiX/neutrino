"""The macOS and Windows update scripts, rendered and run against stand-ins.

The macOS sh runs under ``sh`` with ``launchctl``, ``installer``, ``curl``,
``nhub`` and ``nagent`` as scripts on a PATH of the test's own. The Windows
PowerShell runs where ``pwsh`` is, dot-sourced after functions that stand in
for msiexec, the service and curl. Each leaves the state file the panel
reads, and that is what is asserted.
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
    stub(bin_dir, "installer", body=f'echo "installer $*" >> {log}; echo installed')
    stub(
        bin_dir,
        "launchctl",
        body=f'echo "launchctl $*" >> {log}\n'
        'case "$1" in print) echo "state = running" ;; esac',
    )
    stub(bin_dir, "curl", body="exit 0")
    stub(bin_dir, "nhub", body='echo "0.5.1"')
    stub(bin_dir, "nagent", body='echo "0.5.0"')
    return bin_dir, directory, cache, log


def run_mac(mac, *, rollback=True):
    bin_dir, directory, cache, log = mac
    text = render_script(
        plan_for(directory, "pkg", rollback=rollback),
        directory=directory,
        gate_timeout_s=1,
        poll_s=0.2,
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
    installs = [line for line in asked if line.startswith("installer")]
    assert installs[0].endswith("neutrino-hub-0.5.1-macos-arm64.pkg -target /")
    assert installs[1] == (
        f"installer -pkg {cache}/neutrino-agent-0.5.1-macos-arm64.pkg -target /"
    )
    assert "launchctl kickstart system/com.neutrino.hub" in asked


def test_a_mac_job_ends_with_zero_whatever_happened(mac):
    """launchd starts a submitted job that fails again."""
    bin_dir, _directory, _cache, _log = mac
    stub(bin_dir, "nhub", body='echo "0.0.1"')

    code, raw, _asked = run_mac(mac)

    assert code == 0
    assert raw["stage"] == "failed"
    assert raw["reason"] == "health_gate_failed"


def test_a_mac_install_that_fails_puts_the_older_package_back(mac):
    bin_dir, directory, _cache, log = mac
    stub(
        bin_dir,
        "installer",
        body=f'echo "installer $*" >> {log}\n'
        'case "$*" in *0.5.1*) echo "installer: failed"; exit 1;; esac',
    )
    stub(bin_dir, "nhub", body='echo "0.5.0"')

    code, raw, asked = run_mac(mac)

    assert code == 0
    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "package_install_failed"
    assert "installer: failed" in raw["output"]
    assert (
        f"installer -pkg {directory}/neutrino-hub-0.5.0-macos-arm64.pkg -target /"
        in asked
    )
    record = HubUpdateStateFile(path=directory / "state.json").load()
    assert record.stage == "rolled_back"


def test_a_mac_gate_reports_a_stopped_service(mac):
    bin_dir, _directory, _cache, log = mac
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
        f'case "$1" in print) [ -e {log}.boot ] && echo "state = running" && exit 0;'
        f" exit 113;; bootstrap) touch {log}.boot;; esac",
    )

    _code, raw, asked = run_mac(mac)

    assert raw["stage"] == "installed"
    assert (
        "launchctl bootstrap system /Library/LaunchDaemons/com.neutrino.hub.plist"
        in asked
    )


# --- the Windows script ---

pwsh = shutil.which("pwsh")

# Stand-ins defined before the script is dot-sourced, so its calls reach them.
WINDOWS_STAND_INS = """
function Start-Process {
    param([string]$FilePath, [switch]$Wait, [switch]$PassThru, [string]$WindowStyle,
          [string]$ArgumentList)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value "msiexec $ArgumentList"
    $code = 0
    if ($env:FAKE_FAILING -and $ArgumentList -like "*$env:FAKE_FAILING*") { $code = 1603 }
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
function curl.exe { $global:LASTEXITCODE = 0 }
"""


@pytest.fixture
def windows(tmp_path):
    if pwsh is None:
        pytest.skip("PowerShell is not installed")
    directory = tmp_path / "hub_update"
    directory.mkdir()
    nhub = tmp_path / "nhub.exe"
    return directory, nhub, tmp_path / "asked"


def run_windows(
    windows, *, version="0.5.1", service="Running", failing="", rollback=True
):
    directory, nhub, asked = windows
    stub(nhub.parent, nhub.name, body=f'echo "{version}"')
    text = render_script(
        plan_for(directory, "msi", rollback=rollback),
        directory=directory,
        gate_timeout_s=1,
        poll_s=1,
    )
    text = text.replace(
        f"'{installer_module.constants.UTILS_STATIC_ROOT / 'nhub.exe'}'", f"'{nhub}'"
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
        },
    )
    raw = json.loads((directory / "state.json").read_text())
    lines = asked.read_text().splitlines() if asked.exists() else []
    return raw, lines


def test_a_windows_install_the_gate_passes_is_installed(windows):
    directory, _nhub, _asked = windows

    raw, asked = run_windows(windows)

    assert raw["stage"] == "installed"
    assert raw["from_version"] == "0.5.0"
    assert asked[0] == (
        f'msiexec /i "{directory}/neutrino-hub-0.5.1-windows-amd64.msi" /qn /norestart'
    )
    assert "start neutrino_hub" in asked
    assert (directory / "update.pid").read_text().strip().isdigit()
    assert HubUpdateStateFile(path=directory / "state.json").load().stage == (
        "installed"
    )


def test_a_windows_rollback_takes_the_newer_version_away_first(windows):
    """msiexec refuses an older version over a newer one."""
    directory, _nhub, _asked = windows

    raw, asked = run_windows(windows, version="0.5.0", failing="0.5.1")

    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "package_install_failed"
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
