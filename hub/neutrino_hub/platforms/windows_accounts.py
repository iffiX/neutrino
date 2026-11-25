"""The machine's local accounts as setup reads them on Windows: the list, a profile, the console's account, one logon.

Copied from the agent's and cut to what setup asks. The accounts are
``NetUserEnum``'s normal accounts at level 1, each enabled unless its flags
say disabled. An account has a profile when the registry's ``ProfileList``
names one for its SID, which ``LookupAccountNameW`` reads for the name on
this computer. A password is checked with one network logon, closed at
once. The decoder takes the bytes ``NetUserEnum`` filled and the address
they sat at, never a live handle; the calls take the bound libraries as
their seam.

Not pure: calls netapi32, advapi32, kernel32 and wtsapi32, and reads the
registry.
"""

import ctypes

from neutrino_hub.exceptions import AccountTestRefusedError
from neutrino_hub.platforms import win32
from neutrino_hub.platforms.constants import (
    PLATFORM_CODE_ACCOUNT_LOGON_REFUSED,
    PLATFORM_CODE_CREDENTIAL_INVALID,
)

try:
    import winreg
except ImportError:  # Only Windows has the registry module.
    winreg = None

# Where Windows records each SID's profile, read from the 64-bit view.
WINDOWS_ACCOUNTS_PROFILE_LIST_KEY = (
    "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList"
)
WINDOWS_ACCOUNTS_PROFILE_PATH_VALUE = "ProfileImagePath"
# The local account database a logon names.
WINDOWS_ACCOUNTS_LOCAL_DOMAIN = "."


def users_from(data: bytes, base: int, count: int) -> list:
    """The accounts a ``NetUserEnum`` level-1 buffer lists.

    Args:
        data: The buffer's bytes.
        base: The address the buffer sat at, which its pointers count from.
        count: How many rows the call read.

    Returns:
        ``[{"name", "description", "is_enabled"}]`` in the buffer's order,
        the description being the account's comment.

    Raises:
        ValueError: When the rows do not fit the buffer or a pointer leads
            outside it.
    """
    row_size = ctypes.sizeof(win32.UserInfo1)
    if count < 0 or count * row_size > len(data):
        raise ValueError(f"{count} accounts do not fit {len(data)} bytes")
    users = []
    for index in range(count):
        row = win32.UserInfo1.from_buffer_copy(data, index * row_size)
        users.append(
            {
                "name": win32.utf16_at(data, base, row.usri1_name),
                "description": win32.utf16_at(data, base, row.usri1_comment),
                "is_enabled": not row.usri1_flags & win32.UF_ACCOUNTDISABLE,
            }
        )
    return users


def read_users(netapi32) -> list:
    """Every normal local account of this machine, as :func:`users_from` reads them.

    Args:
        netapi32: The bound netapi32.

    Returns:
        The accounts.

    Raises:
        OSError: When the accounts cannot be listed.
        ValueError: When the buffer Windows filled cannot be read.
    """
    buffer = ctypes.c_void_p()
    read = win32.DWORD(0)
    total = win32.DWORD(0)
    resume = win32.DWORD(0)
    status = netapi32.NetUserEnum(
        None,
        1,
        win32.FILTER_NORMAL_ACCOUNT,
        ctypes.byref(buffer),
        win32.MAX_PREFERRED_LENGTH,
        ctypes.byref(read),
        ctypes.byref(total),
        ctypes.byref(resume),
    )
    try:
        if status != win32.NO_ERROR:
            raise OSError(status, f"NetUserEnum answered {status}")
        if not buffer.value:
            return []
        size = win32.DWORD(0)
        if netapi32.NetApiBufferSize(buffer, ctypes.byref(size)) != win32.NO_ERROR:
            raise OSError("NetApiBufferSize refused the accounts' buffer")
        data = ctypes.string_at(buffer.value, size.value)
        return users_from(data, buffer.value, read.value)
    finally:
        if buffer.value:
            netapi32.NetApiBufferFree(buffer)


def has_profile(account: str, *, advapi32, kernel32) -> bool:
    """Whether a local account has a profile, as the registry records it.

    Args:
        account: The account's name on this computer.
        advapi32: The bound advapi32.
        kernel32: The bound kernel32.

    Returns:
        True when ``ProfileList`` holds an entry with a path for the
        account's SID; False for an account this computer lacks or one that
        never signed in.

    Raises:
        OSError: When the SID or the registry cannot be read.
    """
    try:
        sid = account_sid(account, advapi32=advapi32, kernel32=kernel32)
    except KeyError:
        return False
    if winreg is None:
        raise OSError("no registry on this system")
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            WINDOWS_ACCOUNTS_PROFILE_LIST_KEY + "\\" + sid,
            0,
            winreg.KEY_READ | win32.KEY_WOW64_64KEY,
        ) as key:
            value, _kind = winreg.QueryValueEx(key, WINDOWS_ACCOUNTS_PROFILE_PATH_VALUE)
    except FileNotFoundError:
        return False
    return bool(str(value or ""))


def account_sid(account: str, *, advapi32, kernel32) -> str:
    """One local account's SID, as ``S-1-5-21-...``.

    The name is looked up as ``<this computer>\\<account>``, so a domain's
    account or a well-known one of the same name is not taken for it.

    Args:
        account: The account's name on this computer.
        advapi32: The bound advapi32.
        kernel32: The bound kernel32.

    Returns:
        The SID's text.

    Raises:
        KeyError: When this computer has no account of that name.
        OSError: When the name or the SID cannot be read.
    """
    qualified = _computer_name(kernel32) + "\\" + account
    sid_size = win32.DWORD(0)
    domain_size = win32.DWORD(0)
    use = win32.DWORD(0)
    advapi32.LookupAccountNameW(
        None,
        qualified,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(use),
    )
    if not sid_size.value:
        error = win32.last_error()
        if getattr(error, "winerror", None) == win32.ERROR_NONE_MAPPED:
            raise KeyError(account)
        raise error
    sid = ctypes.create_string_buffer(sid_size.value)
    domain = ctypes.create_unicode_buffer(max(domain_size.value, 1))
    if not advapi32.LookupAccountNameW(
        None,
        qualified,
        sid,
        ctypes.byref(sid_size),
        domain,
        ctypes.byref(domain_size),
        ctypes.byref(use),
    ):
        raise win32.last_error()
    if use.value != win32.SID_TYPE_USER:
        raise KeyError(account)
    text = ctypes.c_void_p()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise win32.last_error()
    try:
        return ctypes.wstring_at(text.value)
    finally:
        kernel32.LocalFree(text)


def check_password(account: str, password: str, *, advapi32, kernel32) -> None:
    """Test an account's password with one network logon, closed at once.

    A network logon stores no credential and loads no profile, and the
    password is an argument of this call alone. Windows checks the password
    before the logon kind, so a kind the account may not use passes.

    Args:
        account: The account's name on this computer.
        password: Its password.
        advapi32: The bound advapi32.
        kernel32: The bound kernel32.

    Raises:
        AccountTestRefusedError: ``credential_invalid {account}`` when
            Windows refuses the password, ``account_logon_refused {account,
            detail}`` when it refuses the logon for another reason,
            ``detail`` Windows' own sentence.
    """
    token = ctypes.c_void_p()
    if advapi32.LogonUserW(
        account,
        WINDOWS_ACCOUNTS_LOCAL_DOMAIN,
        password,
        win32.LOGON32_LOGON_NETWORK,
        win32.LOGON32_PROVIDER_DEFAULT,
        ctypes.byref(token),
    ):
        kernel32.CloseHandle(token)
        return
    refused = win32.last_error()
    code = getattr(refused, "winerror", None)
    if code == win32.ERROR_LOGON_TYPE_NOT_GRANTED:
        return
    if code == win32.ERROR_LOGON_FAILURE:
        raise AccountTestRefusedError(
            PLATFORM_CODE_CREDENTIAL_INVALID, {"account": account}
        )
    raise AccountTestRefusedError(
        PLATFORM_CODE_ACCOUNT_LOGON_REFUSED,
        {"account": account, "detail": str(refused.strerror or refused)},
    )


def console_account(kernel32, wtsapi32) -> str:
    """The account signed in on the console session.

    Args:
        kernel32: The bound kernel32.
        wtsapi32: The bound wtsapi32.

    Returns:
        Its name; empty when no one is signed in at the console.
    """
    session = kernel32.WTSGetActiveConsoleSessionId()
    if session == win32.WTS_NO_CONSOLE_SESSION:
        return ""
    buffer = ctypes.c_void_p()
    size = win32.DWORD(0)
    if not wtsapi32.WTSQuerySessionInformationW(
        win32.WTS_CURRENT_SERVER_HANDLE,
        session,
        win32.WTS_USER_NAME,
        ctypes.byref(buffer),
        ctypes.byref(size),
    ):
        return ""
    try:
        return ctypes.wstring_at(buffer.value) if buffer.value else ""
    finally:
        wtsapi32.WTSFreeMemory(buffer)


def _computer_name(kernel32) -> str:
    """This computer's name, as its local accounts are qualified with."""
    name = ctypes.create_unicode_buffer(win32.COMPUTER_NAME_CHARS)
    size = win32.DWORD(win32.COMPUTER_NAME_CHARS)
    if not kernel32.GetComputerNameW(name, ctypes.byref(size)):
        raise win32.last_error()
    return name.value
