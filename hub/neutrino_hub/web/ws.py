"""Websocket endpoints: live statistics, the DNS log, terminals, and tasks.

Everything that streams lives here. Each socket checks the session cookie itself
and closes with a policy-violation code when it is missing, since a websocket
route cannot answer with a 401 the way an HTTP route does.
"""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.podman.config import CONTAINER_NAME_PATTERN
from neutrino_hub.modules.podman.ops import shell_command
from neutrino_hub.system.local_shell import LocalShellSession
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator, SshCredentials
from neutrino_hub.web.constants import WEB_SESSION_COOKIE, WEB_STATS_PUSH_INTERVAL_S
from neutrino_hub.web.dns_log import DnsLogReader
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


@router.websocket("/ws/container/{name}")
async def container_shell_socket(websocket: WebSocket, name: str) -> None:
    """Bridge a browser terminal to a shell inside a running container.

    The same pty machinery as the gateway's own terminal, with ``podman exec``
    on the far end of it — same sweep on close, same everything.

    Args:
        websocket: The client socket.
        name: The container's name, held to the config charset so it cannot
            smuggle arguments into the exec.
    """
    if not await _accept(websocket):
        return
    if not CONTAINER_NAME_PATTERN.match(name):
        await websocket.close(code=POLICY_VIOLATION_CODE, reason="bad name")
        return
    await _serve_pty_session(websocket, LocalShellSession(command=shell_command(name)))


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
            await websocket.send_json({"type": "exit", "code": 0})

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
