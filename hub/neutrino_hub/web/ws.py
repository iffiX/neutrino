"""Websocket endpoints: events, live statistics, the DNS log, terminals, tasks.

Everything that streams lives here. Each socket checks the session cookie itself
and closes with a policy-violation code when it is missing, since a websocket
route cannot answer with a 401 the way an HTTP route does.

A terminal reaches a device through its agent: the browser's socket and the
agent's shell stream are bridged here, frame for frame. The browser sends
``{"type": "input", "data"}`` and ``{"type": "resize", "cols", "rows"}``;
it receives ``{"type": "output", "data"}`` and, once the shell is gone,
``{"type": "exit", "code"}``.
"""

import asyncio
import codecs
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from neutrino_hub.modules.devices.agent_sessions import (
    CODE_AGENT_OFFLINE,
    STREAM_KIND_CONTAINER_SHELL,
    STREAM_KIND_SHELL,
    AgentOfflineError,
    StreamRefusedError,
)
from neutrino_hub.web.constants import (
    WEB_EVENT_HELLO,
    WEB_SESSION_COOKIE,
    WEB_STATS_PUSH_INTERVAL_S,
)
from neutrino_hub.web.dns_log import DnsLogReader
from neutrino_hub.web.events import event_frame
from neutrino_hub.web.stats_collector import PanelStatsCollector

router = APIRouter()

POLICY_VIOLATION_CODE = 1008
INTERNAL_ERROR_CODE = 1011
DNS_LOG_POLL_INTERVAL_S = 1.0
DEFAULT_COLUMNS = 80
DEFAULT_ROWS = 24


@router.websocket("/ws/stats")
async def stats_socket(websocket: WebSocket) -> None:
    """Push a statistics frame every second.

    Args:
        websocket: The client socket.
    """
    if not await _accept(websocket):
        return
    collector = PanelStatsCollector(runtime=websocket.app.state.runtime)
    try:
        while True:
            frame = await asyncio.to_thread(collector.collect)
            await websocket.send_json(frame.model_dump())
            await asyncio.sleep(WEB_STATS_PUSH_INTERVAL_S)
    except (WebSocketDisconnect, RuntimeError):
        return


@router.websocket("/ws/events")
async def events_socket(websocket: WebSocket) -> None:
    """Push one frame per invalidation event, for as long as the panel is open.

    The socket opens with a hello frame, so the browser knows it is live and
    can refetch what it draws after a reconnection.

    Args:
        websocket: The client socket.
    """
    if not await _accept(websocket):
        return
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


@router.websocket("/ws/dns_log")
async def dns_log_socket(websocket: WebSocket) -> None:
    """Send the recent DNS queries, then follow the log.

    Args:
        websocket: The client socket.
    """
    if not await _accept(websocket):
        return
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


@router.websocket("/ws/task/{task_id}")
async def task_socket(websocket: WebSocket, task_id: str) -> None:
    """Stream one background job's output.

    Args:
        websocket: The client socket.
        task_id: Identifier returned when the job was started.
    """
    if not await _accept(websocket):
        return
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


@router.websocket("/ws/agent_shell/{device_id}")
async def agent_shell_socket(websocket: WebSocket, device_id: str) -> None:
    """Bridge a browser terminal to a root shell on a device, over its agent.

    Args:
        websocket: The client socket.
        device_id: Which device to open the shell on.
    """
    await _serve_agent_stream(
        websocket,
        device_id,
        STREAM_KIND_SHELL,
        {"cols": DEFAULT_COLUMNS, "rows": DEFAULT_ROWS},
    )


@router.websocket("/ws/agent_container/{device_id}/{name}")
async def agent_container_socket(websocket: WebSocket, device_id: str, name: str):
    """Bridge a browser terminal to a shell inside a container on a device.

    Args:
        websocket: The client socket.
        device_id: Which device the container runs on.
        name: The container.
    """
    await _serve_agent_stream(
        websocket, device_id, STREAM_KIND_CONTAINER_SHELL, {"name": name}
    )


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


async def _serve_agent_stream(
    websocket: WebSocket, device_id: str, kind: str, args: dict
) -> None:
    """Run one agent shell stream over one browser socket.

    Args:
        websocket: The unaccepted client socket.
        device_id: The device.
        kind: The stream kind to open.
        args: What the kind takes.
    """
    if not await _accept(websocket):
        return
    sessions = websocket.app.state.runtime.agent_sessions
    try:
        stream = await sessions.open_stream(device_id.lower(), kind, args)
    except AgentOfflineError:
        await websocket.close(code=POLICY_VIOLATION_CODE, reason=CODE_AGENT_OFFLINE)
        return
    except StreamRefusedError as refused:
        await websocket.close(code=INTERNAL_ERROR_CODE, reason=refused.code)
        return

    reader = asyncio.create_task(_read_input(websocket, stream))
    pump = asyncio.create_task(_pump_stream(websocket, stream))
    # Whichever ends first decides the teardown: the reader ending means
    # the browser closed the terminal, the pump ending means the shell
    # exited or the agent went away.
    done, _ = await asyncio.wait({reader, pump}, return_when=asyncio.FIRST_COMPLETED)
    if pump in done:
        info = stream.close_info or {}
        with contextlib.suppress(RuntimeError):
            await websocket.send_json(
                {"type": "exit", "code": int(info.get("exit_code", 1) or 0)}
            )
    with contextlib.suppress(AgentOfflineError):
        await stream.close()
    for task in (reader, pump):
        task.cancel()
    for task in (reader, pump):
        with contextlib.suppress(asyncio.CancelledError):
            await task
    with contextlib.suppress(RuntimeError):
        await websocket.close()


async def _pump_stream(websocket: WebSocket, stream) -> None:
    """Forward the shell's output until the stream closes or the socket goes."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while True:
        item = await stream.recv()
        if item is None:
            return
        if item[0] != "data":
            continue
        if websocket.client_state is not WebSocketState.CONNECTED:
            return
        text = decoder.decode(item[1])
        if text:
            with contextlib.suppress(RuntimeError):
                await websocket.send_json({"type": "output", "data": text})


async def _read_input(websocket: WebSocket, stream) -> None:
    """Forward keystrokes and resizes until the browser goes away.

    Returns when the socket closes, which is how the caller learns the
    browser shut the terminal.

    Args:
        websocket: The client socket.
        stream: The live shell stream to drive.
    """
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "input":
                await stream.send_bytes(str(message.get("data", "")).encode("utf-8"))
            elif kind == "resize":
                await stream.resize(
                    int(message.get("cols", DEFAULT_COLUMNS)),
                    int(message.get("rows", DEFAULT_ROWS)),
                )
    except (WebSocketDisconnect, RuntimeError, ValueError, KeyError):
        return
    except AgentOfflineError:
        return


async def _accept(websocket: WebSocket) -> bool:
    runtime = websocket.app.state.runtime
    token = websocket.cookies.get(WEB_SESSION_COOKIE)
    if not runtime.sessions.is_valid(token):
        await websocket.close(code=POLICY_VIOLATION_CODE, reason="not authenticated")
        return False
    await websocket.accept()
    return True
