"""The rows the fine mode of a permission lists under each kind.

A row is one thing a client reaches under one kind: an app with an entry of
that kind, a machine's SSH server, a share, a desktop or a managed machine.
Each is composed from what the hub publishes now, with its row id, its
title and the machine that provides it.
"""

import functools

from neutrino_hub.modules.clients.constants import (
    CLIENT_PERMISSION_ROW_KINDS,
    CLIENT_PERMISSION_TERMINAL,
)
from neutrino_hub.modules.clients.permissions import (
    entry_device_id,
    entry_row_id,
    terminal_row_id,
)
from neutrino_hub.modules.clients.services import device_owners
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.constants import SERVICES_APP_SOURCE_ORDER


def permission_rows(runtime) -> dict:
    """Every row of every kind that has rows, as the hub publishes now.

    Args:
        runtime: The shared runtime, for the published list and the
            devices' names.

    Returns:
        Kind to its rows, each ``{id, title, device_id, device_name}``,
        ``device_id`` the machine providing it and empty for none known.
        The apps' rows come in the Services page's order, then the shares
        and the desktops by machine, then the managed machines. Every kind
        of :data:`CLIENT_PERMISSION_ROW_KINDS` is a key.
    """
    entries, _ = runtime.published_services.entries()
    names = runtime.device_names()
    hub_device_id, device_ids_by_address = device_owners(runtime)
    apps = {app["id"]: app for app in runtime.published_services.apps()}
    rows = {kind: [] for kind in CLIENT_PERMISSION_ROW_KINDS}
    loose = {kind: [] for kind in CLIENT_PERMISSION_ROW_KINDS}
    seen = set()
    for entry in sorted(entries, key=functools.partial(_app_rank, apps)):
        kind = entry.get("type")
        row_id = entry_row_id(entry)
        if kind not in rows or not row_id or (kind, row_id) in seen:
            continue
        seen.add((kind, row_id))
        provider = entry_device_id(
            entry,
            hub_device_id=hub_device_id,
            device_ids_by_address=device_ids_by_address,
        )
        app = apps.get(str(entry.get("app_id") or ""))
        row = {
            "id": row_id,
            "title": app["title"] if app is not None else _loose_title(entry),
            "device_id": provider,
            "device_name": names.get(provider, ""),
        }
        (rows if app is not None else loose)[kind].append(row)
    for kind, held in loose.items():
        rows[kind] += sorted(held, key=_machine_rank)
    for device in DeviceRegistry().all_stored():
        if device.is_managed:
            rows[CLIENT_PERMISSION_TERMINAL].append(
                {
                    "id": terminal_row_id(device.id),
                    "title": names.get(device.id, device.id),
                    "device_id": device.id,
                    "device_name": names.get(device.id, ""),
                }
            )
    return rows


def _app_rank(apps: dict, entry: dict) -> tuple:
    """Where an entry's app stands in the Services page's order."""
    app = apps.get(str(entry.get("app_id") or ""))
    if app is None:
        return (len(SERVICES_APP_SOURCE_ORDER) + 1, "")
    source = app["source"]
    if source in SERVICES_APP_SOURCE_ORDER:
        return (SERVICES_APP_SOURCE_ORDER.index(source), str(app["title"]).lower())
    return (len(SERVICES_APP_SOURCE_ORDER), str(app["title"]).lower())


def _machine_rank(row: dict) -> tuple:
    """A row of no app, ordered by its machine and then its title."""
    return (row["device_name"].lower(), row["title"].lower())


def _loose_title(entry: dict) -> str:
    """The title of a row of no app: a share's name, else the entry's title."""
    share = (entry.get("payload") or {}).get("share")
    return str(share or entry.get("title", "") or "")
