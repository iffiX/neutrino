"""Websocket endpoints: events, live statistics, the DNS log, terminals, tasks.

Everything that streams lives here. Each socket checks the session cookie itself
and closes with a policy-violation code when it is missing, since a websocket
route cannot answer with a 401 the way an HTTP route does.
"""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.system.local_shell import LocalShellSession
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator, SshCredentials
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
DNS_LOG_POLL_INTERVAL_S = 1.0


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


@router.websocket("/ws/ssh/{mac_address}")
async def ssh_socket(websocket: WebSocket, mac_address: str) -> None:
    """Bridge a browser terminal to a device's shell.

    Args:
        websocket: The client socket.
        mac_address: Which device to connect to.
    """
    if not await _accept(websocket):
        return
    device = DeviceRegistry().get(mac_address)
    if not device.has_ssh:
        await websocket.close(
            code=POLICY_VIOLATION_CODE, reason="no SSH credentials for this device"
        )
        return

    loop = asyncio.get_running_loop()
    outgoing: asyncio.Queue = asyncio.Queue()

    def on_output(chunk: str) -> None:
        loop.call_soon_threadsafe(outgoing.put_nowait, chunk)

    operator = DeviceSshOperator(credentials=SshCredentials.from_dict(device.ssh or {}))
    try:
        session = await operator.open_shell(on_output=on_output)
    except Exception as error:  # noqa: BLE001 - the reason is shown in the terminal
        await websocket.send_json({"type": "output", "data": f"\r\n{error}\r\n"})
        await websocket.close(code=POLICY_VIOLATION_CODE, reason="connection failed")
        return

    sender = asyncio.create_task(_send_output(websocket, outgoing))
    pump = asyncio.create_task(session.pump_output())
    reader = asyncio.create_task(_read_input(websocket, session))

    # Whichever ends first decides how the session tears down: the reader ending
    # means the browser closed the terminal, and the pump ending means the
    # remote shell exited. Both must lead to the same clean teardown — the SSH
    # process killed, no orphan left, and the browser told the session ended.
    done, _ = await asyncio.wait({pump, reader}, return_when=asyncio.FIRST_COMPLETED)

    if pump in done:
        exit_code = pump.result()
        with contextlib.suppress(RuntimeError):
            await websocket.send_json({"type": "exit", "code": exit_code})

    session.close()
    for task in (sender, pump, reader):
        task.cancel()
    for task in (sender, pump, reader):
        with contextlib.suppress(asyncio.CancelledError):
            await task
    with contextlib.suppress(RuntimeError):
        await websocket.close()


@router.websocket("/ws/terminal")
async def terminal_socket(websocket: WebSocket) -> None:
    """Bridge a browser terminal to a shell on the gateway itself.

    Every tab in the panel's terminal opens one of these, so closing a tab has
    to leave nothing behind — the session kills its whole process group on the
    way out rather than only the shell.

    Args:
        websocket: The client socket.
    """
    if not await _accept(websocket):
        return
    await _serve_pty_session(websocket, LocalShellSession())


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


async def _serve_pty_session(websocket: WebSocket, session: LocalShellSession) -> None:
    """Run one pty session over one socket, and leave nothing behind.

    Args:
        websocket: The accepted client socket.
        session: The unstarted session to serve.
    """
    try:
        await session.start()
    except OSError as error:
        await websocket.send_json({"type": "output", "data": f"\r\n{error}\r\n"})
        await websocket.close(code=POLICY_VIOLATION_CODE, reason="no shell")
        return

    reader = asyncio.create_task(_read_input(websocket, session))
    pump = asyncio.create_task(_pump_local_shell(websocket, session))

    # Whichever finishes first decides the teardown: the reader ending means
    # the tab was closed, the pump ending means the shell exited. Both lead to
    # the same place — no process left running, and the browser told so.
    done, _ = await asyncio.wait({reader, pump}, return_when=asyncio.FIRST_COMPLETED)
    if pump in done:
        with contextlib.suppress(RuntimeError):
            await websocket.send_json(
                {"type": "exit", "code": await session.exit_code()}
            )

    await session.close()
    for task in (reader, pump):
        task.cancel()
    for task in (reader, pump):
        with contextlib.suppress(asyncio.CancelledError):
            await task
    with contextlib.suppress(RuntimeError):
        await websocket.close()


async def _pump_local_shell(websocket: WebSocket, session: LocalShellSession) -> None:
    """Forward the shell's output until it exits or the socket goes away."""
    while True:
        chunk = await session.read()
        if not chunk:
            return
        if websocket.client_state is not WebSocketState.CONNECTED:
            return
        with contextlib.suppress(RuntimeError):
            await websocket.send_json(
                {"type": "output", "data": chunk.decode("utf-8", errors="replace")}
            )


async def _read_input(websocket: WebSocket, session) -> None:
    """Forward keystrokes and resizes until the browser goes away.

    Returns (rather than looping forever) when the socket closes, which is how
    the caller learns the browser shut the terminal.

    Args:
        websocket: The client socket.
        session: The live shell session to drive.
    """
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "input":
                session.write(message.get("data", ""))
            elif kind == "resize":
                session.resize(
                    int(message.get("cols", 80)), int(message.get("rows", 24))
                )
    except (WebSocketDisconnect, RuntimeError, ValueError, KeyError):
        return


async def _send_output(websocket: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        chunk = await queue.get()
        if websocket.client_state is not WebSocketState.CONNECTED:
            return
        await websocket.send_json({"type": "output", "data": chunk})


async def _accept(websocket: WebSocket) -> bool:
    runtime = websocket.app.state.runtime
    token = websocket.cookies.get(WEB_SESSION_COOKIE)
    if not runtime.sessions.is_valid(token):
        await websocket.close(code=POLICY_VIOLATION_CODE, reason="not authenticated")
        return False
    await websocket.accept()
    return True
