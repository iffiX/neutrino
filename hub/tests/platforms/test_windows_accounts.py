"""The machine's local accounts as setup reads them on Windows, from recorded bytes and faked calls.

What these pin, with the agent's own cases: the ``NetUserEnum`` level-1
block recorded on nmxwin decodes to every normal account with its comment
and whether it is enabled; rows past the buffer or a pointer outside it
raise; the live read frees the block always; an account has a profile when
the registry's profile list names a path for the SID of its name on this
computer, and a name with no account, a SID that is no user's and a SID with
no profile have none; a password check is one network logon, closed at
once, a wrong password ``credential_invalid``, a kind the account may not
use passing, and another refusal ``account_logon_refused`` with Windows'
sentence; the console's account is the console session's user name.
"""

import base64
import ctypes
import json
from pathlib import Path

import pytest

import neutrino_hub.platforms.windows_accounts as accounts_module
from neutrino_hub.exceptions import AccountTestRefusedError
from neutrino_hub.platforms import win32
from neutrino_hub.platforms.windows_accounts import (
    check_password,
    console_account,
    has_profile,
    read_users,
    users_from,
)

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "windows_accounts_nmxwin.json").read_text()
)
USERS = base64.b64decode(GOLDEN["users"]["data"])
BASE = GOLDEN["users"]["base"]
COUNT = GOLDEN["users"]["read"]
PROFILES = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\"


def win_error(code: int, sentence: str = "") -> OSError:
    error = OSError(code, sentence or f"error {code}")
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
    """GetComputerNameW, LocalFree, CloseHandle and the console session."""

    def __init__(self, session=1):
        self.session = session
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

    def WTSGetActiveConsoleSessionId(self):
        return self.session


class FakeAdvapi32:
    """LookupAccountNameW and ConvertSidToStringSidW for one local account."""

    def __init__(self, *, sid="S-1-5-21-1-2-3-1001", use=win32.SID_TYPE_USER):
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


class Key:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_an_account_has_a_profile_where_its_sid_has_one(monkeypatch):
    registry = FakeWinreg({PROFILES + "S-1-5-21-1-2-3-1001": "C:\\Users\\lab"})
    monkeypatch.setattr(accounts_module, "winreg", registry)
    advapi32, kernel32 = FakeAdvapi32(), FakeKernel32()

    assert has_profile("lab", advapi32=advapi32, kernel32=kernel32) is True
    ((root, path, access),) = registry.opened
    assert (root, path) == ("HKLM", PROFILES + "S-1-5-21-1-2-3-1001")
    assert access & win32.KEY_WOW64_64KEY
    assert kernel32.freed == [ctypes.addressof(advapi32.text)]


def test_an_account_this_computer_lacks_has_no_profile(monkeypatch):
    monkeypatch.setattr(accounts_module, "winreg", FakeWinreg({}))
    monkeypatch.setattr(win32, "last_error", lambda: win_error(1332))

    assert (
        has_profile("ghost", advapi32=FakeAdvapi32(), kernel32=FakeKernel32()) is False
    )


def test_a_name_that_is_no_user_has_no_profile(monkeypatch):
    monkeypatch.setattr(accounts_module, "winreg", FakeWinreg({}))

    assert (
        has_profile("lab", advapi32=FakeAdvapi32(use=2), kernel32=FakeKernel32())
        is False
    )


@pytest.mark.parametrize("profiles", [{}, {PROFILES + "S-1-5-21-1-2-3-1001": ""}])
def test_an_account_that_never_signed_in_has_no_profile(monkeypatch, profiles):
    monkeypatch.setattr(accounts_module, "winreg", FakeWinreg(profiles))

    assert has_profile("lab", advapi32=FakeAdvapi32(), kernel32=FakeKernel32()) is False


def test_a_lookup_that_fails_otherwise_is_an_os_error(monkeypatch):
    monkeypatch.setattr(accounts_module, "winreg", FakeWinreg({}))
    monkeypatch.setattr(win32, "last_error", lambda: win_error(1722))

    with pytest.raises(OSError):
        has_profile("ghost", advapi32=FakeAdvapi32(), kernel32=FakeKernel32())


class FakeLogon:
    """LogonUserW, recorded; each kind answered with a token or an error."""

    def __init__(self, answers, sentence=""):
        self.answers = dict(answers)
        self.sentence = sentence
        self.calls: list = []

    def LogonUserW(self, account, domain, password, kind, provider, token):
        self.calls.append(("logon", account, domain, password, kind))
        answer = self.answers.get(kind, 0)
        if answer:
            self.error = win_error(answer, self.sentence)
            return 0
        token._obj.value = 0x700 + kind
        return 1


def test_a_right_password_makes_one_network_logon_and_closes_it():
    advapi32, kernel32 = FakeLogon({}), FakeKernel32()

    check_password("lab", "pw", advapi32=advapi32, kernel32=kernel32)

    assert advapi32.calls == [("logon", "lab", ".", "pw", win32.LOGON32_LOGON_NETWORK)]
    assert kernel32.closed == [0x700 + win32.LOGON32_LOGON_NETWORK]


def test_a_wrong_password_is_one_failed_logon_and_credential_invalid(monkeypatch):
    advapi32 = FakeLogon({win32.LOGON32_LOGON_NETWORK: win32.ERROR_LOGON_FAILURE})
    monkeypatch.setattr(win32, "last_error", lambda: advapi32.error)

    with pytest.raises(AccountTestRefusedError) as caught:
        check_password("lab", "old", advapi32=advapi32, kernel32=FakeKernel32())

    assert (caught.value.code, caught.value.params) == (
        "credential_invalid",
        {"account": "lab"},
    )
    assert len(advapi32.calls) == 1


def test_a_logon_kind_the_account_may_not_use_passes_the_check(monkeypatch):
    advapi32, kernel32 = (
        FakeLogon({win32.LOGON32_LOGON_NETWORK: win32.ERROR_LOGON_TYPE_NOT_GRANTED}),
        FakeKernel32(),
    )
    monkeypatch.setattr(win32, "last_error", lambda: advapi32.error)

    check_password("lab", "pw", advapi32=advapi32, kernel32=kernel32)

    assert len(advapi32.calls) == 1
    assert kernel32.closed == []


def test_a_logon_refused_otherwise_carries_windows_sentence(monkeypatch):
    advapi32 = FakeLogon(
        {win32.LOGON32_LOGON_NETWORK: 1909}, "The referenced account is locked out."
    )
    monkeypatch.setattr(win32, "last_error", lambda: advapi32.error)

    with pytest.raises(AccountTestRefusedError) as caught:
        check_password("lab", "pw", advapi32=advapi32, kernel32=FakeKernel32())

    assert (caught.value.code, caught.value.params) == (
        "account_logon_refused",
        {"account": "lab", "detail": "The referenced account is locked out."},
    )


class FakeWtsapi32:
    """The console session's user name, from a buffer of its own."""

    def __init__(self, name):
        self.held = ctypes.create_unicode_buffer(name)
        self.freed: list = []

    def WTSQuerySessionInformationW(self, server, session, kind, buffer, size):
        assert (server, kind) == (win32.WTS_CURRENT_SERVER_HANDLE, win32.WTS_USER_NAME)
        buffer._obj.value = ctypes.addressof(self.held)
        return 1

    def WTSFreeMemory(self, buffer):
        self.freed.append(buffer.value)


def test_the_console_account_is_the_console_sessions_user():
    wtsapi32 = FakeWtsapi32("lab")

    assert console_account(FakeKernel32(), wtsapi32) == "lab"
    assert wtsapi32.freed == [ctypes.addressof(wtsapi32.held)]


def test_no_console_session_is_no_account():
    kernel32 = FakeKernel32(session=win32.WTS_NO_CONSOLE_SESSION)

    assert console_account(kernel32, FakeWtsapi32("lab")) == ""
