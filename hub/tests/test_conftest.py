"""The suite's guard: PowerShell runs only a script a test wrote under the
temporary directory, and every other refused program stays refused."""

import tempfile

from tests.conftest import _refuses


def test_powershell_on_a_script_under_the_temporary_directory_runs(tmp_path):
    script = tmp_path / "driver.ps1"

    assert _refuses(["/usr/bin/pwsh", "-NoProfile", "-File", str(script)]) is None


def test_powershell_on_any_other_script_is_refused():
    assert _refuses(["pwsh", "-File", "/opt/neutrino/hub/update.ps1"]) is not None


def test_powershell_with_a_command_line_is_refused():
    assert _refuses(["powershell.exe", "-Command", "Get-NetFirewallRule"]) is not None


def test_powershell_naming_no_script_is_refused():
    assert _refuses(["pwsh", "-File"]) is not None


def test_the_other_refused_programs_stay_refused():
    assert _refuses(["podman", "ps"]) is not None
    assert _refuses(["ufw", "status"]) is not None


def test_the_temporary_directory_is_where_the_test_scripts_live(tmp_path):
    assert str(tmp_path).startswith(tempfile.gettempdir())
