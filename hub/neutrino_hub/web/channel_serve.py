"""Serving one channel from its welcome to its last frame, per role.

An agent's socket carries its reports up and the hub's state and streams
down; a client's carries its reports up and the published list down. Both
loops read the same frames: a ``report`` is recorded, an ``open`` hands a
peer-opened stream to its kind's handler, a ``close`` or a ``credit`` goes
to the stream it names, a ``ping`` is answered with a ``pong`` carrying its
nonce, and bytes go to theirs. The kinds a peer may open
are ``package``, ``log`` and, for its AI gateway forward, ``connect`` from
an agent, and ``service``, ``shell``, ``exec``, ``command`` and ``connect``
from a client. An agent older than
the hub whose own package was refused before the hub knew its platform is
sent ``reinstall`` once, when the report naming the platform lands, unless
it runs on the hub's own machine, whose agent the hub's update installs.

An agent of 0.5 is served for its own update alone: the welcome, its
reports read for the platform, ``package {}``, and ``protocol_too_old`` for
every other stream it opens. Its session is in ``agent_update_sessions``,
never in ``agent_sessions``: the hub pushes it no state and opens it no stream.
"""

import asyncio
import time
import codecs
import functools
import hashlib
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from neutrino_hub.exceptions import AgentArtifactFetchError, AgentOfflineError
from neutrino_hub.modules.channel.admission import admit
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CHUNK_BYTES,
    CHANNEL_CLOSE_REPLACED,
    CHANNEL_CODE_REPLACED,
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_DEV_VERSION_SUFFIX,
    CHANNEL_ROLE_CLIENT,
    CHANNEL_FRAME_OPEN,
    CHANNEL_FRAME_PING,
    CHANNEL_FRAME_PONG,
    CHANNEL_FRAME_REPORT,
    CHANNEL_PING_NONCE_CHARS_MAX,
    CHANNEL_PROTOCOL_UPDATE_ONLY,
    CHANNEL_STREAM_COMMAND,
    CHANNEL_STREAM_CONNECT,
    CHANNEL_STREAM_EXEC,
    CHANNEL_STREAM_KINDS,
    CHANNEL_STREAM_LOG,
    CHANNEL_PACKAGE_PLATFORM_POLL_S,
    CHANNEL_PACKAGE_PLATFORM_WAIT_S,
    CHANNEL_STREAM_PACKAGE,
    CHANNEL_STREAM_SERVICE,
    CHANNEL_STREAM_SHELL,
    CHANNEL_VERB_REINSTALL,
)
from neutrino_hub.modules.channel.sessions import (
    ChannelSession,
    ChannelStream,
    version_of_software,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.clients.services import panel_material, service_material
from neutrino_hub.modules.devices.agent_module_cache import AgentModuleFetchProgress
from neutrino_hub.modules.devices.agent_package import platform_family
from neutrino_hub.modules.devices.agent_reports import (
    record_hello,
    record_offline,
    record_report,
)
from neutrino_hub.modules.devices.constants import AGENT_MODULE_PROGRESS_VERB_SEND
from neutrino_hub.modules.devices.manifests import (
    load_module_manifests,
    load_tool_manifests,
)
from neutrino_hub.system.machine import machine_id
from neutrino_hub.utils.version_number import parse_version
from neutrino_hub.web import channel_state
from neutrino_hub.web.channel_connect import (
    serve_agent_connect_stream,
    serve_connect_stream,
)
from neutrino_hub.web.channel_shell import (
    serve_command_stream,
    serve_exec_stream,
    serve_shell_stream,
)
from neutrino_hub.web.constants import (
    WEB_EVENT_CLIENTS,
    WEB_EVENT_DEVICE_REPORT,
    WEB_EVENT_DEVICES,
    WEB_EVENT_METRICS,
    WEB_TASK_LABEL_MODULE,
)

LOGGER = logging.getLogger(__name__)

# What a report has to change before the panel refetches the device list.
# Metrics are not among them: every report carries them, and they ride
# their own event to the tiles and the monitor.
REPORT_PANEL_SECTIONS = ("modules", "desktop", "error", "ai_tools")


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
    sessions.stream_handlers.setdefault(
        CHANNEL_STREAM_CONNECT, functools.partial(serve_agent_connect_stream, runtime)
    )
    update = runtime.agent_update_sessions.pop(device.id, None)
    if update is not None and not update.is_closed:
        await update.close(CHANNEL_CLOSE_REPLACED, CHANNEL_CODE_REPLACED)
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
        frames = _AgentFrames(
            runtime,
            session,
            device,
            hub_version=version_of_software(welcome["software"]),
        )
        await _serve_frames(websocket, session, frames)
    except (WebSocketDisconnect, AgentOfflineError):
        pass
    finally:
        if sessions.detach(session):
            record_offline(runtime, device)


async def serve_update_only_agent(
    websocket: WebSocket, runtime, session: ChannelSession, device, welcome: dict
) -> None:
    """Serve an agent of 0.5 for its own update alone, to its last frame.

    The session stays in ``agent_update_sessions`` after its socket ends,
    until the updated agent says hello with this hub's number.

    Args:
        websocket: The agent's socket, past its hello.
        runtime: The shared runtime.
        session: The session built from the hello.
        device: The device the token resolved to.
        welcome: The hub's identity card.
    """
    session.stream_handlers = {
        kind: functools.partial(_serve_update_only_stream, runtime)
        for kind in CHANNEL_STREAM_KINDS
    }
    previous = runtime.agent_update_sessions.get(device.id)
    runtime.agent_update_sessions[device.id] = session
    if previous is not None and not previous.is_closed:
        await previous.close(CHANNEL_CLOSE_REPLACED, CHANNEL_CODE_REPLACED)
    runtime.events.publish(WEB_EVENT_DEVICES)
    try:
        await session.send_json(welcome)
        frames = _UpdateOnlyAgentFrames(runtime, session, device)
        await _serve_frames(websocket, session, frames)
    except (WebSocketDisconnect, AgentOfflineError):
        pass
    finally:
        session.fail_streams()
        runtime.events.publish(WEB_EVENT_DEVICES)


def listener_port(websocket: WebSocket) -> int:
    """The hub's port a socket arrived on.

    Args:
        websocket: The socket.

    Returns:
        The port of the listening socket that took it; 0 when unknown.
    """
    server = websocket.scope.get("server") or ()
    try:
        return int(server[1])
    except (IndexError, TypeError, ValueError):
        return 0


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
    sessions.stream_handlers.setdefault(
        CHANNEL_STREAM_SHELL, functools.partial(serve_shell_stream, runtime)
    )
    sessions.stream_handlers.setdefault(
        CHANNEL_STREAM_EXEC, functools.partial(serve_exec_stream, runtime)
    )
    sessions.stream_handlers.setdefault(
        CHANNEL_STREAM_COMMAND, functools.partial(serve_command_stream, runtime)
    )
    sessions.stream_handlers.setdefault(
        CHANNEL_STREAM_CONNECT, functools.partial(serve_connect_stream, runtime)
    )
    await sessions.attach(session)
    try:
        await asyncio.to_thread(
            channel_state.note_client_scope,
            runtime,
            client.id,
            peer_host=session.address,
            reached_host=websocket.url.hostname or "",
            listener_port=listener_port(websocket),
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

    ``{module}`` names a module's package from the hub's cache, or a
    program the agent runs itself, such as cc-switch, and ``{module,
    component}`` one component of a module that unpacks several archives;
    ``{}`` is the agent's own package for its platform. The bytes go down
    under the agent's credit and the close carries their ``sha256`` and the
    file's own ``name``, the release's file name with no directory. A
    module's bytes are counted into its task as ``hub: sending <title>,
    <sent> / <total> MB to <device>`` lines while they go.

    Args:
        runtime: The shared runtime.
        session: The agent's session.
        stream: The stream, closed here.
    """
    module = str(stream.args.get("module", "") or "")
    component = str(stream.args.get("component", "") or "")
    platform = dict(runtime.device_platform.get(session.key, {}))
    if not platform:
        platform = await _platform_once_reported(runtime, session.key)
    is_module = bool(module) and module in load_module_manifests()
    on_progress = None
    if is_module:
        on_progress = functools.partial(
            _publish_module_line_from_thread,
            asyncio.get_running_loop(),
            runtime,
            module_task_label(session.key, module),
        )
    try:
        path, title = await asyncio.to_thread(
            _package_file, runtime, module, platform, on_progress, component
        )
    except AgentArtifactFetchError as error:
        if not module and not platform:
            session.is_reinstall_due = True
        if is_module:
            detail = " ".join(f"{k}={v}" for k, v in sorted(error.params.items()))
            publish_module_line(
                runtime,
                module_task_label(session.key, module),
                f"hub: the download failed: {error.code} {detail}".rstrip(),
            )
        LOGGER.warning(
            "package stream for %s refused: %s %s",
            module or "agent",
            error.code,
            error.params,
        )
        await stream.close(error.code, error.params)
        return
    progress = None
    size = 0
    if is_module:
        progress = AgentModuleFetchProgress(
            title=title,
            on_line=functools.partial(
                publish_module_line, runtime, module_task_label(session.key, module)
            ),
            verb=AGENT_MODULE_PROGRESS_VERB_SEND,
            recipient=session.name,
        )
        size = await asyncio.to_thread(_file_size, path)
    sent = 0
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = await asyncio.to_thread(handle.read, CHANNEL_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                await stream.send_bytes(chunk)
                sent += len(chunk)
                if progress is not None:
                    progress.note(sent, size)
    except OSError:
        await stream.close("module_artifact_missing", {})
        return
    if progress is not None:
        progress.note(sent, size, is_done=True)
    await stream.close("", {"sha256": digest.hexdigest(), "name": path.name})


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


def publish_module_line(runtime, label: str, line: str) -> None:
    """Add one ``hub:`` line to a module's running task, or log it.

    Args:
        runtime: The shared runtime.
        label: The task's label, from :func:`module_task_label`.
        line: The line, without its newline.
    """
    task = runtime.tasks.running(label)
    if task is None:
        LOGGER.info("%s", line)
        return
    task.publish(line + "\n")


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
    """Serve a ``service`` stream a client opened: the entry's material as the
    close, or a panel sign-in token for ``{is_panel: true}``.

    Args:
        runtime: The shared runtime.
        session: The client's session.
        stream: The stream, closed here.
    """
    if stream.args.get("is_panel") is True:
        code, params = await asyncio.to_thread(panel_material, runtime, session.key)
        await stream.close(code, params)
        return
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


def _publish_module_line_from_thread(loop, runtime, label: str, line: str) -> None:
    """Hand one task line from a worker thread to the event loop."""
    loop.call_soon_threadsafe(publish_module_line, runtime, label, line)


async def _serve_update_only_stream(
    runtime, session: ChannelSession, stream: ChannelStream
) -> None:
    """Serve a stream an agent of 0.5 opened: its own package, and nothing else.

    Args:
        runtime: The shared runtime.
        session: The agent's session; a refusal of its package marks it.
        stream: The stream, closed here.
    """
    if stream.kind == CHANNEL_STREAM_PACKAGE and not stream.args.get("module"):
        await serve_package_stream(runtime, session, stream)
        if (stream.close_info or {}).get("code"):
            session.is_package_refused = True
            runtime.events.publish(WEB_EVENT_DEVICES)
        return
    refusal = admit(CHANNEL_PROTOCOL_UPDATE_ONLY)
    await stream.close(refusal["code"], refusal["params"])


def _file_size(path) -> int:
    """A file's size in bytes, 0 when it cannot be read."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


async def _platform_once_reported(runtime, key: str) -> dict:
    """The device's platform once its first report of the connection lands.

    An agent asks for its own package right after the welcome, before its
    first report; the platform that report carries is what names the package.

    Args:
        runtime: The shared runtime.
        key: The device's id.

    Returns:
        The platform tuple, or an empty dict when none arrived in
        ``CHANNEL_PACKAGE_PLATFORM_WAIT_S``.
    """
    deadline = time.monotonic() + CHANNEL_PACKAGE_PLATFORM_WAIT_S
    while time.monotonic() < deadline:
        platform = dict(runtime.device_platform.get(key, {}))
        if platform:
            return platform
        await asyncio.sleep(CHANNEL_PACKAGE_PLATFORM_POLL_S)
    return {}


def _package_file(
    runtime, module: str, platform: dict, on_progress=None, component: str = ""
) -> tuple:
    """Where the package a ``package`` stream asks for is on this hub, and its title.

    Returns:
        ``(path, title)``, the title empty for the agent's own package.

    Raises:
        AgentArtifactFetchError: ``module_unknown`` for a name no manifest
            names, and the caches' own typed reasons.
    """
    if not module:
        path = runtime.agent_packages.package(
            family=platform_family(platform), architecture=str(platform.get("arch", ""))
        )
        return path, ""
    manifest = load_module_manifests().get(module) or load_tool_manifests().get(module)
    if manifest is None:
        raise AgentArtifactFetchError("module_unknown", name=module)
    artifact = runtime.agent_modules.artifact(
        name=module,
        manifest=manifest,
        platform=platform,
        component=component,
        on_progress=on_progress,
    )
    return artifact.path, artifact.title


async def _serve_frames(websocket: WebSocket, session: ChannelSession, frames) -> None:
    """Read frames until the socket ends.

    Reports are handled one after another on a task of their own, so a
    ``ping`` that arrives while a report is being recorded is answered at
    once and the round trip it measures is the wire's.

    Args:
        websocket: The peer's socket.
        session: The attached session.
        frames: The role's report handler, called with each decoded report.

    Raises:
        Exception: Whatever the report handler raised, once the socket ends.
    """
    reports: asyncio.Queue = asyncio.Queue()
    recorder = asyncio.create_task(_take_reports(reports, frames))
    try:
        while not recorder.done():
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
                reports.put_nowait(decoded)
            elif kind == CHANNEL_FRAME_OPEN:
                await session.accept_stream(decoded)
            elif kind == CHANNEL_FRAME_PING:
                await session.send_json(_pong(decoded))
            else:
                session.dispatch_text(decoded)
        recorder.result()
    finally:
        if not recorder.done():
            recorder.cancel()
            try:
                await recorder
            except asyncio.CancelledError:
                pass


async def _take_reports(reports: asyncio.Queue, frames) -> None:
    """Hand every queued report to the role's handler, in order."""
    while True:
        report = await reports.get()
        await frames.take_report(report)


def _pong(ping: dict) -> dict:
    """The answer to a ``ping``: its nonce as received, empty when absent."""
    nonce = ping.get("nonce")
    if not isinstance(nonce, str):
        nonce = ""
    return {"type": CHANNEL_FRAME_PONG, "nonce": nonce[:CHANNEL_PING_NONCE_CHARS_MAX]}


def _sessions_of(report: dict) -> list:
    """The shell sessions a report's ``machine`` section lists."""
    machine = report.get("machine") if isinstance(report, dict) else None
    sessions = machine.get("sessions") if isinstance(machine, dict) else None
    return sessions if isinstance(sessions, list) else []


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

    def __init__(self, runtime, session: ChannelSession, device, *, hub_version: str):
        self._runtime = runtime
        self._session = session
        self._device = device
        self._hub_version = hub_version

    async def take_report(self, report: dict) -> None:
        """Record one report, tell the panel, offer the state once, and send
        ``reinstall`` once to an older agent refused its package for want of
        the platform this report names, unless it is on the hub's machine."""
        runtime = self._runtime
        session = self._session
        key = self._device.id
        is_first = not session.report
        is_panel_change = _is_panel_change(session.report, report)
        is_module_change = session.report.get("modules") != report.get("modules")
        is_session_change = _sessions_of(session.report) != _sessions_of(report)
        session.record_report(report)
        await asyncio.to_thread(
            record_report,
            runtime,
            self._device,
            report,
            peer_host=session.address,
            is_first=is_first,
        )
        session.note_report_recorded()
        if is_module_change:
            runtime.published_services.schedule_refresh()
        if is_panel_change or is_session_change:
            runtime.events.publish(WEB_EVENT_DEVICE_REPORT, key)
        if is_session_change:
            await asyncio.to_thread(
                channel_state.push_states, runtime, CHANNEL_ROLE_CLIENT
            )
        runtime.events.publish(
            WEB_EVENT_METRICS, key, data=dict(runtime.device_metrics.get(key, {}))
        )
        if session.offered_hash is None:
            document = await asyncio.to_thread(channel_state.agent_state, runtime, key)
            if document["hash"] != session.state_hash:
                await session.push_state(document)
            session.offered_hash = document["hash"]
        elif await asyncio.to_thread(runtime.desired_states.is_ai_tools_enabled, key):
            # Whether the gateway serves moves with no write to announce it,
            # so a machine whose AI tools use it has its state read again.
            document = await asyncio.to_thread(channel_state.agent_state, runtime, key)
            if document["hash"] != session.offered_hash:
                await session.push_state(document)
                session.offered_hash = document["hash"]
        if session.is_reinstall_due and runtime.device_platform.get(key):
            session.is_reinstall_due = False
            if not _is_older_release(session.version, self._hub_version):
                return
            if await asyncio.to_thread(_is_hub_machine, self._device):
                LOGGER.info(
                    "agent %s on %s is on the hub's own machine; "
                    "the hub's update installs it",
                    session.name,
                    session.version,
                )
                return
            await _send_reinstall(session, self._hub_version)


class _UpdateOnlyAgentFrames:
    """What an agent of 0.5's reports do to the hub: they name its platform."""

    def __init__(self, runtime, session: ChannelSession, device):
        self._runtime = runtime
        self._session = session
        self._device = device

    async def take_report(self, report: dict) -> None:
        """Keep the report on the session and the platform it names, which
        names the package; tell the panel when its error moved."""
        previous = self._session.report
        self._session.record_report(report)
        machine = report.get("machine")
        platform = machine.get("platform") if isinstance(machine, dict) else None
        if isinstance(platform, dict) and platform:
            self._runtime.device_platform[self._device.id] = dict(platform)
        if not previous or previous.get("error") != report.get("error"):
            self._runtime.events.publish(WEB_EVENT_DEVICES)


def _is_hub_machine(device) -> bool:
    """Whether a device is the machine this hub runs on, by the id its join noted."""
    own_machine = machine_id()
    return bool(own_machine) and device.machine_id == own_machine


def _is_older_release(version: str, than: str) -> bool:
    """Whether one released version comes before another.

    Args:
        version: The version that may be the older.
        than: The version it is held against.

    Returns:
        True when ``version`` orders before ``than``; False when either does
        not parse or ends in ``CHANNEL_DEV_VERSION_SUFFIX``.
    """
    if version.endswith(CHANNEL_DEV_VERSION_SUFFIX) or than.endswith(
        CHANNEL_DEV_VERSION_SUFFIX
    ):
        return False
    older = parse_version(version)
    newer = parse_version(than)
    return older is not None and newer is not None and older < newer


async def _send_reinstall(session: ChannelSession, hub_version: str) -> None:
    """Open ``command {module: agent, verb: reinstall}`` on an agent's socket.

    The agent takes its package down a ``package`` stream and installs it,
    as the Devices page's Reinstall agent has it do; the command's close is
    logged when it comes.

    Args:
        session: The agent's session.
        hub_version: The version the hub runs.

    Raises:
        AgentOfflineError: If the socket is gone.
    """
    stream = await session.open_stream(
        CHANNEL_STREAM_COMMAND,
        {"module": CHANNEL_COMMAND_MODULE_AGENT, "verb": CHANNEL_VERB_REINSTALL},
    )
    LOGGER.info(
        "agent %s on %s asked for its package before the hub knew its platform; "
        "reinstall sent to reach %s",
        session.name,
        session.version,
        hub_version,
    )
    asyncio.create_task(_log_reinstall_close(session.name, stream))


async def _log_reinstall_close(name: str, stream: ChannelStream) -> None:
    """Read a ``reinstall`` command to its close and log the close.

    Args:
        name: The agent's name, for the line.
        stream: The command's stream.
    """
    try:
        while await stream.recv() is not None:
            pass
    except AgentOfflineError:
        pass
    info = stream.close_info or {"code": AgentOfflineError.code, "params": {}}
    params = {
        field: value
        for field, value in (info.get("params") or {}).items()
        if field != "output"
    }
    LOGGER.info(
        "reinstall of agent %s closed: %s %s", name, info.get("code") or "ok", params
    )


class _ClientFrames:
    """What a client's reports do to the hub."""

    def __init__(self, runtime, session: ChannelSession, client):
        self._runtime = runtime
        self._session = session
        self._client = client

    async def take_report(self, report: dict) -> None:
        """Record one report and hand the state down when the hashes differ,
        or whatever they are when the report says ``is_refresh``."""
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
            os_machine_id=str(machine.get("os_machine_id", "") or ""),
        )
        session.note_report_recorded()
        document = await asyncio.to_thread(
            channel_state.client_state, runtime, self._client.id
        )
        if report.get("is_refresh") is True or document["hash"] != session.state_hash:
            await session.push_state(document)
        session.offered_hash = document["hash"]
