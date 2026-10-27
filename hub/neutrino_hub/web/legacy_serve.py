"""Serving an agent of 0.5 on the legacy listener, for its own update alone.

Its socket carries its reports up, read for the platform that names its
package, and ``package {}`` down; ``protocol_too_old`` closes every other
stream it opens, and the hub pushes it no state. Its session is in
``agent_update_sessions``, never in ``agent_sessions``, and stays there
after its socket ends until the updated agent knocks on the transport
(transport.md, "An agent of 0.5").
"""

import asyncio
import functools
import json

from fastapi import WebSocket, WebSocketDisconnect

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.admission import admit
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CLOSE_REPLACED,
    CHANNEL_CODE_REPLACED,
    CHANNEL_FRAME_OPEN,
    CHANNEL_FRAME_PING,
    CHANNEL_FRAME_PONG,
    CHANNEL_FRAME_REPORT,
    CHANNEL_PING_NONCE_CHARS_MAX,
    CHANNEL_PROTOCOL_UPDATE_ONLY,
    CHANNEL_STREAM_KINDS,
    CHANNEL_STREAM_PACKAGE,
)
from neutrino_hub.modules.channel.legacy_sessions import (
    LegacyChannelSession,
    LegacyChannelStream,
)
from neutrino_hub.web.channel_serve import serve_package_stream
from neutrino_hub.web.constants import WEB_EVENT_DEVICES


async def serve_update_only_agent(
    websocket: WebSocket, runtime, session: LegacyChannelSession, device, welcome
) -> None:
    """Serve an agent of 0.5 for its own update alone, to its last frame.

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


def decode_frame(text: "str | None") -> "dict | None":
    """One text frame as the object it carries, or None."""
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


async def _serve_update_only_stream(
    runtime, session: LegacyChannelSession, stream: LegacyChannelStream
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


async def _serve_frames(websocket: WebSocket, session: LegacyChannelSession, frames):
    """Read frames until the socket ends.

    Reports are handled one after another on a task of their own, so a
    ``ping`` that arrives while a report is being recorded is answered at
    once.

    Args:
        websocket: The peer's socket.
        session: The attached session.
        frames: The report handler, called with each decoded report.

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
    """Hand every queued report to the handler, in order."""
    while True:
        report = await reports.get()
        await frames.take_report(report)


def _pong(ping: dict) -> dict:
    """The answer to a ``ping``: its nonce as received, empty when absent."""
    nonce = ping.get("nonce")
    if not isinstance(nonce, str):
        nonce = ""
    return {"type": CHANNEL_FRAME_PONG, "nonce": nonce[:CHANNEL_PING_NONCE_CHARS_MAX]}


class _UpdateOnlyAgentFrames:
    """What an agent of 0.5's reports do to the hub: they name its platform."""

    def __init__(self, runtime, session: LegacyChannelSession, device):
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
