"""A module's software from the hub, unpacked and sealed.

What these pin: a tarball and a zip land whole; an unknown kind and a
member outside the directory are refused; a sealed tree has no write bit
left; and removing a sealed tree takes all of it.
"""

import io
import os
import stat
import tarfile
import zipfile

import pytest

from neutrino_agent.modules.shared.unpacked_tree import (
    extract_archive,
    remove_tree,
    seal_tree,
    unpack_into,
)


def _tarball(path, members: dict) -> str:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
    return str(path)


def test_a_tarball_and_a_zip_land_whole(tmp_path):
    tarball = _tarball(tmp_path / "a.tar.gz", {"top/bin/run": b"#!/bin/sh\n"})
    with zipfile.ZipFile(tmp_path / "b.zip", "w") as archive:
        archive.writestr("top/file.txt", "z")

    extract_archive(tarball, "tar", str(tmp_path / "t"))
    extract_archive(str(tmp_path / "b.zip"), "zip", str(tmp_path / "z"))

    assert (tmp_path / "t" / "top" / "bin" / "run").read_bytes() == b"#!/bin/sh\n"
    assert (tmp_path / "z" / "top" / "file.txt").read_text() == "z"


def test_an_unknown_kind_and_a_member_outside_are_refused(tmp_path):
    with zipfile.ZipFile(tmp_path / "bad.zip", "w") as archive:
        archive.writestr("../escape.txt", "x")

    with pytest.raises(ValueError):
        extract_archive(str(tmp_path / "bad.zip"), "rar", str(tmp_path / "x"))
    with pytest.raises(ValueError):
        extract_archive(str(tmp_path / "bad.zip"), "zip", str(tmp_path / "x"))
    assert not (tmp_path / "escape.txt").exists()


def test_a_sealed_tree_has_no_write_bit_and_removing_it_takes_all(tmp_path):
    tree = tmp_path / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "file").write_text("x")

    seal_tree(str(tree))
    modes = [
        stat.S_IMODE(os.stat(os.path.join(parent, name)).st_mode)
        for parent, directories, files in os.walk(tree)
        for name in [*directories, *files]
    ]

    assert all(mode & 0o222 == 0 for mode in modes)
    assert stat.S_IMODE(tree.stat().st_mode) == 0o555
    remove_tree(str(tree))
    assert not tree.exists()


def test_a_components_archive_lands_without_its_one_top_directory(tmp_path):
    archive = _tarball(
        tmp_path / "a.tar.gz",
        {"node-v22/bin/node": b"#!node", "node-v22/LICENSE": b"x"},
    )

    unpack_into(archive, "tar", str(tmp_path / "cloudcli" / "node"))

    node = tmp_path / "cloudcli" / "node"
    assert sorted(os.listdir(node)) == ["LICENSE", "bin"]
    assert (node / "bin" / "node").read_bytes() == b"#!node"
    assert stat.S_IMODE(node.stat().st_mode) == 0o555
    assert stat.S_IMODE((node / "bin" / "node").stat().st_mode) & 0o222 == 0
    assert sorted(os.listdir(tmp_path / "cloudcli")) == ["node"]


def test_an_archive_with_files_at_its_top_lands_as_it_is_and_replaces_what_was_there(
    tmp_path,
):
    first = _tarball(
        tmp_path / "a.tar.gz", {"codeg-server": b"1", "web/index.html": b"<html>"}
    )
    second = _tarball(tmp_path / "b.tar.gz", {"codeg-server": b"2"})
    target = str(tmp_path / "codeg" / "server")

    unpack_into(first, "tar", target)
    assert sorted(os.listdir(target)) == ["codeg-server", "web"]
    unpack_into(second, "tar", target)

    assert os.listdir(target) == ["codeg-server"]
    assert (tmp_path / "codeg" / "server" / "codeg-server").read_bytes() == b"2"


def test_a_broken_archive_leaves_the_directory_as_it_was(tmp_path):
    target = tmp_path / "demo" / "node"
    target.mkdir(parents=True)
    (target / "kept").write_text("x")
    junk = tmp_path / "junk.tar.gz"
    junk.write_bytes(b"not an archive")

    with pytest.raises(tarfile.TarError):
        unpack_into(str(junk), "tar", str(target))

    assert (target / "kept").read_text() == "x"
    assert sorted(os.listdir(tmp_path / "demo")) == ["node"]
