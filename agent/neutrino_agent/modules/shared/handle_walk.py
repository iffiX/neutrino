"""Paths walked one folder at a time by open handle, following no link, on Linux and macOS.

Each level of a path is opened relative to the folder above it, with no
link followed: a link at any level stops the walk. What the agent does as root in a folder
it made or owns goes through these; what it does in an account's place
runs as the account (:mod:`account_files`). :func:`place_owner` tells the
two apart: the account that can change a path, or root. :func:`give_tree`
gives an entry only while the path its open descriptor names, read from the
descriptor itself, is inside the folder given.

Not pure: opens, makes and gives folders.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import errno
import os
import stat
import sys

# How each level is opened: a folder, no link followed.
WALK_DIR_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
# How a file is opened to give it away: no link followed and no wait on a
# pipe.
WALK_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
# The bits that let others than a folder's owner change what it holds.
SHARED_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH
# The buffer macOS writes an open descriptor's path into, ``MAXPATHLEN``.
GETPATH_BYTES = 1024


def _levels(path: str) -> list:
    """The names of an absolute path's levels below ``/``. Pure."""
    if not os.path.isabs(path):
        raise ValueError(f"{path} is not absolute")
    return [part for part in os.path.normpath(path).split(os.sep) if part]


def open_dir(path: str) -> int:
    """Open a folder by walking down from ``/``, following no link.

    Args:
        path: The absolute folder.

    Returns:
        An open descriptor of the folder; the caller closes it.

    Raises:
        OSError: When a level is missing, is a link or no folder
            (``ELOOP`` or ``ENOTDIR``).
    """
    descriptor = os.open("/", WALK_DIR_FLAGS)
    try:
        for name in _levels(path):
            below = os.open(name, WALK_DIR_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = below
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def make_dirs(path: str, mode: int, *, owner: tuple = ()) -> list:
    """Make a folder and each one missing above it, following no link.

    Args:
        path: The absolute folder.
        mode: The mode of each folder made.
        owner: ``(uid, gid)`` each folder made is given, on its open
            descriptor; empty keeps root's.

    Returns:
        The folders made, top down.

    Raises:
        OSError: When a level is a link or no folder (``ELOOP`` or
            ``ENOTDIR``), or a folder cannot be made or given.
    """
    made = []
    current = "/"
    descriptor = os.open("/", WALK_DIR_FLAGS)
    try:
        for name in _levels(path):
            current = os.path.join(current, name)
            try:
                below = os.open(name, WALK_DIR_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(name, mode, dir_fd=descriptor)
                below = os.open(name, WALK_DIR_FLAGS, dir_fd=descriptor)
                os.fchmod(below, mode)
                if owner:
                    os.fchown(below, owner[0], owner[1])
                made.append(current)
            os.close(descriptor)
            descriptor = below
    finally:
        os.close(descriptor)
    return made


def opened_path(descriptor: int) -> str:
    """The path an open descriptor names, read from the descriptor itself.

    Linux reads ``/proc/self/fd/<fd>``; macOS asks ``fcntl`` with
    ``F_GETPATH``.

    Args:
        descriptor: The open file or folder.

    Returns:
        The absolute path; empty when the system names none.
    """
    try:
        if sys.platform == "darwin":
            import fcntl

            held = fcntl.fcntl(descriptor, fcntl.F_GETPATH, bytes(GETPATH_BYTES))
            return os.fsdecode(held.split(b"\0", 1)[0])
        return os.readlink(f"/proc/self/fd/{descriptor}")
    except (OSError, AttributeError):
        return ""


def give_tree(path: str, uid: int, gid: int) -> list:
    """Give a folder and everything under it to an account, by open handle.

    Each entry is opened relative to its folder with no link followed and
    given on its descriptor; a link stays as it is, and a file that has a
    second name elsewhere is left. An entry whose descriptor names a path
    outside the one the folder's own descriptor names is left with what it
    holds. A folder is given after what it holds.

    Args:
        path: The absolute folder; nothing happens when it is not there or
            is a link.
        uid: The account's uid.
        gid: The account's group.

    Returns:
        The paths left because their descriptors named them outside the
        folder; the folder itself when its own descriptor names no path, and
        nothing is given.

    Raises:
        OSError: When an entry cannot be given.
    """
    try:
        descriptor = open_dir(path)
    except FileNotFoundError:
        return []
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            return []
        raise
    left: list = []
    try:
        top = opened_path(descriptor)
        if not top:
            return [path]
        _give_below(descriptor, uid, gid, top.rstrip(os.sep) + os.sep, left)
        os.fchown(descriptor, uid, gid)
    finally:
        os.close(descriptor)
    return left


def _give_below(descriptor: int, uid: int, gid: int, prefix: str, left: list) -> None:
    """Give what one open folder holds inside ``prefix``, each folder after its contents; add each entry outside it to ``left``."""
    for name in os.listdir(descriptor):
        try:
            status = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(status.st_mode):
            continue
        flags = WALK_DIR_FLAGS if stat.S_ISDIR(status.st_mode) else WALK_FILE_FLAGS
        if not (stat.S_ISDIR(status.st_mode) or stat.S_ISREG(status.st_mode)):
            continue
        try:
            held = os.open(name, flags, dir_fd=descriptor)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as error:
            if error.errno == errno.ELOOP:
                continue
            raise
        try:
            where = opened_path(held)
            if not where.startswith(prefix):
                left.append(where or name)
                continue
            opened = os.fstat(held)
            if stat.S_ISDIR(opened.st_mode):
                _give_below(held, uid, gid, prefix, left)
            elif not stat.S_ISREG(opened.st_mode) or opened.st_nlink > 1:
                continue
            os.fchown(held, uid, gid)
        finally:
            os.close(held)


def place_owner(path: str) -> "int | None":
    """Who can change what a path names: root, or the account that owns a level of it.

    The first level from ``/`` an account owns decides. A folder of root's
    that others may write without the sticky bit makes the path nobody's.

    Args:
        path: The absolute path; the levels that are missing are judged by
            the last one there.

    Returns:
        0 for root's place; the uid of the account whose place it is; None
        when a level is a link or a folder others may write.

    Raises:
        OSError: When a level cannot be read.
    """
    descriptor = os.open("/", WALK_DIR_FLAGS)
    try:
        status = os.fstat(descriptor)
        if _is_shared(status):
            return None
        for name in _levels(path):
            try:
                status = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                return 0
            if stat.S_ISLNK(status.st_mode):
                return None
            if status.st_uid != 0:
                return status.st_uid
            if not stat.S_ISDIR(status.st_mode):
                return 0
            if _is_shared(status):
                return None
            below = os.open(name, WALK_DIR_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = below
        return 0
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)


def _is_shared(status) -> bool:
    """Whether others than a folder's owner can replace what it holds. Pure."""
    return bool(status.st_mode & SHARED_WRITE_BITS) and not (
        status.st_mode & stat.S_ISVTX
    )
