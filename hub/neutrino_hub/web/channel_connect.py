"""A client's ``connect`` stream: one TCP connection the hub carries.

A client opens ``connect {id}`` for a published entry or ``connect
{is_panel: true}`` for the hub's own panel. The hub judges it with the
``service`` stream's checks, the stream limit among them, and connects its
far end: a managed machine's agent through ``connect {port}``, or a socket
the hub dials itself for a declared record, the gateway and the panel.
Bytes go both ways, each side under the other's credit. End of file on
either end closes the stream once what was read is sent, and the other end
is closed after it; there is no half-close.
"""

import asyncio
import contextlib
import errno

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CHUNK_BYTES,
    CHANNEL_CODE_CONNECT_FAILED,
    CHANNEL_CONNECT_DIAL_TIMEOUT_S,
    CHANNEL_CONNECT_REFUSED,
    CHANNEL_CONNECT_TIMEOUT,
    CHANNEL_CONNECT_UNREACHABLE,
    CHANNEL_STREAM_CONNECT,
)
from neutrino_hub.modules.channel.sessions import ChannelSession, ChannelStream
from neutrino_hub.modules.clients.services import connect_target
from neutrino_hub.web.constants import WEB_DEFAULT_LISTEN_PORT

# The errors a refused dial raises, beside ConnectionRefusedError.
REFUSED_ERRNOS = (errno.ECONNREFUSED, errno.ECONNRESET)


async def serve_connect_stream(
    runtime, session: ChannelSession, stream: ChannelStream
) -> None:
    """Serve a ``connect`` stream a client opened, to the end of its connection.

    Args:
        runtime: The shared runtime.
        session: The client's session; its ``connects`` holds the stream,
            with the kind and the machine it was judged by, while it is
            open.
        stream: The client's stream, closed here.
    """
    open_count = len(session.connects)
    session.connects[stream.id] = ("", "")
    try:
        code, params, target = await asyncio.to_thread(
            connect_target,
            runtime,
            session.key,
            stream.args,
            open_count=open_count,
            panel_port=_panel_port(runtime),
        )
        if code:
            await stream.close(code, params)
            return
        session.connects[stream.id] = (target.kind, target.provider)
        if target.device_id:
            await _relay_to_agent(runtime, stream, target)
            return
        await _relay_to_socket(stream, target)
    finally:
        session.connects.pop(stream.id, None)


async def _relay_to_agent(runtime, stream: ChannelStream, target) -> None:
    """Carry the client's stream to a machine's agent as ``connect {port}``."""
    try:
        far = await runtime.agent_sessions.open_stream(
            target.device_id, CHANNEL_STREAM_CONNECT, {"port": target.port}
        )
    except AgentOfflineError as offline:
        await stream.close(offline.code, {"device": target.device_id})
        return

    async def write(data: bytes) -> None:
        await far.send_bytes(data)

    async def read() -> "bytes | None":
        item = await far.recv()
        return None if item is None else item[1]

    async def close_far() -> None:
        with contextlib.suppress(AgentOfflineError):
            await far.close()

    def far_result() -> tuple:
        info = far.close_info or {}
        return str(info.get("code", "") or ""), dict(info.get("params") or {})

    await _relay(stream, read, write, close_far, far_result)


async def _relay_to_socket(stream: ChannelStream, target) -> None:
    """Carry the client's stream to a socket the hub dials itself."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(target.host, target.port),
            CHANNEL_CONNECT_DIAL_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        await stream.close(
            CHANNEL_CODE_CONNECT_FAILED, {"reason": CHANNEL_CONNECT_TIMEOUT}
        )
        return
    except OSError as error:
        await stream.close(CHANNEL_CODE_CONNECT_FAILED, {"reason": dial_reason(error)})
        return

    async def write(data: bytes) -> None:
        writer.write(data)
        await writer.drain()

    async def read() -> "bytes | None":
        try:
            data = await reader.read(CHANNEL_CHUNK_BYTES)
        except OSError:
            return None
        return data or None

    async def close_far() -> None:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()

    await _relay(stream, read, write, close_far, lambda: ("", {}))


def dial_reason(error: OSError) -> str:
    """The ``connect_failed`` reason one failed dial gives.

    Args:
        error: What the dial raised.

    Returns:
        ``refused`` when the far end turned the connection away, ``timeout``
        when it did not answer in time, ``unreachable`` for anything else.
    """
    if isinstance(error, ConnectionRefusedError) or error.errno in REFUSED_ERRNOS:
        return CHANNEL_CONNECT_REFUSED
    if isinstance(error, TimeoutError):
        return CHANNEL_CONNECT_TIMEOUT
    return CHANNEL_CONNECT_UNREACHABLE


async def _relay(stream: ChannelStream, read, write, close_far, far_result) -> None:
    """Move bytes both ways until either end ends.

    Args:
        stream: The client's stream.
        read: Awaited for the far end's next bytes; None at its end.
        write: Awaited with bytes for the far end; returns once it took them.
        close_far: Awaited to close the far end.
        far_result: Called once the far end ended, for ``(code, params)``,
            the close the client's stream gets.
    """
    upward = asyncio.ensure_future(_far_to_client(stream, read))
    downward = asyncio.ensure_future(_client_to_far(stream, write))
    try:
        await asyncio.wait({upward, downward}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (upward, downward):
            task.cancel()
        await asyncio.gather(upward, downward, return_exceptions=True)
    if not stream.is_closed:
        code, params = far_result()
        with contextlib.suppress(AgentOfflineError):
            await stream.close(code, params)
    await close_far()


async def _far_to_client(stream: ChannelStream, read) -> None:
    """Relay the far end's bytes to the client under the client's credit."""
    while True:
        data = await read()
        if data is None:
            return
        try:
            await stream.send_bytes(data)
        except AgentOfflineError:
            return


async def _client_to_far(stream: ChannelStream, write) -> None:
    """Relay the client's bytes to the far end until the client stops."""
    while True:
        item = await stream.recv()
        if item is None:
            return
        try:
            await write(item[1])
        except (AgentOfflineError, OSError):
            return


def _panel_port(runtime) -> int:
    """The port the panel answers plain HTTP on."""
    return int(runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT))
