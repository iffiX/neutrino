"""The default account of a machine 0.6.1 kept, set once at the panel's start.

0.6.1 kept no default account. Each ``accounts.json`` with no
``default_account`` key gets its first available account, the one added
earliest, and empty when it has none (agent/accounts.md, "A machine with no
default"). That account moves first in every module file that enables it,
and is enabled in Terminal, the SSH server and every module of the account
layer whose ``want`` is neither empty nor ``absent``; nothing new installs.
SiYuan's keys and the container modules' keys then follow the AI switches.
A file that holds the key, empty included, is left alone.
"""

import logging

from neutrino_hub.modules.clients.ai_keys import (
    settle_instance_keys,
    settle_module_keys,
)
from neutrino_hub.modules.devices.accounts import DeviceAccountStore
from neutrino_hub.modules.devices.constants import DEVICE_ACCOUNTS_FILE
from neutrino_hub.modules.devices.module_table import (
    account_layer_names,
    gateway_instance_names,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK

LOGGER = logging.getLogger(__name__)


def set_legacy_defaults(store, devices: dict) -> list:
    """Give every machine whose ``accounts.json`` names no default account its first one.

    Args:
        store: The :class:`DesiredStateStore` the files are read and written
            through.
        devices: Device id to the device's name, for the keys' labels.

    Returns:
        The ids of the machines whose file gained the key.

    Raises:
        OSError: When a file cannot be written.
        VaultLockedError: When a newly enabled account's secret cannot be
            sealed.
    """
    changed = []
    for device_id, name in devices.items():
        default = _set_one(store, device_id)
        if default is None:
            continue
        changed.append(device_id)
        LOGGER.info("device %s: the default account is %r", device_id, default)
        if not default:
            continue
        for module in gateway_instance_names():
            if store.read(device_id, module):
                settle_instance_keys(store, device_id, module, name)
        settle_module_keys(store, device_id, name)
    return changed


def _set_one(store, key: str) -> "str | None":
    """One machine's default written; None when its file holds the key or there is no file."""
    if not (store.directory_of(key) / DEVICE_ACCOUNTS_FILE).exists():
        return None
    accounts = DeviceAccountStore(store)
    with CONFIG_WRITE_LOCK:
        if accounts.has_default_key(key):
            return None
        names = accounts.names(key)
        default = names[0] if names else ""
        accounts.set_default_account(key, default)
        if not default:
            return default
        installed = set(store.default_modules(key))
        for module in account_layer_names():
            if module in installed or default in store.enabled_accounts(key, module):
                store.enable_default(key, module)
    return default
