"""The machine's local accounts as Windows keeps them: the list, a home, acting as one.

The accounts are ``NetUserEnum``'s normal accounts at level 1, each enabled
unless its flags say disabled. An account's home is the profile the
registry's ``ProfileList`` names for its SID, which ``LookupAccountNameW``
reads for the name on this computer. A thread acts as an account under a
logon its password makes, ``LogonUserW`` then ``ImpersonateLoggedOnUser``,
until it reverts. The decoder takes the bytes ``NetUserEnum`` filled and the
address they sat at, never a live handle; the calls take the bound
libraries as their seam.

Not pure: calls netapi32, advapi32 and kernel32, and reads the registry.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ctypes

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.platforms import win32

try:
    import winreg
except ImportError:  # Only Windows has the registry module.
    winreg = None

# Where Windows records each SID's profile, read from the 64-bit view.
WINDOWS_ACCOUNTS_PROFILE_LIST_KEY = (
    "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList"
)
WINDOWS_ACCOUNTS_PROFILE_PATH_VALUE = "ProfileImagePath"
# The logons tried in turn for an account's own files, and the local
# account database they name.
WINDOWS_ACCOUNTS_LOGON_KINDS = (
    win32.LOGON32_LOGON_NETWORK_CLEARTEXT,
    win32.LOGON32_LOGON_BATCH,
)
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


def read_users(netapi32=None) -> list:
    """Every normal local account of this machine, as :func:`users_from` reads them.

    Args:
        netapi32: The bound netapi32; None binds the real one.

    Returns:
        The accounts.

    Raises:
        OSError: When the accounts cannot be listed.
        ValueError: When the buffer Windows filled cannot be read.
    """
    if netapi32 is None:
        netapi32 = win32.libraries().netapi32
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


def account_home(account: str, *, advapi32=None, kernel32=None) -> str:
    """One local account's profile directory, as the registry records it.

    Args:
        account: The account's name on this computer.
        advapi32: The bound advapi32; None binds the real one.
        kernel32: The bound kernel32; None binds the real one.

    Returns:
        The profile path, its variables expanded.

    Raises:
        KeyError: When this computer has no such account, or the account
            has no profile yet.
        OSError: When the SID or the registry cannot be read.
    """
    sid = account_sid(account, advapi32=advapi32, kernel32=kernel32)
    if winreg is None:
        raise OSError("no registry on this system")
    key_path = WINDOWS_ACCOUNTS_PROFILE_LIST_KEY + "\\" + sid
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            key_path,
            0,
            winreg.KEY_READ | win32.KEY_WOW64_64KEY,
        ) as key:
            value, _kind = winreg.QueryValueEx(key, WINDOWS_ACCOUNTS_PROFILE_PATH_VALUE)
    except FileNotFoundError as error:
        raise KeyError(account) from error
    home = winreg.ExpandEnvironmentStrings(str(value or ""))
    if not home:
        raise KeyError(account)
    return home


def account_sid(account: str, *, advapi32=None, kernel32=None) -> str:
    """One local account's SID, as ``S-1-5-21-...``.

    Args:
        account: The account's name on this computer.
        advapi32: The bound advapi32; None binds the real one.
        kernel32: The bound kernel32; None binds the real one.

    Returns:
        The SID's text.

    Raises:
        KeyError: When this computer has no account of that name.
        OSError: When the name or the SID cannot be read.
    """
    libraries = None
    if advapi32 is None or kernel32 is None:
        libraries = win32.libraries()
    advapi32 = advapi32 or libraries.advapi32
    kernel32 = kernel32 or libraries.kernel32
    sid = account_sid_buffer(account, advapi32=advapi32, kernel32=kernel32)
    text = ctypes.c_void_p()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise win32.last_error()
    try:
        return ctypes.wstring_at(text.value)
    finally:
        kernel32.LocalFree(text)


def account_sid_buffer(account: str, *, advapi32, kernel32):
    """One local account's SID, in a buffer the caller keeps alive.

    The name is looked up as ``<this computer>\\<account>``, so a domain's
    account or a well-known one of the same name is not taken for it.

    Args:
        account: The account's name on this computer.
        advapi32: The bound advapi32.
        kernel32: The bound kernel32.

    Returns:
        The SID's bytes, as a ctypes buffer.

    Raises:
        KeyError: When this computer has no account of that name.
        OSError: When the name cannot be read.
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
    return sid


@contextlib.contextmanager
def impersonated(account: str, password: str, *, advapi32=None, kernel32=None):
    """This thread acting as a local account, under a logon its password makes.

    A network logon is tried first, then a batch logon; the thread reverts
    and the logon is closed when the block ends.

    Args:
        account: The account's name on this computer.
        password: Its password.
        advapi32: The bound advapi32; None binds the real one.
        kernel32: The bound kernel32; None binds the real one.

    Yields:
        Nothing; the block runs as the account.

    Raises:
        ModuleApplyError: ``credential_invalid {account}`` when Windows
            refuses the password.
        OSError: When no logon is granted, or the thread cannot act as the
            account or cannot revert.
    """
    libraries = None
    if advapi32 is None or kernel32 is None:
        libraries = win32.libraries()
    advapi32 = advapi32 or libraries.advapi32
    kernel32 = kernel32 or libraries.kernel32
    token = logon_token(advapi32, account, password)
    try:
        if not advapi32.ImpersonateLoggedOnUser(token):
            raise win32.last_error()
        try:
            yield
        finally:
            if not advapi32.RevertToSelf():
                raise win32.last_error()
    finally:
        kernel32.CloseHandle(token)


def logon_token(
    advapi32, account: str, password: str, *, kinds=WINDOWS_ACCOUNTS_LOGON_KINDS
):
    """A logon of the account, each kind tried in turn.

    Args:
        advapi32: The bound advapi32.
        account: The account's name on this computer.
        password: Its password.
        kinds: The logon kinds, tried in order.

    Returns:
        The logon's token handle.

    Raises:
        ModuleApplyError: ``credential_invalid {account}`` when Windows
            refuses the password.
        OSError: When no kind of logon is granted.
    """
    refused = None
    for kind in kinds:
        token = ctypes.c_void_p()
        if advapi32.LogonUserW(
            account,
            WINDOWS_ACCOUNTS_LOCAL_DOMAIN,
            password,
            kind,
            win32.LOGON32_PROVIDER_DEFAULT,
            ctypes.byref(token),
        ):
            return token
        refused = win32.last_error()
        if getattr(refused, "winerror", None) == win32.ERROR_LOGON_FAILURE:
            raise ModuleApplyError("credential_invalid", {"account": account})
    raise refused


def _computer_name(kernel32) -> str:
    """This computer's name, as its local accounts are qualified with."""
    name = ctypes.create_unicode_buffer(win32.COMPUTER_NAME_CHARS)
    size = win32.DWORD(win32.COMPUTER_NAME_CHARS)
    if not kernel32.GetComputerNameW(name, ctypes.byref(size)):
        raise win32.last_error()
    return name.value
