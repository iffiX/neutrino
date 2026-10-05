"""Websocket endpoints: events, live statistics, the DNS log, terminals, tasks.

Everything that streams lives here. Each socket checks the session cookie itself
and closes with a policy-violation code when it is missing, since a websocket
route cannot answer with a 401 the way an HTTP route does. An open socket
checks its session every ``WEB_SOCKET_SESSION_CHECK_INTERVAL_S`` and closes
with the same code once the session has ended: signed out, expired, or
ended by the Clients page.

A terminal reaches a device through its agent: the browser's socket and the
agent's shell stream are bridged here, frame for frame. The browser sends
``{"type": "input", "data"}``, ``{"type": "resize", "cols", "rows"}`` and
``{"type": "persist", "is_persistent", "is_shared"}``; it receives
``{"type": "output", "data"}``, ``{"type": "refused", "code", "params"}``
for a persist on a session the panel does not own, and, once the shell is
gone, ``{"type": "exit", "code"}``. A shell's first size, its session id and
the ``owner: hub`` stamp ride its open; a later size is a ``command {agent,
resize, shell, cols, rows}`` stream and a persist a ``command {agent,
persist, session_id, is_persistent, is_shared}``, each closed by the agent
as soon as it is applied.
"""

import asyncio
import codecs
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_SESSION_NOT_OWNED,
    CHANNEL_SHELL_CONTAINER_MODULE,
    CHANNEL_SHELL_OWNER_HUB,
    CHANNEL_STREAM_SHELL,
)
from neutrino_hub.web.constants import (
    WEB_EVENT_HELLO,
    WEB_SOCKET_SESSION_CHECK_INTERVAL_S,
    WEB_SOCKET_SESSION_END_GRACE_S,
    WEB_STATS_PUSH_INTERVAL_S,
)
from neutrino_hub.web.dependencies import session_cookie
from neutrino_hub.web.dns_log import DnsLogReader
from neutrino_hub.web.events import event_frame
from neutrino_hub.web.shell_bridge import (
    DEFAULT_COLUMNS,
    DEFAULT_ROWS,
    is_session_refused,
    persist_flags,
    persist_session,
    record_opened,
    record_sharing,
    resize_shell,
    settle_shell,
    shell_output,
)
from neutrino_hub.web.stats_collector import PanelStatsCollector

router = APIRouter()

POLICY_VIOLATION_CODE = 1008
INTERNAL_ERROR_CODE = 1011
# What starlette's close raises when the browser is already gone.
ABNORMAL_CLOSURE_CODE = 1006
DNS_LOG_POLL_INTERVAL_S = 1.0


@router.websocket("/ws/hub/dashboard/stat")
async def stats_socket(websocket: WebSocket) -> None:
    """Push a statistics frame every second.

    Args:
        websocket: The client socket.
    """
    if not await _accept(websocket):
        return
    await _while_signed_in(websocket, _push_stats(websocket))


@router.websocket("/ws/hub/event")
async def events_socket(websocket: WebSocket) -> None:
    """Push one frame per invalidation event, for as long as the panel is open.

    The socket opens with a hello frame, so the browser knows it is live and
    can refetch what it draws after a reconnection.

    Args:
        websocket: The client socket.
    """
    if not await _accept(websocket):
        return
    await _while_signed_in(websocket, _follow_events(websocket))


@router.websocket("/ws/hub/dashboard/dns_log")
async def dns_log_socket(websocket: WebSocket) -> None:
    """Send the recent DNS queries, then follow the log.

    Args:
        websocket: The client socket.
    """
    if not await _accept(websocket):
        return
    await _while_signed_in(websocket, _follow_dns_log(websocket))


@router.websocket("/ws/hub/task")
async def task_socket(websocket: WebSocket, task_id: str) -> None:
    """Stream one background job's output.

    Args:
        websocket: The client socket.
        task_id: Identifier returned when the job was started, from the
            query.
    """
    if not await _accept(websocket):
        return
    await _while_signed_in(websocket, _follow_task(websocket, task_id))


@router.websocket("/ws/agent/terminal")
async def terminal_socket(
    websocket: WebSocket,
    device_id: str,
    container: str = "",
    session_id: str = "",
    is_resumed: bool = False,
    is_shared: bool = False,
) -> None:
    """Bridge a browser terminal to a shell on a device, over its agent.

    A shell with a session id is opened as the panel's own, ``owner: hub``.
    The panel joins any session, whoever owns it.

    Args:
        websocket: The client socket.
        device_id: Which device to open the shell on, from the query.
        container: A container on the device to open the shell inside of,
            from the query; empty opens a root shell on the device itself.
        session_id: The session the page generated for the shell, from the
            query.
        is_resumed: Whether the page attaches to a session the machine
            listed, from the query; the agent refuses one it does not hold
            and sends the kept output first.
        is_shared: Whether a new session starts shared, from the query.
    """
    args = {"cols": DEFAULT_COLUMNS, "rows": DEFAULT_ROWS}
    if session_id:
        args["session_id"] = session_id
        args["owner"] = CHANNEL_SHELL_OWNER_HUB
        args["is_shared"] = is_shared
        if is_resumed:
            args["is_resumed"] = True
    if container:
        args = {
            "module": CHANNEL_SHELL_CONTAINER_MODULE,
            "container": container,
            **args,
        }
    await _serve_agent_stream(websocket, device_id, args)


async def _push_stats(websocket: WebSocket) -> None:
    """Send a statistics frame every second until the socket goes."""
    collector = PanelStatsCollector(runtime=websocket.app.state.runtime)
    try:
        while True:
            frame = await asyncio.to_thread(collector.collect)
            await websocket.send_json(frame.model_dump())
            await asyncio.sleep(WEB_STATS_PUSH_INTERVAL_S)
    except (WebSocketDisconnect, RuntimeError):
        return


async def _follow_events(websocket: WebSocket) -> None:
    """Send every event until the browser closes the socket."""
    events = websocket.app.state.runtime.events
    queue = events.subscribe()
    pump = asyncio.create_task(_pump_events(websocket, queue))
    try:
        await _await_disconnect(websocket)
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        events.unsubscribe(queue)


async def _follow_dns_log(websocket: WebSocket) -> None:
    """Send the recent queries, then each new one, until the socket goes."""
    reader = DnsLogReader()
    try:
        initial = await asyncio.to_thread(reader.tail)
        await websocket.send_json(
            {"entries": [entry.model_dump() for entry in reversed(initial)]}
        )
        while True:
            await asyncio.sleep(DNS_LOG_POLL_INTERVAL_S)
            entries = await asyncio.to_thread(reader.follow)
            if entries:
                await websocket.send_json(
                    {"entries": [entry.model_dump() for entry in entries]}
                )
    except (WebSocketDisconnect, RuntimeError):
        return


async def _follow_task(websocket: WebSocket, task_id: str) -> None:
    """Send one job's output, then its exit code."""
    stream = websocket.app.state.runtime.tasks.get(task_id)
    if stream is None:
        await websocket.close(code=POLICY_VIOLATION_CODE, reason="unknown task")
        return
    try:
        async for chunk in stream.subscribe():
            await websocket.send_json({"type": "output", "data": chunk})
        await websocket.send_json({"type": "done", "exit_code": stream.exit_code or 0})
    except (WebSocketDisconnect, RuntimeError):
        return


async def _pump_events(websocket: WebSocket, queue: asyncio.Queue) -> None:
    """Send the hello frame, then every event, until the socket goes away."""
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        await websocket.send_json(event_frame(WEB_EVENT_HELLO))
        while True:
            await websocket.send_json(await queue.get())


async def _await_disconnect(websocket: WebSocket) -> None:
    """Read and drop frames until the browser closes the socket.

    Nothing travels up this socket; reading it is how the disconnect is
    noticed.
    """
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            if (await websocket.receive())["type"] == "websocket.disconnect":
                return


async def _serve_agent_stream(websocket: WebSocket, device_id: str, args: dict) -> None:
    """Run one agent shell stream over one browser socket.

    Args:
        websocket: The unaccepted client socket.
        device_id: The device.
        args: What the ``shell`` open carries.
    """
    if not await _accept(websocket):
        return
    await _while_signed_in(websocket, _bridge_shell(websocket, device_id, args))


async def _bridge_shell(websocket: WebSocket, device_id: str, args: dict) -> None:
    """Bridge an accepted socket to a new shell stream until either ends."""
    runtime = websocket.app.state.runtime
    sessions = runtime.agent_sessions
    session_id = str(args.get("session_id", "") or "")
    if session_id and args.get("is_resumed") is not True:
        record_opened(
            runtime,
            device_id,
            session_id,
            CHANNEL_SHELL_OWNER_HUB,
            args.get("is_shared") is True,
        )
    try:
        stream = await sessions.open_stream(device_id, CHANNEL_STREAM_SHELL, args)
    except AgentOfflineError as offline:
        await websocket.close(code=POLICY_VIOLATION_CODE, reason=offline.code)
        return

    reader = asyncio.create_task(
        _read_input(websocket, stream, sessions, device_id, args)
    )
    pump = asyncio.create_task(_pump_stream(websocket, stream))
    info = await settle_shell(stream, reader, pump)
    refusal = str(info.get("code", "") or "") if info is not None else ""
    if info is not None and not refusal:
        params = info.get("params") or {}
        with contextlib.suppress(RuntimeError):
            await websocket.send_json(
                {"type": "exit", "code": int(params.get("exit_code", 1) or 0)}
            )
    if refusal:
        # A close reason holds 123 bytes, so the params ride a frame before it.
        with contextlib.suppress(RuntimeError):
            await websocket.send_json(
                {
                    "type": "closing",
                    "code": refusal,
                    "params": dict(info.get("params") or {}),
                }
            )
        await _close(websocket, code=INTERNAL_ERROR_CODE, reason=refusal)
    else:
        await _close(websocket)


async def _close(websocket: WebSocket, **kwargs) -> None:
    """Close the browser's socket; one the browser already left stays closed.

    Args:
        websocket: The browser's socket.
        kwargs: The close code and reason, when there is one.

    Raises:
        WebSocketDisconnect: For any close code but the one of a browser
            already gone.
    """
    try:
        await websocket.close(**kwargs)
    except RuntimeError:
        return
    except WebSocketDisconnect as gone:
        if gone.code != ABNORMAL_CLOSURE_CODE:
            raise


async def _pump_stream(websocket: WebSocket, stream) -> None:
    """Forward the shell's output until the stream closes or the socket goes."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    async for data in shell_output(stream):
        if websocket.client_state is not WebSocketState.CONNECTED:
            return
        text = decoder.decode(data)
        if text:
            with contextlib.suppress(RuntimeError):
                await websocket.send_json({"type": "output", "data": text})


async def _read_input(
    websocket: WebSocket, stream, sessions, device_id: str, args: dict
) -> None:
    """Forward keystrokes, resizes and persists until the browser goes away.

    Returns when the socket closes, which is how the caller learns the
    browser shut the terminal.

    Args:
        websocket: The client socket.
        stream: The live shell stream to drive.
        sessions: The agents' sessions, which a resize or a persist opens
            its command on.
        device_id: The device the shell runs on.
        args: What the shell's open carried; a persist names its
            ``session_id`` and is dropped when it has none.
    """
    session_id = str(args.get("session_id", "") or "")
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "input":
                await stream.send_bytes(str(message.get("data", "")).encode("utf-8"))
            elif kind == "resize":
                await resize_shell(
                    sessions,
                    device_id,
                    stream.id,
                    int(message.get("cols", DEFAULT_COLUMNS)),
                    int(message.get("rows", DEFAULT_ROWS)),
                )
            elif kind == "persist" and session_id:
                runtime = websocket.app.state.runtime
                if is_session_refused(
                    runtime,
                    device_id,
                    session_id,
                    CHANNEL_SHELL_OWNER_HUB,
                    is_join=False,
                ):
                    await websocket.send_json(
                        {
                            "type": "refused",
                            "code": CHANNEL_CODE_SESSION_NOT_OWNED,
                            "params": {"session_id": session_id},
                        }
                    )
                    continue
                flags = persist_flags(message)
                await persist_session(sessions, device_id, session_id, flags)
                await record_sharing(
                    runtime, device_id, session_id, CHANNEL_SHELL_OWNER_HUB, flags
                )
    except (WebSocketDisconnect, RuntimeError, ValueError, KeyError):
        return
    except AgentOfflineError:
        return


async def _while_signed_in(websocket: WebSocket, serving) -> None:
    """Serve an accepted socket until it ends or its session does.

    A session that ended closes the socket with the policy-violation code,
    which ends what the socket serves by its own path; what is still running
    ``WEB_SOCKET_SESSION_END_GRACE_S`` later is cancelled.

    Args:
        websocket: The accepted socket.
        serving: The coroutine that serves it.
    """
    work = asyncio.ensure_future(serving)
    watch = asyncio.ensure_future(_session_ended(websocket))
    await asyncio.wait({work, watch}, return_when=asyncio.FIRST_COMPLETED)
    if work.done():
        watch.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watch
        work.result()
        return
    with contextlib.suppress(WebSocketDisconnect):
        await _close(websocket, code=POLICY_VIOLATION_CODE, reason="session ended")
    done, _ = await asyncio.wait({work}, timeout=WEB_SOCKET_SESSION_END_GRACE_S)
    if not done:
        work.cancel()
    with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
        await work


async def _session_ended(websocket: WebSocket) -> None:
    """Return once the socket's session is no longer valid."""
    runtime = websocket.app.state.runtime
    token = websocket.cookies.get(session_cookie(runtime))
    while runtime.sessions.is_valid(token):
        await asyncio.sleep(WEB_SOCKET_SESSION_CHECK_INTERVAL_S)


async def _accept(websocket: WebSocket) -> bool:
    runtime = websocket.app.state.runtime
    token = websocket.cookies.get(session_cookie(runtime))
    if not runtime.sessions.is_valid(token):
        await websocket.close(code=POLICY_VIOLATION_CODE, reason="not authenticated")
        return False
    await websocket.accept()
    return True
