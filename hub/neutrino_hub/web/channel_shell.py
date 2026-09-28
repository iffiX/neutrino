"""A client's shell on a managed machine, bridged to that machine's agent.

A client opens ``shell {device_id, cols, rows}``; the hub opens the agent's
own ``shell`` stream and relays bytes both ways, each side under the other's
credit, as the panel's terminal does. The client's stream closes with the
agent's ``exit_code``, or with the refusal. A later size is a client-opened
``command {agent, resize, shell, cols, rows}`` naming the client's own shell
stream, which the hub maps to the agent's.
"""

import asyncio
import contextlib

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_BINDING_UNKNOWN,
    CHANNEL_CODE_SHELL_UNKNOWN,
    CHANNEL_CODE_VERB_UNKNOWN,
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_STREAM_SHELL,
    CHANNEL_VERB_RESIZE,
)
from neutrino_hub.modules.channel.sessions import ChannelSession, ChannelStream
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_DISABLED,
    CLIENT_CODE_PERMISSION_DENIED,
    CLIENT_PERMISSION_TERMINAL,
)
from neutrino_hub.modules.clients.permissions import permitted_kinds
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web.shell_bridge import (
    DEFAULT_COLUMNS,
    DEFAULT_ROWS,
    resize_shell,
    settle_shell,
    shell_output,
)


async def serve_shell_stream(
    runtime, session: ChannelSession, stream: ChannelStream
) -> None:
    """Serve a ``shell`` stream a client opened, to the end of the agent's shell.

    Args:
        runtime: The shared runtime.
        session: The client's session; its ``shells`` holds the bridge while
            it runs.
        stream: The client's stream, closed here.
    """
    device_id = str(stream.args.get("device_id", "") or "")
    code, params = await asyncio.to_thread(_judge, session.key)
    if code:
        await stream.close(code, params)
        return
    cols, rows = _size(stream.args)
    try:
        shell = await runtime.agent_sessions.open_stream(
            device_id, CHANNEL_STREAM_SHELL, {"cols": cols, "rows": rows}
        )
    except AgentOfflineError as offline:
        await stream.close(offline.code, {"device": device_id})
        return
    session.shells[stream.id] = (device_id, shell.id)
    reader = asyncio.create_task(_forward_input(stream, shell))
    pump = asyncio.create_task(_forward_output(shell, stream))
    try:
        info = await settle_shell(shell, reader, pump)
    finally:
        session.shells.pop(stream.id, None)
    if info is None:
        return
    refusal = str(info.get("code", "") or "")
    if refusal:
        await stream.close(refusal, dict(info.get("params") or {}))
        return
    exit_code = (info.get("params") or {}).get("exit_code", 1)
    await stream.close("", {"exit_code": int(exit_code or 0)})


async def serve_command_stream(
    runtime, session: ChannelSession, stream: ChannelStream
) -> None:
    """Serve a ``command`` stream a client opened; only ``resize`` is one.

    Args:
        runtime: The shared runtime.
        session: The client's session, whose ``shells`` names the bridge.
        stream: The client's stream, closed here.
    """
    module = str(stream.args.get("module", "") or "")
    verb = str(stream.args.get("verb", "") or "")
    if module != CHANNEL_COMMAND_MODULE_AGENT or verb != CHANNEL_VERB_RESIZE:
        await stream.close(CHANNEL_CODE_VERB_UNKNOWN, {"module": module, "verb": verb})
        return
    shell_id = stream.args.get("shell")
    bridged = session.shells.get(shell_id) if isinstance(shell_id, int) else None
    if bridged is None:
        await stream.close(CHANNEL_CODE_SHELL_UNKNOWN, {"shell": shell_id})
        return
    device_id, agent_shell_id = bridged
    cols, rows = _size(stream.args)
    try:
        await resize_shell(
            runtime.agent_sessions, device_id, agent_shell_id, cols, rows
        )
    except AgentOfflineError as offline:
        await stream.close(offline.code, {"device": device_id})
        return
    await stream.close()


def _judge(client_id: str) -> tuple:
    """Whether a client may open a shell now, as ``(code, params)``."""
    registry = ClientRegistry()
    client = registry.get(client_id)
    if client is None:
        return CHANNEL_CODE_BINDING_UNKNOWN, {}
    if client.is_disabled:
        return CLIENT_CODE_DISABLED, {}
    if CLIENT_PERMISSION_TERMINAL not in permitted_kinds(registry, client):
        return CLIENT_CODE_PERMISSION_DENIED, {"kind": CLIENT_PERMISSION_TERMINAL}
    return "", {}


def _size(args: dict) -> tuple:
    """The ``cols`` and ``rows`` an open names, the defaults where it names none."""
    try:
        cols = int(args.get("cols") or DEFAULT_COLUMNS)
        rows = int(args.get("rows") or DEFAULT_ROWS)
    except (TypeError, ValueError):
        return DEFAULT_COLUMNS, DEFAULT_ROWS
    return max(1, cols), max(1, rows)


async def _forward_input(client_stream: ChannelStream, shell: ChannelStream) -> None:
    """Relay the client's keystrokes to the agent until the client stops."""
    with contextlib.suppress(AgentOfflineError):
        while True:
            item = await client_stream.recv()
            if item is None:
                return
            await shell.send_bytes(item[1])


async def _forward_output(shell: ChannelStream, client_stream: ChannelStream) -> None:
    """Relay the shell's output to the client until the shell ends."""
    with contextlib.suppress(AgentOfflineError):
        async for data in shell_output(shell):
            await client_stream.send_bytes(data)
