"""The suite's guard: no test starts a program that reads or changes the machine.

What these pin: the firewalls, the network tools, the service and package
managers, Podman and the rest of the refused programs are refused by name,
by path and as a shell line; PowerShell runs only a script under the
temporary directory; a fake of a refused name a test put under the
temporary directory runs; a refused program never starts, through
``subprocess`` or ``os.system``, and fails the test even when the code under
test swallowed the refusal; and any other program still runs.
"""

import os
import subprocess
import sys

import pytest

from tests.conftest import REFUSED_PROGRAMS, _refuses


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
        ["systemctl", "disable", "--now", "podman.socket"],
        ["/usr/bin/podman", "--version"],
        ["sudo", "true"],
        "pkexec true",
        ["/nonexistent/podman", "exec", "web"],
    ],
)
def test_the_refused_programs_are_refused(command):
    assert _refuses(command)


def test_powershell_runs_a_script_a_test_wrote_under_the_temporary_directory(
    tmp_path,
):
    assert _refuses(["pwsh", "-NoProfile", "-File", str(tmp_path / "x.ps1")]) is None


def test_a_fake_of_a_refused_name_under_the_temporary_directory_runs(tmp_path):
    fake = tmp_path / "systemctl"
    fake.write_text("#!/bin/sh\necho fake\n")
    fake.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}/usr/bin:/bin"}

    assert _refuses([str(fake), "stop", "x"]) is None
    done = subprocess.run(
        ["systemctl", "stop", "x"], capture_output=True, text=True, env=environment
    )

    assert done.stdout == "fake\n"


def test_a_refused_program_never_starts_and_fails_the_test(
    _no_test_reaches_the_machine,
):
    with pytest.raises(pytest.fail.Exception) as refused:
        subprocess.run(["ufw", "status"], capture_output=True)

    assert "would start ['ufw', 'status']" in str(refused.value)
    assert len(_no_test_reaches_the_machine) == 1
    _no_test_reaches_the_machine.clear()


def test_a_refusal_the_code_under_test_swallows_still_fails_the_test(
    _no_test_reaches_the_machine,
):
    try:
        subprocess.run(["systemctl", "--version"], capture_output=True)
    except BaseException:  # noqa: BLE001 - the code under test's own catch
        pass

    assert len(_no_test_reaches_the_machine) == 1
    _no_test_reaches_the_machine.clear()


def test_os_system_is_guarded_too(_no_test_reaches_the_machine):
    with pytest.raises(pytest.fail.Exception):
        os.system("podman --version")

    assert len(_no_test_reaches_the_machine) == 1
    _no_test_reaches_the_machine.clear()


def test_any_other_program_still_runs():
    done = subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True)

    assert done.stdout.strip() == b"1"


def test_the_list_holds_what_changes_the_machine_or_asks_to():
    assert {
        "systemctl",
        "podman",
        "sudo",
        "pkexec",
        "nft",
        "ufw",
        "ip",
        "virsh",
        "useradd",
        "loginctl",
        "apt",
        "dnf",
    } <= REFUSED_PROGRAMS
