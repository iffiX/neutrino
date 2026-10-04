"""A module's software from the hub, unpacked under the module's own directory.

The archive comes down a package stream, a tarball or a zip as its
publisher ships it. It is unpacked whole into a directory, refusing any
member that would land outside it, then sealed: owned by the agent's own
account with every write bit taken away, so every account may read and run
it and none may change it.

Not pure: writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import shutil
import stat
import tarfile
import zipfile

from neutrino_agent.constants import AGENT_PACKAGE_KIND_TAR, AGENT_PACKAGE_KIND_ZIP


def extract_archive(path: str, package_kind: str, directory: str) -> None:
    """Unpack an archive whole into a directory, refusing a path outside it.

    Args:
        path: The archive on disk.
        package_kind: ``tar`` or ``zip``.
        directory: Where it is unpacked.

    Raises:
        ValueError: For an unknown kind or a member outside the directory.
        tarfile.TarError: When a tarball cannot be read.
        zipfile.BadZipFile: When a zip cannot be read.
        OSError: When the directory cannot be written.
    """
    if package_kind == AGENT_PACKAGE_KIND_TAR:
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
    elif package_kind == AGENT_PACKAGE_KIND_ZIP:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                _check_member(name, directory)
            archive.extractall(directory)
    else:
        raise ValueError(f"unknown package kind {package_kind!r}")


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
