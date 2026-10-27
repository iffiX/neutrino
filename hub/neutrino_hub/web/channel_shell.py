"""A client's shells and commands on managed machines, as the hub judges them.

The transport relays a client's ``shell`` and ``exec`` streams to the agent
once the hub's Python admitted the open (transport.md, "The hub's local
channel"); the Python's part is the judgment, the stamps the agent's open
carries, and the two frames on a kept shell, ``persist`` and
``stop_session``, which the hub relays to the machine holding the session
and answers with the agent's ``reply`` ("Kept shells").
"""

import asyncio
import secrets

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_BINDING_UNKNOWN,
    CHANNEL_CODE_NEVER_REPORTED,
    CHANNEL_CODE_SESSION_NOT_OWNED,
    CHANNEL_CODE_SESSION_UNKNOWN,
    CHANNEL_FRAME_PERSIST,
    CHANNEL_FRAME_REPLY,
    CHANNEL_FRAME_STOP_SESSION,
    CHANNEL_REPLY_TIMEOUT_S,
    CHANNEL_SHELL_OWNER_CLIENT_PREFIX,
    CHANNEL_STREAM_EXEC,
    CHANNEL_STREAM_SHELL,
)
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
    device_of_session,
    is_session_refused,
    persist_flags,
    record_sharing,
)

# What a shell's open carries on to the agent's own, beside the stamps.
SHELL_OPEN_FIELDS = ("account", "session_id", "is_resumed", "is_shared")
EXEC_OPEN_FIELDS = ("argv", "is_tty", "account")
SESSION_VERBS = (CHANNEL_FRAME_PERSIST, CHANNEL_FRAME_STOP_SESSION)


def shell_owner(client_id: str) -> str:
    """The owner the hub stamps on a shell a client opens, ``client:<id>``."""
    return f"{CHANNEL_SHELL_OWNER_CLIENT_PREFIX}{client_id}"


def judge_terminal(client_id: str, device_id: str) -> tuple:
    """Whether a client may open a shell or run a command on a machine.

    Args:
        client_id: The client.
        device_id: The machine.

    Returns:
        ``(code, params)``: ``binding_unknown``, ``client_disabled`` or
        ``permission_denied {kind: terminal}``, or an empty code.
    """
    registry = ClientRegistry()
    client = registry.get(client_id)
    if client is None:
        return CHANNEL_CODE_BINDING_UNKNOWN, {}
    if client.is_disabled:
        return CLIENT_CODE_DISABLED, {}
    if CLIENT_PERMISSION_TERMINAL not in permitted_kinds(registry, client):
        return CLIENT_CODE_PERMISSION_DENIED, {"kind": CLIENT_PERMISSION_TERMINAL}
    if not is_device_permitted(
        permitted_devices(registry, client), CLIENT_PERMISSION_TERMINAL, device_id
    ):
        return CLIENT_CODE_PERMISSION_DENIED, {"kind": CLIENT_PERMISSION_TERMINAL}
    return "", {}


def agent_shell_open(kind: str, open_body: dict, *, owner: str) -> dict:
    """The open the hub writes on the agent for a client's shell or command.

    Args:
        kind: ``shell`` or ``exec``.
        open_body: The client's open.
        owner: The stamp a kept shell carries; an ``exec`` carries none.

    Returns:
        The agent's open record's object.
    """
    cols, rows = _size(open_body)
    if kind == CHANNEL_STREAM_EXEC:
        sent = {"kind": CHANNEL_STREAM_EXEC, "cols": cols, "rows": rows}
        for field in EXEC_OPEN_FIELDS:
            if field in open_body:
                sent[field] = open_body[field]
        sent.setdefault("argv", [])
        sent.setdefault("is_tty", False)
        sent.setdefault("account", "")
        return sent
    sent = {"kind": CHANNEL_STREAM_SHELL, "cols": cols, "rows": rows}
    for field in SHELL_OPEN_FIELDS:
        if field in open_body:
            sent[field] = open_body[field]
    sent.setdefault("account", "")
    if sent.get("session_id"):
        sent["owner"] = owner
    return sent


class SessionReplyBook:
    """The replies the hub waits for from agents, by the request it sent."""

    def __init__(self):
        self._pending: dict = {}

    def expect(self, device_id: str, request: str) -> asyncio.Future:
        """A future the agent's ``reply`` of that request resolves."""
        future = asyncio.get_running_loop().create_future()
        self._pending[(device_id, request)] = future
        return future

    def forget(self, device_id: str, request: str) -> None:
        """Stop waiting for one reply."""
        self._pending.pop((device_id, request), None)

    def resolve(self, device_id: str, frame: dict) -> bool:
        """Hand an agent's ``reply`` to whoever waits for it.

        Returns:
            True when a request was waiting for it.
        """
        request = str(frame.get("request", "") or "")
        future = self._pending.pop((device_id, request), None)
        if future is None or future.done():
            return False
        future.set_result(frame)
        return True


async def relay_session_verb(runtime, session, frame: dict) -> None:
    """Relay a client's ``persist`` or ``stop_session`` and reply with the agent's.

    Args:
        runtime: The shared runtime.
        session: The client's session.
        frame: The frame, ``{type, request, session_id, ...}``.
    """
    request = str(frame.get("request", "") or "")
    session_id = str(frame.get("session_id", "") or "")
    verb = str(frame.get("type", "") or "")
    code, params = await _judge_verb(runtime, session.key, verb, session_id)
    if not code:
        code, params = await _ask_agent(runtime, session.key, verb, session_id, frame)
    try:
        await session.send_json(
            {
                "type": CHANNEL_FRAME_REPLY,
                "request": request,
                "code": code,
                "params": params,
            }
        )
    except AgentOfflineError:
        return


async def _judge_verb(runtime, client_id: str, verb: str, session_id: str) -> tuple:
    """The permission checks a session verb runs before it reaches a machine."""
    device_id = await asyncio.to_thread(
        device_of_session, runtime.agent_sessions, session_id
    )
    if not device_id:
        return CHANNEL_CODE_SESSION_UNKNOWN, {"session_id": session_id}
    code, params = await asyncio.to_thread(judge_terminal, client_id, device_id)
    if code:
        return code, params
    if verb == CHANNEL_FRAME_PERSIST and await asyncio.to_thread(
        is_session_refused,
        runtime,
        device_id,
        session_id,
        shell_owner(client_id),
        is_join=False,
    ):
        return CHANNEL_CODE_SESSION_NOT_OWNED, {"session_id": session_id}
    return "", {}


async def _ask_agent(
    runtime, client_id: str, verb: str, session_id: str, frame: dict
) -> tuple:
    """Send the verb to the machine holding the session and wait for its reply."""
    device_id = await asyncio.to_thread(
        device_of_session, runtime.agent_sessions, session_id
    )
    agent = runtime.agent_sessions.get(device_id)
    if agent is None:
        return AgentOfflineError.code, {"device": device_id}
    request = secrets.token_hex(8)
    flags = persist_flags(frame) if verb == CHANNEL_FRAME_PERSIST else {}
    future = runtime.channel_replies.expect(device_id, request)
    try:
        await agent.send_json(
            {"type": verb, "request": request, "session_id": session_id, **flags}
        )
        reply = await asyncio.wait_for(future, CHANNEL_REPLY_TIMEOUT_S)
    except AgentOfflineError:
        runtime.channel_replies.forget(device_id, request)
        return AgentOfflineError.code, {"device": device_id}
    except asyncio.TimeoutError:
        runtime.channel_replies.forget(device_id, request)
        return CHANNEL_CODE_NEVER_REPORTED, {"device": device_id}
    code = str(reply.get("code", "") or "")
    params = reply.get("params")
    params = dict(params) if isinstance(params, dict) else {}
    if not code and verb == CHANNEL_FRAME_PERSIST:
        await record_sharing(
            runtime, device_id, session_id, shell_owner(client_id), flags
        )
    return code, params


def _size(args: dict) -> tuple:
    """A terminal's first size, the defaults where the open names none."""
    try:
        cols = int(args.get("cols") or DEFAULT_COLUMNS)
        rows = int(args.get("rows") or DEFAULT_ROWS)
    except (TypeError, ValueError):
        return DEFAULT_COLUMNS, DEFAULT_ROWS
    return max(1, cols), max(1, rows)
