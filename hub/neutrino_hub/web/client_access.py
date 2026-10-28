"""Closing at once what a client no longer holds.

A change on the Clients page holds for the next stream by itself, since every
``open`` is judged then. What is already open is closed here, through the
transport: the session of a client switched off or deleted, with
``session_close``; otherwise its streams of each kind it lost, of each
machine it lost under a kind and of each row it lost, with
``streams_close``, the panel's forward among them; and its panel sessions
once ``panel`` goes (transport.md, "The hub's local channel"). A stream closed this way ends with the refusal its
next ``open`` would get. A persistent or shared shell stays on its machine;
only this client's stream to it closes.

The routes run in the panel's request threads, and the sessions live on the
channel's loop, so every close is handed onto the loop and waited for at most
``CHANNEL_CALL_TIMEOUT_S``.
"""

import logging

from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_DISABLED,
    CLIENT_CODE_PERMISSION_DENIED,
    CLIENT_PERMISSION_KINDS,
    CLIENT_PERMISSION_PANEL,
)
from neutrino_hub.modules.clients.permissions import (
    client_permission,
    is_device_permitted,
    is_permitted,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.clients.rows import permission_rows
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.panel_sign_in import may_open_panel

LOGGER = logging.getLogger(__name__)


def close_lost_access(runtime, *, why: str, names: "dict | None" = None) -> dict:
    """Close everything each client no longer holds, after a change.

    Args:
        runtime: The shared runtime, which holds the clients' sockets and the
            panel's sessions.
        why: What the hub's log says ended a panel session.
        names: Client id to name for clients whose row is already gone, so
            the log names them.

    Returns:
        What was closed, by client id: ``socket``, ``streams``, the
        ``(kind, device_id, row_id)`` triples whose streams were asked
        closed, an empty device for every machine and an empty row for
        every row, and ``panel_sessions``, each only where something was.
    """
    registry = ClientRegistry()
    closed: dict = {}
    device_ids = [device.id for device in DeviceRegistry().all_stored()]
    rows = None
    for session in runtime.client_sessions.sessions():
        client = registry.get(session.key)
        if client is None:
            continue
        if client.is_disabled:
            runtime.client_sessions.refuse_from_thread(
                session.key, CLIENT_CODE_DISABLED
            )
            closed.setdefault(session.key, {})["socket"] = True
            continue
        permission = client_permission(registry, client)
        if rows is None and permission.entries:
            rows = permission_rows(runtime)
        lost = lost_streams(permission, device_ids, rows or {})
        for kind, device_id, row_id in lost:
            if not runtime.client_sessions.close_streams_from_thread(
                session.key,
                kind=kind,
                device_id=device_id,
                row_id=row_id,
                code=CLIENT_CODE_PERMISSION_DENIED,
                params={"kind": kind},
            ):
                LOGGER.warning(
                    "client %s: its %s streams were not closed", session.key, kind
                )
        if lost:
            closed.setdefault(session.key, {})["streams"] = lost
    for token, client_id in runtime.sessions.client_sessions():
        client = registry.get(client_id)
        if client is not None and may_open_panel(client):
            continue
        runtime.sessions.logout(token)
        name = (
            client.name
            if client is not None
            else (names or {}).get(client_id, client_id)
        )
        LOGGER.info("panel: session of client %s ended (%s)", name, why)
        closed.setdefault(client_id, {}).setdefault("panel_sessions", 0)
        closed[client_id]["panel_sessions"] += 1
    return closed


def lost_streams(permission, device_ids: list, rows: dict) -> list:
    """The streams one permission no longer covers, as closes to ask for.

    A kind with no row set on is closed whole when it is off, and on each
    machine outside its list when it has one. A kind with a row set on is
    closed row by row, so the rows it keeps stay open.

    Args:
        permission: The :class:`ClientPermission` the client is held to.
        device_ids: Every stored device.
        rows: Kind to its rows from :func:`permission_rows`; needed only
            while ``entries`` names a row.

    Returns:
        ``(kind, device_id, row_id)`` triples, an empty device for every
        machine and an empty row for every row.
    """
    lost = []
    for kind in CLIENT_PERMISSION_KINDS:
        if kind == CLIENT_PERMISSION_PANEL:
            continue
        held = rows.get(kind) or []
        if any(permission.entries.get(row["id"]) is True for row in held):
            lost += [
                (kind, row["device_id"], row["id"])
                for row in held
                if not is_permitted(permission, kind, row["device_id"], row["id"])
            ]
            continue
        if kind not in permission.kinds:
            lost.append((kind, "", ""))
            continue
        if permission.devices.get(kind):
            lost += [
                (kind, device_id, "")
                for device_id in device_ids
                if not is_device_permitted(permission.devices, kind, device_id)
            ]
        lost += [
            (kind, row["device_id"], row["id"])
            for row in held
            if permission.entries.get(row["id"]) is False
            and is_device_permitted(permission.devices, kind, row["device_id"])
        ]
    if not is_permitted(permission, CLIENT_PERMISSION_PANEL):
        lost.append((CLIENT_PERMISSION_PANEL, "", ""))
    return lost
