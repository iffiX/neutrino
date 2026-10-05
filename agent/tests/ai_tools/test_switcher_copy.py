"""The copy of cc-switch the agent keeps under its state root.

What these pin: the program's place on each system; a Windows copy comes
from the zip with ``cc-switch.exe`` at its top; a copy is replaced whole,
nothing of the old one left, with its version beside it; and a removed copy
is reported once.
"""

import os
import zipfile

import pytest

from neutrino_agent.ai_tools import switcher_copy


@pytest.mark.parametrize(
    "os_name, name",
    [("linux", "cc-switch"), ("darwin", "cc-switch"), ("windows", "cc-switch.exe")],
)
def test_the_program_is_in_bin_under_its_system_s_name(os_name, name):
    assert switcher_copy.binary_path("/state/ai_tools", os_name) == os.path.join(
        "/state/ai_tools", "bin", name
    )


def test_a_windows_copy_is_unpacked_from_the_zip_and_replaces_the_old_one(tmp_path):
    root = tmp_path / "ai_tools"
    old = root / "bin"
    old.mkdir(parents=True)
    (old / "stale").write_text("old")
    archive = tmp_path / "cc.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("cc-switch.exe", b"MZ cc-switch")
    opened: list = []

    path = switcher_copy.install_copy(
        str(archive),
        root=str(root),
        os_name="windows",
        version="5.10.4",
        open_to_accounts=opened.append,
    )

    assert path == str(root / "bin" / "cc-switch.exe")
    assert sorted(os.listdir(root / "bin")) == ["cc-switch.exe", "version"]
    assert switcher_copy.installed_version(str(root)) == "5.10.4"
    assert opened == [str(root / "bin")]
    assert [name for name in os.listdir(root) if name.startswith(".")] == []


def test_a_removed_copy_is_reported_once(tmp_path):
    (tmp_path / "bin").mkdir()

    assert switcher_copy.remove_copy(str(tmp_path)) == [str(tmp_path / "bin")]
    assert switcher_copy.remove_copy(str(tmp_path)) == []
    assert switcher_copy.installed_version(str(tmp_path)) == ""
