"""A client's ``connect`` stream for a UDP ``port`` entry.

One stream carries every datagram of the entry. A frame is the source port
the datagram left from on the client's machine, two bytes big-endian, then
the datagram. Nothing waits: a frame for a side that has granted too little
credit is dropped, and the side it came from is granted its bytes back all
the same. The stream has no idle close.

Between a client and an agent the hub relays each frame unchanged. What
the client sends before the agent's stream has had its first credit is held,
at most ``CHANNEL_UDP_HELD_DATAGRAMS_MAX`` frames, and passed on in order
when the credit comes; more are dropped. For a
declared ``generic_udp`` record the hub is the far end: it keeps one UDP
socket connected to the record's host and port for each source, closes one
that carried nothing either way for ``CHANNEL_UDP_IDLE_TIMEOUT_S``, keeps at
most ``CHANNEL_UDP_SOURCES_MAX`` and gives the one idle the longest away for
a new source. An error on a source's socket loses that datagram alone.
"""

import asyncio
import contextlib
import socket
import time

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_CONNECT_FAILED,
    CHANNEL_UDP_HELD_DATAGRAMS_MAX,
    CHANNEL_UDP_IDLE_TIMEOUT_S,
    CHANNEL_UDP_SOURCE_BYTES,
    CHANNEL_UDP_SOURCES_MAX,
)
from neutrino_hub.modules.channel.sessions import ChannelStream

# How often the far end looks for sources that went idle.
UDP_SWEEP_INTERVAL_S = 5.0


class UdpSourceTable:
    """The far end's sockets of one UDP stream, one per source.

    Attributes:
        sockets: Source to its open endpoint.
    """

    def __init__(
        self,
        *,
        open_socket,
        idle_timeout_s: float = CHANNEL_UDP_IDLE_TIMEOUT_S,
        limit: int = CHANNEL_UDP_SOURCES_MAX,
    ):
        """
        Args:
            open_socket: Awaited with a source for a new endpoint, which has
                ``send(bytes)`` and ``close()``.
            idle_timeout_s: How long a source keeps its socket with no
                datagram either way.
            limit: How many sources the table keeps.
        """
        self._open_socket = open_socket
        self._idle_timeout_s = idle_timeout_s
        self._limit = limit
        self.sockets: dict = {}
        self._last_seen: dict = {}

    async def endpoint(self, source: int, now: float):
        """The source's socket, opened now when it has none.

        Args:
            source: The client-side port.
            now: The current time on a clock that never goes back.

        Returns:
            The endpoint.

        Raises:
            OSError: When a socket for the source cannot be opened.
        """
        held = self.sockets.get(source)
        if held is None:
            if len(self.sockets) >= self._limit:
                idlest = min(self._last_seen, key=self._last_seen.get)
                self.forget(idlest)
            held = await self._open_socket(source)
            self.sockets[source] = held
        self._last_seen[source] = now
        return held

    def touch(self, source: int, now: float) -> None:
        """Count a datagram either way for a source that has a socket."""
        if source in self.sockets:
            self._last_seen[source] = now

    def sweep(self, now: float) -> list:
        """Close every source idle for the idle time.

        Args:
            now: The current time.

        Returns:
            The sources forgotten.
        """
        idle = [
            source
            for source, seen in self._last_seen.items()
            if now - seen >= self._idle_timeout_s
        ]
        for source in idle:
            self.forget(source)
        return idle

    def forget(self, source: int) -> None:
        """Close one source's socket and forget it."""
        held = self.sockets.pop(source, None)
        self._last_seen.pop(source, None)
        if held is not None:
            held.close()

    def close(self) -> None:
        """Close every socket."""
        for source in list(self.sockets):
            self.forget(source)


def split_frame(data: bytes) -> "tuple | None":
    """A UDP frame's source and datagram, None for a frame too short.

    Args:
        data: The frame's bytes after the stream id.

    Returns:
        ``(source, datagram)``.
    """
    if len(data) < CHANNEL_UDP_SOURCE_BYTES:
        return None
    return int.from_bytes(data[:CHANNEL_UDP_SOURCE_BYTES], "big"), bytes(
        data[CHANNEL_UDP_SOURCE_BYTES:]
    )


def frame_of(source: int, datagram: bytes) -> bytes:
    """One UDP frame's bytes after the stream id."""
    return source.to_bytes(CHANNEL_UDP_SOURCE_BYTES, "big") + datagram


async def relay_to_agent(stream: ChannelStream, far: ChannelStream) -> None:
    """Relay every frame unchanged between a client's stream and an agent's.

    The stream that ends first decides the client's close: the agent's own
    close, or nothing to send when the client closed. The client's frames
    wait for the agent's first credit as :func:`_pass_held_frames` holds
    them; the agent's go to the client as they come.

    Args:
        stream: The client's stream.
        far: The agent's ``connect {port, protocol: udp}`` stream.
    """
    upward = asyncio.ensure_future(_pass_frames(far, stream))
    downward = asyncio.ensure_future(_pass_held_frames(stream, far))
    try:
        await asyncio.wait({upward, downward}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (upward, downward):
            task.cancel()
        await asyncio.gather(upward, downward, return_exceptions=True)
    if not stream.is_closed:
        info = far.close_info or {}
        with contextlib.suppress(AgentOfflineError):
            await stream.close(
                str(info.get("code", "") or ""), dict(info.get("params") or {})
            )
    with contextlib.suppress(AgentOfflineError):
        await far.close()


async def relay_to_socket(
    stream: ChannelStream, host: str, port: int, *, reason_of
) -> None:
    """Be the far end of a UDP stream for a declared record.

    A socket the hub cannot open towards the record at all closes the stream
    ``connect_failed {reason}``.

    Args:
        stream: The client's stream.
        host: The record's host.
        port: The record's port.
        reason_of: Called with the ``OSError`` of a failed open for the
            ``connect_failed`` reason, the TCP path's.
    """
    loop = asyncio.get_running_loop()
    try:
        address = await _resolve(loop, host, port)
        _check_route(address)
    except OSError as error:
        await stream.close(CHANNEL_CODE_CONNECT_FAILED, {"reason": reason_of(error)})
        return

    async def open_socket(source: int):
        return _Endpoint(loop, address, stream, table, source)

    table = UdpSourceTable(open_socket=open_socket)
    sweeper = asyncio.ensure_future(_sweep(table))
    try:
        while True:
            item = await stream.recv()
            if item is None:
                return
            split = split_frame(item[1])
            if split is None:
                continue
            source, datagram = split
            try:
                endpoint = await table.endpoint(source, time.monotonic())
            except OSError:
                continue
            endpoint.send(datagram)
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        table.close()


async def _pass_frames(source: ChannelStream, target: ChannelStream) -> None:
    """Hand every frame from one stream to the other, dropping what lacks credit."""
    while True:
        item = await source.recv()
        if item is None:
            return
        try:
            await target.send_datagram(item[1])
        except AgentOfflineError:
            return


async def _pass_held_frames(
    source: ChannelStream,
    target: ChannelStream,
    *,
    held_max: int = CHANNEL_UDP_HELD_DATAGRAMS_MAX,
) -> None:
    """Hand frames on as :func:`_pass_frames` does, holding the first ones.

    Until the target's first credit, at most ``held_max`` frames are held
    and the rest dropped; the held ones go on in order once it comes. A
    target that closes first takes nothing, and what was held is dropped.

    Args:
        source: The stream the frames come from.
        target: The stream they go to.
        held_max: How many frames wait for the target's first credit.
    """
    held: list = []
    credit = (
        None
        if target.has_credit_arrived
        else asyncio.ensure_future(target.wait_first_credit())
    )
    receiving = None
    try:
        while True:
            if receiving is None:
                receiving = asyncio.ensure_future(source.recv())
            waiting = {receiving} if credit is None else {receiving, credit}
            await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
            if credit is not None and credit.done():
                credit = None
                for frame in held:
                    await target.send_datagram(frame)
                held = []
            if not receiving.done():
                continue
            item = receiving.result()
            receiving = None
            if item is None:
                return
            if credit is not None:
                if len(held) < held_max:
                    held.append(item[1])
                continue
            await target.send_datagram(item[1])
    except AgentOfflineError:
        return
    finally:
        for task in (receiving, credit):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


async def _sweep(table: UdpSourceTable) -> None:
    while True:
        await asyncio.sleep(UDP_SWEEP_INTERVAL_S)
        table.sweep(time.monotonic())


async def _resolve(loop, host: str, port: int) -> tuple:
    """The first address the record's host and port resolve to, for UDP.

    Raises:
        OSError: When the name does not resolve.
    """
    found = await loop.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    if not found:
        raise OSError(f"{host} resolves to nothing")
    return found[0]


def _check_route(address: tuple) -> None:
    """Connect one UDP socket to the address and close it, sending nothing.

    Raises:
        OSError: When the system has no route to it.
    """
    family, kind, proto, _, sockaddr = address
    with socket.socket(family, kind, proto) as probe:
        probe.connect(sockaddr)


class _Endpoint:
    """One source's socket, connected to the record, read as replies arrive."""

    def __init__(self, loop, address: tuple, stream, table, source: int):
        """
        Args:
            loop: The loop the stream lives on.
            address: The record's address, as ``getaddrinfo`` gives it.
            stream: The client's stream the replies go into.
            table: The table that counts the source's datagrams.
            source: The client-side port this socket is for.

        Raises:
            OSError: When the socket cannot be opened or connected.
        """
        family, kind, proto, _, sockaddr = address
        self._socket = socket.socket(family, kind, proto)
        try:
            self._socket.setblocking(False)
            self._socket.connect(sockaddr)
        except OSError:
            self._socket.close()
            raise
        self._loop = loop
        self._stream = stream
        self._table = table
        self._source = source
        self._sending: set = set()
        loop.add_reader(self._socket.fileno(), self._read)

    def send(self, datagram: bytes) -> None:
        """Send one datagram; an error loses it alone."""
        with contextlib.suppress(OSError):
            self._socket.send(datagram)

    def close(self) -> None:
        self._loop.remove_reader(self._socket.fileno())
        self._socket.close()

    def _read(self) -> None:
        """Hand every waiting reply into the stream; an error loses one."""
        while True:
            try:
                data = self._socket.recv(65535)
            except OSError:
                return
            self._table.touch(self._source, time.monotonic())
            task = asyncio.ensure_future(self._send(frame_of(self._source, data)))
            self._sending.add(task)
            task.add_done_callback(self._sending.discard)

    async def _send(self, frame: bytes) -> None:
        with contextlib.suppress(AgentOfflineError):
            await self._stream.send_datagram(frame)
