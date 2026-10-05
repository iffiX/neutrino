"""Closing at once what a client no longer holds.

A change on the Clients page holds for the next stream by itself, since every
``open`` is judged then. What is already open is closed here: the socket of a
client switched off or deleted; otherwise the ``shell`` streams of machines it
lost under ``terminal``, the ``connect`` streams whose kind or machine it lost,
the panel's forward among them, and its panel sessions once ``panel`` goes. A
stream closed this way ends with the refusal its next ``open`` would get. A
persistent or shared shell stays on its machine; only this client's stream to
it closes.

The routes run in the panel's request threads, and the streams live on the
channel's loop, so every close is handed onto the loop and waited for at most
``CHANNEL_CALL_TIMEOUT_S``.
"""

import logging

from neutrino_hub.exceptions import StreamRefusedError
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_DISABLED,
    CLIENT_CODE_PERMISSION_DENIED,
    CLIENT_PERMISSION_FILTERED_KINDS,
    CLIENT_PERMISSION_TERMINAL,
)
from neutrino_hub.modules.clients.permissions import (
    is_device_permitted,
    permitted_devices,
    permitted_kinds,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web.panel_sign_in import may_open_panel

LOGGER = logging.getLogger(__name__)


def close_lost_access(runtime, *, why: str) -> dict:
    """Close everything each client no longer holds, after a change.

    Args:
        runtime: The shared runtime, which holds the clients' sockets and the
            panel's sessions.
        why: What the hub's log says ended a panel session.

    Returns:
        What was closed, by client id: ``socket``, and the ids of the
        ``shell`` and ``connect`` streams, and ``panel_sessions``, each only
        where something was.
    """
    registry = ClientRegistry()
    closed: dict = {}
    for session in runtime.client_sessions.sessions():
        client = registry.get(session.key)
        if client is None:
            continue
        if client.is_disabled:
            _close_all(session)
            runtime.client_sessions.refuse_from_thread(
                session.key, CLIENT_CODE_DISABLED
            )
            closed.setdefault(session.key, {})["socket"] = True
            continue
        streams = _lost_streams(registry, client, session)
        for stream_id, kind in streams:
            _close(session, stream_id, CLIENT_CODE_PERMISSION_DENIED, {"kind": kind})
        if streams:
            closed.setdefault(session.key, {})["streams"] = [
                stream_id for stream_id, _ in streams
            ]
    for token, client_id in runtime.sessions.client_sessions():
        client = registry.get(client_id)
        if client is not None and may_open_panel(client):
            continue
        runtime.sessions.logout(token)
        name = client.name if client is not None else client_id
        LOGGER.info("panel: session of client %s ended (%s)", name, why)
        closed.setdefault(client_id, {}).setdefault("panel_sessions", 0)
        closed[client_id]["panel_sessions"] += 1
    return closed


def _lost_streams(registry, client, session) -> list:
    """The open streams of one client its permission no longer covers.

    Returns:
        ``(stream_id, kind)`` pairs, ``shell`` streams first.
    """
    kinds = permitted_kinds(registry, client)
    devices = permitted_devices(registry, client)
    lost = []
    for stream_id, bridged in dict(session.shells).items():
        device_id = bridged[0]
        if CLIENT_PERMISSION_TERMINAL not in kinds or not is_device_permitted(
            devices, CLIENT_PERMISSION_TERMINAL, device_id
        ):
            lost.append((stream_id, CLIENT_PERMISSION_TERMINAL))
    for stream_id, (kind, provider) in dict(session.connects).items():
        if not kind:
            continue
        if kind not in kinds or (
            kind in CLIENT_PERMISSION_FILTERED_KINDS
            and not is_device_permitted(devices, kind, provider)
        ):
            lost.append((stream_id, kind))
    return lost


def _close_all(session) -> None:
    """Close every stream a switched-off client opened with ``client_disabled``."""
    for stream_id in list(dict(session.shells)) + list(dict(session.connects)):
        _close(session, stream_id, CLIENT_CODE_DISABLED, {})


def _close(session, stream_id: int, code: str, params: dict) -> None:
    """Close one stream on the channel's loop, from a request thread."""
    try:
        session.close_stream_from_thread(stream_id, code, params)
    except (StreamRefusedError, RuntimeError) as error:
        LOGGER.warning(
            "client %s: stream %s did not close in time (%s)",
            session.key,
            stream_id,
            error,
        )
