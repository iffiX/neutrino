"""The batch logon right of the accounts the agent runs tasks as on Windows.

A scheduled task under an account's login signs the account in with a
batch logon. Windows admits that logon only for an account with "Log on as
a batch job", ``SeBatchLogonRight``. An administrator has it through its
group, and a standard account does not. The agent grants the right to an
account when it registers a task under the account's login, and takes it
away when it removes the account's last such task. An account that passes
a batch logon before the agent's first task is never granted the right, and
the agent takes away only a right it granted. The record under the state
root lists each account with a task: its tasks, and whether its right is
the agent's grant.

Not pure: logs accounts on, changes the local security policy and writes
the record.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import json
import ntpath
import os
import threading

from neutrino_agent.constants import AGENT_BATCH_LOGON_RIGHT
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows_accounts import (
    account_sid_buffer,
    logon_token,
)

# One lock around the record for every object in this process.
_RECORD_LOCK = threading.Lock()


class WindowsBatchLogonRight:
    """The batch logon right the agent grants accounts, and the record of its grants."""

    def __init__(self, *, record_path: str, advapi32=None, kernel32=None):
        """
        Args:
            record_path: The record's file.
            advapi32: The bound advapi32; None binds the real one on first
                use.
            kernel32: The bound kernel32; None binds the real one on first
                use.
        """
        self._record_path = record_path
        self._advapi32 = advapi32
        self._kernel32 = kernel32

    def hold(self, account: str, task: str, password: str) -> None:
        """Record a task under the account's login, and grant the account the right where it needs it.

        An account the record does not list is tried with a batch logon
        first, and granted the right when Windows refuses that kind of
        logon. An account whose right is the agent's grant is granted it
        again.

        Args:
            account: The account.
            task: The task's name.
            password: The account's login.

        Raises:
            ModuleApplyError: ``credential_invalid {account}`` when Windows
                refuses the login.
            KeyError: When the machine does not have the account.
            OSError: When the logon, the policy or the record fails.
        """
        with _RECORD_LOCK:
            record = self._read()
            key = account.lower()
            entry = record.get(key)
            if entry is None:
                entry = {
                    "account": account,
                    "is_granted": not self._can_log_on(account, password),
                    "tasks": [],
                }
            if task not in entry["tasks"]:
                entry["tasks"] = [*entry["tasks"], task]
                record[key] = entry
                self._write(record)
            if entry["is_granted"]:
                self._change(account, is_added=True)

    def release(self, account: str, task: str) -> bool:
        """Forget a task of the account, and take the agent's grant away with the last one.

        Args:
            account: The account.
            task: The task's name.

        Returns:
            Whether the right was taken away.

        Raises:
            OSError: When the policy or the record fails.
        """
        with _RECORD_LOCK:
            record = self._read()
            key = account.lower()
            entry = record.get(key)
            if entry is None:
                return False
            tasks = [held for held in entry["tasks"] if held != task]
            if tasks:
                entry["tasks"] = tasks
                self._write(record)
                return False
            is_taken = bool(entry["is_granted"]) and self._take(entry["account"])
            del record[key]
            self._write(record)
            return is_taken

    def release_all(self) -> list:
        """Take away every right the agent granted, and delete the record.

        Returns:
            The accounts whose right was taken away, in the record's order.

        Raises:
            OSError: When the policy refuses.
        """
        with _RECORD_LOCK:
            taken = [
                entry["account"]
                for entry in self._read().values()
                if entry["is_granted"] and self._take(entry["account"])
            ]
            try:
                os.unlink(self._record_path)
            except FileNotFoundError:
                pass
            return taken

    def _can_log_on(self, account: str, password: str) -> bool:
        """Whether Windows admits a batch logon of the account."""
        advapi32, kernel32 = self._libraries()
        try:
            token = logon_token(
                advapi32, account, password, kinds=(win32.LOGON32_LOGON_BATCH,)
            )
        except OSError as error:
            if getattr(error, "winerror", None) == win32.ERROR_LOGON_TYPE_NOT_GRANTED:
                return False
            raise
        kernel32.CloseHandle(token)
        return True

    def _take(self, account: str) -> bool:
        """Take the right away from an account; False for an account the machine no longer has."""
        try:
            self._change(account, is_added=False)
        except KeyError:
            return False
        return True

    def _change(self, account: str, *, is_added: bool) -> None:
        """Grant the right to an account or take it away, in the local security policy.

        Raises:
            KeyError: When the machine does not have the account.
            OSError: When the policy refuses.
        """
        advapi32, kernel32 = self._libraries()
        sid = account_sid_buffer(account, advapi32=advapi32, kernel32=kernel32)
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
            buffer = ctypes.create_unicode_buffer(AGENT_BATCH_LOGON_RIGHT)
            rights = (win32.LsaUnicodeString * 1)()
            rights[0].Length = len(AGENT_BATCH_LOGON_RIGHT) * 2
            rights[0].MaximumLength = (len(AGENT_BATCH_LOGON_RIGHT) + 1) * 2
            rights[0].Buffer = ctypes.cast(buffer, ctypes.c_void_p)
            if is_added:
                status = advapi32.LsaAddAccountRights(policy, sid, rights, 1)
            else:
                status = advapi32.LsaRemoveAccountRights(policy, sid, 0, rights, 1)
                if status == win32.STATUS_OBJECT_NAME_NOT_FOUND:
                    status = 0
            if status:
                code = advapi32.LsaNtStatusToWinError(status)
                verb = "LsaAddAccountRights" if is_added else "LsaRemoveAccountRights"
                raise OSError(code, f"{verb} refused {account}: error {code}")
        finally:
            advapi32.LsaClose(policy)

    def _libraries(self) -> tuple:
        """The bound advapi32 and kernel32, the real ones where none was given."""
        if self._advapi32 is None or self._kernel32 is None:
            libraries = win32.libraries()
            self._advapi32 = self._advapi32 or libraries.advapi32
            self._kernel32 = self._kernel32 or libraries.kernel32
        return self._advapi32, self._kernel32

    def _read(self) -> dict:
        """The record's accounts, by lower-case name; empty when there is none."""
        try:
            with open(self._record_path, "r", encoding="utf-8") as stream:
                document = json.load(stream)
        except (OSError, ValueError):
            return {}
        accounts = document.get("accounts") if isinstance(document, dict) else None
        if not isinstance(accounts, dict):
            return {}
        return {
            str(key): {
                "account": str(entry.get("account", "") or key),
                "is_granted": bool(entry.get("is_granted")),
                "tasks": [str(task) for task in entry.get("tasks") or []],
            }
            for key, entry in accounts.items()
            if isinstance(entry, dict)
        }

    def _write(self, record: dict) -> None:
        """Write the record whole.

        Raises:
            OSError: When the file cannot be written.
        """
        os.makedirs(ntpath.dirname(self._record_path) or ".", exist_ok=True)
        temporary = self._record_path + ".new"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump({"accounts": record}, stream, indent=2, sort_keys=True)
        os.replace(temporary, self._record_path)
