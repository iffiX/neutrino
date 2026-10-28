"""Answering the transport's ``entry`` question: where one stream goes.

A client's ``connect`` names a published entry or the panel, its ``shell``
or ``exec`` a managed machine; an agent's ``connect`` names the ``ai``
entry. The hub's Python judges each against the binding's permission and
names the far end: a stream to open on the agent's session with the hub's
stamps written in, or an address the transport dials itself (transport.md,
"The hub's local channel").
"""

import asyncio

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_KIND_UNKNOWN,
    CHANNEL_CONNECT_LOOPBACK,
    CHANNEL_ROLE_AGENT,
    CHANNEL_STREAM_CONNECT,
    CHANNEL_STREAM_EXEC,
    CHANNEL_STREAM_SHELL,
)
from neutrino_hub.modules.clients.constants import CLIENT_PERMISSION_TERMINAL
from neutrino_hub.modules.clients.permissions import terminal_row_id
from neutrino_hub.modules.clients.services import (
    agent_connect_target,
    connect_target,
)
from neutrino_hub.web.channel_shell import (
    agent_shell_open,
    judge_terminal,
    shell_owner,
)
from neutrino_hub.web.constants import WEB_DEFAULT_LISTEN_PORT
from neutrino_hub.web.shell_bridge import is_session_refused, record_opened
from neutrino_hub.modules.channel.constants import CHANNEL_CODE_SESSION_NOT_OWNED


async def entry_answer(runtime, *, role: str, binding_id: str, open_body: dict) -> dict:
    """The answer to one ``entry`` question.

    Args:
        runtime: The shared runtime.
        role: The session's role, ``agent`` or ``client``.
        binding_id: The binding the session is bound to.
        open_body: The open record's object, ``kind`` first.

    Returns:
        ``{kind, device_id, key, target}`` to admit the stream, ``key`` the
        stream's row id in a permission, or ``{code, params}`` to refuse
        it.
    """
    kind = str(open_body.get("kind", "") or "")
    if role == CHANNEL_ROLE_AGENT:
        if kind != CHANNEL_STREAM_CONNECT:
            return _refusal(CHANNEL_CODE_KIND_UNKNOWN, {"kind": kind})
        code, params, target = await asyncio.to_thread(
            agent_connect_target, runtime, binding_id, open_body
        )
        if code:
            return _refusal(code, params)
        return {
            "kind": target.kind,
            "device_id": target.provider,
            "key": target.row_id,
            "target": {
                "address": target.host,
                "port": target.port,
                "protocol": target.protocol,
            },
        }
    if kind == CHANNEL_STREAM_CONNECT:
        return await _client_connect(runtime, binding_id, open_body)
    if kind in (CHANNEL_STREAM_SHELL, CHANNEL_STREAM_EXEC):
        return await _client_terminal(runtime, binding_id, kind, open_body)
    return _refusal(CHANNEL_CODE_KIND_UNKNOWN, {"kind": kind})


async def _client_connect(runtime, client_id: str, open_body: dict) -> dict:
    """A client's ``connect``: the entry's far end, judged for the client now."""
    code, params, target = await asyncio.to_thread(
        connect_target,
        runtime,
        client_id,
        open_body,
        open_count=0,
        panel_port=panel_port(runtime),
    )
    if code:
        return _refusal(code, params)
    if target.device_id:
        agent = runtime.agent_sessions.get(target.device_id)
        if agent is None:
            return _refusal(AgentOfflineError.code, {"device": target.device_id})
        return {
            "kind": target.kind,
            "device_id": target.provider,
            "key": target.row_id,
            "target": {
                "session": agent.session_id,
                "open": {
                    "kind": CHANNEL_STREAM_CONNECT,
                    "port": target.port,
                    "protocol": target.protocol,
                },
            },
        }
    return {
        "kind": target.kind,
        "device_id": target.provider,
        "key": target.row_id,
        "target": {
            "address": target.host or CHANNEL_CONNECT_LOOPBACK,
            "port": target.port,
            "protocol": target.protocol,
        },
    }


async def _client_terminal(runtime, client_id: str, kind: str, open_body: dict) -> dict:
    """A client's ``shell`` or ``exec``: the agent's own stream, stamped."""
    device_id = str(open_body.get("device_id", "") or "")
    code, params = await asyncio.to_thread(judge_terminal, client_id, device_id)
    if code:
        return _refusal(code, params)
    agent = runtime.agent_sessions.get(device_id)
    if agent is None:
        return _refusal(AgentOfflineError.code, {"device": device_id})
    owner = shell_owner(client_id)
    session_id = str(open_body.get("session_id", "") or "")
    if kind == CHANNEL_STREAM_SHELL and session_id:
        if await asyncio.to_thread(
            is_session_refused, runtime, device_id, session_id, owner, is_join=True
        ):
            return _refusal(CHANNEL_CODE_SESSION_NOT_OWNED, {"session_id": session_id})
        if open_body.get("is_resumed") is not True:
            await asyncio.to_thread(
                record_opened,
                runtime,
                device_id,
                session_id,
                owner,
                open_body.get("is_shared") is True,
            )
    return {
        "kind": CLIENT_PERMISSION_TERMINAL,
        "device_id": device_id,
        "key": terminal_row_id(device_id),
        "target": {
            "session": agent.session_id,
            "open": agent_shell_open(kind, open_body, owner=owner),
        },
    }


def panel_port(runtime) -> int:
    """The port the panel answers plain HTTP on."""
    try:
        return int(runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT))
    except (TypeError, ValueError):
        return WEB_DEFAULT_LISTEN_PORT


def _refusal(code: str, params: dict) -> dict:
    return {"code": code, "params": dict(params or {})}
