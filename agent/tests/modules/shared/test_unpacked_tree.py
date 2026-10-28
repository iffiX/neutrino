"""A module's software from the hub, unpacked and sealed.

What these pin: a tarball and a zip land whole; an unknown kind and a
member outside the directory are refused; a sealed tree has no write bit
left; removing a sealed tree takes all of it; and an archive placed beside
what a directory holds replaces its namesakes and leaves the rest. A disk
image, against faked ``hdiutil`` and ``ditto`` on ``PATH``, is attached
read-only at a mount point of its own, its one folder copied out and sealed,
and detached also when the folder is missing; an installer's 7z archive
lands whole under the artifact's directory.
"""

import io
import os
import stat
import tarfile
import zipfile

import pytest

from neutrino_agent.modules.shared import unpacked_tree
from neutrino_agent.modules.shared.unpacked_tree import (
    extract_archive,
    remove_tree,
    seal_tree,
    unpack_beside,
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

    extract_archive(tarball, "tar_gz", str(tmp_path / "t"))
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


def test_an_artifacts_archive_lands_without_its_one_top_directory(tmp_path):
    archive = _tarball(
        tmp_path / "a.tar.gz",
        {"node-v22/bin/node": b"#!node", "node-v22/LICENSE": b"x"},
    )

    unpack_into(archive, "tar_gz", str(tmp_path / "cloudcli" / "node"))

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

    unpack_into(first, "tar_gz", target)
    assert sorted(os.listdir(target)) == ["codeg-server", "web"]
    unpack_into(second, "tar_gz", target)

    assert os.listdir(target) == ["codeg-server"]
    assert (tmp_path / "codeg" / "server" / "codeg-server").read_bytes() == b"2"


def test_a_broken_archive_leaves_the_directory_as_it_was(tmp_path):
    target = tmp_path / "demo" / "node"
    target.mkdir(parents=True)
    (target / "kept").write_text("x")
    junk = tmp_path / "junk.tar.gz"
    junk.write_bytes(b"not an archive")

    with pytest.raises(tarfile.TarError):
        unpack_into(str(junk), "tar_gz", str(target))

    assert (target / "kept").read_text() == "x"
    assert sorted(os.listdir(tmp_path / "demo")) == ["node"]


def test_removing_a_tree_gives_each_sealed_file_its_write_bit_first(
    tmp_path, monkeypatch
):
    """On Windows a file with no write bit is read-only and cannot be deleted:
    an uninstall of VS Code left its sealed ``code.exe`` and read
    ``uninstall_unconfirmed``."""
    tree = tmp_path / "vscode"
    (tree / "tokens").mkdir(parents=True)
    (tree / "code.exe").write_text("MZ")
    (tree / "tokens" / "lab.token").write_text("t")
    seal_tree(str(tree))
    seen = {}

    def rmtree(path, ignore_errors=False):
        for parent, _directories, files in os.walk(path):
            for name in files:
                full = os.path.join(parent, name)
                seen[name] = stat.S_IMODE(os.stat(full).st_mode) & stat.S_IWRITE
        real_rmtree(path, ignore_errors=ignore_errors)

    real_rmtree = unpacked_tree.shutil.rmtree
    monkeypatch.setattr(unpacked_tree.shutil, "rmtree", rmtree)

    remove_tree(str(tree))

    assert seen == {"code.exe": stat.S_IWRITE, "lab.token": stat.S_IWRITE}
    assert not tree.exists()


def test_a_sealed_file_placed_beside_is_given_its_write_bit_before_it_goes(
    tmp_path, monkeypatch
):
    module = tmp_path / "vscode"
    module.mkdir()
    (module / "code").write_text("old")
    os.chmod(module / "code", 0o555)
    archive = _tarball(tmp_path / "cli.tar.gz", {"code": b"#!new"})
    modes = []
    real_unseal = unpacked_tree._unseal_file

    def unseal(path):
        real_unseal(path)
        modes.append(stat.S_IMODE(os.stat(path).st_mode) & stat.S_IWRITE)

    monkeypatch.setattr(unpacked_tree, "_unseal_file", unseal)

    unpack_beside(archive, "tar_gz", str(module))

    assert modes == [stat.S_IWRITE]
    assert (module / "code").read_bytes() == b"#!new"


def test_an_archive_placed_beside_replaces_its_namesakes_and_keeps_the_rest(
    tmp_path,
):
    module = tmp_path / "vscode"
    (module / "tokens").mkdir(parents=True)
    (module / "tokens" / "lab.token").write_text("secret")
    (module / "code").write_text("old")
    archive = _tarball(tmp_path / "cli.tar.gz", {"code": b"#!new"})

    placed = unpack_beside(archive, "tar_gz", str(module))

    assert placed == [str(module / "code")]
    assert (module / "code").read_bytes() == b"#!new"
    assert stat.S_IMODE((module / "code").stat().st_mode) & 0o222 == 0
    assert (module / "tokens" / "lab.token").read_text() == "secret"
    assert stat.S_IMODE(module.stat().st_mode) == 0o755
    assert sorted(os.listdir(module)) == ["code", "tokens"]


def test_an_archive_placed_beside_drops_its_one_top_directory(tmp_path):
    with zipfile.ZipFile(tmp_path / "cli.zip", "w") as archive:
        archive.writestr("top/code.exe", "MZ")

    unpack_beside(str(tmp_path / "cli.zip"), "zip", str(tmp_path / "module"))

    assert os.listdir(tmp_path / "module") == ["code.exe"]


# --- a disk image and an installer ---

FAKE_HDIUTIL = """#!/bin/sh
echo "hdiutil $*" >> "$FAKE_LOG"
if [ "$1" = attach ]; then
    [ -n "$FAKE_ATTACH_FAILS" ] && { echo "hdiutil: attach failed - corrupt image" >&2; exit 1; }
    for last; do :; done
    mount=""
    while [ $# -gt 0 ]; do
        [ "$1" = -mountpoint ] && mount="$2"
        shift
    done
    cp -R "$FAKE_IMAGE/." "$mount/"
    exit 0
fi
if [ "$1" = detach ]; then
    rm -rf "$2"/*
    exit 0
fi
exit 2
"""
FAKE_DITTO = """#!/bin/sh
echo "ditto $*" >> "$FAKE_LOG"
mkdir -p "$2" && cp -R "$1/." "$2/"
"""


def _fake_image_tools(tmp_path, monkeypatch) -> str:
    """hdiutil and ditto on PATH, an image holding SiYuan's app layout; the log they write."""
    tools = tmp_path / "bin"
    tools.mkdir()
    for name, text in (("hdiutil", FAKE_HDIUTIL), ("ditto", FAKE_DITTO)):
        (tools / name).write_text(text)
        (tools / name).chmod(0o755)
    image = tmp_path / "image" / "SiYuan.app" / "Contents" / "Resources" / "kernel"
    image.mkdir(parents=True)
    (image / "SiYuan-Kernel").write_text("kernel")
    (image.parent / "stage").mkdir()
    log = tmp_path / "tools.log"
    monkeypatch.setenv("PATH", f"{tools}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_IMAGE", str(tmp_path / "image"))
    monkeypatch.setenv("FAKE_LOG", str(log))
    return str(log)


def test_a_disk_image_is_attached_read_only_and_its_folder_copied_out(
    tmp_path, monkeypatch
):
    log = _fake_image_tools(tmp_path, monkeypatch)
    dmg = tmp_path / "siyuan.dmg"
    dmg.write_bytes(b"image")
    target = tmp_path / "state" / "siyuan" / "app"

    unpack_into(str(dmg), "dmg", str(target), member="SiYuan.app/Contents/Resources")

    assert (target / "kernel" / "SiYuan-Kernel").read_text() == "kernel"
    assert (target / "stage").is_dir()
    assert (
        stat.S_IMODE(os.stat(target / "kernel" / "SiYuan-Kernel").st_mode) & 0o222 == 0
    )
    lines = open(log).read().splitlines()
    attach = lines[0].split()
    assert attach[:5] == ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint"]
    assert attach[6] == str(dmg)
    mount = attach[5]
    assert (
        lines[1] == f"ditto {mount}/SiYuan.app/Contents/Resources {lines[1].split()[2]}"
    )
    assert lines[2] == f"hdiutil detach {mount}"
    assert not os.path.exists(mount)


def test_an_image_without_the_folder_is_refused_and_detached(tmp_path, monkeypatch):
    log = _fake_image_tools(tmp_path, monkeypatch)
    dmg = tmp_path / "siyuan.dmg"
    dmg.write_bytes(b"image")

    with pytest.raises(ValueError, match="no folder Other.app"):
        extract_archive(str(dmg), "dmg", str(tmp_path / "out"), member="Other.app")

    assert open(log).read().splitlines()[-1].startswith("hdiutil detach ")


def test_an_image_that_does_not_attach_or_a_member_outside_is_refused(
    tmp_path, monkeypatch
):
    _fake_image_tools(tmp_path, monkeypatch)
    dmg = tmp_path / "siyuan.dmg"
    dmg.write_bytes(b"image")

    with pytest.raises(ValueError, match="outside"):
        extract_archive(str(dmg), "dmg", str(tmp_path / "out"), member="../x")
    monkeypatch.setenv("FAKE_ATTACH_FAILS", "1")
    with pytest.raises(ValueError, match="corrupt image"):
        extract_archive(str(dmg), "dmg", str(tmp_path / "out"), member="SiYuan.app")


def test_an_installer_lands_whole_under_the_artifacts_directory(tmp_path):
    archive = (
        os.path.dirname(__file__) + os.sep + "seven_zip_archives" + os.sep + "copy.7z"
    )
    installer = tmp_path / "siyuan-win.exe"
    installer.write_bytes(b"MZ" + b"\x00" * 600 + open(archive, "rb").read())
    target = tmp_path / "state" / "siyuan" / "app"

    unpack_into(str(installer), "nsis", str(target))

    assert (target / "top.txt").read_bytes() == b"top level\n"
    assert (target / "dir" / "sub" / "notes.md").exists()
    assert stat.S_IMODE(os.stat(target / "top.txt").st_mode) & 0o222 == 0
