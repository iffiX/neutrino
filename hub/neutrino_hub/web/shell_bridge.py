"""What every bridge to an agent's shell stream shares.

The panel's terminal socket and a client's ``shell`` stream both drive one
agent shell: its output read as it arrives, its end settled when either side
stops, and a later size sent on a ``command {agent, resize}`` stream the
agent closes itself. A shell is a session its opener names by a generated
id: the hub stamps the opener as its ``owner``, the agent reports every
session it holds, a ``persist`` command from the owner keeps one past its
streams or shares it, and ``stop_session`` ends one. Which sessions a viewer
sees is :func:`sessions_for`.
"""

import asyncio
import contextlib
import functools

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CALL_TIMEOUT_S,
    CHANNEL_CODE_NEVER_REPORTED,
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_SHELL_OWNER_CLIENT_PREFIX,
    CHANNEL_SHELL_OWNER_HUB,
    CHANNEL_STREAM_COMMAND,
    CHANNEL_VERB_PERSIST,
    CHANNEL_VERB_RESIZE,
    CHANNEL_VERB_STOP_SESSION,
)
from neutrino_hub.modules.clients.constants import CLIENT_PERMISSION_TERMINAL
from neutrino_hub.modules.clients.permissions import (
    is_device_permitted,
    permitted_devices,
    permitted_kinds,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.identity import hub_name

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
    sessions, device_id: str, session_id: str, flags: dict
) -> None:
    """Set a session's two flags on the agent; it closes the command.

    Args:
        sessions: The agents' sessions.
        device_id: The device.
        session_id: The session, by the id its opener generated.
        flags: ``is_persistent``, whether it stays when its last stream
            closes, and ``is_shared``, whether every viewer with terminal
            rights on the machine sees it; a flag left out keeps its value.

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
            **flags,
        },
    )


def persist_flags(message: dict) -> dict:
    """The flags a ``persist`` names, each a bool; the ones it leaves out absent.

    Args:
        message: The browser's message or the client's command arguments.

    Returns:
        ``is_persistent`` and ``is_shared`` where the message carries them.
    """
    return {
        name: bool(message[name])
        for name in ("is_persistent", "is_shared")
        if name in message
    }


def client_owner(client_id: str) -> str:
    """The owner the hub stamps on a shell a client opens.

    Args:
        client_id: The client.

    Returns:
        ``client:<id>``.
    """
    return f"{CHANNEL_SHELL_OWNER_CLIENT_PREFIX}{client_id}"


def is_persist_refused(
    agent_sessions, device_id: str, session_id: str, viewer: str
) -> bool:
    """Whether a ``persist`` from this viewer is refused ``session_not_owned``.

    Args:
        agent_sessions: The agents' sessions, whose reports name each
            session's owner.
        device_id: The machine holding the session.
        session_id: The session.
        viewer: The owner stamp of whoever sent it: ``hub`` or
            ``client:<id>``.

    Returns:
        True when the machine reports the session under another owner; a
        session it does not list yet is the viewer's own new one.
    """
    for session in reported_sessions(agent_sessions):
        if session["device_id"] == device_id and session["session_id"] == session_id:
            return session["owner"] != "" and session["owner"] != viewer
    return False


def sessions_for(runtime, viewer: str) -> list:
    """The shell sessions one viewer sees, from the machines' latest reports.

    Args:
        runtime: The shared runtime.
        viewer: ``hub`` for the panel, ``client:<id>`` for a client.

    Returns:
        Every session the viewer owns, and every shared session on a machine
        it has terminal rights on, oldest first, as :func:`viewer_rows`
        gives them. A client that is gone or switched off sees none.
    """
    if viewer == CHANNEL_SHELL_OWNER_HUB:
        is_allowed = _every_device
    else:
        is_allowed = _client_terminal_rights(
            viewer.removeprefix(CHANNEL_SHELL_OWNER_CLIENT_PREFIX)
        )
        if is_allowed is None:
            return []
    seen = [
        session
        for session in reported_sessions(runtime.agent_sessions)
        if session["owner"] == viewer
        or (session["is_shared"] and is_allowed(session["device_id"]))
    ]
    return viewer_rows(runtime, viewer, seen)


def viewer_rows(runtime, viewer: str, sessions: list) -> list:
    """Reported sessions as one viewer is shown them.

    Args:
        runtime: The shared runtime, for the machines' names.
        viewer: The owner stamp ``is_owned`` is read against.
        sessions: Entries of :func:`reported_sessions`.

    Returns:
        Each entry with ``device_name``, ``owner_name`` and ``is_owned``
        added.
    """
    names = {
        device.id: device_name(runtime, device)
        for device in DeviceRegistry().all_stored()
    }
    clients = ClientRegistry()
    return [
        {
            **session,
            "device_name": names.get(session["device_id"], session["device_id"]),
            "owner_name": owner_name(session["owner"], clients),
            "is_owned": session["owner"] == viewer,
        }
        for session in sessions
    ]


def owner_name(owner: str, clients: ClientRegistry) -> str:
    """What a session's owner is called: the hub's name, or a client's.

    Args:
        owner: The stamp a session holds, ``hub`` or ``client:<id>``.
        clients: The registry the client's name is read from.

    Returns:
        The hub's name for the panel, the client's name for a client the
        registry holds, and the stamp itself otherwise.
    """
    if owner == CHANNEL_SHELL_OWNER_HUB:
        try:
            return hub_name() or owner
        except (FileNotFoundError, ValueError):
            return owner
    if owner.startswith(CHANNEL_SHELL_OWNER_CLIENT_PREFIX):
        client = clients.get(owner[len(CHANNEL_SHELL_OWNER_CLIENT_PREFIX) :])
        if client is not None and client.name:
            return client.name
    return owner


def device_name(runtime, device) -> str:
    """What the hub calls one device: its name, its hostname, its address.

    Args:
        runtime: The shared runtime, for the hostname the machine reports.
        device: The stored device.

    Returns:
        The first of those that is set, else the device's id.
    """
    return (
        device.name
        or runtime.device_hostname.get(device.id, "")
        or device.ipv4_address
        or device.id
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
        ``{device_id, session_id, account, started_at, title, owner,
        is_attached, is_persistent, is_shared, attached_count}`` per session,
        ordered by ``started_at``.
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
        ``{session_id, account, started_at, title, owner, is_attached,
        is_persistent, is_shared, attached_count}``, or None for an entry
        naming no id. An agent that reports no count has one stream
        attached while ``is_attached`` holds.
    """
    if not isinstance(entry, dict):
        return None
    session_id = str(entry.get("session_id", "") or "")
    if not session_id:
        return None
    is_attached = bool(entry.get("is_attached", False))
    return {
        "session_id": session_id,
        "account": str(entry.get("account", "") or ""),
        "started_at": _seconds(entry.get("started_at")),
        "title": str(entry.get("title", "") or ""),
        "owner": str(entry.get("owner", "") or ""),
        "is_attached": is_attached,
        "is_persistent": bool(entry.get("is_persistent", False)),
        "is_shared": bool(entry.get("is_shared", False)),
        "attached_count": _count(entry.get("attached_count"), int(is_attached)),
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


def _every_device(device_id: str) -> bool:
    """The panel's terminal rights: every machine."""
    return True


def _client_terminal_rights(client_id: str):
    """Whether a client has terminal rights on a machine, as a predicate;
    None for a client that is gone or switched off."""
    registry = ClientRegistry()
    client = registry.get(client_id)
    if client is None or client.is_disabled:
        return None
    if CLIENT_PERMISSION_TERMINAL not in permitted_kinds(registry, client):
        return _no_device
    devices = permitted_devices(registry, client)
    return functools.partial(is_device_permitted, devices, CLIENT_PERMISSION_TERMINAL)


def _no_device(device_id: str) -> bool:
    """Terminal rights on no machine."""
    return False


def _count(value, fallback: int) -> int:
    """A reported count, the fallback where it is not a number."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def _seconds(value) -> int:
    """A reported stamp in Unix seconds, 0 where it is not a number."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _session_order(session: dict) -> tuple:
    return (session["started_at"], session["device_id"], session["session_id"])
