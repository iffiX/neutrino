"""A module's software from the hub, unpacked under the module's own directory.

The archive comes down a package stream, a tarball or a zip as its
publisher ships it, a macOS disk image whose one folder is copied out of it
while it is attached read-only, or a Windows NSIS installer whose 7z archive
the agent reads itself. It is unpacked whole into a directory, refusing any
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

import contextlib
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile

from neutrino_agent.constants import (
    AGENT_ARTIFACT_KIND_DMG,
    AGENT_ARTIFACT_KIND_NSIS,
    AGENT_ARTIFACT_KIND_TAR_GZ,
    AGENT_ARTIFACT_KIND_ZIP,
)
from neutrino_agent.modules.shared.seven_zip import extract_embedded

# How long attaching, copying out of and detaching a disk image may take.
DMG_STEP_TIMEOUT_S = 600


def extract_archive(path: str, kind: str, directory: str, *, member: str = "") -> None:
    """Unpack an archive whole into a directory, refusing a path outside it.

    Args:
        path: The archive on disk.
        kind: ``tar_gz``, ``zip``, ``dmg`` or ``nsis``.
        directory: Where it is unpacked.
        member: The folder a ``dmg`` holds the program in, relative to the
            image's root; unread for the other kinds.

    Raises:
        ValueError: For an unknown kind, a member outside the directory, an
            image that does not attach or holds no such folder, or an
            installer whose archive does not read.
        tarfile.TarError: When a tarball cannot be read.
        zipfile.BadZipFile: When a zip cannot be read.
        OSError: When the directory cannot be written or a tool cannot run.
    """
    if kind == AGENT_ARTIFACT_KIND_NSIS:
        extract_embedded(path, directory)
        return
    if kind == AGENT_ARTIFACT_KIND_DMG:
        copy_out_of_image(path, member, directory)
        return
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


def copy_out_of_image(path: str, member: str, directory: str) -> None:
    """Copy one folder out of a macOS disk image attached read-only.

    The image is attached at a mount point of its own with ``hdiutil
    attach -nobrowse -readonly``, the folder's contents are copied with
    ``ditto``, and the image is detached whatever happened.

    Args:
        path: The disk image.
        member: The folder, relative to the image's root.
        directory: Where its contents go.

    Raises:
        ValueError: For a member outside the image, an image that does not
            attach, or a copy that fails.
        OSError: When a tool cannot run.
    """
    parts = [part for part in member.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise ValueError(f"the image's folder {member!r} is outside it")
    mount = tempfile.mkdtemp(prefix="neutrino_dmg_")
    try:
        _run_image_tool(
            ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mount, path]
        )
        try:
            source = os.path.join(mount, *parts)
            if not os.path.isdir(source):
                raise ValueError(f"the image holds no folder {member}")
            _run_image_tool(["ditto", source, directory])
        finally:
            with contextlib.suppress(ValueError, OSError):
                _run_image_tool(["hdiutil", "detach", mount])
    finally:
        with contextlib.suppress(OSError):
            os.rmdir(mount)


def unpack_into(path: str, kind: str, directory: str, *, member: str = "") -> None:
    """Unpack an artifact's archive under its directory and seal it.

    An archive whose members all sit under one top directory is unpacked
    without it, so the artifact's files sit directly under the directory;
    one with files at its top is unpacked as it is. What the directory
    held before is replaced.

    Args:
        path: The archive on disk.
        kind: ``tar_gz``, ``zip``, ``dmg`` or ``nsis``.
        directory: The artifact's directory.
        member: The folder a ``dmg`` holds the program in.

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
        source = _unpacked_top(path, kind, staging, member)
        remove_tree(directory)
        os.replace(source, directory)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    seal_tree(directory)


def unpack_beside(path: str, kind: str, directory: str, *, member: str = "") -> list:
    """Unpack an archive's files directly into a directory, each sealed.

    The archive's single top directory is dropped as :func:`unpack_into`
    drops it. Each file or directory it holds replaces its namesake in the
    directory, and everything else the directory holds stays.

    Args:
        path: The archive on disk.
        kind: ``tar_gz``, ``zip``, ``dmg`` or ``nsis``.
        directory: The module's directory, made readable by every account.
        member: The folder a ``dmg`` holds the program in.

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
        source = _unpacked_top(path, kind, staging, member)
        for name in sorted(os.listdir(source)):
            target = os.path.join(directory, name)
            if os.path.isdir(target) and not os.path.islink(target):
                remove_tree(target)
            elif os.path.lexists(target):
                _unseal_file(target)
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


def _unpacked_top(path: str, kind: str, staging: str, member: str = "") -> str:
    """Unpack into staging and answer where the archive's files sit there."""
    extract_archive(path, kind, staging, member=member)
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

    On Windows a file with no write bit has the read-only attribute and
    cannot be deleted, so each file gets its owner's write bit back first.

    Args:
        path: The tree's root; nothing happens when it is not there.
    """
    for parent, directories, files in os.walk(path):
        for name in directories:
            child = os.path.join(parent, name)
            if not os.path.islink(child):
                os.chmod(child, stat.S_IMODE(os.stat(child).st_mode) | 0o700)
        for name in files:
            _unseal_file(os.path.join(parent, name))
    if os.path.isdir(path) and not os.path.islink(path):
        os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | 0o700)
    shutil.rmtree(path, ignore_errors=True)


def _unseal_file(path: str) -> None:
    """Give one file its owner's write bit back, which clears Windows' read-only attribute."""
    if os.path.islink(path):
        return
    with contextlib.suppress(OSError):
        os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | stat.S_IWRITE)


def _check_member(name: str, directory: str) -> None:
    """Refuse an archive member that would land outside the directory."""
    root = os.path.realpath(directory)
    target = os.path.realpath(os.path.join(directory, name))
    if target != root and not target.startswith(root + os.sep):
        raise ValueError(f"the archive names a path outside it: {name}")


def _run_image_tool(command: list) -> None:
    """Run one of macOS's disk image tools; a failure is a ValueError with its last words.

    Raises:
        ValueError: When the tool exits other than 0 or does not finish.
        OSError: When it cannot run.
    """
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=DMG_STEP_TIMEOUT_S
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"{command[0]} did not finish") from error
    if result.returncode != 0:
        said = (result.stderr or result.stdout or "").strip()[-200:]
        raise ValueError(
            f"{command[0]} {command[1]} failed: {said or result.returncode}"
        )
