"""A machine's available accounts: ``config/devices/<id>/accounts.json``.

An available account is one of the machine's accounts the person added on
the machine page, with what every feature of the account layer needs of it:
its Windows login, the folder its share serves, the shell its terminal and
SSH server start, and whether its AI tools use the hub's gateway with which
models (agent.md, "The two layers and the accounts"). The file is
``{accounts: [{account, login_id, share_path, shell_path,
is_ai_tools_enabled, tool_configs}]}`` in the order the accounts were added.

Every write re-reads the file under the config lock, as every store does.
"""

from dataclasses import dataclass, field

from neutrino_hub.modules.devices.ai_tools import clean_tool_configs
from neutrino_hub.modules.devices.constants import (
    DEVICE_ACCOUNTS_NAME,
    DEVICE_ENABLED_ACCOUNTS_KEY,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK


@dataclass
class DeviceAccount:
    """One available account of one machine.

    Attributes:
        account: The account's name, one the machine reports.
        login_id: The vault login holding its password on Windows; empty
            elsewhere.
        share_path: The folder its share serves; empty for its home.
        shell_path: The shell its terminal and SSH server start; empty for
            its login shell, PowerShell on Windows.
        is_ai_tools_enabled: Whether its AI tools use the hub's gateway.
        tool_configs: Its model choices, each slot empty for the gateway's
            default.
    """

    account: str
    login_id: str = ""
    share_path: str = ""
    shell_path: str = ""
    is_ai_tools_enabled: bool = False
    tool_configs: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceAccount":
        """Build from a stored row.

        Args:
            data: The stored object.

        Returns:
            The parsed account, its tool choices cleaned as the client
            cleans them.
        """
        return cls(
            account=str(data.get("account", "") or ""),
            login_id=str(data.get("login_id", "") or ""),
            share_path=str(data.get("share_path", "") or ""),
            shell_path=str(data.get("shell_path", "") or ""),
            is_ai_tools_enabled=data.get("is_ai_tools_enabled") is True,
            tool_configs=clean_tool_configs(data.get("tool_configs") or {}),
        )

    def to_dict(self) -> dict:
        """Serialize to the stored row shape."""
        return {
            "account": self.account,
            "login_id": self.login_id,
            "share_path": self.share_path,
            "shell_path": self.shell_path,
            "is_ai_tools_enabled": bool(self.is_ai_tools_enabled),
            "tool_configs": clean_tool_configs(self.tool_configs),
        }


class DeviceAccountStore:
    """Reads and writes each machine's ``accounts.json``."""

    def __init__(self, store):
        """
        Args:
            store: The per-device store the file is read and written
                through, a :class:`DesiredStateStore`.
        """
        self._store = store

    def accounts(self, key: str) -> list:
        """One machine's available accounts, in the order they were added.

        Args:
            key: The device.

        Returns:
            The accounts; empty when the machine has none.
        """
        held = self._store.read(key, DEVICE_ACCOUNTS_NAME)
        rows = held.get(DEVICE_ENABLED_ACCOUNTS_KEY)
        accounts = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("account"):
                accounts.append(DeviceAccount.from_dict(row))
        return accounts

    def names(self, key: str) -> list:
        """The names of one machine's available accounts, in their order."""
        return [account.account for account in self.accounts(key)]

    def get(self, key: str, account: str) -> "DeviceAccount | None":
        """One available account by name, or None when the machine has none."""
        for held in self.accounts(key):
            if held.account == account:
                return held
        return None

    def add(self, key: str, account: DeviceAccount) -> None:
        """Add an available account to one machine.

        Args:
            key: The device.
            account: The account's row.

        Raises:
            ValueError: When the machine already has an account of that name.
            OSError: When the file cannot be written.
        """
        with CONFIG_WRITE_LOCK:
            accounts = self.accounts(key)
            if any(held.account == account.account for held in accounts):
                raise ValueError(f"account {account.account!r} is already available")
            self._write(key, accounts + [account])

    def replace(self, key: str, account: DeviceAccount) -> None:
        """Replace one available account's row, keeping its place.

        Args:
            key: The device.
            account: The row as it stands afterwards.

        Raises:
            KeyError: When the machine has no account of that name.
            OSError: When the file cannot be written.
        """
        with CONFIG_WRITE_LOCK:
            accounts = self.accounts(key)
            if not any(held.account == account.account for held in accounts):
                raise KeyError(account.account)
            self._write(
                key,
                [
                    account if held.account == account.account else held
                    for held in accounts
                ],
            )

    def remove(self, key: str, account: str) -> "DeviceAccount | None":
        """Take one available account off a machine.

        Args:
            key: The device.
            account: The account's name.

        Returns:
            The row removed, or None when the machine had none of that name.

        Raises:
            OSError: When the file cannot be written.
        """
        with CONFIG_WRITE_LOCK:
            accounts = self.accounts(key)
            removed = next((held for held in accounts if held.account == account), None)
            if removed is None:
                return None
            self._write(key, [held for held in accounts if held.account != account])
        return removed

    def ai_tool_accounts(self, key: str) -> list:
        """The available accounts whose AI tools use the gateway.

        Args:
            key: The device.

        Returns:
            The rows whose switch is on, in the file's order.
        """
        return [held for held in self.accounts(key) if held.is_ai_tools_enabled]

    def _write(self, key: str, accounts: list) -> None:
        self._store.write(
            key,
            DEVICE_ACCOUNTS_NAME,
            {DEVICE_ENABLED_ACCOUNTS_KEY: [held.to_dict() for held in accounts]},
        )
