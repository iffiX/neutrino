"""The default account setup asked for the hub's own machine, kept until that machine reports it.

The setup step that writes the answers stores a Windows account's password
as a vault login and writes ``setup_default_account.json``, ``{account,
login_id}``, mode 0600, under the state root (files.md). At the first report
of the hub's own machine that lists the account, while the file exists, the
hub writes the account as available and default, enables it in Terminal and
the SSH server, and deletes the file (agent/accounts.md, "The default
account").
"""

import json
import logging
import os

from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.constants import (
    DEVICE_SETUP_DEFAULT_ACCOUNT_MODE,
    DEVICE_SETUP_DEFAULT_ACCOUNT_PATH,
    DEVICE_SSH_SERVER_MODULE,
    DEVICE_TERMINAL_MODULE,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK

LOGGER = logging.getLogger(__name__)


def write_setup_default(account: str, login_id: str, path=None) -> None:
    """Keep the default account setup asked until the hub's own machine reports it.

    Args:
        account: The account.
        login_id: The vault login holding its Windows password; empty
            elsewhere.
        path: The file; None is :data:`DEVICE_SETUP_DEFAULT_ACCOUNT_PATH`.

    Raises:
        OSError: When the file cannot be written.
    """
    path = path or DEVICE_SETUP_DEFAULT_ACCOUNT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, DEVICE_SETUP_DEFAULT_ACCOUNT_MODE
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"account": account, "login_id": login_id}, stream)


def read_setup_default(path=None) -> dict:
    """The default account setup asked, while its file exists.

    Args:
        path: The file; None is :data:`DEVICE_SETUP_DEFAULT_ACCOUNT_PATH`.

    Returns:
        ``{account, login_id}``; empty with no file or one that does not
        read.
    """
    path = path or DEVICE_SETUP_DEFAULT_ACCOUNT_PATH
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(held, dict) or not isinstance(held.get("account"), str):
        return {}
    return {
        "account": held["account"],
        "login_id": str(held.get("login_id", "") or ""),
    }


def is_setup_default_kept(path=None) -> bool:
    """Whether setup left a default account for the hub's own machine.

    Args:
        path: The file; None is :data:`DEVICE_SETUP_DEFAULT_ACCOUNT_PATH`.

    Returns:
        True while the file exists.
    """
    return (path or DEVICE_SETUP_DEFAULT_ACCOUNT_PATH).exists()


def apply_setup_default(store, key: str, accounts: list, path=None) -> bool:
    """Make the account setup asked the default of the hub's own machine, once it reports the account.

    Args:
        store: The :class:`DesiredStateStore` the files are written through.
        key: The hub's own machine.
        accounts: The accounts its report's ``machine`` section lists.
        path: The file; None is :data:`DEVICE_SETUP_DEFAULT_ACCOUNT_PATH`.

    Returns:
        True when the account was written and the file deleted; False while
        there is no file, the report does not list the account, or the
        machine already has a default.

    Raises:
        OSError: When a file cannot be written.
        VaultLockedError: When the SSH server's key for the account cannot
            be sealed.
    """
    path = path or DEVICE_SETUP_DEFAULT_ACCOUNT_PATH
    held = read_setup_default(path)
    if not held or held["account"] not in accounts:
        return False
    account_store = DeviceAccountStore(store)
    with CONFIG_WRITE_LOCK:
        if account_store.default_account(key):
            path.unlink(missing_ok=True)
            return False
        row = account_store.get(key, held["account"])
        if row is None:
            account_store.add(
                key,
                DeviceAccount(account=held["account"], login_id=held["login_id"]),
                is_default=True,
            )
        else:
            account_store.set_default_account(key, row.account)
        for module in (DEVICE_TERMINAL_MODULE, DEVICE_SSH_SERVER_MODULE):
            store.enable_default(key, module)
    path.unlink(missing_ok=True)
    LOGGER.info(
        "device %s: %r is the default account setup asked", key, held["account"]
    )
    return True
