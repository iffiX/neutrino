"""The Terminal module's configuration and the checks a shell open makes of it.

``{account, shell_path}``, both strings, both empty for the shell the agent
runs today as itself. An account is one the machine's account database
has; a shell path is an absolute path to a file that can be run. Windows
reads the shell path alone.

Not pure: the checks read the account database and the file system.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.terminal.constants import (
    TERMINAL_ACCOUNT_KEY,
    TERMINAL_CODE_ACCOUNT_UNKNOWN,
    TERMINAL_CODE_CONFIG_INVALID,
    TERMINAL_CODE_SHELL_UNUSABLE,
    TERMINAL_SHELL_PATH_KEY,
)

try:
    import pwd
except ImportError:  # Windows carries no pwd.
    pwd = None


class TerminalConfig:
    """The account and the shell program a new shell runs."""

    def __init__(self, *, account: str = "", shell_path: str = ""):
        """
        Args:
            account: The account; empty runs the shell as the agent runs.
            shell_path: The shell program; empty is the shell the stream
                picks.
        """
        self.account = account
        self.shell_path = shell_path

    @classmethod
    def from_dict(cls, raw, *, os_name: str) -> "TerminalConfig":
        """Read a configuration as the state carries it.

        Args:
            raw: ``{account, shell_path}``; anything else is the defaults.
            os_name: ``linux``, ``darwin`` or ``windows``; Windows drops the
                account.

        Returns:
            The configuration.

        Raises:
            ModuleApplyError: ``config_invalid {field}`` for a setting that
                is not a string.
        """
        raw = raw if isinstance(raw, dict) else {}
        values = {}
        for key in (TERMINAL_ACCOUNT_KEY, TERMINAL_SHELL_PATH_KEY):
            value = raw.get(key, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise ModuleApplyError(TERMINAL_CODE_CONFIG_INVALID, {"field": key})
            values[key] = value.strip()
        if os_name == "windows":
            values[TERMINAL_ACCOUNT_KEY] = ""
        return cls(
            account=values[TERMINAL_ACCOUNT_KEY],
            shell_path=values[TERMINAL_SHELL_PATH_KEY],
        )

    def to_dict(self) -> dict:
        """The configuration as the state carries it."""
        return {
            TERMINAL_ACCOUNT_KEY: self.account,
            TERMINAL_SHELL_PATH_KEY: self.shell_path,
        }

    def validate(self) -> None:
        """Check that a shell can run as these settings say.

        Raises:
            ModuleApplyError: ``account_unknown {account}`` for an account
                the machine does not have, and ``shell_program_unusable
                {path}`` for a shell program that is missing, not absolute
                or not executable.
        """
        if self.account:
            account_entry(self.account)
        if self.shell_path:
            check_shell_program(self.shell_path)


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
