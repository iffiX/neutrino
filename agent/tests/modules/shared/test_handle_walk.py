"""Paths walked one folder at a time by open descriptor, following no link.

What these pin: a folder opens through every real level and a link at any
level stops the walk ``ELOOP``; missing folders are made with their mode,
the last given an owner on its descriptor, and a link on the way makes
nothing beyond it; a tree is given folder after contents, a link and a file
with a second name left, and a link at the top gives nothing; who can
change a path is the first level an account owns, root where every level is
root's, and nobody where a level is a link or a folder others may write
without the sticky bit.
"""

import errno
import os
import stat

import pytest

from neutrino_agent.modules.shared import handle_walk
from neutrino_agent.modules.shared.handle_walk import (
    give_tree,
    make_dirs,
    open_dir,
    place_owner,
)

from tests.conftest import chowned_path


def test_a_folder_opens_through_real_levels_and_a_link_stops_the_walk(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "link").symlink_to(tmp_path / "a")

    descriptor = open_dir(str(tmp_path / "a" / "b"))
    os.close(descriptor)

    with pytest.raises(OSError) as refused:
        open_dir(str(tmp_path / "link" / "b"))
    assert refused.value.errno in (errno.ELOOP, errno.ENOTDIR)


def test_missing_folders_are_made_with_their_mode_and_a_link_makes_nothing(
    tmp_path,
):
    made = make_dirs(str(tmp_path / "x" / "y"), 0o750)

    assert made == [str(tmp_path / "x"), str(tmp_path / "x" / "y")]
    assert stat.S_IMODE((tmp_path / "x" / "y").stat().st_mode) == 0o750
    assert make_dirs(str(tmp_path / "x" / "y"), 0o750) == []

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "link").symlink_to(elsewhere)
    with pytest.raises(OSError):
        make_dirs(str(tmp_path / "link" / "made"), 0o700)
    assert os.listdir(elsewhere) == []


def test_a_tree_is_given_folder_after_contents_leaving_links_and_second_names(
    tmp_path, monkeypatch
):
    given = []
    monkeypatch.setattr(
        os,
        "fchown",
        lambda descriptor, uid, gid: given.append(chowned_path(descriptor)),
    )
    root = tmp_path / "data"
    (root / "repo").mkdir(parents=True)
    (root / "repo" / "file").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("root's")
    (root / "link").symlink_to(outside)
    os.link(outside / "secret", root / "second")

    give_tree(str(root), 1001, 1001)

    assert given.index(str(root / "repo" / "file")) < given.index(str(root / "repo"))
    assert given[-1] == str(root)
    assert str(outside) not in given
    assert str(root / "second") not in given
    assert str(outside / "secret") not in given


def test_a_folder_moved_out_after_its_open_is_left_with_what_it_holds(
    tmp_path, monkeypatch
):
    """The account owns the folders it can move out between the listing and
    the open; the descriptor's own path shows where the folder now is."""
    given = []
    monkeypatch.setattr(
        os,
        "fchown",
        lambda descriptor, uid, gid: given.append(chowned_path(descriptor)),
    )
    root = tmp_path / "data"
    (root / "moved" / "inner").mkdir(parents=True)
    (root / "moved" / "inner" / "file").write_text("x")
    (root / "kept").mkdir()
    outside = tmp_path / "elsewhere"
    real_open = os.open

    def open_then_move(name, flags, mode=0o777, *, dir_fd=None):
        held = real_open(name, flags, mode, dir_fd=dir_fd)
        if name == "moved" and dir_fd is not None:
            os.rename(root / "moved", outside)
        return held

    monkeypatch.setattr(os, "open", open_then_move)

    left = give_tree(str(root), 1001, 1001)

    assert left == [str(outside)]
    assert given == [str(root / "kept"), str(root)]


def test_a_folder_moved_out_while_its_contents_are_walked_stops_its_walk(
    tmp_path, monkeypatch
):
    """Once the folder itself is elsewhere, nothing more of it is given and
    one path is named."""
    given = []
    monkeypatch.setattr(
        os,
        "fchown",
        lambda descriptor, uid, gid: given.append(chowned_path(descriptor)),
    )
    root = tmp_path / "data"
    for index in range(3):
        (root / "moved" / f"d{index}").mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    real_open = os.open
    opened = []

    def open_then_move(name, flags, mode=0o777, *, dir_fd=None):
        held = real_open(name, flags, mode, dir_fd=dir_fd)
        if name.startswith("d") and dir_fd is not None:
            opened.append(name)
            if len(opened) == 2:
                os.rename(root / "moved", outside)
        return held

    monkeypatch.setattr(os, "open", open_then_move)

    left = give_tree(str(root), 1001, 1001)

    assert left == [str(outside)]
    assert len(opened) == 2
    assert str(outside) not in given
    assert [path for path in given if path.startswith(str(outside))] == []
    assert given[-1] == str(root)


def test_a_link_at_the_top_of_a_tree_gives_nothing(tmp_path, monkeypatch):
    given = []
    monkeypatch.setattr(os, "fchown", lambda *args: given.append(args))
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "data").symlink_to(target)

    give_tree(str(tmp_path / "data"), 1001, 1001)
    give_tree(str(tmp_path / "missing"), 1001, 1001)

    assert given == []


class _Status:
    def __init__(self, found, uid, mode=None):
        self.st_uid = uid
        self.st_mode = found.st_mode if mode is None else mode


def owners_seen(monkeypatch, owners: dict, modes: dict = None):
    """Make ``os.stat`` through a folder descriptor and ``os.fstat`` read the owner and mode named by path."""
    modes = modes or {}
    real_stat = os.stat
    real_fstat = os.fstat

    def seen(path, found):
        uid = owners.get(path, 0)
        return _Status(found, uid, modes.get(path))

    def stat_at(name, *, dir_fd=None, follow_symlinks=True):
        found = real_stat(name, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        folder = chowned_path(dir_fd) if dir_fd is not None else ""
        return seen(os.path.join(folder, name), found)

    def fstat(descriptor):
        return seen(chowned_path(descriptor), real_fstat(descriptor))

    monkeypatch.setattr(handle_walk.os, "stat", stat_at)
    monkeypatch.setattr(handle_walk.os, "fstat", fstat)


def test_the_first_level_an_account_owns_decides_whose_place_it_is(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    (home / "ann" / "share").mkdir(parents=True)
    for level in (home, home / "ann", home / "ann" / "share"):
        os.chmod(level, 0o755)
    owners_seen(monkeypatch, {str(home / "ann"): 1001, str(home / "ann" / "share"): 0})

    assert place_owner(str(home / "ann" / "share" / "missing")) == 1001
    assert place_owner(str(home / "other")) == 0


def test_a_link_or_a_folder_others_may_write_is_nobodys_place(tmp_path, monkeypatch):
    (tmp_path / "shared" / "x").mkdir(parents=True)
    (tmp_path / "sticky" / "y").mkdir(parents=True)
    os.chmod(tmp_path / "sticky" / "y", 0o755)
    (tmp_path / "link").symlink_to(tmp_path / "shared")
    owners_seen(
        monkeypatch,
        {},
        {
            str(tmp_path / "shared"): stat.S_IFDIR | 0o777,
            str(tmp_path / "sticky"): stat.S_IFDIR | stat.S_ISVTX | 0o777,
        },
    )

    assert place_owner(str(tmp_path / "shared" / "x")) is None
    assert place_owner(str(tmp_path / "link" / "x")) is None
    assert place_owner(str(tmp_path / "sticky" / "y")) == 0
