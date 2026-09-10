"""What the hub hands a client over its socket, and what it answers.

A client's socket carries four frames down — ``welcome``, ``catalog``,
``ai`` and ``disabled`` — and one exchange up, an ``ask`` answered by an
``answer``. The frames are composed here from the runtime: the published
list resolved for the address the client reaches the hub on, the gateway
credential minted for it, and its record. The panel's toggles and the
published list's fingerprint push through here too, so the socket handler
and the routes cannot compose a frame differently.
"""

from neutrino_hub import HUB_VERSION
from neutrino_hub.modules.clients.ai_keys import client_credential
from neutrino_hub.modules.clients.asks import answer_ask, catalog_frame
from neutrino_hub.modules.clients.registry import Client, ClientRegistry
from neutrino_hub.modules.devices.agent_reports import device_host
from neutrino_hub.modules.services.collector import catalog_entries


def welcome_frame(client: Client) -> dict:
    """The first frame a client reads after its hello."""
    return {
        "type": "welcome",
        "hub_version": HUB_VERSION,
        "client_id": client.id,
        "is_disabled": client.is_disabled,
    }


def disabled_frame(client: Client) -> dict:
    """The frame that tells a client the admin switched it off or on."""
    return {"type": "disabled", "is_disabled": client.is_disabled}


def resolve_client_host(
    runtime, client_id: str, *, peer_host: str, reached_host: str
) -> str:
    """Settle and keep the address a client reaches the hub on.

    Args:
        runtime: The shared runtime.
        client_id: The client.
        peer_host: Where its socket comes from.
        reached_host: The address it connected to.

    Returns:
        The bare address.
    """
    host = device_host(runtime, peer_host, reached_host)
    runtime.client_catalog_host[client_id] = host
    return host


def client_catalog(runtime, client: Client) -> dict:
    """The catalog frame for one client, resolved for its host.

    Args:
        runtime: The shared runtime.
        client: The client; a disabled one is handed an empty list.

    Returns:
        ``{type: "catalog", hash, services}``.
    """
    host = runtime.client_catalog_host.get(client.id, "")
    services = catalog_entries(runtime.published_services.entries_for(host))
    return catalog_frame(services, is_disabled=client.is_disabled)


def client_ai(runtime, registry: ClientRegistry, client: Client) -> dict:
    """The credential frame for one client, null while it has none.

    Args:
        runtime: The shared runtime.
        registry: The client records, for the key id a mint writes.
        client: The client.

    Returns:
        ``{type: "ai", credential}``.
    """
    credential = client_credential(
        registry,
        client,
        hub_host=runtime.client_catalog_host.get(client.id, ""),
        served_models=runtime.served_models,
    )
    return {"type": "ai", "credential": credential}


def answer(runtime, client_id: str, ask: dict) -> dict:
    """Answer one ask from a client, judged against its record right now.

    Args:
        runtime: The shared runtime.
        client_id: The asking client.
        ask: The decoded frame.

    Returns:
        The answer frame.
    """
    client = ClientRegistry().get(client_id)
    return answer_ask(
        ask,
        is_disabled=client is None or client.is_disabled,
        shares=runtime.device_shares.live(),
        seat_password_of=runtime.desired_states.seat_password,
    )


def push_client_state(runtime, client_id: str) -> None:
    """Hand a client its switch, credential and catalog after a toggle.

    Args:
        runtime: The shared runtime.
        client_id: The client; one with no live socket is left alone.
    """
    registry = ClientRegistry()
    client = registry.get(client_id)
    session = runtime.client_sessions.get(client_id)
    if client is None or session is None:
        return
    sessions = runtime.client_sessions
    sessions.send_json_from_thread(client_id, disabled_frame(client))
    sessions.send_json_from_thread(client_id, client_ai(runtime, registry, client))
    _push_catalog(runtime, session, client)


def push_catalogs(runtime) -> None:
    """Hand every client whose catalog composes differently the new one.

    Args:
        runtime: The shared runtime.
    """
    registry = ClientRegistry()
    for session in runtime.client_sessions.sessions():
        client = registry.get(session.key)
        if client is None:
            continue
        runtime.client_catalog_host[client.id] = device_host(
            runtime,
            session.address,
            runtime.client_catalog_host.get(client.id, ""),
        )
        _push_catalog(runtime, session, client)


def push_ai(runtime) -> None:
    """Hand every live client its credential again.

    Args:
        runtime: The shared runtime.
    """
    registry = ClientRegistry()
    for session in runtime.client_sessions.sessions():
        client = registry.get(session.key)
        if client is None:
            continue
        runtime.client_sessions.send_json_from_thread(
            client.id, client_ai(runtime, registry, client)
        )


def _push_catalog(runtime, session, client: Client) -> None:
    """Send the catalog when its hash is not the one the session holds."""
    frame = client_catalog(runtime, client)
    if frame["hash"] == session.state_hash:
        return
    session.state_hash = frame["hash"]
    runtime.client_sessions.send_json_from_thread(client.id, frame)
