"""The file share's folder shares, as ``samba.json`` stores them.

A folder share is ``{name, path, accounts}``: a share the person names, at a
folder on the machine, open to the enabled accounts checked for it, in the
file share's order (file_share.md). Its name is compared without case with
every other share name of the machine. Pure functions over the stored file;
the routes and the store write it.
"""

import re

from neutrino_hub.modules.devices.constants import (
    DEVICE_FOLDER_SHARE_NAME_PATTERN,
    DEVICE_FOLDER_SHARE_RESERVED_NAMES,
    DEVICE_SAMBA_SHARES_KEY,
)
from neutrino_hub.modules.services.file_ids import folder_share_entry_id


def folder_shares(stored: dict) -> list:
    """The folder shares a ``samba.json`` stores, in the order they were added.

    Args:
        stored: The file share's file.

    Returns:
        A fresh ``{name, path, accounts}`` per share; a record of another
        shape is left out.
    """
    shares = []
    for record in (stored or {}).get(DEVICE_SAMBA_SHARES_KEY) or []:
        if not isinstance(record, dict) or not record.get("name"):
            continue
        accounts = record.get("accounts")
        shares.append(
            {
                "name": str(record["name"]),
                "path": str(record.get("path", "") or ""),
                "accounts": [
                    str(account)
                    for account in (accounts if isinstance(accounts, list) else [])
                    if account
                ],
            }
        )
    return shares


def find_folder_share(stored: dict, name: str) -> "dict | None":
    """One folder share by its name.

    Args:
        stored: The file share's file.
        name: The share's name, as it was saved.

    Returns:
        The share, or None when the file stores none of that name.
    """
    for share in folder_shares(stored):
        if share["name"] == name:
            return share
    return None


def is_share_name_valid(name: str) -> bool:
    """Whether a name can name a folder share.

    Args:
        name: The name the person typed.

    Returns:
        True for 1 to 64 letters, digits, ``-``, ``_`` and ``.``, other than
        ``global``, ``homes`` and ``printers`` in any case.
    """
    if not re.fullmatch(DEVICE_FOLDER_SHARE_NAME_PATTERN, name):
        return False
    return name.lower() not in DEVICE_FOLDER_SHARE_RESERVED_NAMES


def is_share_name_taken(
    name: str,
    accounts: list,
    *,
    device_id: str,
    available: list,
    shares: list,
) -> bool:
    """Whether another share of the machine takes a folder share's name.

    Args:
        name: The folder share's name.
        accounts: The accounts checked for it.
        device_id: The machine, for the entries' ids.
        available: The machine's available accounts' names. Each takes a
            Home share of its own name once it is enabled.
        shares: The machine's other folder shares.

    Returns:
        True when an available account or another folder share has the name
        without regard to case, or when one of its entries' ids is another
        folder share entry's.
    """
    lowered = name.lower()
    if any(str(account).lower() == lowered for account in available):
        return True
    if any(share["name"].lower() == lowered for share in shares):
        return True
    taken = {
        folder_share_entry_id(device_id, share["name"], account)
        for share in shares
        for account in share["accounts"]
    }
    return any(
        folder_share_entry_id(device_id, name, account) in taken for account in accounts
    )


def in_file_share_order(accounts: list, enabled: list) -> list:
    """Checked accounts in the order the file share enables them.

    Args:
        accounts: The accounts checked for a folder share.
        enabled: The file share's enabled accounts, in their order.

    Returns:
        Each checked account that is enabled, once, in ``enabled``'s order.
    """
    checked = set(accounts)
    return [account for account in enabled if account in checked]


def with_folder_share(stored: dict, share: dict) -> dict:
    """The file with one folder share added, or replaced under its name.

    Args:
        stored: The file share's file.
        share: ``{name, path, accounts}``.

    Returns:
        A new file. A replaced share keeps its place in the order.
    """
    shares = folder_shares(stored)
    for index, held in enumerate(shares):
        if held["name"] == share["name"]:
            shares[index] = dict(share)
            break
    else:
        shares.append(dict(share))
    return dict(stored or {}, **{DEVICE_SAMBA_SHARES_KEY: shares})


def without_folder_share(stored: dict, name: str) -> dict:
    """The file with one folder share taken out.

    Args:
        stored: The file share's file.
        name: The share's name.

    Returns:
        A new file.
    """
    shares = [share for share in folder_shares(stored) if share["name"] != name]
    return dict(stored or {}, **{DEVICE_SAMBA_SHARES_KEY: shares})


def with_accounts_only(stored: dict, enabled: list) -> dict:
    """The file with every folder share narrowed to the enabled accounts.

    Args:
        stored: The file share's file.
        enabled: The accounts the file share enables.

    Returns:
        A new file. A share left with no account stays in it.
    """
    if DEVICE_SAMBA_SHARES_KEY not in (stored or {}):
        return dict(stored or {})
    shares = [
        dict(share, accounts=in_file_share_order(share["accounts"], enabled))
        for share in folder_shares(stored)
    ]
    return dict(stored, **{DEVICE_SAMBA_SHARES_KEY: shares})
