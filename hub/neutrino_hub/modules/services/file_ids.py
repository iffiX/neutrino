"""The ids of a machine's file entries, and of their rows in a permission.

A Home share has one entry, ``samba_<device id>_<share>``, which is also its
row. A folder share has one entry per account checked for it,
``samba_folder_<device id>_<share>_<account>``, and one row for all of them,
the folder share's id ``samba_folder_<device id>_<share>``. Pure functions.
"""

from neutrino_hub.modules.services.constants import (
    SERVICES_FOLDER_SHARE_ID_PREFIX,
    SERVICES_HOME_SHARE_ID_PREFIX,
    SERVICES_TYPE_FILE,
)


def home_share_entry_id(device_id: str, share: str) -> str:
    """The id of a Home share's entry.

    Args:
        device_id: The machine that serves the share.
        share: The share's name, its account's.

    Returns:
        ``samba_<device id>_<share>``.
    """
    return f"{SERVICES_HOME_SHARE_ID_PREFIX}{device_id}_{share}"


def folder_share_id(device_id: str, share: str) -> str:
    """The id of a folder share, its row in a permission.

    Args:
        device_id: The machine that serves the share.
        share: The folder share's name.

    Returns:
        ``samba_folder_<device id>_<share>``.
    """
    return f"{SERVICES_FOLDER_SHARE_ID_PREFIX}{device_id}_{share}"


def folder_share_entry_id(device_id: str, share: str, account: str) -> str:
    """The id of a folder share's entry for one of its accounts.

    Args:
        device_id: The machine that serves the share.
        share: The folder share's name.
        account: The account the entry logs in as.

    Returns:
        ``samba_folder_<device id>_<share>_<account>``.
    """
    return f"{folder_share_id(device_id, share)}_{account}"


def file_row_id(entry: dict) -> str:
    """The row a ``file`` entry of no app is judged by in a permission.

    Args:
        entry: A published entry.

    Returns:
        The folder share's id for an entry of a folder share, whose payload
        names an ``account``. The entry's own id for any other entry.
    """
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    account = str(payload.get("account", "") or "")
    device_id = str(entry.get("device_id", "") or "")
    if entry.get("type") != SERVICES_TYPE_FILE or not account or not device_id:
        return str(entry.get("id", "") or "")
    return folder_share_id(device_id, str(payload.get("share", "") or ""))
