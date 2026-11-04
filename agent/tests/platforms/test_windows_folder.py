"""A share's folder on Windows, opened by handle, with the Win32 calls faked.

What these pin: a folder is opened with its reparse point opened and never
followed; a folder that is a reparse point, or whose final path is not the
path asked because a folder above it is a junction, is refused ``ELOOP``
and its handle closed; a grant folds one inherited entry of the right's
mask for the account into the list read on that handle and sets it on the
same handle; a revoke folds one revoking entry per account; keeping a
folder's entries copies each inherited entry as its own and sets the list
protected on the handle.
"""

import ctypes
import errno
import struct

import pytest

from neutrino_agent.platforms.windows_folder import WindowsFolderAccess
from neutrino_agent.platforms import win32

HANDLE = 4242


class Kernel32:
    """CreateFileW, the file's facts and its final path, as a test says."""

    def __init__(self, *, attributes=win32.FILE_ATTRIBUTE_DIRECTORY, final=""):
        self.attributes = attributes
        self.final = final
        self.opened: list = []
        self.closed: list = []
        self.freed: list = []

    def CreateFileW(self, path, access, share, security, disposition, flags, template):
        self.opened.append((path, access, flags))
        return HANDLE

    def GetFileInformationByHandle(self, handle, facts):
        facts._obj.dwFileAttributes = self.attributes
        return 1

    def GetFinalPathNameByHandleW(self, handle, buffer, size, flags):
        buffer.value = "\\\\?\\" + (self.final or self.opened[-1][0])
        return len(buffer.value)

    def CloseHandle(self, handle):
        self.closed.append(handle)

    def LocalFree(self, pointer):
        self.freed.append(pointer)


class Advapi32:
    """The security calls, recording what they were handed."""

    def __init__(self, aces=()):
        self.set: list = []
        self.folded: list = []
        self.added: list = []
        self.sids: dict = {}
        self._sid_buffers: list = []
        self._aces = [ctypes.create_string_buffer(ace, len(ace)) for ace in aces]

    def GetSecurityInfo(self, handle, kind, what, owner, group, dacl, sacl, sd):
        return 0

    def SetEntriesInAclW(self, count, entries, old, new):
        for index in range(count):
            entry = entries[index]
            self.folded.append(
                (
                    entry.grfAccessPermissions,
                    entry.grfAccessMode,
                    entry.grfInheritance,
                    entry.Trustee.TrusteeForm,
                    (
                        ctypes.wstring_at(entry.Trustee.ptstrName)
                        if entry.Trustee.TrusteeForm == win32.TRUSTEE_IS_NAME
                        else self.sids[entry.Trustee.ptstrName]
                    ),
                )
            )
        return 0

    def ConvertStringSidToSidW(self, text, sid):
        buffer = ctypes.create_string_buffer(16)
        self._sid_buffers.append(buffer)
        sid._obj.value = ctypes.addressof(buffer)
        self.sids[sid._obj.value] = text
        return 1

    def SetSecurityInfo(self, handle, kind, what, owner, group, dacl, sacl):
        self.set.append((handle, kind, what))
        return 0

    def GetAclInformation(self, dacl, size, length, kind):
        size._obj.AceCount = len(self._aces)
        size._obj.AclBytesInUse = 8 + sum(len(ace) for ace in self._aces)
        return 1

    def InitializeAcl(self, buffer, length, revision):
        return 1

    def GetAce(self, dacl, index, found):
        found._obj.value = ctypes.addressof(self._aces[index])
        return 1

    def AddAce(self, acl, revision, at, ace, length):
        self.added.append(ctypes.string_at(ace, length))
        return 1


class Libraries:
    def __init__(self, kernel32, advapi32):
        self.kernel32 = kernel32
        self.advapi32 = advapi32


def folders(**facts) -> tuple:
    kernel32 = Kernel32(**facts)
    advapi32 = Advapi32()
    return (
        WindowsFolderAccess(libraries=Libraries(kernel32, advapi32)),
        kernel32,
        advapi32,
    )


def test_a_folder_is_opened_with_its_reparse_point_never_followed():
    access, kernel32, _ = folders()

    access.grant("C:\\Users\\ann", "neutrino-ann", "(OI)(CI)M")

    ((path, rights, flags),) = kernel32.opened
    assert path == "C:\\Users\\ann"
    assert flags & win32.FILE_FLAG_OPEN_REPARSE_POINT
    assert flags & win32.FILE_FLAG_BACKUP_SEMANTICS
    assert rights & win32.WRITE_DAC and rights & win32.READ_CONTROL
    assert kernel32.closed == [HANDLE]


def test_a_folder_that_is_a_junction_is_refused_and_its_handle_closed():
    access, kernel32, advapi32 = folders(
        attributes=win32.FILE_ATTRIBUTE_DIRECTORY | win32.FILE_ATTRIBUTE_REPARSE_POINT
    )

    with pytest.raises(OSError) as refused:
        access.grant("C:\\Users\\ann\\share", "neutrino-ann", "(OI)(CI)M")

    assert refused.value.errno == errno.ELOOP
    assert kernel32.closed == [HANDLE]
    assert advapi32.set == []


def test_a_folder_reached_through_a_junction_above_it_is_refused():
    access, kernel32, advapi32 = folders(final="C:\\Windows\\System32")

    with pytest.raises(OSError) as refused:
        access.revoke("C:\\Users\\ann\\link\\System32", ["neutrino-ann"])

    assert refused.value.errno == errno.ELOOP
    assert "C:\\Windows\\System32" in str(refused.value)
    assert kernel32.closed == [HANDLE]
    assert advapi32.set == []


def test_a_final_path_of_another_case_is_the_same_folder():
    access, _, advapi32 = folders(final="c:\\users\\ANN")

    access.grant("C:\\Users\\ann", "neutrino-ann", "(OI)(CI)RX")

    assert len(advapi32.set) == 1


def test_a_grant_folds_one_inherited_entry_and_sets_it_on_the_same_handle():
    access, _, advapi32 = folders()

    access.grant("D:\\media", "neutrino-ann", "(OI)(CI)M")

    assert advapi32.folded == [
        (
            0x1301BF,
            win32.SET_ACCESS,
            win32.SUB_CONTAINERS_AND_OBJECTS_INHERIT,
            win32.TRUSTEE_IS_NAME,
            "neutrino-ann",
        )
    ]
    assert advapi32.set == [
        (HANDLE, win32.SE_FILE_OBJECT, win32.DACL_SECURITY_INFORMATION)
    ]


def test_a_revoke_folds_one_entry_per_account():
    access, _, advapi32 = folders()

    access.revoke("D:\\media", ["neutrino-ann", "neutrino-bob"])
    access.revoke("D:\\media", [])

    assert [entry[1:] for entry in advapi32.folded] == [
        (win32.REVOKE_ACCESS, 0, win32.TRUSTEE_IS_NAME, "neutrino-ann"),
        (win32.REVOKE_ACCESS, 0, win32.TRUSTEE_IS_NAME, "neutrino-bob"),
    ]
    assert len(advapi32.set) == 1


def test_keeping_a_folders_entries_makes_each_inherited_one_its_own_and_protects_it():
    kernel32 = Kernel32()
    inherited = struct.pack("<BBHI", 0, win32.INHERITED_ACE | 0x03, 8, 0x1F01FF)
    own = struct.pack("<BBHI", 0, 0x03, 8, 0x1200A9)
    advapi32 = Advapi32(aces=[own, inherited])
    access = WindowsFolderAccess(libraries=Libraries(kernel32, advapi32))

    access.keep_own("C:\\Users\\ann\\.ssh")

    assert advapi32.added == [own, struct.pack("<BBHI", 0, 0x03, 8, 0x1F01FF)]
    assert advapi32.set == [
        (
            HANDLE,
            win32.SE_FILE_OBJECT,
            win32.DACL_SECURITY_INFORMATION | win32.PROTECTED_DACL_SECURITY_INFORMATION,
        )
    ]
    assert kernel32.closed == [HANDLE]


def test_a_folder_left_to_an_account_gets_a_whole_protected_list_on_its_handle():
    access, kernel32, advapi32 = folders()

    access.leave_to("C:\\ProgramData\\Neutrino\\agent\\state\\run_as\\ann", "ann", "R")

    inherited = win32.SUB_CONTAINERS_AND_OBJECTS_INHERIT
    assert advapi32.folded == [
        (0x120089, win32.SET_ACCESS, inherited, win32.TRUSTEE_IS_NAME, "ann"),
        (0x1F01FF, win32.SET_ACCESS, inherited, win32.TRUSTEE_IS_SID, "S-1-5-18"),
        (0x1F01FF, win32.SET_ACCESS, inherited, win32.TRUSTEE_IS_SID, "S-1-5-32-544"),
    ]
    assert advapi32.set == [
        (
            HANDLE,
            win32.SE_FILE_OBJECT,
            win32.DACL_SECURITY_INFORMATION | win32.PROTECTED_DACL_SECURITY_INFORMATION,
        )
    ]
    assert kernel32.closed == [HANDLE]
    assert len(kernel32.freed) == 3


def test_a_junction_where_a_folder_is_left_to_an_account_is_refused():
    access, kernel32, advapi32 = folders(
        attributes=win32.FILE_ATTRIBUTE_DIRECTORY | win32.FILE_ATTRIBUTE_REPARSE_POINT
    )

    with pytest.raises(OSError) as refused:
        access.leave_to(
            "C:\\ProgramData\\Neutrino\\agent\\state\\run_as\\ann", "ann", "M"
        )

    assert refused.value.errno == errno.ELOOP
    assert advapi32.set == []
    assert len(kernel32.freed) == 2
