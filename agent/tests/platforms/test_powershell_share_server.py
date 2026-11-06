"""The PowerShell host's file share operations against a stopped server, run in PowerShell where there is one.

What these pin: while ``LanmanServer`` is stopped no read asks the server for
a share or a session, since Windows starts a stopped server of Manual start
type for such a read; while it runs the reads ask, and an apply that serves
reads whatever the server is. The sweep is a call of its own, and reads the
server's shares on the same terms. A share whose name a share of the person's
has is left off with ``share_name_taken`` and every other share is made.
"""

import json
import os
import shutil
import subprocess

import pytest

from neutrino_agent.platforms.powershell_host import library_path

pwsh = shutil.which("pwsh")

# Stands in for the server's cmdlets: the service reads FAKE_SERVER, and each
# read of a share or a session is a line in FAKE_ASKED.
SHARE_STAND_INS = """
function Get-Service {
    param($Name, $ErrorAction)
    return [pscustomobject]@{ Status = $env:FAKE_SERVER; StartType = 'Manual'; DependentServices = @() }
}
function Get-SmbShare {
    [CmdletBinding()]
    param([string]$Name)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value "share $Name"
}
function Get-SmbSession {
    [CmdletBinding()]
    param()
    Add-Content -LiteralPath $env:FAKE_ASKED -Value 'session'
}
function Start-Service { param($Name) }
function Get-LocalUser { param($Name, $ErrorAction) }
function Get-NetFirewallRule { param($Name, $ErrorAction) }
function Test-Path { param($Path, $LiteralPath) return $true }
function New-ItemProperty { param($Path, $Name, $Value, $PropertyType, [switch]$Force) }
"""

STATUS = {"op": "share_status", "args": {"marker": "neutrino", "accounts": []}}
APPLY = {
    "op": "share_apply",
    "args": {
        "marker": "neutrino",
        "owned_shares": ["old"],
        "owned_accounts": [],
        "users": [],
        "retired_accounts": [],
        "removed_shares": ["old"],
        "shares": [{"name": "new", "path": "C:\\new", "accounts": []}],
        "retired_rule_name": "fence",
        "share_owner": "Everyone",
        "is_served": False,
        "server_dependents": [],
    },
}
SWEEP = {
    "op": "share_sweep",
    "args": {
        "marker": "neutrino",
        "user_prefix": "neutrino-",
        "is_served": False,
        "earlier_accounts": [],
    },
}
WITHDRAW = {
    "op": "share_withdraw",
    "args": {
        "marker": "neutrino",
        "owned_shares": ["old"],
        "owned_accounts": [],
        "is_removed": True,
    },
}


# A running server holding the person's own share ``taken``; each share made
# is a line in FAKE_ASKED.
PERSONS_SHARE_STAND_INS = """
function Get-SmbShare {
    [CmdletBinding()]
    param([string]$Name)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value "share $Name"
    if ($Name -eq 'taken') {
        return [pscustomobject]@{ Name = 'taken'; Path = 'C:\\theirs'; Description = 'their own' }
    }
}
function New-SmbShare {
    param($Name, $Path, $Description, $FullAccess, $ChangeAccess, $ReadAccess)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value "made $Name"
}
"""
TAKEN = {
    "op": "share_apply",
    "args": {
        **APPLY["args"],
        "owned_shares": [],
        "removed_shares": [],
        "shares": [
            {
                "name": name,
                "path": f"C:\\{name}",
                "description": "neutrino",
                "accounts": [],
                "share_right": "Change",
            }
            for name in ("TAKEN", "free")
        ],
        "is_served": True,
    },
}


def asked_of(tmp_path, request: dict, *, server: str, stand_ins: str = "") -> tuple:
    """Ask the library's own loop one request.

    Returns:
        The answer, and the reads it asked the server for.
    """
    if pwsh is None:
        pytest.skip("PowerShell is not installed")
    driver = tmp_path / "driver.ps1"
    driver.write_text(f"{SHARE_STAND_INS}\n{stand_ins}\n. '{library_path()}'\n")
    asked = tmp_path / "asked"
    done = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
        input=json.dumps({"id": 1, **request}) + "\n",
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "FAKE_ASKED": str(asked),
            "FAKE_SERVER": server,
        },
        timeout=60,
    )
    answer = json.loads(done.stdout.strip().splitlines()[-1])
    reads = asked.read_text().splitlines() if asked.exists() else []
    return answer, reads


def test_the_status_of_a_stopped_server_reads_stopped_and_asks_the_server_nothing(
    tmp_path,
):
    answer, reads = asked_of(tmp_path, STATUS, server="Stopped")

    assert answer["ok"] is True
    assert answer["value"]["is_present"] is True
    assert answer["value"]["is_running"] is False
    assert reads == []


def test_the_status_of_a_running_server_asks_for_its_shares_and_sessions(tmp_path):
    answer, reads = asked_of(tmp_path, STATUS, server="Running")

    assert answer["value"]["is_running"] is True
    assert reads == ["share ", "session"]


def test_an_apply_that_serves_nothing_asks_a_stopped_server_nothing(tmp_path):
    answer, reads = asked_of(tmp_path, APPLY, server="Stopped")

    assert answer["ok"] is True
    assert reads == []


def test_an_apply_that_serves_nothing_asks_a_running_server(tmp_path):
    """The apply asks for its own shares by name; the listing is the sweep's."""
    answer, reads = asked_of(tmp_path, APPLY, server="Running")

    assert answer["ok"] is True
    assert reads == ["share new", "share old"]


def test_a_sweep_that_serves_nothing_asks_a_stopped_server_nothing(tmp_path):
    answer, reads = asked_of(tmp_path, SWEEP, server="Stopped")

    assert answer["ok"] is True
    assert reads == []


def test_a_sweep_lists_a_running_server_s_shares(tmp_path):
    answer, reads = asked_of(tmp_path, SWEEP, server="Running")

    assert answer["ok"] is True
    assert reads == ["share "]


def test_a_withdrawal_asks_a_stopped_server_nothing(tmp_path):
    answer, reads = asked_of(tmp_path, WITHDRAW, server="Stopped")

    assert answer["ok"] is True
    assert reads == []


def test_a_withdrawal_asks_a_running_server(tmp_path):
    answer, reads = asked_of(tmp_path, WITHDRAW, server="Running")

    assert answer["ok"] is True
    assert reads == ["share old"]


def test_a_share_named_like_one_of_the_persons_is_left_off_and_the_rest_made(
    tmp_path,
):
    answer, reads = asked_of(
        tmp_path, TAKEN, server="Running", stand_ins=PERSONS_SHARE_STAND_INS
    )

    assert answer["ok"] is True
    assert answer["value"]["refused"] == [{"name": "TAKEN", "code": "share_name_taken"}]
    assert "made free" in reads
    assert "made TAKEN" not in reads
