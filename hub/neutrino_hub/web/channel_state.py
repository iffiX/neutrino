"""The two state documents the hub pushes, and when it pushes them.

An agent's state is what its device is to host, composed from
``config/devices/<id>/``; a client's state is the published service list
resolved for the scope its socket arrived from, and whether it is switched
off. Each carries the hash the peer's reports name back; a client's is
computed on the resolved list, so the same list hashes differently for two
scopes. One push goes down on a connection's first report whose hash
differs; after that a push happens only when the hub's own copy changes,
through the functions here.
"""

import hashlib
import json

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_AGENT
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.services.collector import catalog_entries
from neutrino_hub.modules.services.host_scope import (
    HostScope,
    link_scope,
    scope_of,
)


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
            handed an empty list.

    Returns:
        ``{hash, is_disabled, services}``.
    """
    client = ClientRegistry().get(client_id)
    is_disabled = client is None or client.is_disabled
    services = []
    if not is_disabled:
        scope = runtime.client_scope.get(client_id) or link_scope("")
        services = catalog_entries(runtime.published_services.entries_for(scope))
    body = {"is_disabled": is_disabled, "services": services}
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


def _compose(runtime, role: str, key: str) -> dict:
    if role == CHANNEL_ROLE_AGENT:
        return agent_state(runtime, key)
    return client_state(runtime, key)


def _registry(runtime, role: str):
    if role == CHANNEL_ROLE_AGENT:
        return runtime.agent_sessions
    return runtime.client_sessions
