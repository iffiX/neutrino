"""A folder on Windows, opened by handle with no reparse point followed, its access list set on that handle.

SYSTEM sets the access list of a folder an account can change in two
places: the file share grants a share's folder to the SMB users of its
accounts and keeps them off the ``.ssh`` folder under it, and a folder of
SYSTEM's under the state root is left to one account, as the one-shot task
of ``run_as_account`` reads and writes it. An account can put a junction
where such a folder is, or at a folder above it, and turn a change by path
onto any folder of the machine. So each folder is opened by handle with
the reparse point itself opened, never followed: a folder that is a
junction or a link, or whose final path is not the path asked, a folder
above it being a junction, is refused. The access list is read and set on
the open handle, which holds the folder that was checked.

Not pure: opens folders and sets access lists.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import errno
import ntpath
import os

from neutrino_agent.platforms import win32

# The access a share's folder is opened with, and how.
FOLDER_ACCESS = win32.READ_CONTROL | win32.WRITE_DAC | win32.FILE_READ_ATTRIBUTES
FOLDER_FLAGS = win32.FILE_FLAG_BACKUP_SEMANTICS | win32.FILE_FLAG_OPEN_REPARSE_POINT
# The access mask each folder right names, as icacls spells the right.
FOLDER_RIGHT_MASKS = {"(OI)(CI)M": 0x1301BF, "(OI)(CI)RX": 0x1200A9}
# The mask of each right a folder is left to an account with, and of full
# control.
LEFT_RIGHT_MASKS = {"R": 0x120089, "RX": 0x1200A9, "M": 0x1301BF}
FULL_CONTROL_MASK = 0x1F01FF
# SYSTEM and the administrators, by their well-known SIDs.
SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
# What the final path of an open handle starts with.
FINAL_PATH_PREFIX = "\\\\?\\"
# How many characters a final path holds at most.
FINAL_PATH_CHARS = 32768
# The index AddAce takes to put an entry at the end.
ACE_AT_END = 0xFFFFFFFF


def same_path(one: str, other: str) -> bool:
    """Whether two Windows paths name one place, without regard to case. Pure."""
    return ntpath.normcase(ntpath.normpath(one)) == ntpath.normcase(
        ntpath.normpath(other)
    )


class WindowsFolderAccess:
    """The access lists of a share's folders, each set on a handle that followed no reparse point."""

    def __init__(self, *, libraries=None):
        """
        Args:
            libraries: The bound :class:`Win32Libraries`; None binds them at
                the first call.
        """
        self._libraries = libraries

    def grant(self, path: str, account: str, right: str) -> None:
        """Replace an account's own entries on a folder with one right, inherited below it.

        Args:
            path: The folder.
            account: The account.
            right: ``(OI)(CI)M`` or ``(OI)(CI)RX``.

        Raises:
            OSError: ``ELOOP`` for a folder that is a reparse point or is
                reached through one; any other when Windows refuses.
        """
        entry = self._entry(account, win32.SET_ACCESS, FOLDER_RIGHT_MASKS[right])
        entry.grfInheritance = win32.SUB_CONTAINERS_AND_OBJECTS_INHERIT
        self._set_entries(path, [entry])

    def revoke(self, path: str, accounts: list) -> None:
        """Take every allow entry of these accounts off a folder.

        Args:
            path: The folder.
            accounts: The accounts.

        Raises:
            OSError: ``ELOOP`` for a folder that is a reparse point or is
                reached through one; any other when Windows refuses.
        """
        if accounts:
            self._set_entries(
                path, [self._entry(name, win32.REVOKE_ACCESS, 0) for name in accounts]
            )

    def leave_to(self, path: str, account: str, right: str) -> None:
        """Leave a folder to one account, SYSTEM and the administrators, nothing inherited.

        The account takes the right named, SYSTEM and the administrators
        full control, each inherited by what the folder holds; the list is
        set whole and protected on the folder's handle.

        Args:
            path: The folder.
            account: The account.
            right: ``R``, ``RX`` or ``M``.

        Raises:
            OSError: ``ELOOP`` for a folder that is a reparse point or is
                reached through one; any other when Windows refuses.
        """
        libraries = self._bound()
        sids = [_sid(SYSTEM_SID, libraries.advapi32)]
        try:
            sids.append(_sid(ADMINISTRATORS_SID, libraries.advapi32))
            entries = [self._entry(account, win32.SET_ACCESS, LEFT_RIGHT_MASKS[right])]
            for sid in sids:
                entry = self._entry("", win32.SET_ACCESS, FULL_CONTROL_MASK)
                entry.Trustee.TrusteeForm = win32.TRUSTEE_IS_SID
                entry.Trustee.ptstrName = sid.value
                entries.append(entry)
            for entry in entries:
                entry.grfInheritance = win32.SUB_CONTAINERS_AND_OBJECTS_INHERIT
            handle = self.open(path)
            try:
                self._set_whole(handle, path, entries)
            finally:
                libraries.kernel32.CloseHandle(handle)
        finally:
            for sid in sids:
                libraries.kernel32.LocalFree(sid)

    def keep_own(self, path: str) -> None:
        """Stop a folder inheriting, its inherited entries kept as its own.

        Raises:
            OSError: ``ELOOP`` for a folder that is a reparse point or is
                reached through one; any other when Windows refuses.
        """
        libraries = self._bound()
        handle = self.open(path)
        try:
            dacl, descriptor = self._dacl(handle)
            try:
                own = _without_inheritance(dacl, libraries.advapi32)
            finally:
                libraries.kernel32.LocalFree(descriptor)
            code = libraries.advapi32.SetSecurityInfo(
                handle,
                win32.SE_FILE_OBJECT,
                win32.DACL_SECURITY_INFORMATION
                | win32.PROTECTED_DACL_SECURITY_INFORMATION,
                None,
                None,
                own,
                None,
            )
            if code:
                raise OSError(code, f"could not keep the entries of {path}")
        finally:
            libraries.kernel32.CloseHandle(handle)

    def make(self, path: str) -> None:
        """Make a missing folder and each one missing above it, each checked by handle once made.

        Raises:
            OSError: ``ELOOP`` when a folder there or made is a reparse
                point or is reached through one; any other when Windows
                refuses.
        """
        missing = []
        current = ntpath.normpath(path)
        while not os.path.lexists(current):
            missing.append(current)
            parent = ntpath.dirname(current)
            if parent == current:
                break
            current = parent
        if not missing:
            return
        libraries = self._bound()
        libraries.kernel32.CloseHandle(self.open(current))
        for level in reversed(missing):
            os.mkdir(level)
            libraries.kernel32.CloseHandle(self.open(level))

    def open(self, path: str):
        """One folder's handle, its reparse point opened and never followed.

        Args:
            path: The folder.

        Returns:
            The handle; the caller closes it.

        Raises:
            OSError: ``ELOOP`` for a folder that is a reparse point, or
                whose final path is not ``path``; ``ENOTDIR`` for no
                folder; any other when it cannot be opened.
        """
        libraries = self._bound()
        handle = libraries.kernel32.CreateFileW(
            path,
            FOLDER_ACCESS,
            win32.FILE_SHARE_ALL,
            None,
            win32.OPEN_EXISTING,
            FOLDER_FLAGS,
            None,
        )
        if handle in (None, win32.INVALID_HANDLE_VALUE):
            raise win32.last_error()
        try:
            facts = win32.ByHandleFileInformation()
            if not libraries.kernel32.GetFileInformationByHandle(
                handle, ctypes.byref(facts)
            ):
                raise win32.last_error()
            if facts.dwFileAttributes & win32.FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError(errno.ELOOP, f"{path} is a junction or a link")
            if not facts.dwFileAttributes & win32.FILE_ATTRIBUTE_DIRECTORY:
                raise OSError(errno.ENOTDIR, f"{path} is no folder")
            final = _final_path(handle, libraries.kernel32)
            if not same_path(final, path):
                raise OSError(errno.ELOOP, f"{path} leads to {final}")
        except BaseException:
            libraries.kernel32.CloseHandle(handle)
            raise
        return handle

    def _set_entries(self, path: str, entries: list) -> None:
        """Fold entries into a folder's access list, read and set on its handle."""
        libraries = self._bound()
        handle = self.open(path)
        try:
            dacl, descriptor = self._dacl(handle)
            try:
                folded = ctypes.c_void_p()
                array = (win32.ExplicitAccessW * len(entries))(*entries)
                code = libraries.advapi32.SetEntriesInAclW(
                    len(entries), array, dacl, ctypes.byref(folded)
                )
                if code:
                    raise OSError(code, f"could not fold the entries of {path}")
                try:
                    code = libraries.advapi32.SetSecurityInfo(
                        handle,
                        win32.SE_FILE_OBJECT,
                        win32.DACL_SECURITY_INFORMATION,
                        None,
                        None,
                        folded,
                        None,
                    )
                    if code:
                        raise OSError(code, f"could not set the entries of {path}")
                finally:
                    libraries.kernel32.LocalFree(folded)
            finally:
                libraries.kernel32.LocalFree(descriptor)
        finally:
            libraries.kernel32.CloseHandle(handle)

    def _set_whole(self, handle, path: str, entries: list) -> None:
        """Set a new protected access list of these entries alone on an open folder."""
        libraries = self._bound()
        folded = ctypes.c_void_p()
        array = (win32.ExplicitAccessW * len(entries))(*entries)
        code = libraries.advapi32.SetEntriesInAclW(
            len(entries), array, None, ctypes.byref(folded)
        )
        if code:
            raise OSError(code, f"could not fold the entries of {path}")
        try:
            code = libraries.advapi32.SetSecurityInfo(
                handle,
                win32.SE_FILE_OBJECT,
                win32.DACL_SECURITY_INFORMATION
                | win32.PROTECTED_DACL_SECURITY_INFORMATION,
                None,
                None,
                folded,
                None,
            )
            if code:
                raise OSError(code, f"could not set the entries of {path}")
        finally:
            libraries.kernel32.LocalFree(folded)

    def _dacl(self, handle) -> tuple:
        """An open folder's access list and the descriptor that holds it, to be freed.

        Raises:
            OSError: When Windows refuses.
        """
        libraries = self._bound()
        dacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        code = libraries.advapi32.GetSecurityInfo(
            handle,
            win32.SE_FILE_OBJECT,
            win32.DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if code:
            raise OSError(code, "could not read an access list")
        return dacl, descriptor

    @staticmethod
    def _entry(account: str, mode: int, mask: int):
        """One entry naming an account."""
        entry = win32.ExplicitAccessW()
        entry.grfAccessPermissions = mask
        entry.grfAccessMode = mode
        entry.grfInheritance = 0
        entry.Trustee.pMultipleTrustee = None
        entry.Trustee.MultipleTrusteeOperation = win32.NO_MULTIPLE_TRUSTEE
        entry.Trustee.TrusteeForm = win32.TRUSTEE_IS_NAME
        entry.Trustee.TrusteeType = win32.TRUSTEE_IS_UNKNOWN
        name = ctypes.create_unicode_buffer(account)
        entry.Trustee.ptstrName = ctypes.cast(name, ctypes.c_void_p)
        entry.name = name
        return entry

    def _bound(self):
        if self._libraries is None:
            self._libraries = win32.libraries()
        return self._libraries


def _sid(text: str, advapi32):
    """A well-known SID from its text, to be freed with ``LocalFree``.

    Raises:
        OSError: When Windows cannot read it.
    """
    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(text, ctypes.byref(sid)):
        raise win32.last_error()
    return sid


def _final_path(handle, kernel32) -> str:
    """The path Windows resolves an open handle to, without its ``\\\\?\\``.

    Raises:
        OSError: When Windows cannot name it.
    """
    buffer = ctypes.create_unicode_buffer(FINAL_PATH_CHARS)
    length = kernel32.GetFinalPathNameByHandleW(handle, buffer, FINAL_PATH_CHARS, 0)
    if not length or length >= FINAL_PATH_CHARS:
        raise win32.last_error()
    final = buffer.value
    return (
        final[len(FINAL_PATH_PREFIX) :]
        if final.startswith(FINAL_PATH_PREFIX)
        else final
    )


def _without_inheritance(dacl, advapi32):
    """A copy of an access list with every inherited entry made the list's own.

    Returns:
        The copy, a ctypes buffer the caller keeps alive.

    Raises:
        OSError: When the list cannot be read or written.
    """
    size = win32.AclSizeInformation()
    if not advapi32.GetAclInformation(
        dacl,
        ctypes.byref(size),
        ctypes.sizeof(size),
        win32.ACL_SIZE_INFORMATION_CLASS,
    ):
        raise win32.last_error()
    copy = ctypes.create_string_buffer(int(size.AclBytesInUse) + 64)
    if not advapi32.InitializeAcl(copy, len(copy), win32.ACL_REVISION):
        raise win32.last_error()
    for index in range(int(size.AceCount)):
        found = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, index, ctypes.byref(found)):
            raise win32.last_error()
        header = ctypes.string_at(found.value, 4)
        length = header[2] | (header[3] << 8)
        entry = bytearray(ctypes.string_at(found.value, length))
        entry[1] &= ~win32.INHERITED_ACE & 0xFF
        held = ctypes.create_string_buffer(bytes(entry), length)
        if not advapi32.AddAce(copy, win32.ACL_REVISION, ACE_AT_END, held, length):
            raise win32.last_error()
    return copy
