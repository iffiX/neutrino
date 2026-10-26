"""The device files of 0.5, moved once into the account layer.

A hub of 0.5 kept one machine's accounts inside each module's file: the
Terminal module's one ``account`` and ``shell_path``, every other program's
``instances``, each ``{account, port, login_id, <sealed fields>}``, the
Podman machine's ``login_id``, the file share's ``users``, Hermes WebUI's
``port`` and the machine's AI tools setting in ``ai_tools.json``. 0.6.0
keeps the accounts in ``accounts.json`` and each module's enabled accounts
under ``accounts``, and the ports are the agent's (protocol.md, "The account
layer in the state"). The move runs at the panel's start, once per machine
directory, and leaves a file already of the new shape alone.
"""

import logging

from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.constants import (
    DEVICE_AI_TOOLS_FILE,
    DEVICE_ENABLED_ACCOUNTS_KEY,
    DEVICE_HERMES_WEBUI_MODULE,
    DEVICE_INSTANCE_LOGIN_KEY,
    DEVICE_PODMAN_MACHINE_KEY,
    DEVICE_PODMAN_MODULE,
    DEVICE_SAMBA_MODULE,
    DEVICE_TERMINAL_MODULE,
)
from neutrino_hub.modules.devices.module_table import account_layer_names

LOGGER = logging.getLogger(__name__)

LEGACY_INSTANCES_KEY = "instances"
LEGACY_SAMBA_USERS_KEY = "users"
LEGACY_PORT_KEY = "port"
LEGACY_AI_TOOLS_ENABLED_KEY = "is_enabled"
LEGACY_AI_TOOLS_CONFIGS_KEY = "tool_configs"


def move_legacy_device_files(store, device_ids) -> list:
    """Move every machine's 0.5 files into the account layer.

    Args:
        store: The :class:`DesiredStateStore` the files are read and written
            through.
        device_ids: The machines whose directories are read.

    Returns:
        The ids of the machines a file was moved for.

    Raises:
        OSError: When a file cannot be written.
    """
    moved = []
    for device_id in device_ids:
        if _move_one(store, device_id):
            moved.append(device_id)
            LOGGER.info(
                "device %s: the 0.5 files moved into the account layer", device_id
            )
    return moved


def _move_one(store, key: str) -> bool:
    """One machine's directory, moved; False when it was of the new shape."""
    accounts = DeviceAccountStore(store)
    known = {account.account: account for account in accounts.accounts(key)}
    found: dict = {}
    is_moved = False

    def note(account: str, **fields) -> None:
        if not account or account in known:
            return
        row = found.setdefault(account, {"account": account})
        for name, value in fields.items():
            if value:
                row[name] = value

    terminal = store.read(key, DEVICE_TERMINAL_MODULE)
    if terminal and DEVICE_ENABLED_ACCOUNTS_KEY not in terminal:
        account = str(terminal.get("account", "") or "")
        note(account, shell_path=str(terminal.get("shell_path", "") or ""))
        store.write(
            key,
            DEVICE_TERMINAL_MODULE,
            {DEVICE_ENABLED_ACCOUNTS_KEY: [{"account": account}] if account else []},
        )
        is_moved = True

    for module in account_layer_names():
        if module in (DEVICE_TERMINAL_MODULE, DEVICE_SAMBA_MODULE):
            continue
        held = store.read(key, module)
        instances = held.get(LEGACY_INSTANCES_KEY)
        if not isinstance(instances, list):
            continue
        records = []
        for instance in instances:
            if not isinstance(instance, dict) or not instance.get("account"):
                continue
            account = str(instance["account"])
            note(
                account, login_id=str(instance.get(DEVICE_INSTANCE_LOGIN_KEY, "") or "")
            )
            records.append(
                {
                    name: value
                    for name, value in instance.items()
                    if name not in (LEGACY_PORT_KEY, DEVICE_INSTANCE_LOGIN_KEY)
                }
            )
        written = {
            name: value for name, value in held.items() if name != LEGACY_INSTANCES_KEY
        }
        written[DEVICE_ENABLED_ACCOUNTS_KEY] = records
        store.write(key, module, written)
        is_moved = True

    samba = store.read(key, DEVICE_SAMBA_MODULE)
    if LEGACY_SAMBA_USERS_KEY in samba:
        store.write(
            key,
            DEVICE_SAMBA_MODULE,
            {
                name: value
                for name, value in samba.items()
                if name != LEGACY_SAMBA_USERS_KEY
            },
        )
        is_moved = True

    podman = store.read(key, DEVICE_PODMAN_MODULE)
    machine = podman.get(DEVICE_PODMAN_MACHINE_KEY)
    if isinstance(machine, dict) and DEVICE_INSTANCE_LOGIN_KEY in machine:
        note(
            str(machine.get("account", "") or ""),
            login_id=str(machine.get(DEVICE_INSTANCE_LOGIN_KEY, "") or ""),
        )
        podman[DEVICE_PODMAN_MACHINE_KEY] = {
            name: value
            for name, value in machine.items()
            if name != DEVICE_INSTANCE_LOGIN_KEY
        }
        store.write(key, DEVICE_PODMAN_MODULE, podman)
        is_moved = True

    hermes = store.read(key, DEVICE_HERMES_WEBUI_MODULE)
    if LEGACY_PORT_KEY in hermes:
        store.write(
            key,
            DEVICE_HERMES_WEBUI_MODULE,
            {name: value for name, value in hermes.items() if name != LEGACY_PORT_KEY},
        )
        is_moved = True

    ai_tools_path = store.directory_of(key) / DEVICE_AI_TOOLS_FILE
    if ai_tools_path.exists():
        setting = store.read(key, DEVICE_AI_TOOLS_FILE[: -len(".json")])
        if setting.get(LEGACY_AI_TOOLS_ENABLED_KEY) is True:
            configs = setting.get(LEGACY_AI_TOOLS_CONFIGS_KEY)
            for row in found.values():
                row["is_ai_tools_enabled"] = True
                if isinstance(configs, dict):
                    row["tool_configs"] = configs
        ai_tools_path.unlink()
        is_moved = True

    for row in found.values():
        accounts.add(key, DeviceAccount.from_dict(row))
    return is_moved
