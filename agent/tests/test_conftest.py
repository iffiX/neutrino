"""The suite's guard: no test starts a firewall or a network tool of the machine.

What these pin: ufw, firewalld's tools, nft, iptables, netsh and ``ip`` are
refused by name, by path and as a shell line; PowerShell runs only a script
under the temporary directory; a refused program never starts; and any
other program still runs.
"""

import subprocess
import sys

import pytest

from tests.conftest import _refuses


@pytest.mark.parametrize(
    "command",
    [
        ["ufw", "status"],
        ["/usr/sbin/firewall-cmd", "--state"],
        ["firewall-offline-cmd", "--list-all"],
        ["nft", "list", "ruleset"],
        ["iptables", "-S"],
        ["ip6tables", "-S"],
        ["netsh", "advfirewall", "show", "allprofiles"],
        ["ip", "-j", "-4", "addr"],
        "ufw status",
        ["pwsh", "-Command", "Get-NetFirewallRule"],
        ["powershell.exe", "-File", "C:\\agent\\host.ps1"],
    ],
)
def test_the_firewalls_and_the_network_tools_are_refused(command):
    assert _refuses(command)


def test_powershell_runs_a_script_a_test_wrote_under_the_temporary_directory(
    tmp_path,
):
    assert _refuses(["pwsh", "-NoProfile", "-File", str(tmp_path / "x.ps1")]) is None


def test_a_refused_program_never_starts():
    with pytest.raises(AssertionError):
        subprocess.run(["ufw", "status"], capture_output=True)


def test_any_other_program_still_runs():
    done = subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True)

    assert done.stdout.strip() == b"1"
