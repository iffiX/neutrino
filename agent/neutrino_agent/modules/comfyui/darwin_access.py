"""The shared folders' access entries on macOS, written as extended access lists on open descriptors.

The default account searches the data directory, lists and searches
``data/``, and takes an inherited entry on each write and read folder: on
``models/``, ``input/`` and ``output/`` beside the service's account,
allowing ``list``, ``add_file``, ``search``, ``delete``,
``add_subdirectory``, ``delete_child``, ``readattr``, ``writeattr``,
``readextattr``, ``writeextattr`` and ``readsecurity``; on ``user/`` and
``custom_nodes/`` allowing ``list``, ``search``, ``readattr``,
``readextattr`` and ``readsecurity``. Every file and folder under those
five takes the same entries again. Each level is opened by descriptor with
no link followed, and the list is set with ``acl_set_fd`` from its text,
each account named by its UUID.

Not pure: opens folders and files and sets their access lists.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import ctypes.util
import os
import stat

from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_READ_FOLDERS,
    COMFYUI_WRITE_FOLDERS,
)
from neutrino_agent.modules.shared.handle_walk import (
    WALK_DIR_FLAGS,
    WALK_FILE_FLAGS,
    open_dir,
)

# The permissions of each entry, by what it allows.
FOLDER_WRITE = (
    "list,add_file,search,delete,add_subdirectory,delete_child,"
    "readattr,writeattr,readextattr,writeextattr,readsecurity"
)
FOLDER_READ = "list,search,readattr,readextattr,readsecurity"
FILE_WRITE = (
    "read,write,append,delete,readattr,writeattr,readextattr,writeextattr,readsecurity"
)
FILE_READ = "read,readattr,readextattr,readsecurity"
PASS_THROUGH = "search"
LIST_THROUGH = "list,search"
INHERITED = ",file_inherit,directory_inherit"


def acl_text(entries: list) -> str:
    """An access list's text, as ``acl_from_text`` reads it. Pure.

    Args:
        entries: ``[(uuid, name, uid, flags, permissions)]``, ``flags``
            empty or :data:`INHERITED`.

    Returns:
        The text: its header line, then one line per entry.
    """
    lines = ["!#acl 1"]
    lines += [
        f"user:{uuid}:{name}:{uid}:allow{flags}:{permissions}"
        for uuid, name, uid, flags, permissions in entries
    ]
    return "\n".join(lines) + "\n"


def file_rights(mode: int, is_written: bool) -> str:
    """What an account is allowed on one file of a shared folder. Pure."""
    rights = FILE_WRITE if is_written else FILE_READ
    if mode & stat.S_IXUSR:
        rights += ",execute"
    return rights


class DarwinAcl:
    """libSystem's access list calls, bound once."""

    def __init__(self):
        library = ctypes.CDLL(ctypes.util.find_library("System") or "libSystem.dylib")
        self._from_text = library.acl_from_text
        self._from_text.restype = ctypes.c_void_p
        self._from_text.argtypes = [ctypes.c_char_p]
        self._set_fd = library.acl_set_fd
        self._set_fd.argtypes = [ctypes.c_int, ctypes.c_void_p]
        self._free = library.acl_free
        self._free.argtypes = [ctypes.c_void_p]
        self._uid_to_uuid = library.mbr_uid_to_uuid
        self._uid_to_uuid.argtypes = [ctypes.c_uint32, ctypes.c_char_p]

    def uuid_of(self, uid: int) -> str:
        """An account's UUID, as an access list's text names it.

        Raises:
            OSError: When the system names none.
        """
        buffer = ctypes.create_string_buffer(16)
        if self._uid_to_uuid(uid, buffer) != 0:
            raise OSError(f"no UUID for uid {uid}")
        hexed = buffer.raw.hex().upper()
        return "-".join(
            (hexed[0:8], hexed[8:12], hexed[12:16], hexed[16:20], hexed[20:32])
        )

    def set_fd(self, descriptor: int, text: str) -> None:
        """Set one open descriptor's access list from its text.

        Raises:
            OSError: When the text does not read or the list is refused.
        """
        acl = self._from_text(text.encode("utf-8"))
        if not acl:
            raise OSError(ctypes.get_errno(), "the access list does not read")
        try:
            if self._set_fd(descriptor, acl) != 0:
                raise OSError(ctypes.get_errno(), "the access list was refused")
        finally:
            self._free(acl)


class DarwinFolderAccess:
    """Writes the default account's entries on ComfyUI's shared folders."""

    def __init__(
        self,
        *,
        data_dir: str,
        base_dir: str,
        service: tuple,
        acl=None,
    ):
        """
        Args:
            data_dir: The data directory, the service's account's.
            base_dir: ``data/`` in it.
            service: The service's account's ``(name, uid)``.
            acl: libSystem's calls, as :class:`DarwinAcl`; None binds them.
        """
        self._data_dir = data_dir
        self._base_dir = base_dir
        self._service = service
        self._acl = acl

    def write(self, account: "tuple | None") -> list:
        """Write every entry for the default account, or none while there is none.

        Args:
            account: The default account's ``(name, uid)``; None names none.

        Returns:
            The paths left as they are.

        Raises:
            OSError: When a top folder cannot be opened or its list set.
        """
        acl = self._bound()
        names = {}
        for held in (self._service, account):
            if held is not None:
                names[held[1]] = (acl.uuid_of(held[1]), held[0], held[1])
        user = names.get(account[1]) if account is not None else None
        service = names[self._service[1]]
        self._set_path(self._data_dir, [(*user, "", PASS_THROUGH)] if user else [])
        self._set_path(self._base_dir, [(*user, "", LIST_THROUGH)] if user else [])
        left: list = []
        base = open_dir(self._base_dir)
        try:
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
                        user,
                        service,
                        is_written,
                        left,
                    )
                finally:
                    os.close(folder)
        finally:
            os.close(base)
        return left

    def _folder_entries(self, user, service, is_written: bool) -> list:
        """The inherited entries of one folder of a shared folder."""
        rights = FOLDER_WRITE if is_written else FOLDER_READ
        entries = [(*service, INHERITED, FOLDER_WRITE)] if is_written else []
        if user:
            entries.append((*user, INHERITED, rights))
        return entries

    def _write_tree(
        self, folder: int, path: str, user, service, is_written: bool, left: list
    ) -> None:
        """Set one folder's entries and every file's and folder's under it."""
        acl = self._bound()
        acl.set_fd(folder, acl_text(self._folder_entries(user, service, is_written)))
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
                        user,
                        service,
                        is_written,
                        left,
                    )
                    continue
                status = os.fstat(descriptor)
                if not stat.S_ISREG(status.st_mode):
                    continue
                rights = file_rights(status.st_mode, is_written)
                entries = [(*service, "", rights)] if is_written else []
                if user:
                    entries.append((*user, "", rights))
                acl.set_fd(descriptor, acl_text(entries))
            except OSError:
                left.append(os.path.join(path, name))
            finally:
                os.close(descriptor)

    def _set_path(self, path: str, entries: list) -> None:
        """Set one folder's list, opened by walking down from ``/``."""
        descriptor = open_dir(path)
        try:
            self._bound().set_fd(descriptor, acl_text(entries))
        finally:
            os.close(descriptor)

    def _bound(self):
        if self._acl is None:
            self._acl = DarwinAcl()
        return self._acl
