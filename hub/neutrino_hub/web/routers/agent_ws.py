"""The agent channel's one socket.

An agent connects, says ``hello`` with its token, and keeps the socket open
for as long as it runs. Everything live rides it: the machine's reports up,
the hub's desired state and every stream down. The socket is served on the
agent TLS port beside the enrollment routes and nowhere else.

The hub relies on the server's protocol-level ping for liveness; the agent
answers pongs and treats silence as a dead socket.
"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from neutrino_hub import HUB_VERSION
from neutrino_hub.modules.devices.agent_reports import (
    record_hello,
    record_offline,
    record_report,
)
from neutrino_hub.modules.devices.agent_sessions import AgentSession
from neutrino_hub.modules.devices.constants import (
    AGENT_WS_CLOSE_BAD_HELLO,
    AGENT_WS_CLOSE_REFUSED,
    AGENT_WS_CLOSE_UNKNOWN_TOKEN,
    AGENT_WS_HELLO_TIMEOUT_S,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.constants import WEB_EVENT_DEVICE_REPORT, WEB_EVENT_METRICS
from neutrino_hub.web.routers.agent import version_refusal

router = APIRouter(prefix="/api/agent")

# What a report has to change before the panel refetches the device list.
# Metrics are not among them: every beat carries them, and they ride their
# own event to the tiles and the monitor rather than costing a request.
REPORT_PANEL_FIELDS = ("modules", "rdp", "last_error")


@router.websocket("/ws")
async def agent_socket(websocket: WebSocket) -> None:
    """Serve one agent's channel from its hello to its last frame.

    Args:
        websocket: The agent's socket.
    """
    runtime = websocket.app.state.runtime
    await websocket.accept()
    hello = await read_hello(websocket)
    if hello is None:
        await websocket.close(code=AGENT_WS_CLOSE_BAD_HELLO, reason="bad_hello")
        return
    registry = DeviceRegistry()
    device = await asyncio.to_thread(
        registry.find_by_client_token, str(hello.get("token", ""))
    )
    if device is None:
        await websocket.close(code=AGENT_WS_CLOSE_UNKNOWN_TOKEN, reason="unknown_token")
        return
    refusal = version_refusal(
        str(hello.get("client_version", "") or ""), wire_of(hello.get("wire"))
    )
    if refusal is not None:
        await websocket.close(code=AGENT_WS_CLOSE_REFUSED, reason=refusal["code"])
        return

    session = AgentSession(
        key=device.mac_address,
        websocket=websocket,
        loop=asyncio.get_running_loop(),
        hostname=str(hello.get("hostname", "") or ""),
        platform=hello.get("platform") or {},
        address=peer_host(websocket),
        version=str(hello.get("client_version", "") or ""),
    )
    await runtime.agent_sessions.attach(session)
    try:
        record_hello(
            runtime,
            device,
            hello,
            peer_host=peer_host(websocket),
            reached_host=websocket.url.hostname or "",
        )
        state_hash, desired = await asyncio.to_thread(runtime.desired_state_for, device)
        await session.send_json(
            {
                "type": "welcome",
                "hub_version": HUB_VERSION,
                "device_id": device.mac_address,
                "state_hash": state_hash,
            }
        )
        # A machine holding another state than the one composed for it is
        # handed the whole state at once, before it asks.
        if str(hello.get("state_hash", "") or "") != state_hash:
            await session.send_json(
                {"type": "state", "hash": state_hash, "desired": desired}
            )
        await _serve(websocket, runtime, session, device)
    except WebSocketDisconnect:
        pass
    finally:
        if runtime.agent_sessions.detach(session):
            record_offline(runtime, device)


async def _serve(websocket: WebSocket, runtime, session: AgentSession, device):
    """Read frames until the socket ends.

    Args:
        websocket: The agent's socket.
        runtime: The shared runtime.
        session: The attached session.
        device: The device the token resolved to.
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        data = message.get("bytes")
        if data is not None:
            session.dispatch_bytes(data)
            continue
        decoded = decode_frame(message.get("text"))
        if decoded is None:
            continue
        kind = decoded.get("type")
        if kind == "report":
            is_panel_change = _is_panel_change(session.report, decoded)
            is_module_change = session.report.get("modules") != decoded.get("modules")
            session.record_report(decoded)
            await asyncio.to_thread(record_report, runtime, device, decoded)
            if is_module_change:
                runtime.published_services.schedule_refresh()
            if is_panel_change:
                runtime.events.publish(WEB_EVENT_DEVICE_REPORT, device.mac_address)
            runtime.events.publish(
                WEB_EVENT_METRICS,
                device.mac_address,
                data=dict(runtime.client_metrics.get(device.mac_address, {})),
            )
        elif kind == "state_request":
            state_hash, desired = await asyncio.to_thread(
                runtime.desired_state_for, device
            )
            await session.send_json(
                {"type": "state", "hash": state_hash, "desired": desired}
            )
        else:
            session.dispatch_text(decoded)


def _is_panel_change(previous: dict, report: dict) -> bool:
    """Whether a report says anything new about what the panel draws.

    Args:
        previous: The report before this one, empty for the first.
        report: The report that just arrived.

    Returns:
        True when one of :data:`REPORT_PANEL_FIELDS` differs.
    """
    return any(
        previous.get(field) != report.get(field) for field in REPORT_PANEL_FIELDS
    )


async def read_hello(websocket: WebSocket) -> "dict | None":
    """The socket's first frame, which must be a hello in time.

    Args:
        websocket: The agent's socket.

    Returns:
        The hello, or None when the first frame is late, not text, not an
        object, or not a hello.
    """
    try:
        message = await asyncio.wait_for(websocket.receive(), AGENT_WS_HELLO_TIMEOUT_S)
    except asyncio.TimeoutError:
        return None
    if message["type"] == "websocket.disconnect":
        return None
    decoded = decode_frame(message.get("text"))
    if decoded is None or decoded.get("type") != "hello":
        return None
    return decoded


def decode_frame(text: "str | None") -> "dict | None":
    """One text frame as the object it carries, or None."""
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def wire_of(value) -> int:
    """The generation a hello names; anything unreadable reads as zero."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def peer_host(websocket: WebSocket) -> str:
    """Where the socket comes from, empty when the transport names none."""
    client = websocket.client
    return client.host if client is not None else ""
