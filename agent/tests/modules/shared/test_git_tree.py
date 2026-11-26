"""The git tree of a tag's archive: the tree hash git computes, and a changed archive refused.

What these pin: the tree computed over a tarball's members below its top
directory equals the tree git names for the commit the archive was made
from, links and files a person may run among them; a changed file, an
extra file and another mode give another tree; ``check_received`` accepts a
``git-tree:`` digest of a ``tar_gz`` only when its tree matches.
"""

import io
import os
import shutil
import subprocess
import tarfile

import pytest

from neutrino_agent.modules.shared.git_tree import archive_tree
from neutrino_agent.modules.shared.package import check_received

GIT = shutil.which("git")


def _repository(path):
    """A repository with one commit: files, a program, a link and a folder."""
    os.makedirs(path)
    (path / "main.py").write_text("print('comfy')\n")
    (path / "run.sh").write_text("#!/bin/sh\necho run\n")
    os.chmod(path / "run.sh", 0o755)
    os.makedirs(path / "comfy" / "inner")
    (path / "comfy" / "inner" / "nodes.py").write_text("NODES = []\n")
    (path / "comfy" / "a.txt").write_text("a\n")
    os.symlink("main.py", path / "link.py")
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    for argv in (
        ["init", "-q"],
        ["add", "-A"],
        ["commit", "-q", "-m", "one"],
    ):
        subprocess.run([GIT, *argv], cwd=path, check=True, env=environment)
    tree = subprocess.run(
        [GIT, "rev-parse", "HEAD^{tree}"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return tree


def _archive(repository, target):
    subprocess.run(
        [
            GIT,
            "archive",
            "--format=tar.gz",
            "--prefix=ComfyUI-1.0/",
            "-o",
            target,
            "HEAD",
        ],
        cwd=repository,
        check=True,
    )
    return str(target)


def _rewritten(source, target, change):
    """A copy of a tarball with one change made to its members."""
    with tarfile.open(source) as old, tarfile.open(target, "w:gz") as new:
        members = [(member, old.extractfile(member)) for member in old.getmembers()]
        for member, stream in members:
            data = stream.read() if stream is not None else None
            member, data = change(member, data)
            new.addfile(member, io.BytesIO(data) if data is not None else None)
        extra = getattr(change, "extra", None)
        if extra is not None:
            info = tarfile.TarInfo("ComfyUI-1.0/extra.py")
            info.size = len(extra)
            new.addfile(info, io.BytesIO(extra))
    return str(target)


@pytest.mark.skipif(GIT is None, reason="no git")
def test_the_tree_of_an_archive_is_the_tree_git_names(tmp_path):
    tree = _repository(tmp_path / "repo")
    archive = _archive(tmp_path / "repo", tmp_path / "tag.tar.gz")
    assert archive_tree(archive) == tree
    artifact = {"name": "source", "kind": "tar_gz", "digest": f"git-tree:{tree}"}
    assert check_received(artifact, {"path": archive, "sha256": "0" * 64}) is None


@pytest.mark.skipif(GIT is None, reason="no git")
def test_a_changed_file_an_extra_file_and_another_mode_are_refused(tmp_path):
    tree = _repository(tmp_path / "repo")
    archive = _archive(tmp_path / "repo", tmp_path / "tag.tar.gz")
    artifact = {"name": "source", "kind": "tar_gz", "digest": f"git-tree:{tree}"}

    def changed_file(member, data):
        if member.name.endswith("main.py"):
            data = b"print('other')\n"
            member.size = len(data)
        return member, data

    def another_mode(member, data):
        if member.name.endswith("a.txt"):
            member.mode = 0o755
        return member, data

    def same(member, data):
        return member, data

    same.extra = b"x = 1\n"
    for index, change in enumerate((changed_file, another_mode, same)):
        other = _rewritten(archive, tmp_path / f"other{index}.tar.gz", change)
        assert archive_tree(other) != tree
        refusal = check_received(artifact, {"path": other, "sha256": "0" * 64})
        assert refusal == {
            "code": "package_digest_mismatch",
            "params": {"artifact": "source"},
        }


def test_a_member_git_records_no_mode_of_is_refused(tmp_path):
    target = tmp_path / "fifo.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        info = tarfile.TarInfo("top/pipe")
        info.type = tarfile.FIFOTYPE
        archive.addfile(info)
    with pytest.raises(ValueError):
        archive_tree(str(target))
    artifact = {"name": "source", "kind": "tar_gz", "digest": "git-tree:" + "0" * 40}
    assert check_received(artifact, {"path": str(target), "sha256": ""}) is not None


def test_a_git_tree_digest_of_another_kind_is_refused(tmp_path):
    target = tmp_path / "plain.zip"
    target.write_bytes(b"PK")
    artifact = {"name": "source", "kind": "zip", "digest": "git-tree:" + "0" * 40}
    assert check_received(artifact, {"path": str(target), "sha256": ""}) is not None
