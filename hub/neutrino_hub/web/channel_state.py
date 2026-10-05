"""The two state documents the hub pushes, and when it pushes them.

An agent's state is what its device is to host, composed from
``config/devices/<id>/``; a client's state is the published service list
resolved for the scope its socket arrived from, whether it is switched
off, the join material of every running overlay and the machines it may
open a shell on,
each as far as its permission allows, whether it may open the hub's panel
and the way its socket reached the hub; every entry names the machine that
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

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_AGENT
from neutrino_hub.modules.clients.constants import (
    CLIENT_PERMISSION_OVERLAY,
    CLIENT_PERMISSION_PANEL,
    CLIENT_PERMISSION_TERMINAL,
)
from neutrino_hub.modules.clients.permissions import (
    entry_device_id,
    entry_host,
    entry_machine_id,
    is_device_permitted,
    permitted_devices,
    permitted_entries,
    permitted_kinds,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.clients.services import device_owners
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.collector import catalog_entries
from neutrino_hub.modules.services.constants import SERVICES_SOURCE_DECLARED
from neutrino_hub.system.machine import machine_id
from neutrino_hub.modules.services.host_scope import (
    HostScope,
    link_scope,
    reached_through,
    scope_of,
)
from neutrino_hub.utils.peer_address import unmapped
from neutrino_hub.web import channel_overlay
from neutrino_hub.web.channel_addresses import channel_urls
from neutrino_hub.web.shell_bridge import client_owner, device_name, sessions_for


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
            its permission allows by kind and by the device providing them,
            the overlays' join material when it is allowed ``overlay``, and
            the managed machines its ``terminal`` permission allows, each
            with the sessions :func:`sessions_for` gives it there, and
            whether it may open the hub's panel.

    Returns:
        ``{hash, is_disabled, services, urls, overlays, terminals,
        is_panel_allowed, reached_through}``.
    """
    registry = ClientRegistry()
    client = registry.get(client_id)
    is_disabled = client is None or client.is_disabled
    services = []
    overlays = []
    terminals = []
    is_panel_allowed = False
    if not is_disabled:
        kinds = permitted_kinds(registry, client)
        devices = permitted_devices(registry, client)
        scope = runtime.client_scope.get(client_id) or link_scope("")
        own_machine_id = client.os_machine_id
        hub_device_id, device_ids_by_address = (
            device_owners(runtime) if devices or own_machine_id else ("", {})
        )
        allowed = [
            entry
            for entry in permitted_entries(
                runtime.published_services.entries_for(scope), kinds
            )
            if is_device_permitted(
                devices,
                entry["type"],
                entry_device_id(
                    entry,
                    hub_device_id=hub_device_id,
                    device_ids_by_address=device_ids_by_address,
                ),
            )
        ]
        services = _named_entries(runtime, allowed)
        _mark_own_machine(
            allowed,
            services,
            own_machine_id=own_machine_id,
            device_ids_by_address=device_ids_by_address,
        )
        if CLIENT_PERMISSION_OVERLAY in kinds:
            overlays = channel_overlay.overlay_materials(runtime)
        if CLIENT_PERMISSION_TERMINAL in kinds:
            terminals = [
                terminal
                for terminal in _terminals(runtime, client_owner(client_id))
                if is_device_permitted(
                    devices, CLIENT_PERMISSION_TERMINAL, terminal["device_id"]
                )
            ]
        is_panel_allowed = CLIENT_PERMISSION_PANEL in kinds
    body = {
        "is_disabled": is_disabled,
        "services": services,
        "urls": channel_urls(runtime),
        "overlays": overlays,
        "terminals": terminals,
        "is_panel_allowed": is_panel_allowed,
        "reached_through": runtime.client_reached.get(client_id, ""),
    }
    serialized = json.dumps(body, sort_keys=True).encode("utf-8")
    return {"hash": hashlib.sha256(serialized).hexdigest()[:16], **body}


def note_client_scope(
    runtime, client_id: str, *, peer_host: str, reached_host: str
) -> HostScope:
    """Settle and keep the scope a client's socket arrived from, and the
    way it reached the hub.

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
    is_ipv6 = ":" in unmapped(peer_host)
    runtime.client_reached[client_id] = reached_through(
        peer_host,
        runtime.overlay_networks(is_ipv6=is_ipv6),
        runtime.interface_networks(is_ipv6=is_ipv6),
    )
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


def _terminals(runtime, viewer: str) -> list:
    """Every managed machine, online or not, by its name, its presence and
    the shell sessions the viewer sees on it, oldest first."""
    held: dict = {}
    for session in sessions_for(runtime, viewer):
        held.setdefault(session["device_id"], []).append(session)
    return [
        {
            "device_id": device.id,
            "name": device_name(runtime, device),
            "is_online": runtime.agent_sessions.is_online(device.id),
            "sessions": held.get(device.id, []),
        }
        for device in DeviceRegistry().all_stored()
        if device.is_managed
    ]


def _named_entries(runtime, entries: list) -> list:
    """The catalog entries, each with ``device_id`` and ``device_name``: the
    machine providing it.

    An entry a device hosts names that device by its id and its name; one of
    the hub's own modules names the hub's machine; a declared record at a
    device's address names that device, and any other names nobody. Only an
    entry a managed machine provides carries an id; every other carries an
    empty one.
    """
    names = {}
    for device in DeviceRegistry().all_stored():
        names[device.id] = device_name(runtime, device)
    by_address = {
        address: names[device_id]
        for device_id, address in runtime.device_address.items()
        if address and device_id in names
    }
    hub_machine = socket.gethostname()
    named = []
    for entry, catalog in zip(entries, catalog_entries(entries)):
        device_id = entry.get("device_id") or ""
        if entry.get("source") == SERVICES_SOURCE_DECLARED:
            device_id = ""
        if device_id:
            provider = names.get(device_id, "")
        elif entry.get("source") == SERVICES_SOURCE_DECLARED:
            provider = by_address.get(entry_host(entry), "")
        else:
            provider = hub_machine
        named.append({**catalog, "device_id": device_id, "device_name": provider})
    return named


def _mark_own_machine(
    entries: list, named: list, *, own_machine_id: str, device_ids_by_address: dict
) -> None:
    """Set ``is_own_machine`` on each named entry: whether the client's machine
    provides it; false on every one while the client names no machine."""
    if not own_machine_id:
        for composed in named:
            composed["is_own_machine"] = False
        return
    hub_machine_id = machine_id()
    machine_ids_by_device = {
        device.id: device.machine_id for device in DeviceRegistry().all_stored()
    }
    for entry, composed in zip(entries, named):
        composed["is_own_machine"] = (
            entry_machine_id(
                entry,
                hub_machine_id=hub_machine_id,
                device_ids_by_address=device_ids_by_address,
                machine_ids_by_device=machine_ids_by_device,
            )
            == own_machine_id
        )


def _compose(runtime, role: str, key: str) -> dict:
    if role == CHANNEL_ROLE_AGENT:
        return agent_state(runtime, key)
    return client_state(runtime, key)


def _registry(runtime, role: str):
    if role == CHANNEL_ROLE_AGENT:
        return runtime.agent_sessions
    return runtime.client_sessions
