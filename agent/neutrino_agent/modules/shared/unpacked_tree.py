"""A module's software from the hub, unpacked under the module's own directory.

The archive comes down a package stream, a tarball or a zip as its
publisher ships it. It is unpacked whole into a directory, refusing any
member that would land outside it, then sealed: owned by the agent's own
account with every write bit taken away, so every account may read and run
it and none may change it. An artifact's archive lands under the artifact's
own directory, without the one top directory its publisher may have wrapped
it in; an artifact that names no directory puts its files directly in the
module's directory, beside what else is there.

Not pure: writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import shutil
import stat
import tarfile
import tempfile
import zipfile

from neutrino_agent.constants import (
    AGENT_ARTIFACT_KIND_TAR_GZ,
    AGENT_ARTIFACT_KIND_ZIP,
)


def extract_archive(path: str, kind: str, directory: str) -> None:
    """Unpack an archive whole into a directory, refusing a path outside it.

    Args:
        path: The archive on disk.
        kind: ``tar_gz`` or ``zip``.
        directory: Where it is unpacked.

    Raises:
        ValueError: For an unknown kind or a member outside the directory.
        tarfile.TarError: When a tarball cannot be read.
        zipfile.BadZipFile: When a zip cannot be read.
        OSError: When the directory cannot be written.
    """
    if kind == AGENT_ARTIFACT_KIND_TAR_GZ:
        with tarfile.open(path, "r:*") as archive:
            if hasattr(tarfile, "data_filter"):
                archive.extractall(directory, filter="data")
                return
            for member in archive.getmembers():
                _check_member(member.name, directory)
                if member.issym() or member.islnk():
                    _check_member(
                        os.path.join(os.path.dirname(member.name), member.linkname),
                        directory,
                    )
            archive.extractall(directory)
    elif kind == AGENT_ARTIFACT_KIND_ZIP:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                _check_member(name, directory)
            archive.extractall(directory)
    else:
        raise ValueError(f"unknown archive kind {kind!r}")


def unpack_into(path: str, kind: str, directory: str) -> None:
    """Unpack an artifact's archive under its directory and seal it.

    An archive whose members all sit under one top directory is unpacked
    without it, so the artifact's files sit directly under the directory;
    one with files at its top is unpacked as it is. What the directory
    held before is replaced.

    Args:
        path: The archive on disk.
        kind: ``tar_gz`` or ``zip``.
        directory: The artifact's directory.

    Raises:
        ValueError: For an unknown kind or a member outside the directory.
        tarfile.TarError: When a tarball cannot be read.
        zipfile.BadZipFile: When a zip cannot be read.
        OSError: When the directory cannot be written.
    """
    parent = os.path.dirname(directory) or "."
    os.makedirs(parent, mode=0o755, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".unpack_", dir=parent)
    try:
        source = _unpacked_top(path, kind, staging)
        remove_tree(directory)
        os.replace(source, directory)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    seal_tree(directory)


def unpack_beside(path: str, kind: str, directory: str) -> list:
    """Unpack an archive's files directly into a directory, each sealed.

    The archive's single top directory is dropped as :func:`unpack_into`
    drops it. Each file or directory it holds replaces its namesake in the
    directory, and everything else the directory holds stays.

    Args:
        path: The archive on disk.
        kind: ``tar_gz`` or ``zip``.
        directory: The module's directory, made readable by every account.

    Returns:
        The paths placed, in name order.

    Raises:
        ValueError: For an unknown kind or a member outside the directory.
        tarfile.TarError: When a tarball cannot be read.
        zipfile.BadZipFile: When a zip cannot be read.
        OSError: When the directory cannot be written.
    """
    os.makedirs(directory, mode=0o755, exist_ok=True)
    os.chmod(directory, 0o755)
    staging = tempfile.mkdtemp(prefix=".unpack_", dir=directory)
    placed = []
    try:
        source = _unpacked_top(path, kind, staging)
        for name in sorted(os.listdir(source)):
            target = os.path.join(directory, name)
            if os.path.isdir(target) and not os.path.islink(target):
                remove_tree(target)
            elif os.path.lexists(target):
                os.unlink(target)
            os.replace(os.path.join(source, name), target)
            placed.append(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    for target in placed:
        if os.path.isdir(target) and not os.path.islink(target):
            seal_tree(target)
        else:
            _seal_file(target)
    return placed


def _unpacked_top(path: str, kind: str, staging: str) -> str:
    """Unpack into staging and answer where the archive's files sit there."""
    extract_archive(path, kind, staging)
    names = os.listdir(staging)
    if len(names) == 1:
        top = os.path.join(staging, names[0])
        if os.path.isdir(top) and not os.path.islink(top):
            return top
    return staging


def _seal_file(path: str) -> None:
    """Make one file the agent's own account's and take away its write bits."""
    if os.path.islink(path):
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        os.chown(path, 0, 0)
    os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) & ~0o222)


def seal_tree(directory: str) -> None:
    """Make a tree the agent's own account's and take away every write bit.

    Args:
        directory: The tree's root.

    Raises:
        OSError: When an owner or a mode cannot be changed.
    """
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    for parent, directories, files in os.walk(directory):
        for name in [*directories, *files]:
            path = os.path.join(parent, name)
            if os.path.islink(path):
                if is_root:
                    os.lchown(path, 0, 0)
                continue
            if is_root:
                os.chown(path, 0, 0)
            mode = stat.S_IMODE(os.stat(path).st_mode)
            os.chmod(path, mode & ~0o222)
    if is_root:
        os.chown(directory, 0, 0)
    os.chmod(directory, 0o555)


def remove_tree(path: str) -> None:
    """Delete a tree, giving its owner the write bits sealing took first.

    Args:
        path: The tree's root; nothing happens when it is not there.
    """
    for parent, directories, _files in os.walk(path):
        for name in directories:
            child = os.path.join(parent, name)
            if not os.path.islink(child):
                os.chmod(child, stat.S_IMODE(os.stat(child).st_mode) | 0o700)
    if os.path.isdir(path) and not os.path.islink(path):
        os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | 0o700)
    shutil.rmtree(path, ignore_errors=True)


def _check_member(name: str, directory: str) -> None:
    """Refuse an archive member that would land outside the directory."""
    root = os.path.realpath(directory)
    target = os.path.realpath(os.path.join(directory, name))
    if target != root and not target.startswith(root + os.sep):
        raise ValueError(f"the archive names a path outside it: {name}")
