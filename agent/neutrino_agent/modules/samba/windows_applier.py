"""The file share on Windows' own SMB server.

Each operation is one function of the agent's PowerShell host, handed a
JSON object and answering one, so a password never appears on a command
line. The module changes only the shares and accounts it made: a share
whose description starts with the marker and that the module's record
lists, an account the record lists. Accounts are local, in no group, hidden
from the sign-in screen and denied the console and RDP. Each share's folder
is granted to its accounts with ``icacls`` once the host has made it, and
the account's ``.ssh`` folder under it is taken back from them, so OpenSSH
goes on reading the account's own files. The host reads each folder's
access list first, and icacls runs only for an entry that differs. The
module fences nothing: the block rule an earlier version made goes at the
first apply that finds it.

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
    SAMBA_LINUX_USER_PREFIX,
    SAMBA_WINDOWS_FENCE_RULE,
    SAMBA_WINDOWS_FOLDER_CHANGE,
    SAMBA_WINDOWS_FOLDER_READ,
    SAMBA_WINDOWS_FOLDER_RULES,
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


def _share_request(share) -> dict:
    """One share as the host's apply converges it."""
    return {
        "name": share.name,
        "path": share.path,
        "description": f"{SAMBA_WINDOWS_MARKER} {share.comment}".strip(),
        "accounts": list(share.valid_users),
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

    def apply(
        self,
        config: SambaConfig,
        record: dict,
        *,
        is_sweep: bool = False,
        is_served: bool = True,
    ) -> list:
        """Make the server serve the configuration, and nothing else of ours.

        An account is the module's when the record lists it or its
        description is the marker; a share is the module's when the record
        lists it and its description starts with the marker. The host also
        deletes the block rule an earlier version made, when it finds one.
        Once the host has converged the server, each share's folder is
        granted to its accounts and taken from the module's others, and
        the ``.ssh`` folder under it is taken from them all. Each folder's
        access list is read before the host converges the server, and
        icacls changes only an entry that differs from it.

        Args:
            config: The validated configuration.
            record: The module's record: ``{"shares", "accounts"}``.
            is_served: Whether the server is started and the shares made.
                False takes every share of the module's off the server and
                makes the accounts and the folders alone.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``share_name_taken`` or ``user_name_taken`` for
                a name the module did not make.
            OSError: When the host, icacls or the local policy fails.
        """
        owned_shares = dict(record.get("shares") or {})
        owned_accounts = list(record.get("accounts") or [])
        served = config.served_shares()
        wanted_shares = {share.name for share in served} if is_served else set()
        known_accounts = owned_accounts + [
            name for name in config.users if name not in owned_accounts
        ]
        grants = folder_grants(served)
        left = _paths_left(owned_shares, grants)
        access = self._read_access(
            left
            + [
                folder
                for path in grants
                for folder in (path, os.path.join(path, SAMBA_WINDOWS_SSH_DIR_NAME))
            ],
            known_accounts,
        )
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
                "shares": [_share_request(share) for share in served],
                "retired_rule_name": SAMBA_WINDOWS_FENCE_RULE,
                "share_owner": SAMBA_WINDOWS_SHARE_OWNER,
                "is_sweep": is_sweep,
                "user_prefix": SAMBA_LINUX_USER_PREFIX,
                "is_served": is_served,
            },
        )
        for path in left:
            for name in _holders(access, path, known_accounts):
                icacls(self._run, [path, "/remove:g", name])
        for path, rights in grants.items():
            self._grant_folder(path, rights, known_accounts, access)
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

    def _read_access(self, paths: list, accounts: list) -> dict:
        """Each folder's own allow rules for the accounts, read through the host.

        Args:
            paths: The folders.
            accounts: The module's accounts.

        Returns:
            Folder, spelled as asked, to ``{"is_protected", "rules"}``:
            whether the folder inherits nothing, and each account holding
            a rule of its own there to the sorted ``(rights, inheritance,
            propagation)`` of those rules. A folder the host does not find
            is left out.

        Raises:
            OSError: When the host fails.
            ModuleApplyError: When the host refuses.
        """
        read = self._powershell.call(
            "folder_access", {"paths": paths, "accounts": list(accounts)}
        )
        access: dict = {}
        for entry in _listed(read.get("folders")):
            if not isinstance(entry, dict) or not entry.get("is_present"):
                continue
            rules: dict = {}
            for rule in _listed(entry.get("rules")):
                if isinstance(rule, dict):
                    rules.setdefault(str(rule.get("account", "")), []).append(
                        (
                            int(rule.get("rights", 0)),
                            int(rule.get("inheritance", 0)),
                            int(rule.get("propagation", 0)),
                        )
                    )
            access[str(entry.get("path", ""))] = {
                "is_protected": bool(entry.get("is_protected")),
                "rules": {name: sorted(held) for name, held in rules.items()},
            }
        return access

    def _grant_folder(
        self, path: str, rights: dict, known_accounts: list, access: dict
    ) -> None:
        """Grant a folder to its shares' accounts and take it from the module's others.

        The ``.ssh`` folder directly under it, when there is one, stops
        inheriting the folder's entries and loses every module account's.
        OpenSSH's check of the account's own files then passes. icacls runs
        only where ``access``, as :meth:`_read_access` reads it, differs.
        An account's grant replaces every rule of its own on the folder.
        """
        held = access.get(path, {}).get("rules", {})
        for name in _holders(access, path, known_accounts):
            if name not in rights:
                icacls(self._run, [path, "/remove:g", name])
        for name, right in rights.items():
            if held.get(name) == [SAMBA_WINDOWS_FOLDER_RULES[right]]:
                continue
            if icacls(self._run, [path, "/grant:r", f"{name}:{right}"]) != 0:
                raise OSError(f"icacls refused {name} on {path}")
        ssh_dir = os.path.join(path, SAMBA_WINDOWS_SSH_DIR_NAME)
        if not os.path.isdir(ssh_dir):
            return
        holders = _holders(access, ssh_dir, known_accounts)
        if not access.get(ssh_dir, {}).get("is_protected"):
            if icacls(self._run, [ssh_dir, "/inheritance:d"]) != 0:
                raise OSError(f"icacls could not keep {ssh_dir} the account's own")
            holders = known_accounts
        for name in holders:
            icacls(self._run, [ssh_dir, "/remove:g", name])


def folder_grants(shares: list) -> dict:
    """The right each account takes on each shared folder.

    Args:
        shares: The shares served, each with its users.

    Returns:
        Folder to ``{account: right}``, the folders in the shares' order.
        An account two shares of one folder name takes the change right
        when either share is writable.
    """
    grants: dict = {}
    for share in shares:
        right = (
            SAMBA_WINDOWS_FOLDER_READ
            if share.is_read_only
            else SAMBA_WINDOWS_FOLDER_CHANGE
        )
        held = grants.setdefault(_folder_key(share.path, grants), {})
        for name in share.valid_users:
            if held.get(name) != SAMBA_WINDOWS_FOLDER_CHANGE:
                held[name] = right
    return grants


def _folder_key(path: str, grants: dict) -> str:
    """The spelling :func:`folder_grants` already keys a folder by, else the path."""
    for held in grants:
        if _is_same_folder(held, path):
            return held
    return path


def _is_same_folder(one: str, other: str) -> bool:
    """Whether two Windows paths name one folder, without regard to case."""
    return one.rstrip("\\/").lower() == other.rstrip("\\/").lower()


def _holders(access: dict, path: str, accounts: list) -> list:
    """The accounts holding a rule of their own on a folder.

    Args:
        access: The folders' rules, as :meth:`SambaWindowsApplier._read_access`
            reads them.
        path: The folder, spelled as it was read.
        accounts: The accounts asked about, in their order.

    Returns:
        Each of ``accounts`` that holds a rule there.
    """
    held = access.get(path, {}).get("rules", {})
    return [name for name in accounts if held.get(name)]


def _paths_left(owned_shares: dict, grants: dict) -> list:
    """The folders of the module's shares that no share serves now.

    Args:
        owned_shares: Share name to its folder, as the record lists them.
        grants: The folders served now, as :func:`folder_grants` gives them.

    Returns:
        Each such folder once, in the record's order.
    """
    left: list = []
    for path in owned_shares.values():
        if not path or any(_is_same_folder(path, held) for held in grants):
            continue
        if not any(_is_same_folder(path, held) for held in left):
            left.append(path)
    return left
