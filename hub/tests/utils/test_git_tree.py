"""The tree hash of a tag's archive, as git computes it over the tag commit's files.

What these pin: an archive under one top directory hashes to the tree git
wrote for the same files, links, executables and a file sorting before a
folder of its name among them; the same files compressed again hash the
same; a changed file, an extra file and another mode change the hash; a
member git records no mode for and a file that is no tarball are refused;
and a ``git-tree:`` digest reads as its 40 hex characters and checks a file
through the fetcher's helpers.
"""

import gzip
import io
import tarfile

import pytest

from neutrino_hub.utils.git_tree import is_git_tree, tar_gz_tree_hex
from neutrino_hub.utils.source_fetch import file_hex, hex_of

# The tree ``git write-tree`` gave a repository holding these files.
FILES = {
    "a.txt": (b"hello\n", 0o664),
    "bin/run.sh": (b"#!/bin/sh\necho run\n", 0o775),
    "sub/deep/x": (b"x", 0o664),
    "sub.txt": (b"y", 0o664),
}
LINKS = {"link": "a.txt"}
TREE = "3f6bb043d8ea526bc36a433782343c6c1561d700"  # scan: allow


def archive(path, files=None, links=None, *, top="pkg-1.0", level=9, extra=()):
    """A gzip tarball of the files under one top directory, as a host makes one."""
    held = io.BytesIO()
    with tarfile.open(fileobj=held, mode="w", format=tarfile.PAX_FORMAT) as tar:
        tar.pax_headers = {"comment": "a" * 40}
        folder = tarfile.TarInfo(top)
        folder.type = tarfile.DIRTYPE
        folder.mode = 0o775
        tar.addfile(folder)
        for name, (body, mode) in (files if files is not None else FILES).items():
            member = tarfile.TarInfo(f"{top}/{name}")
            member.size = len(body)
            member.mode = mode
            tar.addfile(member, io.BytesIO(body))
        for name, target in (links if links is not None else LINKS).items():
            member = tarfile.TarInfo(f"{top}/{name}")
            member.type = tarfile.SYMTYPE
            member.linkname = target
            member.mode = 0o777
            tar.addfile(member)
        for member in extra:
            tar.addfile(member)
    path.write_bytes(gzip.compress(held.getvalue(), compresslevel=level))
    return path


def test_an_archive_hashes_to_the_tree_git_wrote_for_its_files(tmp_path):
    assert tar_gz_tree_hex(archive(tmp_path / "a.tar.gz")) == TREE


def test_the_same_files_compressed_again_hash_the_same(tmp_path):
    again = archive(tmp_path / "b.tar.gz", level=1)

    assert tar_gz_tree_hex(again) == TREE
    assert again.read_bytes() != archive(tmp_path / "a.tar.gz").read_bytes()


@pytest.mark.parametrize(
    "files",
    [
        {**FILES, "a.txt": (b"changed\n", 0o664)},
        {**FILES, "extra.txt": (b"", 0o664)},
        {**FILES, "a.txt": (b"hello\n", 0o775)},
    ],
)
def test_a_changed_file_an_extra_file_or_another_mode_changes_the_hash(tmp_path, files):
    assert tar_gz_tree_hex(archive(tmp_path / "a.tar.gz", files)) != TREE


def special(name: str, **fields) -> tarfile.TarInfo:
    member = tarfile.TarInfo(f"pkg-1.0/{name}")
    for key, value in fields.items():
        setattr(member, key, value)
    return member


@pytest.mark.parametrize(
    "member",
    [
        special("hard", type=tarfile.LNKTYPE, linkname="pkg-1.0/a.txt"),
        special("fifo", type=tarfile.FIFOTYPE),
        special("device", type=tarfile.CHRTYPE),
    ],
)
def test_a_member_git_records_no_mode_for_is_refused(tmp_path, member):
    path = archive(tmp_path / "a.tar.gz", extra=[member])

    with pytest.raises(ValueError):
        tar_gz_tree_hex(path)


def test_a_setuid_file_is_refused(tmp_path):
    files = {**FILES, "bin/run.sh": (b"#!/bin/sh\n", 0o4775)}

    with pytest.raises(ValueError):
        tar_gz_tree_hex(archive(tmp_path / "a.tar.gz", files))


def test_a_file_that_is_no_tarball_is_refused(tmp_path):
    path = tmp_path / "page.html"
    path.write_bytes(b"<html>not found</html>")

    with pytest.raises(ValueError):
        tar_gz_tree_hex(path)


def test_a_git_tree_digest_reads_as_its_hex_and_checks_a_file(tmp_path):
    digest = f"git-tree:{TREE}"
    path = archive(tmp_path / "a.tar.gz")
    page = tmp_path / "page.html"
    page.write_bytes(b"<html></html>")

    assert is_git_tree(digest) and not is_git_tree("sha256:" + "a" * 64)
    assert hex_of(digest) == TREE
    assert file_hex(path, digest) == TREE
    assert file_hex(page, digest) == ""
    with pytest.raises(ValueError):
        hex_of("git-tree:" + "a" * 39)
