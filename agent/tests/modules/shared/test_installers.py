"""Installing a downloaded package: msiexec on Windows, installer on macOS.

msiexec runs in a PowerShell that waits for the Windows Installer's mutex,
runs msiexec once more after a busy answer and exits with msiexec's code;
PowerShell is stood in for by a fake ``subprocess.run`` that answers an exit
code, and where ``pwsh`` is installed the script itself runs with a
stand-in msiexec. What is pinned: the msiexec command lines, the wait and
the one retry in the script, 0 and 3010 as success with 3010 owing a
restart, every other exit an ``InstallError`` carrying the code, and the
``installer`` command line for a pkg.
"""

import os
import shutil
import subprocess
import sys

import pytest

from neutrino_agent.exceptions import InstallError
from neutrino_agent.modules.shared import installers

MSI = "C:\\ProgramData\\Neutrino\\agent\\state\\podman\\installer\\podman.msi"
LOG = "C:\\ProgramData\\Neutrino\\agent\\state\\podman\\installer.log"
PRODUCT = "{12345678-1234-1234-1234-123456789ABC}"


class FakePowerShell:
    """``subprocess.run`` standing in for PowerShell: each call recorded and
    answered with the next canned exit code and errors, or raising a canned
    exception."""

    def __init__(self):
        self.answers: list = []
        self.calls: list = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        returncode, stderr = answer
        return subprocess.CompletedProcess(command, returncode, "", stderr)

    def script(self) -> str:
        """The script the last call ran."""
        return self.calls[-1][0][-1]


@pytest.fixture
def powershell(monkeypatch):
    held = FakePowerShell()
    monkeypatch.setattr(installers.subprocess, "run", held)
    return held


def test_the_msiexec_command_line_is_a_quiet_logged_install_with_its_properties():
    assert installers.msiexec_arguments(MSI, log_path=LOG) == (
        f'/i "{MSI}" /qn /norestart /l*v "{LOG}"'
    )
    assert installers.msiexec_arguments(
        MSI, log_path=LOG, properties=("ALLUSERS=1", "MACHINE_PROVIDER=wsl")
    ) == (f'/i "{MSI}" /qn /norestart /l*v "{LOG}" ALLUSERS=1 MACHINE_PROVIDER=wsl')


def test_the_script_waits_for_the_windows_installer_and_tries_once_more_when_busy():
    script = installers.msiexec_script('/i "C:\\it\'s.msi" /qn')

    assert "[Threading.Mutex]::TryOpenExisting('Global\\_MSIExecute', [ref]$held)" in (
        script
    )
    assert "$deadline = (Get-Date).AddSeconds(300)" in script
    assert (
        "    Wait-Installer\n"
        "    $run = Start-Process -FilePath msiexec.exe -Wait -PassThru -NoNewWindow "
        "-ArgumentList '/i \"C:\\it''s.msi\" /qn'\n"
    ) in script
    assert script.endswith(
        "$code = Invoke-Install\nif ($code -eq 1618) { $code = Invoke-Install }\n"
    )


def test_lines_before_msiexec_run_after_each_wait():
    before = "    if ($skip) {\n        return 0\n    }\n"

    script = installers.msiexec_script("/x {A}", before=before)

    assert "    Wait-Installer\n" + before + "    $run = Start-Process" in script


def test_an_msi_installs_through_powershell_with_its_properties_and_waits(powershell):
    powershell.answers.append((0, ""))

    is_reboot_owed = installers.install_msi(
        MSI, log_path=LOG, properties=("ALLUSERS=1", "MACHINE_PROVIDER=wsl")
    )

    assert is_reboot_owed is False
    ((command, kwargs),) = powershell.calls
    assert command[:-1] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
    ]
    arguments = (
        f'/i "{MSI}" /qn /norestart /l*v "{LOG}" ALLUSERS=1 MACHINE_PROVIDER=wsl'
    )
    assert command[-1] == (
        "$ErrorActionPreference = 'Continue'\n"
        + installers.msiexec_script(arguments)
        + "if ($code -isnot [int]) { exit 1 }\nexit $code\n"
    )
    assert kwargs["timeout"] == installers.INSTALL_TIMEOUT_S
    assert (kwargs["stdout"], kwargs["stderr"]) == (subprocess.DEVNULL, subprocess.PIPE)


def test_an_install_that_owes_a_restart_is_a_success_that_says_so(powershell):
    powershell.answers.append((3010, ""))

    assert installers.install_msi(MSI, log_path=LOG) is True


@pytest.mark.parametrize("code", [1603, 1618, 1619])
def test_any_other_exit_is_an_install_error_with_the_code(powershell, code):
    powershell.answers.append((code, ""))

    with pytest.raises(InstallError) as caught:
        installers.install_msi(MSI, log_path=LOG)

    assert caught.value.exit_code == code
    assert str(code) in str(caught.value)


def test_an_msiexec_that_did_not_start_is_an_install_error_with_powershells_words(
    powershell,
):
    powershell.answers.append((1, "Start-Process : This command cannot be run."))

    with pytest.raises(InstallError, match="cannot be run") as caught:
        installers.install_msi(MSI, log_path=LOG)

    assert caught.value.exit_code == 1


@pytest.mark.parametrize(
    "error",
    [OSError("no powershell.exe"), subprocess.TimeoutExpired("powershell.exe", 1800)],
)
def test_a_powershell_that_cannot_run_is_an_install_error(powershell, error):
    powershell.answers.append(error)

    with pytest.raises(InstallError) as caught:
        installers.install_msi(MSI, log_path=LOG)

    assert caught.value.exit_code is None


def test_a_product_is_uninstalled_by_its_code_quietly_and_logged(powershell):
    powershell.answers.append((0, ""))

    assert installers.uninstall_msi(PRODUCT, log_path=LOG) is False
    assert powershell.script() == (
        "$ErrorActionPreference = 'Continue'\n"
        + installers.msiexec_script(f'/x {PRODUCT} /qn /norestart /l*v "{LOG}"')
        + "if ($code -isnot [int]) { exit 1 }\nexit $code\n"
    )


def test_an_uninstall_takes_3010_as_a_success_and_fails_on_anything_else(powershell):
    powershell.answers.extend([(3010, ""), (1605, "")])

    assert installers.uninstall_msi(PRODUCT, log_path=LOG) is True
    with pytest.raises(InstallError) as caught:
        installers.uninstall_msi(PRODUCT, log_path=LOG)
    assert caught.value.exit_code == 1605


def test_a_pkg_is_installed_by_the_system_installer_on_the_whole_disk(monkeypatch):
    ran = []

    def run(command, **kwargs):
        ran.append((list(command), kwargs["timeout"]))
        return subprocess.CompletedProcess(command, 0, "installer: done", "")

    monkeypatch.setattr(installers.subprocess, "run", run)

    installers.install_pkg("/tmp/podman installer.pkg")

    assert ran == [
        (
            ["installer", "-pkg", "/tmp/podman installer.pkg", "-target", "/"],
            installers.INSTALL_TIMEOUT_S,
        )
    ]


def test_a_failed_pkg_is_an_install_error_with_the_code_and_the_installers_words(
    monkeypatch,
):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "installer: no space")

    monkeypatch.setattr(installers.subprocess, "run", run)

    with pytest.raises(InstallError, match="no space") as caught:
        installers.install_pkg("/tmp/podman.pkg")

    assert caught.value.exit_code == 1


# --- the msiexec script, run in PowerShell where there is one ---

pwsh = shutil.which("pwsh")

# msiexec's busy code, 1618, is past 255: only Windows keeps a process's whole
# exit code, and other systems keep its low byte.
windows_exit_codes = pytest.mark.skipif(
    sys.platform != "win32", reason="exit codes past 255 are Windows'"
)

# Stands in for msiexec: each call takes the next exit code of FAKE_CODES.
STAND_INS = """
function Start-Process {
    param([string]$FilePath, [switch]$Wait, [switch]$PassThru, [switch]$NoNewWindow,
          [string]$ArgumentList)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value "msiexec $ArgumentList"
    $calls = @(Get-Content -LiteralPath $env:FAKE_ASKED).Count
    return [pscustomobject]@{ ExitCode = [int]($env:FAKE_CODES.Split(',')[$calls - 1]) }
}
"""


def run_in_pwsh(tmp_path, monkeypatch, codes: str):
    """Make ``subprocess.run`` run the script in pwsh, msiexec stood in for.

    Returns:
        The file each stand-in call is written to.
    """
    if pwsh is None:
        pytest.skip("PowerShell is not installed")
    asked = tmp_path / "asked"
    real_run = subprocess.run

    def run(command, **kwargs):
        driver = tmp_path / "driver.ps1"
        driver.write_text(STAND_INS + command[-1])
        return real_run(
            [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
            capture_output=True,
            text=True,
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(tmp_path),
                "FAKE_ASKED": str(asked),
                "FAKE_CODES": codes,
            },
        )

    monkeypatch.setattr(installers.subprocess, "run", run)
    return asked


@windows_exit_codes
def test_a_busy_windows_installer_is_tried_once_more(tmp_path, monkeypatch):
    asked = run_in_pwsh(tmp_path, monkeypatch, "1618,3010")

    assert installers.install_msi(MSI, log_path=LOG) is True
    assert len(asked.read_text().splitlines()) == 2


@windows_exit_codes
def test_a_second_busy_answer_is_the_failure(tmp_path, monkeypatch):
    asked = run_in_pwsh(tmp_path, monkeypatch, "1618,1618,0")

    with pytest.raises(InstallError) as caught:
        installers.install_msi(MSI, log_path=LOG)

    assert caught.value.exit_code == 1618
    assert len(asked.read_text().splitlines()) == 2
