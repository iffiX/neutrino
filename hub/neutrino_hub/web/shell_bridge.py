"""What every bridge to an agent's shell stream shares.

The panel's terminal socket and a client's ``shell`` stream both drive one
agent shell: its output read as it arrives, its end settled when either side
stops, and a later size sent on a ``command {agent, resize}`` stream the
agent closes itself. A shell is a session its opener names by a generated
id: the agent reports every session it holds, a ``persist`` command keeps
one past its stream, and ``stop_session`` ends one.
"""

import asyncio
import contextlib

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CALL_TIMEOUT_S,
    CHANNEL_CODE_NEVER_REPORTED,
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_STREAM_COMMAND,
    CHANNEL_VERB_PERSIST,
    CHANNEL_VERB_RESIZE,
    CHANNEL_VERB_STOP_SESSION,
)

# The size a shell opens at when the viewer names none.
DEFAULT_COLUMNS = 80
DEFAULT_ROWS = 24


async def shell_output(stream):
    """The shell's output as it arrives, until the stream closes.

    Args:
        stream: The agent's shell stream.

    Yields:
        Each chunk of bytes the agent sent.
    """
    while True:
        item = await stream.recv()
        if item is None:
            return
        if item[0] == "data":
            yield item[1]


async def settle_shell(stream, reader: asyncio.Task, pump: asyncio.Task):
    """Wait for either side to end, then stop both and close the shell stream.

    Args:
        stream: The agent's shell stream.
        reader: The task forwarding the viewer's input; its end means the
            viewer went away.
        pump: The task forwarding the shell's output; its end means the
            shell exited, the agent refused it, or the agent went away.

    Returns:
        What the shell stream closed with, ``{code, params}``, when the shell
        ended first; None when the viewer did.
    """
    done, _ = await asyncio.wait({reader, pump}, return_when=asyncio.FIRST_COMPLETED)
    info = dict(stream.close_info or {}) if pump in done else None
    with contextlib.suppress(AgentOfflineError):
        await stream.close()
    for task in (reader, pump):
        task.cancel()
    for task in (reader, pump):
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return info


async def resize_shell(sessions, device_id: str, shell_id: int, cols: int, rows: int):
    """Tell the agent a shell's new size, on a command stream it closes itself.

    Args:
        sessions: The agents' sessions.
        device_id: The device.
        shell_id: The agent shell stream's id.
        cols: Columns.
        rows: Rows.

    Raises:
        AgentOfflineError: When the device has no channel.
    """
    await sessions.open_stream(
        device_id,
        CHANNEL_STREAM_COMMAND,
        {
            "module": CHANNEL_COMMAND_MODULE_AGENT,
            "verb": CHANNEL_VERB_RESIZE,
            "shell": shell_id,
            "cols": cols,
            "rows": rows,
        },
    )


async def persist_session(
    sessions, device_id: str, session_id: str, is_persistent: bool
) -> None:
    """Tell the agent whether a session outlives its stream; it closes the command.

    Args:
        sessions: The agents' sessions.
        device_id: The device.
        session_id: The session, by the id its opener generated.
        is_persistent: Whether it stays when its stream closes.

    Raises:
        AgentOfflineError: When the device has no channel.
    """
    await sessions.open_stream(
        device_id,
        CHANNEL_STREAM_COMMAND,
        {
            "module": CHANNEL_COMMAND_MODULE_AGENT,
            "verb": CHANNEL_VERB_PERSIST,
            "session_id": session_id,
            "is_persistent": bool(is_persistent),
        },
    )


async def session_command(sessions, device_id: str, verb: str, args: dict) -> dict:
    """Run one session verb on the agent and wait for its close.

    Args:
        sessions: The agents' sessions.
        device_id: The device.
        verb: ``persist`` or ``stop_session``.
        args: What the verb takes beside the module and the verb.

    Returns:
        The close, ``{"code", "params"}``; ``agent_never_reported`` when the
        agent did not close it in time.

    Raises:
        AgentOfflineError: When the device has no channel, or the socket
            ends before the close.
    """
    stream = await sessions.open_stream(
        device_id,
        CHANNEL_STREAM_COMMAND,
        {"module": CHANNEL_COMMAND_MODULE_AGENT, "verb": verb, **args},
    )
    try:
        info = await asyncio.wait_for(stream.wait_closed(), CHANNEL_CALL_TIMEOUT_S)
    except asyncio.TimeoutError:
        return {"code": CHANNEL_CODE_NEVER_REPORTED, "params": {}}
    if info is None:
        raise AgentOfflineError(device_id)
    return {
        "code": str(info.get("code", "") or ""),
        "params": dict(info.get("params") or {}),
    }


def reported_sessions(agent_sessions) -> list:
    """Every shell session the online machines report, oldest first.

    Args:
        agent_sessions: The agents' sessions, whose latest reports carry
            each machine's ``machine.sessions``.

    Returns:
        ``{device_id, session_id, account, started_at, title, is_attached,
        is_persistent}`` per session, ordered by ``started_at``.
    """
    listed = []
    for device_id, report in agent_sessions.reports().items():
        machine = report.get("machine") if isinstance(report, dict) else None
        held = machine.get("sessions") if isinstance(machine, dict) else None
        for entry in held if isinstance(held, list) else []:
            session = session_fields(entry)
            if session is not None:
                listed.append({"device_id": device_id, **session})
    listed.sort(key=_session_order)
    return listed


def session_fields(entry) -> "dict | None":
    """One reported session, its fields normalized.

    Args:
        entry: One member of a report's ``machine.sessions``.

    Returns:
        ``{session_id, account, started_at, title, is_attached,
        is_persistent}``, or None for an entry naming no id.
    """
    if not isinstance(entry, dict):
        return None
    session_id = str(entry.get("session_id", "") or "")
    if not session_id:
        return None
    return {
        "session_id": session_id,
        "account": str(entry.get("account", "") or ""),
        "started_at": _seconds(entry.get("started_at")),
        "title": str(entry.get("title", "") or ""),
        "is_attached": bool(entry.get("is_attached", False)),
        "is_persistent": bool(entry.get("is_persistent", False)),
    }


def device_of_session(agent_sessions, session_id: str) -> str:
    """The online machine reporting a session, empty when none does.

    Args:
        agent_sessions: The agents' sessions.
        session_id: The session's id.

    Returns:
        The device id.
    """
    for session in reported_sessions(agent_sessions):
        if session["session_id"] == session_id:
            return session["device_id"]
    return ""


def _seconds(value) -> int:
    """A reported stamp in Unix seconds, 0 where it is not a number."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _session_order(session: dict) -> tuple:
    return (session["started_at"], session["device_id"], session["session_id"])
