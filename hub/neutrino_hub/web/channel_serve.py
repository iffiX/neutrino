"""Serving one channel from its welcome to its last frame, per role.

An agent's socket carries its reports up and the hub's state and streams
down; a client's carries its reports up and the published list down. Both
loops read the same frames: a ``report`` is recorded, an ``open`` hands a
peer-opened stream to its kind's handler, a ``close`` or a ``credit`` goes
to the stream it names, and bytes go to theirs. The kinds a peer may open
are ``package`` and ``log`` from an agent and ``service`` from a client.
"""

import asyncio
import codecs
import functools
import hashlib
import json

from fastapi import WebSocket, WebSocketDisconnect

from neutrino_hub.exceptions import AgentArtifactFetchError, AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CHUNK_BYTES,
    CHANNEL_FRAME_OPEN,
    CHANNEL_FRAME_REPORT,
    CHANNEL_STREAM_LOG,
    CHANNEL_STREAM_PACKAGE,
    CHANNEL_STREAM_SERVICE,
)
from neutrino_hub.modules.channel.sessions import ChannelSession, ChannelStream
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.clients.services import service_material
from neutrino_hub.modules.devices.agent_package import platform_family
from neutrino_hub.modules.devices.agent_reports import (
    record_hello,
    record_offline,
    record_report,
)
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.web import channel_state
from neutrino_hub.web.constants import (
    WEB_EVENT_CLIENTS,
    WEB_EVENT_DEVICE_REPORT,
    WEB_EVENT_METRICS,
    WEB_TASK_LABEL_MODULE,
)

# What a report has to change before the panel refetches the device list.
# Metrics are not among them: every report carries them, and they ride
# their own event to the tiles and the monitor.
REPORT_PANEL_SECTIONS = ("modules", "desktop", "error")


async def serve_agent(
    websocket: WebSocket, runtime, session: ChannelSession, device, welcome: dict
) -> None:
    """Serve one agent's channel: the welcome, then every frame to the last.

    Args:
        websocket: The agent's socket, past its hello.
        runtime: The shared runtime.
        session: The session built from the hello.
        device: The device the token resolved to.
        welcome: The hub's identity card.
    """
    sessions = runtime.agent_sessions
    sessions.stream_handlers.setdefault(
        CHANNEL_STREAM_PACKAGE, functools.partial(serve_package_stream, runtime)
    )
    sessions.stream_handlers.setdefault(
        CHANNEL_STREAM_LOG, functools.partial(serve_log_stream, runtime)
    )
    await sessions.attach(session)
    try:
        await session.send_json(welcome)
        await asyncio.to_thread(
            record_hello,
            runtime,
            device,
            name=session.name,
            peer_host=session.address,
            reached_host=websocket.url.hostname or "",
        )
        await _serve_frames(websocket, session, _AgentFrames(runtime, session, device))
    except (WebSocketDisconnect, AgentOfflineError):
        pass
    finally:
        if sessions.detach(session):
            record_offline(runtime, device)


async def serve_client(
    websocket: WebSocket, runtime, session: ChannelSession, client, welcome: dict
) -> None:
    """Serve one client's channel: the welcome, then every frame to the last.

    Args:
        websocket: The client's socket, past its hello.
        runtime: The shared runtime.
        session: The session built from the hello.
        client: The client the token resolved to.
        welcome: The hub's identity card.
    """
    sessions = runtime.client_sessions
    sessions.stream_handlers.setdefault(
        CHANNEL_STREAM_SERVICE, functools.partial(serve_service_stream, runtime)
    )
    await sessions.attach(session)
    try:
        await asyncio.to_thread(
            channel_state.note_client_scope,
            runtime,
            client.id,
            peer_host=session.address,
            reached_host=websocket.url.hostname or "",
        )
        await session.send_json(welcome)
        await asyncio.to_thread(
            ClientRegistry().record_seen,
            client.id,
            hostname="",
            platform={},
            version=session.version,
        )
        runtime.events.publish(WEB_EVENT_CLIENTS)
        await _serve_frames(websocket, session, _ClientFrames(runtime, session, client))
    except (WebSocketDisconnect, AgentOfflineError):
        pass
    finally:
        sessions.detach(session)
        runtime.events.publish(WEB_EVENT_CLIENTS)


async def serve_package_stream(
    runtime, session: ChannelSession, stream: ChannelStream
) -> None:
    """Serve a ``package`` stream an agent opened: the bytes, then their digest.

    ``{module}`` names a module's package from the hub's cache; ``{}`` is
    the agent's own package for its platform. The bytes go down under the
    agent's credit and the close carries their ``sha256``.

    Args:
        runtime: The shared runtime.
        session: The agent's session.
        stream: The stream, closed here.
    """
    module = str(stream.args.get("module", "") or "")
    platform = dict(runtime.device_platform.get(session.key, {}))
    try:
        path = await asyncio.to_thread(_package_path, runtime, module, platform)
    except AgentArtifactFetchError as error:
        await stream.close(error.code, error.params)
        return
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = await asyncio.to_thread(handle.read, CHANNEL_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                await stream.send_bytes(chunk)
    except OSError:
        await stream.close("module_artifact_missing", {})
        return
    await stream.close("", {"sha256": digest.hexdigest()})


async def serve_log_stream(
    runtime, session: ChannelSession, stream: ChannelStream
) -> None:
    """Serve a ``log`` stream an agent opened: its lines become one task.

    ``{module}`` names the module being installed or uninstalled. The task
    runs under :data:`WEB_TASK_LABEL_MODULE`, which is how the module list
    finds it for the panel to follow on ``/ws/hub/task``, and it ends with
    the close: the module's ``state``, and the code when the operation
    failed.

    Args:
        runtime: The shared runtime.
        session: The agent's session.
        stream: The stream, closed by the agent.
    """
    module = str(stream.args.get("module", "") or "")
    runtime.tasks.start(
        label=module_task_label(session.key, module), source=_log_lines(stream)
    )
    await stream.wait_closed()


def module_task_label(device_id: str, module: str) -> str:
    """The label a module's install or uninstall task runs under."""
    return WEB_TASK_LABEL_MODULE.format(device_id=device_id, module=module)


async def _log_lines(stream: ChannelStream):
    """A log stream's lines as they arrive, then what it closed with.

    Yields:
        Each line, then a JSON line ``{"code", "params"}`` when the close
        carries a code, then ``[<state>]`` for the module's state after
        the operation.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while True:
        item = await stream.recv()
        if item is None:
            break
        text = decoder.decode(item[1])
        if text:
            yield text
    info = stream.close_info or {}
    params = dict(info.get("params") or {})
    state = str(params.pop("state", "") or "")
    if info.get("code"):
        yield json.dumps({"code": info["code"], "params": params}) + "\n"
    if state:
        yield f"[{state}]\n"


async def serve_service_stream(
    runtime, session: ChannelSession, stream: ChannelStream
) -> None:
    """Serve a ``service`` stream a client opened: the entry's material as the close.

    Args:
        runtime: The shared runtime.
        session: The client's session.
        stream: The stream, closed here.
    """
    entry_id = str(stream.args.get("id", "") or "")
    code, params = await asyncio.to_thread(
        service_material, runtime, session.key, entry_id
    )
    await stream.close(code, params)


def decode_frame(text: "str | None") -> "dict | None":
    """One text frame as the object it carries, or None."""
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _package_path(runtime, module: str, platform: dict):
    """Where the package a ``package`` stream asks for is on this hub.

    Raises:
        AgentArtifactFetchError: ``module_unknown`` for a module no manifest
            names, and the caches' own typed reasons.
    """
    if not module:
        return runtime.agent_packages.package(
            family=platform_family(platform), architecture=str(platform.get("arch", ""))
        )
    manifest = load_module_manifests().get(module)
    if manifest is None:
        raise AgentArtifactFetchError("module_unknown", name=module)
    return runtime.agent_modules.artifact(
        name=module, manifest=manifest, platform=platform
    ).path


async def _serve_frames(websocket: WebSocket, session: ChannelSession, frames) -> None:
    """Read frames until the socket ends.

    Args:
        websocket: The peer's socket.
        session: The attached session.
        frames: The role's report handler, called with each decoded report.
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        data = message.get("bytes")
        if data is not None:
            session.dispatch_bytes(data)
            continue
        decoded = decode_frame(message.get("text"))
        if decoded is None:
            continue
        kind = decoded.get("type")
        if kind == CHANNEL_FRAME_REPORT:
            await frames.take_report(decoded)
        elif kind == CHANNEL_FRAME_OPEN:
            await session.accept_stream(decoded)
        else:
            session.dispatch_text(decoded)


def _is_panel_change(previous: dict, report: dict) -> bool:
    """Whether a report says anything new about what the panel draws.

    Args:
        previous: The report before this one, empty for the first.
        report: The report that just arrived.

    Returns:
        True when one of :data:`REPORT_PANEL_SECTIONS` differs.
    """
    return any(
        previous.get(section) != report.get(section)
        for section in REPORT_PANEL_SECTIONS
    )


class _AgentFrames:
    """What an agent's reports do to the hub."""

    def __init__(self, runtime, session: ChannelSession, device):
        self._runtime = runtime
        self._session = session
        self._device = device

    async def take_report(self, report: dict) -> None:
        """Record one report, tell the panel, and offer the state once."""
        runtime = self._runtime
        session = self._session
        key = self._device.id
        is_panel_change = _is_panel_change(session.report, report)
        is_module_change = session.report.get("modules") != report.get("modules")
        session.record_report(report)
        await asyncio.to_thread(
            record_report, runtime, self._device, report, peer_host=session.address
        )
        session.note_report_recorded()
        if is_module_change:
            runtime.published_services.schedule_refresh()
        if is_panel_change:
            runtime.events.publish(WEB_EVENT_DEVICE_REPORT, key)
        runtime.events.publish(
            WEB_EVENT_METRICS, key, data=dict(runtime.device_metrics.get(key, {}))
        )
        if session.offered_hash is None:
            document = await asyncio.to_thread(channel_state.agent_state, runtime, key)
            if document["hash"] != session.state_hash:
                await session.push_state(document)
            session.offered_hash = document["hash"]


class _ClientFrames:
    """What a client's reports do to the hub."""

    def __init__(self, runtime, session: ChannelSession, client):
        self._runtime = runtime
        self._session = session
        self._client = client

    async def take_report(self, report: dict) -> None:
        """Record one report and offer the state once."""
        runtime = self._runtime
        session = self._session
        session.record_report(report)
        machine = report.get("machine")
        machine = machine if isinstance(machine, dict) else {}
        await asyncio.to_thread(
            ClientRegistry().record_seen,
            self._client.id,
            hostname=str(machine.get("hostname", "") or ""),
            platform=(
                dict(machine["platform"])
                if isinstance(machine.get("platform"), dict)
                else {}
            ),
            version="",
        )
        session.note_report_recorded()
        if session.offered_hash is None:
            document = await asyncio.to_thread(
                channel_state.client_state, runtime, self._client.id
            )
            if document["hash"] != session.state_hash:
                await session.push_state(document)
            session.offered_hash = document["hash"]
