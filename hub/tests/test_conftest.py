"""The suite's guards: PowerShell runs only a script a test wrote under the
temporary directory, and every other refused program stays refused.

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
import sys
import tempfile
from pathlib import Path

import pytest

from tests.conftest import _is_test_owned, _refuses

# A path under a missing folder outside the temporary folders. Without the
# guard every change to it fails, so a broken guard changes nothing.
HERE = os.path.realpath(os.path.dirname(__file__))
OUTSIDE = os.path.join(HERE, "no_such_folder", "probe")


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
