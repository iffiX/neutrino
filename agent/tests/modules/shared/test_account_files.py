"""Files in an account's places, each touched as that account.

What these pin: on Linux and macOS every step is a ``/bin/sh`` the
platform's step-down starts as the account, here run as the test's own
user and recorded: a read gives the bytes or None for a missing file, a
write lands whole with its mode and leaves no staged file, a write in
place keeps the inode, a folder is made with each missing one above it
under the umask asked and says whether it was made, a tree and an empty
folder go, a file's end comes with its size, a folder's names come back,
and an account the machine lacks or a step that fails is an ``OSError``;
on Windows each step runs on a thread acting as the account, with its
login, and a write there lands whole too.
"""

import os
import stat

import pytest

from neutrino_agent.modules.shared.account_files import (
    READ_SHELL,
    WRITE_SHELL,
    AccountFiles,
)


class Platform:
    """A machine whose accounts' commands run as the test's own user, each recorded."""

    def __init__(self, os_name="linux"):
        self.os_name = os_name
        self.asked: list = []

    def account_process(self, account, argv):
        if account == "ghost":
            raise KeyError(account)
        self.asked.append((account, list(argv)))
        return list(argv), {}

    def as_account(self, account, step, *arguments, password=""):
        self.asked.append((account, step.__name__, password))
        return step(*arguments)


def files_of(os_name="linux", account="ann", password="") -> AccountFiles:
    return AccountFiles(platform=Platform(os_name), account=account, password=password)


def test_a_read_runs_as_the_account_and_gives_none_for_a_missing_file(tmp_path):
    files = files_of()
    path = tmp_path / "settings"
    path.write_bytes(b"one\x00two")

    assert files.read(str(path)) == b"one\x00two"
    assert files.read(str(tmp_path / "missing")) is None
    assert files._platform.asked[0] == (
        "ann",
        ["/bin/sh", "-c", READ_SHELL, str(path)],
    )


def test_a_write_lands_whole_with_its_mode_and_leaves_no_staged_file(tmp_path):
    files = files_of()
    path = tmp_path / "made" / "below" / "settings"

    files.write(str(path), b"text\n", 0o640)

    assert path.read_bytes() == b"text\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert not (tmp_path / "made" / "below" / "settings.new").exists()
    assert files._platform.asked == [
        ("ann", ["/bin/sh", "-c", WRITE_SHELL, str(path), "640"])
    ]


def test_a_write_in_place_keeps_the_inode(tmp_path):
    files = files_of()
    path = tmp_path / ".bashrc"
    path.write_text("old\n")
    inode = path.stat().st_ino

    files.write_in_place(str(path), b"new\n")

    assert path.read_text() == "new\n"
    assert path.stat().st_ino == inode


def test_a_folder_is_made_with_those_above_it_under_the_umask_asked(tmp_path):
    files = files_of()
    path = tmp_path / "a" / "b" / "c"

    assert files.make_dir(str(path)) is True
    assert files.make_dir(str(path)) is False
    assert files.make_dir(str(tmp_path / "shared"), umask=0o022) is True

    for level in (tmp_path / "a", tmp_path / "a" / "b", path):
        assert stat.S_IMODE(level.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "shared").stat().st_mode) == 0o755


def test_a_file_a_tree_and_empty_folders_go(tmp_path):
    files = files_of()
    (tmp_path / "tree" / "deep").mkdir(parents=True)
    (tmp_path / "tree" / "deep" / "file").write_text("x")
    (tmp_path / "one").write_text("x")
    (tmp_path / "e1" / "e2").mkdir(parents=True)

    files.remove(str(tmp_path / "one"))
    files.remove(str(tmp_path / "one"))
    files.remove_tree(str(tmp_path / "tree"))
    files.remove_empty_dirs([str(tmp_path / "e1" / "e2"), str(tmp_path / "e1")])

    assert sorted(os.listdir(tmp_path)) == []


def test_a_files_end_comes_with_its_size_and_a_folders_names(tmp_path):
    files = files_of()
    path = tmp_path / "log"
    path.write_bytes(b"0123456789")

    assert files.read_tail(str(path), 4) == (10, b"6789")
    assert files.read_tail(str(tmp_path / "missing"), 4) is None
    assert sorted(files.names(str(tmp_path))) == ["log"]
    assert files.names(str(tmp_path / "missing")) is None
    assert files.existing([str(path), str(tmp_path / "missing")]) == [str(path)]


def test_an_account_the_machine_lacks_or_a_failed_step_is_an_oserror(tmp_path):
    (tmp_path / "file").write_text("x")

    with pytest.raises(OSError, match="no account ghost"):
        files_of(account="ghost").read(str(tmp_path / "x"))
    with pytest.raises(OSError, match="could not make"):
        files_of().make_dir(str(tmp_path / "file" / "below"))


def test_on_windows_each_step_runs_acting_as_the_account_with_its_login(tmp_path):
    files = files_of("windows", password="pw")  # scan: allow
    path = str(tmp_path / "data" / "settings")

    assert files.make_dir(str(tmp_path / "data")) is True
    files.write(path, b"text")
    assert files.read(path) == b"text"
    files.remove(path)
    assert files.read(path) is None

    assert [step for _account, step, _password in files._platform.asked] == [
        "_step_make_dir",
        "_step_write",
        "_step_read",
        "_step_remove",
        "_step_read",
    ]
    assert {password for *_rest, password in files._platform.asked} == {"pw"}
    assert not os.path.exists(path + ".new")
    with pytest.raises(OSError):
        files.run(["true"])
