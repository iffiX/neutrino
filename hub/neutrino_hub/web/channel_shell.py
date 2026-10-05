"""A client's shell on a managed machine, bridged to that machine's agent.

A client opens ``shell {device_id, cols, rows, session_id, is_resumed,
is_shared}``; the hub opens the agent's own ``shell`` stream with the same
``session_id``, ``is_resumed`` and ``is_shared``, stamped ``owner:
client:<id>``, and relays bytes both ways, each side under the other's
credit, as the panel's terminal does. The client's stream closes with the
agent's ``exit_code``, or with the refusal. A later size is a client-opened
``command {agent, resize, shell, cols, rows}`` naming the client's own shell
stream, which the hub maps to the agent's. ``command {agent, persist,
session_id, is_persistent, is_shared}`` from the session's owner and
``command {agent, stop_session, session_id}`` go to the machine holding the
session unchanged, since the id is the agent's own. A ``shell`` naming a
session another viewer owns and has not shared is refused
``session_not_owned`` (:func:`neutrino_hub.web.shell_bridge.is_session_refused`),
and an unshare closes every other client's stream on the session.
"""

import asyncio
import contextlib

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_BINDING_UNKNOWN,
    CHANNEL_CODE_SESSION_NOT_OWNED,
    CHANNEL_CODE_SESSION_UNKNOWN,
    CHANNEL_CODE_SHELL_UNKNOWN,
    CHANNEL_CODE_VERB_UNKNOWN,
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_STREAM_SHELL,
    CHANNEL_VERB_PERSIST,
    CHANNEL_VERB_RESIZE,
    CHANNEL_VERB_STOP_SESSION,
)
from neutrino_hub.modules.channel.sessions import ChannelSession, ChannelStream
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_DISABLED,
    CLIENT_CODE_PERMISSION_DENIED,
    CLIENT_PERMISSION_TERMINAL,
)
from neutrino_hub.modules.clients.permissions import (
    is_device_permitted,
    permitted_devices,
    permitted_kinds,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web.shell_bridge import (
    DEFAULT_COLUMNS,
    DEFAULT_ROWS,
    client_owner,
    device_of_session,
    is_session_refused,
    persist_flags,
    record_opened,
    record_sharing,
    resize_shell,
    session_command,
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
    session_id = str(stream.args.get("session_id", "") or "")
    code, params = await asyncio.to_thread(_judge, session.key, device_id)
    if code:
        await stream.close(code, params)
        return
    viewer = client_owner(session.key)
    if session_id and is_session_refused(
        runtime, device_id, session_id, viewer, is_join=True
    ):
        await stream.close(CHANNEL_CODE_SESSION_NOT_OWNED, {"session_id": session_id})
        return
    cols, rows = _size(stream.args)
    args = {"cols": cols, "rows": rows}
    if session_id:
        args["session_id"] = session_id
        args["owner"] = viewer
        args["is_shared"] = stream.args.get("is_shared") is True
        if stream.args.get("is_resumed") is True:
            args["is_resumed"] = True
        else:
            record_opened(runtime, device_id, session_id, viewer, args["is_shared"])
    try:
        shell = await runtime.agent_sessions.open_stream(
            device_id, CHANNEL_STREAM_SHELL, args
        )
    except AgentOfflineError as offline:
        await stream.close(offline.code, {"device": device_id})
        return
    session.shells[stream.id] = (device_id, shell.id, session_id)
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
    """Serve a ``command`` stream a client opened: ``resize``, ``persist`` or
    ``stop_session`` on module ``agent``.

    Args:
        runtime: The shared runtime.
        session: The client's session, whose ``shells`` names the bridge.
        stream: The client's stream, closed here.
    """
    module = str(stream.args.get("module", "") or "")
    verb = str(stream.args.get("verb", "") or "")
    if module == CHANNEL_COMMAND_MODULE_AGENT and verb in (
        CHANNEL_VERB_PERSIST,
        CHANNEL_VERB_STOP_SESSION,
    ):
        await _serve_session_verb(runtime, session, stream, verb)
        return
    if module != CHANNEL_COMMAND_MODULE_AGENT or verb != CHANNEL_VERB_RESIZE:
        await stream.close(CHANNEL_CODE_VERB_UNKNOWN, {"module": module, "verb": verb})
        return
    shell_id = stream.args.get("shell")
    bridged = session.shells.get(shell_id) if isinstance(shell_id, int) else None
    if bridged is None:
        await stream.close(CHANNEL_CODE_SHELL_UNKNOWN, {"shell": shell_id})
        return
    device_id, agent_shell_id, _ = bridged
    cols, rows = _size(stream.args)
    try:
        await resize_shell(
            runtime.agent_sessions, device_id, agent_shell_id, cols, rows
        )
    except AgentOfflineError as offline:
        await stream.close(offline.code, {"device": device_id})
        return
    await stream.close()


async def _serve_session_verb(
    runtime, session: ChannelSession, stream: ChannelStream, verb: str
) -> None:
    """Send ``persist`` or ``stop_session`` to the machine holding the session.

    The machine is the one this client's open bridge names for the id, else
    the online machine whose report lists it; the client must be allowed a
    terminal there, and a ``persist`` must come from the session's owner.
    The agent's close is the client's.

    Args:
        runtime: The shared runtime.
        session: The client's session.
        stream: The client's stream, closed here.
        verb: ``persist`` or ``stop_session``.
    """
    session_id = str(stream.args.get("session_id", "") or "")
    device_id = next(
        (
            bridged[0]
            for bridged in session.shells.values()
            if session_id and bridged[2] == session_id
        ),
        "",
    ) or (device_of_session(runtime.agent_sessions, session_id) if session_id else "")
    if not device_id:
        await stream.close(CHANNEL_CODE_SESSION_UNKNOWN, {"session_id": session_id})
        return
    code, params = await asyncio.to_thread(_judge, session.key, device_id)
    if code:
        await stream.close(code, params)
        return
    args = {"session_id": session_id}
    viewer = client_owner(session.key)
    if verb == CHANNEL_VERB_PERSIST:
        if is_session_refused(runtime, device_id, session_id, viewer, is_join=False):
            await stream.close(
                CHANNEL_CODE_SESSION_NOT_OWNED, {"session_id": session_id}
            )
            return
        args.update(persist_flags(stream.args))
    try:
        info = await session_command(runtime.agent_sessions, device_id, verb, args)
    except AgentOfflineError as offline:
        await stream.close(offline.code, {"device": device_id})
        return
    if verb == CHANNEL_VERB_PERSIST and not info["code"]:
        await record_sharing(
            runtime, device_id, session_id, viewer, persist_flags(stream.args)
        )
    await stream.close(info["code"], info["params"])


def _judge(client_id: str, device_id: str) -> tuple:
    """Whether a client may open a shell on one device now, as ``(code, params)``."""
    registry = ClientRegistry()
    client = registry.get(client_id)
    if client is None:
        return CHANNEL_CODE_BINDING_UNKNOWN, {}
    if client.is_disabled:
        return CLIENT_CODE_DISABLED, {}
    if CLIENT_PERMISSION_TERMINAL not in permitted_kinds(
        registry, client
    ) or not is_device_permitted(
        permitted_devices(registry, client), CLIENT_PERMISSION_TERMINAL, device_id
    ):
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
