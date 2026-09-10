"""The client channel's one socket.

A client connects, says ``hello`` with its token, and keeps the socket open
for as long as it runs. Down come the welcome, the catalog when the
client's copy is stale, the gateway credential, and the switch when the
admin toggles it; up come asks, each answered on the same socket. Served
on the agent TLS port beside the agent's socket and nowhere else.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from neutrino_hub.modules.clients.constants import CLIENT_ENROLLMENT_KIND
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.agent_sessions import AgentSession
from neutrino_hub.modules.devices.constants import (
    AGENT_SESSION_KIND_CLIENT,
    AGENT_WS_CLOSE_BAD_HELLO,
    AGENT_WS_CLOSE_REFUSED,
    AGENT_WS_CLOSE_UNKNOWN_TOKEN,
)
from neutrino_hub.web import client_channel
from neutrino_hub.web.routers.agent_ws import decode_frame, peer_host, read_hello
from neutrino_hub.web.routers.client import client_version_refusal

router = APIRouter(prefix="/api/client")


@router.websocket("/ws")
async def client_socket(websocket: WebSocket) -> None:
    """Serve one client's channel from its hello to its last frame.

    Args:
        websocket: The client's socket.
    """
    runtime = websocket.app.state.runtime
    await websocket.accept()
    hello = await read_hello(websocket)
    if hello is None or hello.get("kind") != CLIENT_ENROLLMENT_KIND:
        await websocket.close(code=AGENT_WS_CLOSE_BAD_HELLO, reason="bad_hello")
        return
    registry = ClientRegistry()
    client = await asyncio.to_thread(
        registry.find_by_token, str(hello.get("token", ""))
    )
    if client is None:
        await websocket.close(code=AGENT_WS_CLOSE_UNKNOWN_TOKEN, reason="unknown_token")
        return
    version = str(hello.get("client_version", "") or "")
    refusal = client_version_refusal(version)
    if refusal is not None:
        await websocket.close(code=AGENT_WS_CLOSE_REFUSED, reason=refusal["code"])
        return

    session = AgentSession(
        key=client.id,
        kind=AGENT_SESSION_KIND_CLIENT,
        websocket=websocket,
        loop=asyncio.get_running_loop(),
        hostname=str(hello.get("hostname", "") or ""),
        platform=hello.get("platform") or {},
        address=peer_host(websocket),
        version=version,
    )
    session.state_hash = str(hello.get("catalog_hash", "") or "")
    await runtime.client_sessions.attach(session)
    try:
        await asyncio.to_thread(
            registry.record_seen,
            client.id,
            hostname=session.hostname,
            platform=session.platform,
            version=version,
        )
        client_channel.resolve_client_host(
            runtime,
            client.id,
            peer_host=session.address,
            reached_host=websocket.url.hostname or "",
        )
        await session.send_json(client_channel.welcome_frame(client))
        catalog = client_channel.client_catalog(runtime, client)
        if catalog["hash"] != session.state_hash:
            session.state_hash = catalog["hash"]
            await session.send_json(catalog)
        await session.send_json(
            await asyncio.to_thread(client_channel.client_ai, runtime, registry, client)
        )
        await _serve(websocket, runtime, session)
    except WebSocketDisconnect:
        pass
    finally:
        runtime.client_sessions.detach(session)


async def _serve(websocket: WebSocket, runtime, session: AgentSession) -> None:
    """Read frames until the socket ends, answering each ask.

    Args:
        websocket: The client's socket.
        runtime: The shared runtime.
        session: The attached session.
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        decoded = decode_frame(message.get("text"))
        if decoded is None or decoded.get("type") != "ask":
            continue
        reply = await asyncio.to_thread(
            client_channel.answer, runtime, session.key, decoded
        )
        await session.send_json(reply)
