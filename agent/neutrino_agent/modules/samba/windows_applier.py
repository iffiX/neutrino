"""The file share on Windows' own SMB server.

Each operation is one function of the agent's PowerShell host, handed a
JSON object and answering one, so a password never appears on a command
line. The module changes only the shares and accounts it made: a share
whose description starts with the marker and that the module's record
lists, an account the record lists. Accounts are local, in no group, hidden
from the sign-in screen and denied the console and RDP. Each share's folder
is granted to its accounts with ``icacls`` once the host has made it, and
the account's ``.ssh`` folder under it is taken back from them, so OpenSSH
goes on reading the account's own files. The module fences nothing: the
block rule an earlier version made goes at the first apply that finds it.

Not pure: drives the PowerShell host, runs icacls and calls the local
security policy.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import os

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_WINDOWS_DENIED_RIGHTS,
    SAMBA_WINDOWS_FENCE_RULE,
    SAMBA_WINDOWS_FOLDER_CHANGE,
    SAMBA_WINDOWS_FOLDER_READ,
    SAMBA_WINDOWS_MARKER,
    SAMBA_WINDOWS_SERVER_LOG,
    SAMBA_WINDOWS_SHARE_CHANGE,
    SAMBA_WINDOWS_SHARE_OWNER,
    SAMBA_WINDOWS_SHARE_READ,
    SAMBA_WINDOWS_SSH_DIR_NAME,
)
from neutrino_agent.modules.shared.subprocess_run import run as run_command
from neutrino_agent.modules.shared.windows_acl import icacls
from neutrino_agent.platforms import win32


def deny_interactive_logon(account: str, *, advapi32=None) -> None:
    """Deny one local account the console and RDP in the local policy.

    Args:
        account: The local account's name.
        advapi32: The bound advapi32; None binds the real one.

    Raises:
        OSError: When the account has no SID or the policy refuses.
    """
    if advapi32 is None:
        advapi32 = win32.libraries().advapi32
    sid = _account_sid(advapi32, account)
    attributes = win32.LsaObjectAttributes()
    attributes.Length = ctypes.sizeof(win32.LsaObjectAttributes)
    policy = ctypes.c_void_p()
    status = advapi32.LsaOpenPolicy(
        None,
        ctypes.byref(attributes),
        win32.POLICY_CREATE_ACCOUNT | win32.POLICY_LOOKUP_NAMES,
        ctypes.byref(policy),
    )
    if status:
        code = advapi32.LsaNtStatusToWinError(status)
        raise OSError(code, f"LsaOpenPolicy refused: error {code}")
    try:
        buffers = [
            ctypes.create_unicode_buffer(name) for name in SAMBA_WINDOWS_DENIED_RIGHTS
        ]
        rights = (win32.LsaUnicodeString * len(buffers))()
        for index, (name, buffer) in enumerate(
            zip(SAMBA_WINDOWS_DENIED_RIGHTS, buffers)
        ):
            rights[index].Length = len(name) * 2
            rights[index].MaximumLength = (len(name) + 1) * 2
            rights[index].Buffer = ctypes.cast(buffer, ctypes.c_void_p)
        status = advapi32.LsaAddAccountRights(policy, sid, rights, len(buffers))
        if status:
            code = advapi32.LsaNtStatusToWinError(status)
            raise OSError(code, f"LsaAddAccountRights refused {account}: error {code}")
    finally:
        advapi32.LsaClose(policy)


def _account_sid(advapi32, account: str):
    """One account's SID, in a buffer the caller keeps alive."""
    sid_size = win32.DWORD(0)
    domain_size = win32.DWORD(0)
    use = win32.DWORD(0)
    advapi32.LookupAccountNameW(
        None,
        account,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(use),
    )
    if not sid_size.value:
        raise OSError(f"no SID for the account {account}")
    sid = ctypes.create_string_buffer(sid_size.value)
    domain = ctypes.create_unicode_buffer(max(domain_size.value, 1))
    if not advapi32.LookupAccountNameW(
        None,
        account,
        sid,
        ctypes.byref(sid_size),
        domain,
        ctypes.byref(domain_size),
        ctypes.byref(use),
    ):
        raise OSError(f"no SID for the account {account}")
    return sid


def _share_request(share, config: SambaConfig) -> dict:
    """One share as the host's apply converges it."""
    return {
        "name": share.name,
        "path": share.path,
        "description": f"{SAMBA_WINDOWS_MARKER} {share.comment}".strip(),
        "accounts": list(share.valid_users or config.users),
        "share_right": (
            SAMBA_WINDOWS_SHARE_READ
            if share.is_read_only
            else SAMBA_WINDOWS_SHARE_CHANGE
        ),
    }


def _listed(value) -> list:
    """A member the host answers as a list; anything else is none."""
    return value if isinstance(value, list) else []


def _share_detail(entry) -> dict:
    """One marked share in the shape the Linux module reports."""
    entry = entry if isinstance(entry, dict) else {}
    description = str(entry.get("description", ""))
    comment = description[len(SAMBA_WINDOWS_MARKER) :].strip()
    access = [
        item
        for item in _listed(entry.get("access"))
        if isinstance(item, dict)
        and str(item.get("account", "")) != SAMBA_WINDOWS_SHARE_OWNER
    ]
    users = [str(item.get("account", "")).rsplit("\\", 1)[-1] for item in access]
    is_read_only = all(
        str(item.get("right", "")) == SAMBA_WINDOWS_SHARE_READ for item in access
    )
    return {
        "name": str(entry.get("name", "")),
        "path": str(entry.get("path", "")),
        "params": {
            "comment": comment,
            "read only": "Yes" if is_read_only else "No",
            "valid users": " ".join(users),
        },
    }


def _session_detail(entry) -> dict:
    """One SMB session in the shape the Linux module reports."""
    entry = entry if isinstance(entry, dict) else {}
    address = str(entry.get("address", ""))
    return {
        "username": str(entry.get("user", "")).rsplit("\\", 1)[-1],
        "hostname": address,
        "remote_address": address,
        "shares": [],
    }


class SambaWindowsApplier:
    """Converges Windows' SMB server with the module's configuration."""

    def __init__(self, *, powershell, deny_logon=None, run=None):
        """
        Args:
            powershell: The agent's PowerShell host, asked as
                :meth:`WindowsPowerShellHost.call` is.
            deny_logon: Called with an account name to deny it the console
                and RDP. None calls the local security policy.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
        """
        self._powershell = powershell
        self._deny_logon = (
            deny_logon if deny_logon is not None else deny_interactive_logon
        )
        self._run = run if run is not None else run_command

    def read_status(self, record: dict) -> dict:
        """What the server holds of the module's, read now.

        Args:
            record: The module's record: ``{"shares", "accounts"}``.

        Returns:
            ``{"is_present", "is_running", "shares", "sessions", "users"}``;
            ``is_present`` false when the host cannot answer.
        """
        try:
            read = self._powershell.call(
                "share_status",
                {
                    "marker": SAMBA_WINDOWS_MARKER,
                    "accounts": list(record.get("accounts") or []),
                },
            )
        except (OSError, ModuleApplyError):
            return {"is_present": False, "is_running": False}
        return {
            "is_present": bool(read.get("is_present")),
            "is_running": bool(read.get("is_running")),
            "shares": [_share_detail(entry) for entry in _listed(read.get("shares"))],
            "sessions": [
                _session_detail(entry) for entry in _listed(read.get("sessions"))
            ],
            "users": [
                {
                    "name": str(entry.get("name", "")),
                    "is_present": bool(entry.get("is_present")),
                    "has_password": bool(entry.get("is_enabled")),
                }
                for entry in _listed(read.get("users"))
                if isinstance(entry, dict)
            ],
        }

    def apply(self, config: SambaConfig, record: dict) -> list:
        """Make the server serve the configuration, and nothing else of ours.

        An account is the module's when the record lists it or its
        description is the marker; a share is the module's when the record
        lists it and its description starts with the marker. The host also
        deletes the block rule an earlier version made, when it finds one.
        Once the host has converged the server, each share's folder is
        granted to its accounts and taken from the module's others, and
        the ``.ssh`` folder under it is taken from them all.

        Args:
            config: The validated configuration.
            record: The module's record: ``{"shares", "accounts"}``.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``share_name_taken`` or ``user_name_taken`` for
                a name the module did not make.
            OSError: When the host, icacls or the local policy fails.
        """
        owned_shares = dict(record.get("shares") or {})
        owned_accounts = list(record.get("accounts") or [])
        wanted_shares = {share.name for share in config.shares}
        known_accounts = owned_accounts + [
            name for name in config.users if name not in owned_accounts
        ]
        answer = self._powershell.call(
            "share_apply",
            {
                "marker": SAMBA_WINDOWS_MARKER,
                "owned_shares": sorted(owned_shares),
                "owned_accounts": owned_accounts,
                "users": list(config.users),
                "retired_accounts": [
                    name for name in owned_accounts if name not in config.users
                ],
                "removed_shares": sorted(set(owned_shares) - wanted_shares),
                "shares": [_share_request(share, config) for share in config.shares],
                "retired_rule_name": SAMBA_WINDOWS_FENCE_RULE,
                "share_owner": SAMBA_WINDOWS_SHARE_OWNER,
            },
        )
        for share in config.shares:
            self._grant_folder(share, config, known_accounts)
        for name in config.users:
            self._deny_logon(name)
        return [str(note) for note in _listed(answer.get("notes"))]

    def withdraw(self, record: dict, *, is_removed: bool) -> None:
        """Take the module's shares off the server.

        Args:
            record: The module's record: ``{"shares", "accounts"}``.
            is_removed: Also disable the module's accounts, as an uninstall
                does.

        Raises:
            OSError: When the host fails.
        """
        self._powershell.call(
            "share_withdraw",
            {
                "marker": SAMBA_WINDOWS_MARKER,
                "owned_shares": sorted(record.get("shares") or {}),
                "owned_accounts": list(record.get("accounts") or []),
                "is_removed": is_removed,
            },
        )

    def read_server_log(self, lines: int) -> list:
        """The SMB server's latest events from its event log, oldest first.

        Args:
            lines: How many events to read at most.

        Returns:
            One line per event, ``<time> <event id> <message>``.

        Raises:
            OSError: When the host fails or does not answer in time.
            ModuleApplyError: When the host refuses.
        """
        read = self._powershell.call(
            "share_log",
            {"log_name": SAMBA_WINDOWS_SERVER_LOG, "lines": int(lines)},
        )
        return [str(line) for line in _listed(read.get("lines")) if str(line).strip()]

    def set_password(self, name: str, password: str) -> None:
        """Set one of the module's accounts' password and enable it.

        Args:
            name: An account the record lists.
            password: The new password; it reaches the host on its standard
                input.

        Raises:
            OSError: When the host fails.
        """
        self._powershell.call("share_password", {"name": name, "password": password})

    def _grant_folder(self, share, config: SambaConfig, known_accounts: list) -> None:
        """Grant one share's folder to its accounts and take it from the others.

        The ``.ssh`` folder under the share, when there is one, stops
        inheriting the folder's entries and loses every module account's,
        so OpenSSH's check of the account's own files passes.
        """
        accounts = list(share.valid_users or config.users)
        right = (
            SAMBA_WINDOWS_FOLDER_READ
            if share.is_read_only
            else SAMBA_WINDOWS_FOLDER_CHANGE
        )
        for name in known_accounts:
            if name not in accounts:
                icacls(self._run, [share.path, "/remove:g", name])
        for name in accounts:
            if icacls(self._run, [share.path, "/grant", f"{name}:{right}"]) != 0:
                raise OSError(f"icacls refused {name} on {share.path}")
        ssh_dir = os.path.join(share.path, SAMBA_WINDOWS_SSH_DIR_NAME)
        if not os.path.isdir(ssh_dir):
            return
        if icacls(self._run, [ssh_dir, "/inheritance:d"]) != 0:
            raise OSError(f"icacls could not keep {ssh_dir} the account's own")
        for name in known_accounts:
            icacls(self._run, [ssh_dir, "/remove:g", name])
