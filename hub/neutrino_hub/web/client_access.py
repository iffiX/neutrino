"""Closing at once what a client no longer holds.

A change on the Clients page holds for the next stream by itself, since every
``open`` is judged then. What is already open is closed here, through the
transport: the session of a client switched off or deleted, with
``session_close``; otherwise its streams of each kind it lost, and of each
machine it lost under a kind, with ``streams_close``, the panel's forward
among them; and its panel sessions once ``panel`` goes (protocol.md, "The
hub's local channel"). A stream closed this way ends with the refusal its
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
    CLIENT_PERMISSION_FILTERED_KINDS,
    CLIENT_PERMISSION_KINDS,
    CLIENT_PERMISSION_PANEL,
)
from neutrino_hub.modules.clients.permissions import (
    is_device_permitted,
    permitted_devices,
    permitted_kinds,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
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
        ``(kind, device_id)`` pairs whose streams were asked closed, an
        empty device for every machine, and ``panel_sessions``, each only
        where something was.
    """
    registry = ClientRegistry()
    closed: dict = {}
    device_ids = [device.id for device in DeviceRegistry().all_stored()]
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
        lost = _lost_kinds(registry, client, device_ids)
        for kind, device_id in lost:
            if not runtime.client_sessions.close_streams_from_thread(
                session.key,
                kind=kind,
                device_id=device_id,
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


def _lost_kinds(registry, client, device_ids: list) -> list:
    """The kinds and machines one client's permission no longer covers.

    Returns:
        ``(kind, device_id)`` pairs: a kind the client lost whole with an
        empty device, and for a kind kept with a device list, each stored
        machine outside the list.
    """
    kinds = permitted_kinds(registry, client)
    devices = permitted_devices(registry, client)
    lost = []
    for kind in CLIENT_PERMISSION_KINDS:
        if kind == CLIENT_PERMISSION_PANEL:
            continue
        if kind not in kinds:
            lost.append((kind, ""))
            continue
        if kind not in CLIENT_PERMISSION_FILTERED_KINDS or not devices.get(kind):
            continue
        for device_id in device_ids:
            if not is_device_permitted(devices, kind, device_id):
                lost.append((kind, device_id))
    if CLIENT_PERMISSION_PANEL not in kinds:
        lost.append((CLIENT_PERMISSION_PANEL, ""))
    return lost
