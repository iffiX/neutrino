"""The legacy listener's routes: a 0.5 agent's channel and the key move.

Every peer of 0.6.0 is on the transport. These two routes are served over
the agent TLS pair on ``127.0.0.1`` alone, behind the
``is_legacy_channel_enabled`` switch: the PROTOCOL 3 channel of a 0.5 agent,
admitted for its own update and nothing else, and ``POST
/api/channel/key/set``, through which an updated agent or client records its
static public key on its binding and takes the hub's (protocol.md, "An
agent of 0.5").
"""

import asyncio
import contextlib

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError

from neutrino_hub.modules.channel.admission import is_update_only
from neutrino_hub.modules.channel.bindings import resolve_token
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CLOSE_REFUSED,
    CHANNEL_CODE_BINDING_UNKNOWN,
    CHANNEL_CODE_CHANNEL_FULL,
    CHANNEL_CODE_HELLO_INVALID,
    CHANNEL_CODE_PROTOCOL_TOO_NEW,
    CHANNEL_CODE_ROLE_MISMATCH,
    CHANNEL_FRAME_HELLO,
    CHANNEL_FRAME_REFUSED,
    CHANNEL_HELLO_TIMEOUT_S,
    CHANNEL_ROLE_AGENT,
    PROTOCOL,
)
from neutrino_hub.modules.channel.legacy_sessions import LegacyChannelSession
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.transport.ops import read_public_key
from neutrino_hub.utils.peer_address import unmapped
from neutrino_hub.web import legacy_serve
from neutrino_hub.web.channel_serve import welcome_frame
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.legacy_serve import decode_frame
from neutrino_hub.web.models import (
    LegacyHello,
    LegacyKeySetRequest,
    LegacyKeySetView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/channel", tags=["channel"])


@router.post("/key/set", response_model=LegacyKeySetView)
def set_key(
    request: LegacyKeySetRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> LegacyKeySetView:
    """Record an updated peer's static public key on its binding, once.

    Args:
        request: The binding's id and token, and the peer's new key.
        runtime: The shared runtime.

    Returns:
        The hub's static public key, which the peer knocks with from now on.

    Raises:
        HTTPException: 401 ``binding_unknown`` when the token names no
            binding with that id, which ends the binding on the peer; 409
            ``transport_key_missing`` when the transport has made no key yet.
    """
    binding = resolve_token(request.token)
    if binding is None or binding.id != request.id:
        runtime.channel_port.record_failure()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": CHANNEL_CODE_BINDING_UNKNOWN, "params": {}},
        )
    try:
        hub_key = read_public_key()
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "transport_key_missing", "params": {}},
        ) from error
    if binding.role == CHANNEL_ROLE_AGENT:
        DeviceRegistry().set_public_key(binding.id, request.public_key)
    else:
        ClientRegistry().set_public_key(binding.id, request.public_key)
    return LegacyKeySetView(key=hub_key)


@router.websocket("/socket")
async def socket(websocket: WebSocket) -> None:
    """Serve a 0.5 agent's channel for its own update, from hello to last frame.

    Args:
        websocket: The agent's socket.
    """
    runtime = websocket.app.state.runtime
    await websocket.accept()
    hello = await _read_hello(websocket)
    if hello is None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.send_json(
                {
                    "type": CHANNEL_FRAME_REFUSED,
                    "code": CHANNEL_CODE_HELLO_INVALID,
                    "params": {},
                }
            )
        with contextlib.suppress(RuntimeError):
            await websocket.close(
                code=CHANNEL_CLOSE_REFUSED, reason=CHANNEL_CODE_HELLO_INVALID
            )
        return
    session = LegacyChannelSession(
        key=hello.id,
        role=hello.role,
        websocket=websocket,
        loop=asyncio.get_running_loop(),
        name=hello.name,
        software=hello.software,
        address=_peer_host(websocket),
    )
    if not is_update_only(hello.role, hello.protocol):
        # Every peer of this hub's own number knocks on the transport; a
        # number above it is one this hub does not read.
        code = (
            CHANNEL_CODE_PROTOCOL_TOO_NEW
            if hello.protocol > PROTOCOL
            else CHANNEL_CODE_HELLO_INVALID
        )
        await session.refuse(code, {})
        return
    binding = await asyncio.to_thread(resolve_token, hello.token)
    if binding is None or binding.id != hello.id:
        runtime.channel_port.record_failure()
        await session.refuse(CHANNEL_CODE_BINDING_UNKNOWN, {})
        return
    if binding.role != hello.role:
        await session.refuse(CHANNEL_CODE_ROLE_MISMATCH, {"role": hello.role})
        return
    admission = runtime.channel_port.admit(_connection_key(websocket))
    if admission is None:
        await session.refuse(
            CHANNEL_CODE_CHANNEL_FULL, {"limit": runtime.channel_port.sockets_max}
        )
        return
    try:
        welcome = await asyncio.to_thread(welcome_frame)
        device = await asyncio.to_thread(DeviceRegistry().get, binding.id)
        await asyncio.to_thread(
            DeviceRegistry().note_agent_version, binding.id, session.version
        )
        await legacy_serve.serve_update_only_agent(
            websocket, runtime, session, device, welcome
        )
    finally:
        runtime.channel_port.release(admission)


async def _read_hello(websocket: WebSocket) -> "LegacyHello | None":
    """The socket's first frame, which must be a hello in time.

    Returns:
        The hello, or None when the first frame is late, not text, not a
        hello, or not one this hub can read.
    """
    try:
        message = await asyncio.wait_for(websocket.receive(), CHANNEL_HELLO_TIMEOUT_S)
    except asyncio.TimeoutError:
        return None
    if message["type"] == "websocket.disconnect":
        return None
    decoded = decode_frame(message.get("text"))
    if decoded is None or decoded.get("type") != CHANNEL_FRAME_HELLO:
        return None
    try:
        return LegacyHello.model_validate(decoded)
    except ValidationError:
        return None


def _connection_key(connection) -> tuple:
    """The connection's peer address and port, which name it on the listener."""
    client = connection.client
    if client is None:
        return ("", 0)
    return (unmapped(client.host), client.port)


def _peer_host(connection) -> str:
    """Where a connection comes from, empty when the transport names none."""
    client = connection.client
    return unmapped(client.host) if client is not None else ""
