"""The two state documents the hub pushes, and when it pushes them.

An agent's state is what its device is to host, composed from
``config/devices/<id>/``; a client's state is the published service list
resolved for the scope its socket arrived from, whether it is switched
off, the overlay's join material and the machines it may open a shell on,
each as far as its permission allows; every entry names the machine that
provides it. Both name every address the hub answers the channel on. Each
carries the hash the peer's reports name back; a client's is computed on the
resolved list, so the same list hashes differently for two scopes. An agent
is pushed its state on a connection's first report whose hash differs, a
client on any report whose hash differs; after that a push happens when the
hub's own copy changes, through the functions here.
"""

import hashlib
import json
import socket
from urllib.parse import urlsplit

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_AGENT
from neutrino_hub.modules.clients.constants import (
    CLIENT_PERMISSION_OVERLAY,
    CLIENT_PERMISSION_TERMINAL,
)
from neutrino_hub.modules.clients.permissions import (
    permitted_entries,
    permitted_kinds,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.collector import catalog_entries
from neutrino_hub.modules.services.constants import SERVICES_SOURCE_DECLARED
from neutrino_hub.modules.services.host_scope import (
    HostScope,
    link_scope,
    scope_of,
)
from neutrino_hub.web import channel_overlay
from neutrino_hub.web.channel_addresses import channel_urls


def agent_state(runtime, device_id: str) -> dict:
    """The ``state`` frame's body for one device.

    Args:
        runtime: The shared runtime.
        device_id: The device.

    Returns:
        ``{hash, modules, desktop}``.
    """
    state_hash, document = runtime.desired_state_for(device_id)
    return {"hash": state_hash, **document}


def client_state(runtime, client_id: str) -> dict:
    """The ``state`` frame's body for one client.

    Args:
        runtime: The shared runtime.
        client_id: The client; one that is switched off, or gone, is
            handed an empty list, and one that is on is handed the entries
            its permission allows, the overlay's join material when it is
            allowed ``overlay``, and the managed machines when it is allowed
            ``terminal``.

    Returns:
        ``{hash, is_disabled, services, urls, overlay, terminals}``.
    """
    registry = ClientRegistry()
    client = registry.get(client_id)
    is_disabled = client is None or client.is_disabled
    services = []
    overlay = None
    terminals = []
    if not is_disabled:
        kinds = permitted_kinds(registry, client)
        scope = runtime.client_scope.get(client_id) or link_scope("")
        services = permitted_entries(
            _named_entries(runtime, runtime.published_services.entries_for(scope)),
            kinds,
        )
        if CLIENT_PERMISSION_OVERLAY in kinds:
            overlay = channel_overlay.overlay_material(runtime)
        if CLIENT_PERMISSION_TERMINAL in kinds:
            terminals = _terminals(runtime)
    body = {
        "is_disabled": is_disabled,
        "services": services,
        "urls": channel_urls(runtime),
        "overlay": overlay,
        "terminals": terminals,
    }
    serialized = json.dumps(body, sort_keys=True).encode("utf-8")
    return {"hash": hashlib.sha256(serialized).hexdigest()[:16], **body}


def note_client_scope(
    runtime, client_id: str, *, peer_host: str, reached_host: str
) -> HostScope:
    """Settle and keep the scope a client's socket arrived from.

    Args:
        runtime: The shared runtime.
        client_id: The client.
        peer_host: Where its socket comes from.
        reached_host: The address it connected to.

    Returns:
        The scope.
    """
    scope = scope_of(peer_host, reached_host, runtime.host_scopes())
    runtime.client_scope[client_id] = scope
    return scope


def push_state(runtime, role: str, key: str) -> None:
    """Hand one binding its state now, from outside the loop.

    Args:
        runtime: The shared runtime.
        role: ``agent`` or ``client``.
        key: The binding.

    Raises:
        AgentOfflineError: When the binding has no channel.
        StreamRefusedError: When the socket did not take it in time.
    """
    _registry(runtime, role).push_state_from_thread(key, _compose(runtime, role, key))


def push_states(runtime, role: str) -> None:
    """Hand every live binding of one role its state, where it changed.

    Args:
        runtime: The shared runtime.
        role: ``agent`` or ``client``.
    """
    registry = _registry(runtime, role)
    served = runtime.host_scopes() if role != CHANNEL_ROLE_AGENT else []
    for session in registry.sessions():
        if role != CHANNEL_ROLE_AGENT:
            held = runtime.client_scope.get(session.key)
            runtime.client_scope[session.key] = scope_of(
                session.address, held.hub_address if held else "", served
            )
        document = _compose(runtime, role, session.key)
        if document["hash"] == session.offered_hash:
            continue
        registry.send_json_from_thread(session.key, {"type": "state", **document})
        session.offered_hash = document["hash"]


def _terminals(runtime) -> list:
    """Every managed machine, online or not, by its name and its presence."""
    return [
        {
            "device_id": device.id,
            "name": _device_name(runtime, device),
            "is_online": runtime.agent_sessions.is_online(device.id),
        }
        for device in DeviceRegistry().all_stored()
        if device.is_managed
    ]


def _named_entries(runtime, entries: list) -> list:
    """The catalog entries, each with ``device_name``: the machine providing it.

    An entry a device hosts names that device; one of the hub's own modules
    names the hub's machine; a declared record at a device's address names
    that device, and any other names nobody.
    """
    names = {}
    for device in DeviceRegistry().all_stored():
        names[device.id] = _device_name(runtime, device)
    by_address = {
        address: names[device_id]
        for device_id, address in runtime.device_address.items()
        if address and device_id in names
    }
    hub_machine = socket.gethostname()
    named = []
    for entry, catalog in zip(entries, catalog_entries(entries)):
        device_id = entry.get("device_id") or ""
        if device_id:
            device_name = names.get(device_id, "")
        elif entry.get("source") == SERVICES_SOURCE_DECLARED:
            device_name = by_address.get(_entry_host(entry), "")
        else:
            device_name = hub_machine
        named.append({**catalog, "device_name": device_name})
    return named


def _entry_host(entry: dict) -> str:
    """The host an entry's payload names, wherever its type keeps it."""
    payload = entry.get("payload") or {}
    for key in ("url", "endpoint"):
        if payload.get(key):
            return urlsplit(str(payload[key])).hostname or ""
    return str(payload.get("host", "") or "")


def _device_name(runtime, device) -> str:
    """What the hub calls one device: its name, its hostname, its address."""
    return (
        device.name
        or runtime.device_hostname.get(device.id, "")
        or device.ipv4_address
        or device.id
    )


def _compose(runtime, role: str, key: str) -> dict:
    if role == CHANNEL_ROLE_AGENT:
        return agent_state(runtime, key)
    return client_state(runtime, key)


def _registry(runtime, role: str):
    if role == CHANNEL_ROLE_AGENT:
        return runtime.agent_sessions
    return runtime.client_sessions
