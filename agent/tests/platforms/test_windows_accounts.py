"""The local accounts as Windows keeps them, decoded from recorded bytes and faked calls.

What these pin: the ``NetUserEnum`` level-1 block recorded on nmxwin decodes
to every normal account with its comment and whether it is enabled, and the
enabled ones are the accounts ``Get-LocalUser`` named there; rows past the
buffer or a pointer outside it raise; the live read frees the block always;
an account's home is the registry's profile for the SID of its name on
this computer, variables expanded, and a name with no account, a SID that
is no user's and a SID with no profile are ``KeyError``; a thread acts as an
account under a network logon, a batch logon when that is not granted, a
wrong password is ``credential_invalid`` with no second try, and the thread
reverts and the logon closes whatever the block does.
"""

import base64
import ctypes
import json
from pathlib import Path

import pytest

import neutrino_agent.platforms.windows_accounts as accounts_module
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows_accounts import (
    account_home,
    impersonated,
    read_users,
    users_from,
)

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "windows_accounts_nmxwin.json").read_text()
)
USERS = base64.b64decode(GOLDEN["users"]["data"])
BASE = GOLDEN["users"]["base"]
COUNT = GOLDEN["users"]["read"]


def win_error(code: int) -> OSError:
    error = OSError(code, f"error {code}")
    error.winerror = code
    return error


def test_the_recorded_block_decodes_to_every_normal_account():
    users = users_from(USERS, BASE, COUNT)

    assert [(user["name"], user["is_enabled"]) for user in users] == [
        ("Administrator", False),
        ("DefaultAccount", False),
        ("Guest", False),
        ("lab", True),
        ("labshare", False),
        ("share", True),
        ("test", True),
        ("WDAGUtilityAccount", False),
    ]
    enabled = [
        {"name": user["name"], "description": user["description"]}
        for user in users
        if user["is_enabled"]
    ]
    assert enabled == GOLDEN["expected"]["accounts"]["users"]
    assert users[0]["description"] == (
        "Built-in account for administering the computer/domain"
    )


@pytest.mark.parametrize(
    "data, base, count",
    [(USERS[:100], BASE, COUNT), (USERS, BASE + 0x100000, COUNT), (USERS, BASE, -1)],
    ids=["rows_past_the_end", "pointer_outside", "negative_count"],
)
def test_a_malformed_block_raises(data, base, count):
    with pytest.raises(ValueError):
        users_from(data, base, count)


class FakeNetapi32:
    """NetUserEnum handing out the recorded block from a buffer of its own."""

    def __init__(self, status=0):
        self.status = status
        self.freed: list = []
        self.held = ctypes.create_string_buffer(len(USERS))

    def NetUserEnum(self, server, level, kind, buffer, most, read, total, resume):
        assert (server, level, kind) == (None, 1, win32.FILTER_NORMAL_ACCOUNT)
        assert most == win32.MAX_PREFERRED_LENGTH
        if self.status:
            return self.status
        moved = rebased(USERS, BASE, ctypes.addressof(self.held), COUNT)
        ctypes.memmove(self.held, moved, len(moved))
        buffer._obj.value = ctypes.addressof(self.held)
        read._obj.value = COUNT
        return 0

    def NetApiBufferSize(self, buffer, size):
        size._obj.value = len(USERS)
        return 0

    def NetApiBufferFree(self, buffer):
        self.freed.append(buffer.value)
        return 0


def rebased(data: bytes, old: int, new: int, count: int) -> bytes:
    """The block with each row's pointers moved to a new address."""
    moved = bytearray(data)
    size = ctypes.sizeof(win32.UserInfo1)
    for index in range(count):
        row = win32.UserInfo1.from_buffer(moved, index * size)
        for field in (
            "usri1_name",
            "usri1_password",
            "usri1_home_dir",
            "usri1_comment",
            "usri1_script_path",
        ):
            if getattr(row, field):
                setattr(row, field, getattr(row, field) - old + new)
    return bytes(moved)


def test_the_live_read_decodes_the_block_and_frees_it():
    netapi32 = FakeNetapi32()

    users = read_users(netapi32)

    assert [user["name"] for user in users if user["is_enabled"]] == [
        "lab",
        "share",
        "test",
    ]
    assert netapi32.freed == [ctypes.addressof(netapi32.held)]


def test_a_refused_listing_is_an_os_error():
    with pytest.raises(OSError, match="NetUserEnum answered 5"):
        read_users(FakeNetapi32(status=5))


class FakeKernel32:
    """GetComputerNameW, LocalFree and CloseHandle."""

    def __init__(self):
        self.freed: list = []
        self.closed: list = []

    def GetComputerNameW(self, name, size):
        name.value = "NMXWIN"
        return 1

    def LocalFree(self, pointer):
        self.freed.append(pointer.value)
        return None

    def CloseHandle(self, handle):
        self.closed.append(handle.value)
        return 1


class FakeAdvapi32:
    """LookupAccountNameW and ConvertSidToStringSidW for one local account."""

    def __init__(self, *, sid="S-1-5-21-1-2-3-1001", use=win32.SID_TYPE_USER):
        self.sid = sid
        self.use = use
        self.names: list = []
        self.text = ctypes.create_unicode_buffer(sid)

    def LookupAccountNameW(self, system, name, sid, sid_size, domain, *sizes):
        self.names.append(name)
        if name != "NMXWIN\\lab":
            return 0
        sid_size._obj.value = 12
        sizes[0]._obj.value = 7
        if sid is None:
            return 0
        sizes[1]._obj.value = self.use
        return 1

    def ConvertSidToStringSidW(self, sid, text):
        text._obj.value = ctypes.addressof(self.text)
        return 1


class FakeWinreg:
    """The profile list, holding one profile or none."""

    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_READ = 0x20019

    def __init__(self, profiles):
        self.profiles = profiles
        self.opened: list = []

    def OpenKey(self, root, path, reserved, access):
        self.opened.append((root, path, access))
        if path not in self.profiles:
            raise FileNotFoundError(path)
        return Key(self.profiles[path])

    def QueryValueEx(self, key, name):
        assert name == "ProfileImagePath"
        return key.value, 2

    def ExpandEnvironmentStrings(self, text):
        return text.replace("%SystemDrive%", "C:")


class Key:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


PROFILES = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\"


def test_an_account_home_is_the_profile_of_its_sid(monkeypatch):
    registry = FakeWinreg(
        {PROFILES + "S-1-5-21-1-2-3-1001": "%SystemDrive%\\Users\\lab"}
    )
    monkeypatch.setattr(accounts_module, "winreg", registry)
    advapi32, kernel32 = FakeAdvapi32(), FakeKernel32()

    home = account_home("lab", advapi32=advapi32, kernel32=kernel32)

    assert home == "C:\\Users\\lab"
    assert advapi32.names == ["NMXWIN\\lab", "NMXWIN\\lab"]
    ((root, path, access),) = registry.opened
    assert (root, path) == ("HKLM", PROFILES + "S-1-5-21-1-2-3-1001")
    assert access & win32.KEY_WOW64_64KEY
    assert kernel32.freed == [ctypes.addressof(advapi32.text)]


def test_an_account_this_computer_lacks_has_no_home(monkeypatch):
    monkeypatch.setattr(accounts_module, "winreg", FakeWinreg({}))
    monkeypatch.setattr(win32, "last_error", lambda: win_error(1332))

    with pytest.raises(KeyError):
        account_home("ghost", advapi32=FakeAdvapi32(), kernel32=FakeKernel32())


def test_a_name_that_is_no_user_has_no_home(monkeypatch):
    monkeypatch.setattr(accounts_module, "winreg", FakeWinreg({}))
    advapi32 = FakeAdvapi32(use=2)

    with pytest.raises(KeyError):
        account_home("lab", advapi32=advapi32, kernel32=FakeKernel32())


@pytest.mark.parametrize("profiles", [{}, {PROFILES + "S-1-5-21-1-2-3-1001": ""}])
def test_an_account_with_no_profile_has_no_home(monkeypatch, profiles):
    monkeypatch.setattr(accounts_module, "winreg", FakeWinreg(profiles))

    with pytest.raises(KeyError):
        account_home("lab", advapi32=FakeAdvapi32(), kernel32=FakeKernel32())


def test_a_lookup_that_fails_otherwise_is_an_os_error(monkeypatch):
    monkeypatch.setattr(accounts_module, "winreg", FakeWinreg({}))
    monkeypatch.setattr(win32, "last_error", lambda: win_error(1722))

    with pytest.raises(OSError) as caught:
        account_home("ghost", advapi32=FakeAdvapi32(), kernel32=FakeKernel32())

    assert not isinstance(caught.value, KeyError)


class FakeLogon:
    """LogonUserW, ImpersonateLoggedOnUser and RevertToSelf, each recorded."""

    def __init__(self, answers):
        """
        Args:
            answers: Each logon kind to 0 for a token, or the error it gets.
        """
        self.answers = dict(answers)
        self.calls: list = []

    def LogonUserW(self, account, domain, password, kind, provider, token):
        self.calls.append(("logon", account, domain, password, kind))
        answer = self.answers.get(kind, 0)
        if answer:
            self.error = win_error(answer)
            return 0
        token._obj.value = 0x700 + kind
        return 1

    def ImpersonateLoggedOnUser(self, token):
        self.calls.append(("impersonate", token.value))
        return 1

    def RevertToSelf(self):
        self.calls.append(("revert",))
        return 1


def test_a_thread_acts_as_the_account_under_a_network_logon(monkeypatch):
    advapi32, kernel32 = FakeLogon({}), FakeKernel32()

    with impersonated("ann", "pw", advapi32=advapi32, kernel32=kernel32):
        advapi32.calls.append(("step",))

    assert advapi32.calls == [
        ("logon", "ann", ".", "pw", win32.LOGON32_LOGON_NETWORK_CLEARTEXT),
        ("impersonate", 0x708),
        ("step",),
        ("revert",),
    ]
    assert kernel32.closed == [0x708]


def test_a_batch_logon_is_tried_when_a_network_one_is_not_granted(monkeypatch):
    advapi32, kernel32 = (
        FakeLogon({win32.LOGON32_LOGON_NETWORK_CLEARTEXT: 1385}),
        FakeKernel32(),
    )
    monkeypatch.setattr(win32, "last_error", lambda: advapi32.error)

    with impersonated("ann", "pw", advapi32=advapi32, kernel32=kernel32):
        pass

    assert [call[-1] for call in advapi32.calls if call[0] == "logon"] == [
        win32.LOGON32_LOGON_NETWORK_CLEARTEXT,
        win32.LOGON32_LOGON_BATCH,
    ]
    assert kernel32.closed == [0x700 + win32.LOGON32_LOGON_BATCH]


def test_a_wrong_password_is_credential_invalid_with_no_second_try(monkeypatch):
    advapi32 = FakeLogon({win32.LOGON32_LOGON_NETWORK_CLEARTEXT: 1326})
    monkeypatch.setattr(win32, "last_error", lambda: advapi32.error)

    with pytest.raises(ModuleApplyError) as caught:
        with impersonated("ann", "old", advapi32=advapi32, kernel32=FakeKernel32()):
            pass

    assert (caught.value.code, caught.value.params) == (
        "credential_invalid",
        {"account": "ann"},
    )
    assert len(advapi32.calls) == 1


def test_no_logon_granted_is_an_os_error(monkeypatch):
    advapi32 = FakeLogon({8: 1385, 4: 1385})
    monkeypatch.setattr(win32, "last_error", lambda: advapi32.error)

    with pytest.raises(OSError):
        with impersonated("ann", "pw", advapi32=advapi32, kernel32=FakeKernel32()):
            pass

    assert not any(call[0] == "impersonate" for call in advapi32.calls)


def test_the_thread_reverts_and_the_logon_closes_when_the_block_raises():
    advapi32, kernel32 = FakeLogon({}), FakeKernel32()

    with pytest.raises(RuntimeError):
        with impersonated("ann", "pw", advapi32=advapi32, kernel32=kernel32):
            raise RuntimeError("the step failed")

    assert advapi32.calls[-1] == ("revert",)
    assert kernel32.closed == [0x708]
