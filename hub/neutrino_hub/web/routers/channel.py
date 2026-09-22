"""The channel's three routes on the agent port: join, leave, and the socket.

These are the only routes without a session: a peer authenticates with the
ticket its link carried at ``join`` and with the token that join handed it
in every ``hello``. They are served on the agent TLS port and nowhere
else, and every link carries the certificate fingerprint the peer pins.
"""

import asyncio
import contextlib

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError

from neutrino_hub import HUB_VERSION
from neutrino_hub.modules.channel.admission import admit
from neutrino_hub.modules.channel.bindings import resolve_token, spend_ticket
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CLOSE_REFUSED,
    CHANNEL_CODE_BINDING_UNKNOWN,
    CHANNEL_CODE_HELLO_INVALID,
    CHANNEL_CODE_ROLE_MISMATCH,
    CHANNEL_CODE_TICKET_SPENT,
    CHANNEL_FRAME_HELLO,
    CHANNEL_FRAME_REFUSED,
    CHANNEL_HELLO_TIMEOUT_S,
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
    CHANNEL_ROLE_HUB,
    PROTOCOL,
)
from neutrino_hub.modules.channel.sessions import (
    ChannelSession,
    version_of_software,
)
from neutrino_hub.modules.clients.ai_keys import revoke_client_key
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web import channel_serve
from neutrino_hub.web.channel_serve import decode_frame
from neutrino_hub.web.constants import WEB_EVENT_CLIENTS
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.identity import hub_id, hub_name
from neutrino_hub.web.models import (
    ChannelHello,
    ChannelJoinRequest,
    ChannelJoinView,
    ChannelLeaveRequest,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/channel", tags=["channel"])

ROLES = (CHANNEL_ROLE_AGENT, CHANNEL_ROLE_CLIENT)


@router.post("/join", response_model=ChannelJoinView)
def join(
    request: ChannelJoinRequest,
    http_request: Request,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ChannelJoinView:
    """Let a machine or a person's program join with the ticket its link carries.

    Admission by protocol comes first, so a refused peer has not spent the
    link. The ticket then leaves the store in one step and is judged. An
    agent lands on the row the ticket names, else on the row whose
    ``machine_id`` it reports, else on a new one; a client lands on the row
    whose ``machine_id`` it reports, else on the row its link was made for.

    Args:
        request: The ticket and the peer's identity card.
        http_request: The connection, for where the peer is.
        runtime: The shared runtime, which holds the open tickets.

    Returns:
        The binding: its id and the token every later hello carries.

    Raises:
        HTTPException: 409 with the protocol refusal; 409 ``role_mismatch``
            when the ticket was made for the other role, or the role is
            neither; 401 ``ticket_spent`` when the ticket is unknown,
            expired, or names a row that is gone.
    """
    refusal = admit(request.protocol)
    if refusal is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refusal)
    if request.role not in ROLES:
        raise _role_mismatch(request.role)
    try:
        ticket = spend_ticket(runtime.enrollments, request.ticket, request.role)
    except KeyError:
        raise _ticket_spent()
    except ValueError:
        raise _role_mismatch(request.role)
    if request.role == CHANNEL_ROLE_AGENT:
        binding_id, token = _join_agent(runtime, request, ticket, http_request)
    else:
        binding_id, token = _join_client(runtime, request, ticket)
    return ChannelJoinView(id=binding_id, token=token)


@router.post("/leave")
def leave(
    request: ChannelLeaveRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Take a peer's word that it is leaving: the binding is removed.

    A device keeps its row with everything its owner typed and loses its
    token; a client's row goes with its key.

    Args:
        request: The binding's id and token.
        runtime: The shared runtime, which holds the live sockets.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 401 ``binding_unknown`` when the token belongs to
            no binding with that id.
    """
    binding = resolve_token(request.token)
    if binding is None or binding.id != request.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": CHANNEL_CODE_BINDING_UNKNOWN, "params": {}},
        )
    if binding.role == CHANNEL_ROLE_AGENT:
        DeviceRegistry().drop_token(binding.id)
        runtime.forget_device(binding.id)
        return {}
    registry = ClientRegistry()
    client = registry.get(binding.id)
    if client is not None:
        revoke_client_key(registry, client)
    registry.forget(binding.id)
    runtime.forget_client(binding.id)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return {}


@router.websocket("/socket")
async def socket(websocket: WebSocket) -> None:
    """Serve one peer's channel from its hello to its last frame.

    Args:
        websocket: The peer's socket.
    """
    runtime = websocket.app.state.runtime
    await websocket.accept()
    hello = await _read_hello(websocket)
    if hello is None:
        # A rejected hello gets a refused frame and then the close, like
        # every other; the socket may already be gone, and then only the
        # close is left to try.
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
    session = ChannelSession(
        key=hello.id,
        role=hello.role,
        websocket=websocket,
        loop=asyncio.get_running_loop(),
        name=hello.name,
        software=hello.software,
        address=_peer_host(websocket),
    )
    refusal = admit(hello.protocol)
    if refusal is not None:
        await session.refuse(refusal["code"], refusal["params"])
        return
    binding = await asyncio.to_thread(resolve_token, hello.token)
    if binding is None or binding.id != hello.id:
        await session.refuse(CHANNEL_CODE_BINDING_UNKNOWN, {})
        return
    if binding.role != hello.role:
        await session.refuse(CHANNEL_CODE_ROLE_MISMATCH, {"role": hello.role})
        return
    welcome = await asyncio.to_thread(_welcome)
    if binding.role == CHANNEL_ROLE_AGENT:
        device = await asyncio.to_thread(DeviceRegistry().get, binding.id)
        await channel_serve.serve_agent(websocket, runtime, session, device, welcome)
        return
    client = await asyncio.to_thread(ClientRegistry().get, binding.id)
    await channel_serve.serve_client(websocket, runtime, session, client, welcome)


def _welcome() -> dict:
    """The hub's identity card."""
    return {
        "type": "welcome",
        "protocol": PROTOCOL,
        "role": CHANNEL_ROLE_HUB,
        "id": hub_id(),
        "name": hub_name(),
        "software": f"neutrino_hub/{HUB_VERSION}",
    }


def _join_agent(
    runtime: PanelRuntime, request: ChannelJoinRequest, ticket: dict, http_request
) -> tuple:
    """Bind a machine to its row, or a new one, and issue its token."""
    registry = DeviceRegistry()
    device = None
    if ticket.get("device_id"):
        device = registry.get(ticket["device_id"])
    if device is None:
        device = registry.find_by_machine_id(request.machine_id)
    name = ticket.get("name") or (device.name if device else None) or request.name
    if device is None:
        device = registry.create(name, machine_id=request.machine_id)
    else:
        device = registry.annotate(device.id, {"name": name or device.name})
        registry.note_machine(device.id, machine_id=request.machine_id)
    key = device.id
    token = registry.issue_token(key)
    if request.platform:
        runtime.device_platform[key] = dict(request.platform)
    if request.name:
        runtime.device_hostname[key] = request.name
    address = _peer_host(http_request)
    if address:
        runtime.device_address[key] = address
    return key, token


def _join_client(
    runtime: PanelRuntime, request: ChannelJoinRequest, ticket: dict
) -> tuple:
    """Bind a person's program to the row it had, else to its link's row.

    A machine that already has a row lands back on it: the link's fresh row
    goes, the old row takes the link's name and keeps its key, its switch
    and everything it last reported.
    """
    registry = ClientRegistry()
    client_id = str(ticket.get("client_id", ""))
    if registry.get(client_id) is None:
        raise _ticket_spent()
    enrolled = registry.find_by_machine_id(request.machine_id)
    if enrolled is not None and enrolled.id != client_id:
        registry.forget(client_id)
        runtime.forget_client(client_id)
        client_id = enrolled.id
        registry.rename(client_id, str(ticket.get("name") or "") or enrolled.name)
    registry.record_seen(
        client_id,
        hostname=request.name,
        platform=request.platform,
        version=version_of_software(request.software),
        machine_id=request.machine_id,
    )
    token = registry.issue_token(client_id)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return client_id, token


def _ticket_spent() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": CHANNEL_CODE_TICKET_SPENT, "params": {}},
    )


def _role_mismatch(role: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": CHANNEL_CODE_ROLE_MISMATCH, "params": {"role": role}},
    )


async def _read_hello(websocket: WebSocket) -> "ChannelHello | None":
    """The socket's first frame, which must be a hello in time.

    Args:
        websocket: The peer's socket.

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
        return ChannelHello.model_validate(decoded)
    except ValidationError:
        return None


def _peer_host(connection) -> str:
    """Where a connection comes from, empty when the transport names none."""
    client = connection.client
    return client.host if client is not None else ""
