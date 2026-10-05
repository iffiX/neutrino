"""Every datagram of one UDP entry to a port on this machine, over one stream.

The hub opens ``connect {port, protocol: udp}`` for a client that forwards a
UDP port this machine publishes. Each binary frame is one datagram,
``<u16 source, big-endian><datagram>`` after the stream id, ``source`` being
the port it left from on the client's machine. The stream keeps, per
source, one UDP socket connected to the port, so each socket reads only the
port's replies, and a reply goes up with its socket's source. A source idle
both ways for ``AGENT_UDP_IDLE_TIMEOUT_S`` is forgotten, and one more than
``AGENT_UDP_SOURCES_MAX`` replaces the one idle the longest. A datagram the
hub's credit does not cover is dropped, never queued, and credit is granted
back for each datagram once it is passed on or dropped. The stream has no
idle close; it ends with the hub's close, or ``port_not_published {port}``
once the machine stops publishing the port on UDP.

One thread moves the hub's frames to a queue; one loop over the stream's
sockets does the rest, whatever the number of sources.

Not pure: opens sockets.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import queue
import selectors
import socket
import struct
import threading
import time

from neutrino_agent.constants import (
    AGENT_CODE_CONNECT_FAILED,
    AGENT_CODE_PORT_NOT_PUBLISHED,
    AGENT_CONNECT_TCP,
    AGENT_CONNECT_UDP,
    AGENT_UDP_IDLE_TIMEOUT_S,
    AGENT_UDP_SOURCES_MAX,
    AGENT_WS_STREAM_CREDIT_BYTES,
)
from neutrino_agent.exceptions import StreamClosed, StreamRefused
from neutrino_agent.streams.connect import ConnectStream, dial_reason

# The source port in front of every datagram.
SOURCE = struct.Struct(">H")
# The largest datagram a socket reads at once.
DATAGRAM_BYTES_MAX = 65535
# How long one turn of the loop waits, and how often the stream asks
# whether the port is still published.
TURN_S = 0.25
PUBLISHED_CHECK_S = 1.0


def open_connect_stream(channel, args: dict, *, published):
    """The handler of one ``connect`` stream, by its protocol.

    Args:
        channel: The stream's :class:`StreamChannel`.
        args: The open's arguments, ``{port, protocol}``.
        published: Called with nothing, or with a protocol, for the ports
            the machine publishes on it now.

    Returns:
        A :class:`UdpConnectStream` for ``udp``, else a
        :class:`ConnectStream`, which refuses any protocol but ``tcp``.
    """
    if args.get("protocol", AGENT_CONNECT_TCP) == AGENT_CONNECT_UDP:
        return UdpConnectStream(channel, args, published=published)
    return ConnectStream(channel, args, published=published)


class UdpConnectStream:
    """Serves one UDP ``connect`` stream: a socket per source, one loop."""

    def __init__(self, channel, args: dict, *, published, clock=time.monotonic):
        """
        Args:
            channel: The stream's :class:`StreamChannel`.
            args: The open's arguments, ``{port, protocol}``.
            published: Called with ``udp`` for the ports the machine
                publishes on UDP now, each to its address.
            clock: Seconds that only go forward.
        """
        self._channel = channel
        self._port = args.get("port")
        self._published = published
        self._clock = clock
        self._address = ""
        # source -> [socket, last datagram either way]
        self._sources: dict = {}
        self._spare: "socket.socket | None" = None
        self._frames: queue.Queue = queue.Queue()
        self._selector = selectors.DefaultSelector()
        self._wake_read, self._wake_write = socket.socketpair()
        self._is_done = threading.Event()

    def open(self) -> None:
        """Take the port when the machine publishes it on UDP, and open the
        first socket to it.

        Raises:
            StreamRefused: ``port_not_published {port}`` for a port the
                machine does not publish on UDP now; ``connect_failed
                {reason}`` when no socket to it can be opened.
        """
        port = self._port
        ports = self._published(AGENT_CONNECT_UDP)
        if isinstance(port, bool) or not isinstance(port, int) or port not in ports:
            self._close_wake()
            raise StreamRefused(AGENT_CODE_PORT_NOT_PUBLISHED, {"port": port})
        self._address = ports[port]
        try:
            self._spare = self._new_socket()
        except OSError as error:
            self._close_wake()
            raise StreamRefused(
                AGENT_CODE_CONNECT_FAILED, {"reason": dial_reason(error)}
            )

    def run(self) -> dict:
        """Carry datagrams both ways until the hub closes the stream or the
        port is no longer published.

        Returns:
            ``{"code": "", "params": {}}`` for the hub's close, or
            ``port_not_published {port}``.
        """
        self._selector.register(self._wake_read, selectors.EVENT_READ, None)
        feeder = threading.Thread(
            target=self._feed,
            name=f"agent_connect_udp_input_{self._channel.id}",
            daemon=True,
        )
        try:
            self._channel.offer_credit(AGENT_WS_STREAM_CREDIT_BYTES)
            feeder.start()
            return self._loop()
        finally:
            self._is_done.set()
            for held, _last in list(self._sources.values()):
                with contextlib.suppress(OSError):
                    held.close()
            self._sources.clear()
            if self._spare is not None:
                with contextlib.suppress(OSError):
                    self._spare.close()
            with contextlib.suppress(OSError):
                self._selector.close()
            self._close_wake()
            if feeder.is_alive():
                feeder.join(timeout=TURN_S * 4)

    def sources(self) -> list:
        """The sources holding a socket now, the idlest first."""
        return sorted(self._sources, key=lambda source: self._sources[source][1])

    def _loop(self) -> dict:
        """The one loop: the hub's frames, the sockets' replies, the idle
        sources and the published check, until the stream ends."""
        checked_at = self._clock()
        while True:
            for key, _events in self._selector.select(timeout=TURN_S):
                if key.data is None:
                    with contextlib.suppress(OSError):
                        self._wake_read.recv(4096)
                else:
                    self._reply(key.data)
            while True:
                try:
                    item = self._frames.get_nowait()
                except queue.Empty:
                    break
                if item[0] == "close":
                    return {"code": "", "params": {}}
                self._forward(item[1])
            now = self._clock()
            self._forget_idle(now)
            if now - checked_at >= PUBLISHED_CHECK_S:
                checked_at = now
                if self._port not in self._published(AGENT_CONNECT_UDP):
                    return {
                        "code": AGENT_CODE_PORT_NOT_PUBLISHED,
                        "params": {"port": self._port},
                    }

    def _feed(self) -> None:
        """Move the hub's items to the loop, waking it for each."""
        while not self._is_done.is_set():
            item = self._channel.recv(timeout=TURN_S)
            if item is None:
                continue
            if item[0] not in ("data", "close"):
                continue
            self._frames.put(item)
            with contextlib.suppress(OSError):
                self._wake_write.send(b"\0")
            if item[0] == "close":
                return

    def _forward(self, frame: bytes) -> None:
        """Send one datagram from the hub out of its source's socket, then
        grant its bytes back."""
        try:
            if len(frame) < SOURCE.size:
                return
            (source,) = SOURCE.unpack_from(frame)
            held = self._socket_for(source)
            if held is None:
                return
            with contextlib.suppress(OSError):
                held.send(frame[SOURCE.size :])
        finally:
            with contextlib.suppress(StreamClosed):
                self._channel.offer_credit(len(frame))

    def _reply(self, source: int) -> None:
        """Send one reply a source's socket read up the stream, or drop it."""
        entry = self._sources.get(source)
        if entry is None:
            return
        try:
            datagram = entry[0].recv(DATAGRAM_BYTES_MAX)
        except OSError:
            return
        entry[1] = self._clock()
        with contextlib.suppress(StreamClosed):
            self._channel.try_send_frame(SOURCE.pack(source) + datagram)

    def _socket_for(self, source: int) -> "socket.socket | None":
        """The socket of a source, opened when it has none; the idlest
        source gives way when the table is full."""
        now = self._clock()
        entry = self._sources.get(source)
        if entry is not None:
            entry[1] = now
            return entry[0]
        if len(self._sources) >= AGENT_UDP_SOURCES_MAX:
            self._forget(self.sources()[0])
        if self._spare is not None:
            held, self._spare = self._spare, None
        else:
            try:
                held = self._new_socket()
            except OSError:
                return None
        self._selector.register(held, selectors.EVENT_READ, source)
        self._sources[source] = [held, now]
        return held

    def _forget_idle(self, now: float) -> None:
        for source in list(self._sources):
            if now - self._sources[source][1] >= AGENT_UDP_IDLE_TIMEOUT_S:
                self._forget(source)

    def _forget(self, source: int) -> None:
        held, _last = self._sources.pop(source)
        with contextlib.suppress(KeyError, ValueError, OSError):
            self._selector.unregister(held)
        with contextlib.suppress(OSError):
            held.close()

    def _new_socket(self) -> socket.socket:
        """One UDP socket connected to the port, so it reads only its replies.

        Raises:
            OSError: When it cannot be opened or connected.
        """
        family = socket.AF_INET6 if ":" in self._address else socket.AF_INET
        held = socket.socket(family, socket.SOCK_DGRAM)
        try:
            held.setblocking(False)
            held.connect((self._address, self._port))
        except OSError:
            held.close()
            raise
        return held

    def _close_wake(self) -> None:
        for end in (self._wake_read, self._wake_write):
            with contextlib.suppress(OSError):
                end.close()
