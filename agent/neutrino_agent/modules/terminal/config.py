"""The Terminal module's configuration and the checks a shell open makes of it.

``{accounts: [{account, shell_path, password}]}``: the module's enabled
accounts, the first being the one a stream that names none runs as. An
account's ``shell_path`` is the shell its terminal starts, empty for its
login shell, and PowerShell on Windows; ``password`` is its login, sent to a
Windows machine alone.

Not pure: the checks read the account database and the file system.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
from dataclasses import dataclass

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.terminal.constants import (
    TERMINAL_ACCOUNT_KEY,
    TERMINAL_ACCOUNTS_KEY,
    TERMINAL_CODE_ACCOUNT_DUPLICATE,
    TERMINAL_CODE_ACCOUNT_MISSING,
    TERMINAL_CODE_ACCOUNT_NOT_ENABLED,
    TERMINAL_CODE_ACCOUNT_UNKNOWN,
    TERMINAL_CODE_CONFIG_INVALID,
    TERMINAL_CODE_CREDENTIAL_MISSING,
    TERMINAL_CODE_SHELL_UNUSABLE,
    TERMINAL_PASSWORD_KEY,
    TERMINAL_SHELL_PATH_KEY,
)

try:
    import pwd
except ImportError:  # Windows carries no pwd.
    pwd = None


@dataclass(frozen=True)
class TerminalAccount:
    """One enabled account of the module.

    Attributes:
        account: The account's name on the machine.
        shell_path: The shell its terminal starts; empty for its login
            shell, and PowerShell on Windows.
        password: Its login, on Windows alone; empty elsewhere.
    """

    account: str
    shell_path: str = ""
    password: str = ""

    def to_dict(self) -> dict:
        """The account as the state carries it."""
        return {
            TERMINAL_ACCOUNT_KEY: self.account,
            TERMINAL_SHELL_PATH_KEY: self.shell_path,
            TERMINAL_PASSWORD_KEY: self.password,
        }


class TerminalConfig:
    """The enabled accounts a shell or a command runs as."""

    def __init__(self, *, accounts=()):
        """
        Args:
            accounts: The enabled accounts, as :class:`TerminalAccount`, in
                the order the person enabled them.
        """
        self.accounts = list(accounts)

    @classmethod
    def from_dict(cls, raw) -> "TerminalConfig":
        """Read a configuration as the state carries it.

        Args:
            raw: ``{accounts: [{account, shell_path, password}]}``; anything
                but a dict is no account.

        Returns:
            The configuration.

        Raises:
            ModuleApplyError: ``config_invalid {field}`` for an account list
                that is not a list, an entry that is not an object or names
                no account, or a field that is not a string;
                ``account_duplicate {account}`` for an account named twice.
        """
        raw = raw if isinstance(raw, dict) else {}
        entries = raw.get(TERMINAL_ACCOUNTS_KEY)
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise ModuleApplyError(
                TERMINAL_CODE_CONFIG_INVALID, {"field": TERMINAL_ACCOUNTS_KEY}
            )
        accounts = []
        for entry in entries:
            held = _account_of(entry)
            if any(each.account == held.account for each in accounts):
                raise ModuleApplyError(
                    TERMINAL_CODE_ACCOUNT_DUPLICATE, {"account": held.account}
                )
            accounts.append(held)
        return cls(accounts=accounts)

    def to_dict(self) -> dict:
        """The configuration as the state carries it."""
        return {TERMINAL_ACCOUNTS_KEY: [held.to_dict() for held in self.accounts]}

    def names(self) -> list:
        """The enabled accounts' names, in order."""
        return [held.account for held in self.accounts]

    def chosen(self, account: str = "") -> TerminalAccount:
        """The enabled account a stream runs as.

        Args:
            account: The account the open names; empty is the first one.

        Returns:
            The account.

        Raises:
            ModuleApplyError: ``terminal_account_missing`` while the module
                enables no account, ``account_not_enabled {account}`` for
                one it does not enable.
        """
        if not self.accounts:
            raise ModuleApplyError(TERMINAL_CODE_ACCOUNT_MISSING)
        if not account:
            return self.accounts[0]
        for held in self.accounts:
            if held.account == account:
                return held
        raise ModuleApplyError(TERMINAL_CODE_ACCOUNT_NOT_ENABLED, {"account": account})

    def validate(self, *, os_name: str, known_accounts=None) -> None:
        """Check that a shell can run for every enabled account.

        Args:
            os_name: ``linux``, ``darwin`` or ``windows``.
            known_accounts: Windows: the machine's accounts; None checks no
                account there.

        Raises:
            ModuleApplyError: ``account_unknown {account}`` for an account
                the machine does not have, ``shell_program_unusable {path}``
                for a shell that is missing or cannot be run, and on Windows
                ``credential_missing {account}`` for an account with no
                login.
        """
        for held in self.accounts:
            if os_name != "windows":
                account_entry(held.account)
                if held.shell_path:
                    check_shell_program(held.shell_path)
                continue
            if known_accounts is not None and held.account not in known_accounts:
                raise ModuleApplyError(
                    TERMINAL_CODE_ACCOUNT_UNKNOWN, {"account": held.account}
                )
            if not held.password:
                raise ModuleApplyError(
                    TERMINAL_CODE_CREDENTIAL_MISSING, {"account": held.account}
                )
            if held.shell_path:
                check_windows_program(held.shell_path)


def _account_of(entry) -> TerminalAccount:
    """One entry of the state's account list.

    Raises:
        ModuleApplyError: ``config_invalid {field}``.
    """
    if not isinstance(entry, dict):
        raise ModuleApplyError(
            TERMINAL_CODE_CONFIG_INVALID, {"field": TERMINAL_ACCOUNTS_KEY}
        )
    values = {}
    for key in (TERMINAL_ACCOUNT_KEY, TERMINAL_SHELL_PATH_KEY, TERMINAL_PASSWORD_KEY):
        value = entry.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ModuleApplyError(TERMINAL_CODE_CONFIG_INVALID, {"field": key})
        values[key] = value
    name = values[TERMINAL_ACCOUNT_KEY].strip()
    if not name:
        raise ModuleApplyError(
            TERMINAL_CODE_CONFIG_INVALID, {"field": TERMINAL_ACCOUNT_KEY}
        )
    return TerminalAccount(
        account=name,
        shell_path=values[TERMINAL_SHELL_PATH_KEY].strip(),
        password=values[TERMINAL_PASSWORD_KEY],
    )


def account_entry(account: str):
    """The account database's entry for an account.

    Args:
        account: The account.

    Returns:
        The ``pwd`` entry.

    Raises:
        ModuleApplyError: ``account_unknown {account}`` when the machine
            does not have it, or has no account database.
    """
    if pwd is None:
        raise ModuleApplyError(TERMINAL_CODE_ACCOUNT_UNKNOWN, {"account": account})
    try:
        return pwd.getpwnam(account)
    except KeyError:
        raise ModuleApplyError(
            TERMINAL_CODE_ACCOUNT_UNKNOWN, {"account": account}
        ) from None


def check_shell_program(path: str) -> None:
    """Refuse a shell program that cannot be run.

    Args:
        path: The program's path.

    Raises:
        ModuleApplyError: ``shell_program_unusable {path}`` when the path is
            not absolute, names no file, or names one with no execute bit.
    """
    if not (os.path.isabs(path) and os.path.isfile(path) and os.access(path, os.X_OK)):
        raise ModuleApplyError(TERMINAL_CODE_SHELL_UNUSABLE, {"path": path})


def check_windows_program(path: str) -> None:
    """Refuse a Windows shell program that is not there.

    Args:
        path: The program's path, absolute from a drive.

    Raises:
        ModuleApplyError: ``shell_program_unusable {path}`` when the path is
            not absolute or names no file.
    """
    if not (os.path.isabs(path) and os.path.isfile(path)):
        raise ModuleApplyError(TERMINAL_CODE_SHELL_UNUSABLE, {"path": path})
