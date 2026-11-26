"""The shared folders' access entries on Linux, written as POSIX access lists on open descriptors.

The default account passes through the data directory with ``--x``, lists
``data/`` with ``r-x``, writes ``models/``, ``input/`` and ``output/`` with
``rwx`` beside the service's account, and reads ``user/`` and
``custom_nodes/`` with ``r-x``. Each folder of a write or read folder takes
the same entries as a default entry, so a new file takes them in place of
the umask. Every file and folder under those five is written again: a file
with read and write, and execute where its owner has it, in a write folder,
and with read alone in a read folder. Each level is opened by descriptor
with no link followed; a link keeps its own entries. An access list is the
kernel's ``system.posix_acl_access`` and ``system.posix_acl_default``
attributes, written on the open descriptor, and one that is already right
is not written.

Not pure: opens folders and files and writes their attributes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import errno
import os
import stat
import struct

from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_READ_FOLDERS,
    COMFYUI_WRITE_FOLDERS,
)
from neutrino_agent.modules.shared.handle_walk import (
    WALK_DIR_FLAGS,
    WALK_FILE_FLAGS,
    open_dir,
)

# The kernel's attributes of an access list and of a folder's default list,
# their version, and each entry's tag.
ACCESS_ATTRIBUTE = "system.posix_acl_access"
DEFAULT_ATTRIBUTE = "system.posix_acl_default"
ACL_VERSION = 2
TAG_USER_OBJ = 0x01
TAG_USER = 0x02
TAG_GROUP_OBJ = 0x04
TAG_MASK = 0x10
TAG_OTHER = 0x20
UNDEFINED_ID = 0xFFFFFFFF
# The permissions of an entry.
READ = 4
WRITE = 2
EXECUTE = 1
ALL = READ | WRITE | EXECUTE
# What a folder made in a shared folder gives its owner, its group and the
# others in place of the umask.
DEFAULT_OWNER = ALL
DEFAULT_GROUP = READ | EXECUTE
DEFAULT_OTHER = 0


def encode(owner: int, group: int, other: int, named: dict) -> bytes:
    """One access list as the kernel's attribute holds it. Pure.

    Args:
        owner: The owner's permissions.
        group: The owning group's permissions.
        other: Everyone else's.
        named: uid to its permissions.

    Returns:
        The attribute's bytes: the version, then each entry in the order
        the kernel keeps, the mask the union of the named entries and the
        group's.
    """
    entries = [(TAG_USER_OBJ, owner, UNDEFINED_ID)]
    entries += [(TAG_USER, named[uid], uid) for uid in sorted(named)]
    entries.append((TAG_GROUP_OBJ, group, UNDEFINED_ID))
    if named:
        mask = group
        for permissions in named.values():
            mask |= permissions
        entries.append((TAG_MASK, mask, UNDEFINED_ID))
    entries.append((TAG_OTHER, other, UNDEFINED_ID))
    return struct.pack("<I", ACL_VERSION) + b"".join(
        struct.pack("<HHI", tag, permissions, uid) for tag, permissions, uid in entries
    )


def mode_parts(mode: int) -> tuple:
    """The owner's, the group's and the others' permissions in a mode. Pure."""
    return (mode >> 6) & ALL, (mode >> 3) & ALL, mode & ALL


def file_permissions(mode: int, is_written: bool) -> int:
    """What a named account gets on one file of a shared folder. Pure.

    Args:
        mode: The file's mode.
        is_written: Whether the folder is one the account writes.

    Returns:
        Read, write where the folder is written, and execute where the
        owner has it.
    """
    permissions = READ | (WRITE if is_written else 0)
    if mode & stat.S_IXUSR:
        permissions |= EXECUTE
    return permissions


class LinuxFolderAccess:
    """Writes the default account's entries on ComfyUI's shared folders."""

    def __init__(self, *, data_dir: str, base_dir: str, service_uid: int):
        """
        Args:
            data_dir: The data directory, the service's account's.
            base_dir: ``data/`` in it.
            service_uid: The service's account's uid.
        """
        self._data_dir = data_dir
        self._base_dir = base_dir
        self._service_uid = service_uid

    def write(self, account_uid: "int | None") -> list:
        """Write every entry for the default account, or none while there is none.

        Args:
            account_uid: The default account's uid; None names no account.

        Returns:
            The paths left as they are because they could not be opened,
            below the data directory.

        Raises:
            OSError: When the data directory or ``data/`` cannot be opened
                or written.
        """
        named_pass = {account_uid: EXECUTE} if account_uid is not None else {}
        named_list = {account_uid: READ | EXECUTE} if account_uid is not None else {}
        top = open_dir(self._data_dir)
        try:
            self._write_folder(top, named_pass, default=None)
        finally:
            os.close(top)
        base = open_dir(self._base_dir)
        left: list = []
        try:
            self._write_folder(base, named_list, default=None)
            for name in COMFYUI_WRITE_FOLDERS + COMFYUI_READ_FOLDERS:
                is_written = name in COMFYUI_WRITE_FOLDERS
                try:
                    folder = os.open(name, WALK_DIR_FLAGS, dir_fd=base)
                except OSError:
                    left.append(os.path.join(self._base_dir, name))
                    continue
                try:
                    self._write_tree(
                        folder,
                        os.path.join(self._base_dir, name),
                        account_uid,
                        is_written,
                        left,
                    )
                finally:
                    os.close(folder)
        finally:
            os.close(base)
        return left

    def _named(self, account_uid, permissions: int, is_written: bool) -> dict:
        """The named entries of one entry of a shared folder."""
        named = {}
        if is_written:
            named[self._service_uid] = permissions
        if account_uid is not None:
            named[account_uid] = (
                permissions if is_written else permissions & ~WRITE
            ) or READ
        return named

    def _write_tree(
        self, folder: int, path: str, account_uid, is_written: bool, left: list
    ) -> None:
        """Write one folder's entries and every file and folder under it."""
        folder_rights = ALL if is_written else READ | EXECUTE
        named = self._named(account_uid, folder_rights, is_written)
        self._write_folder(folder, named, default=named)
        with os.scandir(folder) as entries:
            names = [
                (entry.name, entry.is_dir(follow_symlinks=False))
                for entry in entries
                if not entry.is_symlink()
            ]
        for name, is_folder in names:
            flags = WALK_DIR_FLAGS if is_folder else WALK_FILE_FLAGS
            try:
                descriptor = os.open(name, flags, dir_fd=folder)
            except OSError:
                left.append(os.path.join(path, name))
                continue
            try:
                if is_folder:
                    self._write_tree(
                        descriptor,
                        os.path.join(path, name),
                        account_uid,
                        is_written,
                        left,
                    )
                    continue
                status = os.fstat(descriptor)
                if not stat.S_ISREG(status.st_mode):
                    continue
                rights = file_permissions(status.st_mode, is_written)
                self._write_one(
                    descriptor,
                    ACCESS_ATTRIBUTE,
                    self._list(
                        status.st_mode, self._named(account_uid, rights, is_written)
                    ),
                )
            finally:
                os.close(descriptor)

    def _write_folder(self, folder: int, named: dict, *, default) -> None:
        """Write one folder's access list, and its default list when one is named."""
        mode = os.fstat(folder).st_mode
        self._write_one(folder, ACCESS_ATTRIBUTE, self._list(mode, named))
        if default is not None:
            self._write_one(
                folder,
                DEFAULT_ATTRIBUTE,
                encode(DEFAULT_OWNER, DEFAULT_GROUP, DEFAULT_OTHER, default),
            )

    @staticmethod
    def _list(mode: int, named: dict) -> bytes:
        """The access list of one entry: its own mode's parts and the named entries."""
        owner, group, other = mode_parts(mode)
        return encode(owner, group, other, named)

    @staticmethod
    def _write_one(descriptor: int, attribute: str, value: bytes) -> None:
        """Write one attribute on an open descriptor unless it already holds the value."""
        held = b""
        with contextlib.suppress(OSError):
            held = os.getxattr(descriptor, attribute)
        if held == value:
            return
        try:
            os.setxattr(descriptor, attribute, value)
        except OSError as error:
            if error.errno in (errno.ENOTSUP, errno.EOPNOTSUPP):
                raise OSError(error.errno, "the file system keeps no access list")
            raise
