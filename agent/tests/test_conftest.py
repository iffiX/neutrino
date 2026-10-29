"""The suite's guards: no test starts a program that reads or changes the
machine, and no test changes a file outside its temporary folders.

What these pin: the firewalls, the network tools, the service and package
managers, Podman and the rest of the refused programs are refused by name,
by path and as a shell line; PowerShell runs only a script under the
temporary directory; a fake of a refused name a test put under the
temporary directory runs; a refused program never starts, through
``subprocess`` or ``os.system``, and fails the test even when the code under
test swallowed the refusal; and any other program still runs.

The file guard: a write, a creation, a rename, a removal and a Unix
socket's bind outside the temporary folders fail the test naming the path
and the test, even when swallowed. A change under ``tmp_path`` or the
system's temporary folder, a read, the null device and a bytecode cache
pass. A removed link is checked in its folder, a write through a link at its
target, and a name under a folder descriptor in that folder.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tests.conftest import REFUSED_PROGRAMS, _is_test_owned, _refuses

# A path under a missing folder outside the temporary folders. Without the
# guard every change to it fails, so a broken guard changes nothing.
HERE = os.path.realpath(os.path.dirname(__file__))
OUTSIDE = os.path.join(HERE, "no_such_folder", "probe")


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


def bind(path: str) -> None:
    """Bind a Unix socket at a path."""
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(path)


# Each change to a path outside, given that path and a file under tmp_path.
CHANGES = [
    pytest.param(lambda outside, inside: open(outside, "w"), id="open to write"),
    pytest.param(lambda outside, inside: open(outside, "a"), id="open to append"),
    pytest.param(
        lambda outside, inside: os.open(outside, os.O_WRONLY | os.O_CREAT),
        id="os.open to create",
    ),
    pytest.param(lambda outside, inside: Path(outside).write_text("x"), id="write"),
    pytest.param(lambda outside, inside: Path(outside).touch(), id="touch"),
    pytest.param(lambda outside, inside: os.mkdir(outside), id="mkdir"),
    pytest.param(lambda outside, inside: os.remove(outside), id="remove"),
    pytest.param(lambda outside, inside: os.rmdir(outside), id="rmdir"),
    pytest.param(lambda outside, inside: os.chmod(outside, 0o600), id="chmod"),
    pytest.param(lambda outside, inside: os.truncate(outside, 0), id="truncate"),
    pytest.param(lambda outside, inside: shutil.rmtree(outside), id="rmtree"),
    pytest.param(lambda outside, inside: os.rename(inside, outside), id="rename"),
    pytest.param(lambda outside, inside: os.replace(outside, inside), id="replace"),
    pytest.param(lambda outside, inside: shutil.move(inside, outside), id="move"),
    pytest.param(
        lambda outside, inside: shutil.copyfile(inside, outside), id="copyfile"
    ),
    pytest.param(lambda outside, inside: os.symlink(inside, outside), id="symlink"),
    pytest.param(lambda outside, inside: bind(outside), id="bind"),
]


@pytest.mark.parametrize("change", CHANGES)
def test_a_change_outside_the_temporary_folders_fails_the_test(
    change, tmp_path, _no_test_changes_a_file_of_the_machine
):
    inside = tmp_path / "inside"
    inside.write_text("x")

    with pytest.raises(pytest.fail.Exception) as refused:
        change(OUTSIDE, str(inside))

    assert f"would change {OUTSIDE} on this machine" in str(refused.value)
    assert "test_conftest.py::test_a_change_outside" in str(refused.value)
    assert _no_test_changes_a_file_of_the_machine == [OUTSIDE]
    _no_test_changes_a_file_of_the_machine.clear()


def test_a_change_the_code_under_test_swallows_still_fails_the_test(
    _no_test_changes_a_file_of_the_machine,
):
    try:
        open(OUTSIDE, "w")
    except BaseException:  # noqa: BLE001 - the code under test's own catch
        pass

    assert _no_test_changes_a_file_of_the_machine == [OUTSIDE]
    _no_test_changes_a_file_of_the_machine.clear()


def test_a_change_under_the_temporary_folders_passes(
    tmp_path, _no_test_changes_a_file_of_the_machine
):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a").write_text("x")
    os.replace(folder / "a", folder / "b")
    shutil.copyfile(folder / "b", folder / "c")
    os.remove(folder / "c")
    shutil.rmtree(folder)
    handle, name = tempfile.mkstemp()
    os.close(handle)
    os.remove(name)

    assert _no_test_changes_a_file_of_the_machine == []


def test_a_read_the_null_device_and_a_bytecode_cache_pass(
    _no_test_changes_a_file_of_the_machine,
):
    with open(__file__) as source:
        source.read(1)
    os.close(os.open(os.devnull, os.O_RDWR))

    assert _is_test_owned(os.path.join(HERE, "__pycache__", "x.cpython-39.pyc"))
    assert _no_test_changes_a_file_of_the_machine == []


def test_a_removed_link_is_checked_in_its_folder(
    tmp_path, _no_test_changes_a_file_of_the_machine
):
    os.symlink(sys.executable, tmp_path / "python")
    tree = tmp_path / "tree"
    tree.mkdir()
    os.symlink(sys.executable, tree / "python")

    os.remove(tmp_path / "python")
    shutil.rmtree(tree)

    assert _no_test_changes_a_file_of_the_machine == []


def test_a_write_through_a_link_is_checked_at_its_target(
    tmp_path, _no_test_changes_a_file_of_the_machine
):
    os.symlink(OUTSIDE, tmp_path / "link")

    with pytest.raises(pytest.fail.Exception):
        open(tmp_path / "link", "w")

    assert _no_test_changes_a_file_of_the_machine == [OUTSIDE]
    _no_test_changes_a_file_of_the_machine.clear()


@pytest.mark.skipif(
    not os.path.isdir("/proc/self/fd"), reason="a folder descriptor is read in /proc"
)
def test_a_name_under_a_folder_descriptor_is_checked_in_that_folder(
    tmp_path, _no_test_changes_a_file_of_the_machine
):
    inside = os.open(tmp_path, os.O_RDONLY)
    outside = os.open(HERE, os.O_RDONLY)
    try:
        os.mkdir("made", dir_fd=inside)
        with pytest.raises(pytest.fail.Exception):
            os.rmdir("no_such_folder", dir_fd=outside)
    finally:
        os.close(inside)
        os.close(outside)

    assert (tmp_path / "made").is_dir()
    assert _no_test_changes_a_file_of_the_machine == [
        os.path.join(HERE, "no_such_folder")
    ]
    _no_test_changes_a_file_of_the_machine.clear()
