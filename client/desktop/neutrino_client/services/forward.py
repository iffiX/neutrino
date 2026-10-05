"""The local forwards: a loopback listener per forwarded entry, a ``connect``
stream per connection it accepts.

Every entry the client forwards, and the hub's own panel, listens on
``127.0.0.1`` at the port the one local port table gives it, and every
connection the listener accepts is carried to the hub as one ``connect``
stream: the hub alone dials the service. No forward dials a device address.

The table is the client's to manage: an entry is ``auto`` or a fixed number,
auto takes the entry's own port when no other entry holds it and nothing
listens on it on any address of the machine, else the first free port from
``FORWARD_AUTO_FIRST_PORT`` up, and the pick is kept for every later forward.
No number is held by two entries. The listeners are runtime state and end
with the resident; they are held by service key, so two hubs publishing the
same entry id never collide.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import collections
import errno
import os
import socket
import threading
import time

from neutrino_client.constants import (
    CLIENT_STREAM_TIMEOUT_S,
    CLIENT_UDP_HELD_DATAGRAMS_MAX,
    CLIENT_UDP_REOPEN_INTERVAL_S,
    CLIENT_UDP_SOURCES_MAX,
    CLIENT_WS_CHUNK_BYTES,
)
from neutrino_client.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    LocalPortTakenError,
)
from neutrino_client.platforms import win32
from neutrino_client.services.base import hub_of_key, service_key
from neutrino_client.services.store import STORE_LOCAL_PORT_AUTO

FORWARD_BIND_HOST = "127.0.0.1"
# A local port's setting when the client picks the number.
FORWARD_PORT_AUTO = STORE_LOCAL_PORT_AUTO
# The protocols a port entry is forwarded on; an entry that names none is TCP.
FORWARD_PROTOCOL_TCP = "tcp"
FORWARD_PROTOCOL_UDP = "udp"
# Where an auto pick looks when the entry's own number is not to be had.
FORWARD_AUTO_FIRST_PORT = 20000
FORWARD_PORT_MAX = 65535
# The numbers a fixed setting may name.
FORWARD_FIXED_PORT_MIN = 1024
# The entry id the hub's panel is forwarded under; no published entry has it.
FORWARD_PANEL_ID = ":panel"
# The kinds of forward that end when their entry leaves the hub's list; the
# others end with the job that made them.
FORWARD_LISTED_KINDS = ("port", "web")
# How long one wait for the hub's bytes lasts before the stream is looked at
# again.
FORWARD_STREAM_WAIT_S = 0.5
# The wildcard addresses a free port is probed on.
FORWARD_PROBE_ADDRESSES = (
    (socket.AF_INET, "0.0.0.0"),  # scan: allow
    (socket.AF_INET6, "::"),
)
# What binding the IPv6 wildcard answers on a machine that has no IPv6.
FORWARD_NO_IPV6_ERRNOS = (errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT)
# Where a UDP port is looked up in the system's table instead of bound: a
# UDP socket on a wildcard address makes the Windows firewall ask.
FORWARD_IS_UDP_TABLE = os.name == "nt"
FORWARD_UDP_TABLE_FAMILIES = (win32.WIN_AF_INET, win32.WIN_AF_INET6)


def is_port_free(
    port: int, is_kept: bool = False, protocol: str = FORWARD_PROTOCOL_TCP
) -> bool:
    """Whether nothing listens on a port on any address of the machine.

    The port is bound on the IPv4 wildcard address, and on the IPv6 one
    where the machine has IPv6, with no address-reuse option, then let go:
    with TCP sockets for a TCP entry, UDP sockets for a UDP one. A TCP port
    the table already keeps for an entry is bound with the reuse option off
    Windows, so the client's own closed connections still lingering on it
    do not count while another program's listener does. On Windows a UDP
    port is not bound: the system's table of UDP endpoints is read instead.

    Args:
        port: The port number.
        is_kept: Whether the table keeps the port for an entry already.
        protocol: ``tcp`` or ``udp``.

    Returns:
        True when every probe binds it.
    """
    if protocol == FORWARD_PROTOCOL_UDP and FORWARD_IS_UDP_TABLE:
        return not is_udp_port_held(port)
    kind = socket.SOCK_DGRAM if protocol == FORWARD_PROTOCOL_UDP else socket.SOCK_STREAM
    is_reused = is_kept and protocol == FORWARD_PROTOCOL_TCP
    for family, address in FORWARD_PROBE_ADDRESSES:
        try:
            probe = socket.socket(family, kind)
        except OSError:
            if family == socket.AF_INET6:
                continue
            return False
        try:
            if family == socket.AF_INET6:
                probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            elif is_reused:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((address, port))
        except OverflowError:
            return False
        except OSError as error:
            if family == socket.AF_INET6 and error.errno in FORWARD_NO_IPV6_ERRNOS:
                continue
            return False
        finally:
            probe.close()
    return True


def is_udp_port_held(port: int) -> bool:
    """Whether the system's table lists a UDP endpoint on a port, any address.

    Both families are read; a table that cannot be read counts as held,
    so no number is taken on a guess.

    Args:
        port: The port number.

    Returns:
        True when some endpoint holds it, or the port is no port number.
    """
    if not 0 < port <= FORWARD_PORT_MAX:
        return True
    for family in FORWARD_UDP_TABLE_FAMILIES:
        try:
            endpoints = win32.udp_table_endpoints(win32.udp_table(family), family)
        except (OSError, ValueError):
            return True
        if any(held == port for _address, held in endpoints):
            return True
    return False


def is_udp_port_free(port: int) -> bool:
    """Whether nothing is bound to a UDP port on any address of the machine.

    Args:
        port: The port number.

    Returns:
        True when every probe binds it.
    """
    return is_port_free(port, protocol=FORWARD_PROTOCOL_UDP)


def is_kept_port_free(port: int) -> bool:
    """Whether a port the table keeps is still free on every address.

    Args:
        port: The port number.

    Returns:
        True when no other program listens on it.
    """
    return is_port_free(port, is_kept=True)


def forward_refusal(error: OSError) -> dict:
    """The typed refusal a forward that cannot listen answers with.

    Args:
        error: What making the forward raised.

    Returns:
        ``port_taken`` with the port for a fixed port another program
        listens on, ``forward_failed`` with the detail otherwise.
    """
    if isinstance(error, LocalPortTakenError):
        return {"code": "port_taken", "params": {"port": error.port}}
    return {"code": "forward_failed", "params": {"detail": str(error)[:200]}}


def relay_socket(connection, stream, log=print) -> None:
    """Carry one TCP connection over one open ``connect`` stream until either ends.

    End of file on the connection closes the stream once everything read
    from it is sent; the hub closing the stream writes what it sent and
    closes the connection. There is no half-close. Blocks until both
    directions are done; any thread may call it.

    Args:
        connection: The connected socket.
        stream: The open ``connect`` stream, credit granted.
        log: Callable used for progress messages.
    """
    upward = threading.Thread(
        target=_socket_to_stream,
        args=(connection, stream),
        name="client_forward_up",
        daemon=True,
    )
    upward.start()
    _stream_to_socket(stream, connection)
    stream.close()
    _close_socket(connection)
    upward.join()
    try:
        stream.wait_close(0)
    except GatewayRefusedDetail as refused:
        log(f"the hub refused a connect stream: {refused.code} {refused.params}")
    except GatewayUnreachable:
        pass


class ConnectStreamSocket:
    """An open ``connect`` stream with a socket's ``recv``, ``sendall`` and ``close``.

    A ``close`` from another thread ends a ``recv`` that waits.
    """

    def __init__(self, stream):
        """
        Args:
            stream: The open ``connect`` stream, credit granted.
        """
        self._stream = stream
        self._held = b""

    def recv(self, size: int) -> bytes:
        """Up to ``size`` bytes the far end sent.

        Args:
            size: The most to return.

        Returns:
            The bytes; empty once the stream is over.
        """
        while not self._held:
            data = self._stream.read(FORWARD_STREAM_WAIT_S)
            if data is None:
                continue
            if not data:
                return b""
            self._held = data
        data, self._held = self._held[:size], self._held[size:]
        return data

    def sendall(self, data: bytes) -> None:
        """Send every byte, under the hub's credit.

        Raises:
            GatewayUnreachable: When the stream or the socket has ended.
            TimeoutError: When the hub grants no credit in time.
        """
        self._stream.send(data)

    def close(self) -> None:
        """End the stream from this side. Idempotent."""
        self._stream.close()


def _socket_to_stream(connection, stream) -> None:
    """Send what the connection reads until its end, then close the stream."""
    while True:
        try:
            data = connection.recv(CLIENT_WS_CHUNK_BYTES)
        except OSError:
            break
        if not data:
            break
        try:
            stream.send(data)
        except (GatewayUnreachable, TimeoutError):
            break
    stream.close()


def _stream_to_socket(stream, connection) -> None:
    """Write what the hub sends until the stream ends or the connection fails."""
    while True:
        data = stream.read(FORWARD_STREAM_WAIT_S)
        if data is None:
            continue
        if not data:
            return
        try:
            connection.sendall(data)
        except OSError:
            return


def _close_socket(connection) -> None:
    """Close a socket at once, waking any thread blocked on it."""
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass


def _nobody() -> None:
    """Nobody listening for changes."""


class PortLocalTable:
    """The one table of the loopback ports this client's forwards take.

    Every forwarded entry is ``auto`` or a fixed number. Auto takes the
    entry's own port when no other entry holds it and it is free on every
    address, else the first free one from ``FORWARD_AUTO_FIRST_PORT`` up,
    and the pick is kept for every later forward. A number is held per
    protocol: no two entries of one protocol hold one number, and a TCP
    entry and a UDP entry may hold the same one. A kept or fixed port is
    looked at again each time its forward is about to listen: an auto pick
    another program now listens on is picked again and kept, and a fixed
    one is refused.
    """

    def __init__(
        self, *, store=None, is_free=None, is_kept_free=None, is_udp_free=None
    ):
        """
        Args:
            store: The :class:`~neutrino_client.services.store.ClientServiceStore`
                the table is kept in; None keeps it in memory.
            is_free: ``is_free(port)`` says whether nothing listens on the
                TCP port on any address; None asks the system.
            is_kept_free: The same for a TCP port the table keeps already;
                None is ``is_free`` when that is given, else asks the system.
            is_udp_free: The same for a UDP port, kept or not; None is
                ``is_free`` when that is given, else asks the system.
        """
        self._store = store
        self._is_free = is_free if is_free is not None else is_port_free
        if is_kept_free is None:
            is_kept_free = is_free if is_free is not None else is_kept_port_free
        self._is_kept_free = is_kept_free
        if is_udp_free is None:
            is_udp_free = is_free if is_free is not None else is_udp_port_free
        self._is_udp_free = is_udp_free
        self._lock = threading.Lock()
        self._memory: dict = {}

    def setting(self, key: str):
        """One entry's setting.

        Args:
            key: The entry's service key.

        Returns:
            ``"auto"`` or the fixed number.
        """
        with self._lock:
            record = self._records().get(key)
        return record["setting"] if record else FORWARD_PORT_AUTO

    def configure(
        self, key: str, setting, protocol: str = FORWARD_PROTOCOL_TCP
    ) -> dict:
        """Set one entry's local port.

        Args:
            key: The entry's service key.
            setting: ``"auto"``, or a fixed number from
                ``FORWARD_FIXED_PORT_MIN`` to ``FORWARD_PORT_MAX``.
            protocol: The entry's protocol, ``tcp`` or ``udp``.

        Returns:
            Empty when kept; ``unknown_request`` for a setting of another
            shape, ``port_taken`` with the port for a number another entry
            of the same protocol holds.
        """
        if setting != FORWARD_PORT_AUTO:
            if isinstance(setting, bool) or not isinstance(setting, int):
                return {"code": "unknown_request", "params": {}}
            if not FORWARD_FIXED_PORT_MIN <= setting <= FORWARD_PORT_MAX:
                return {"code": "unknown_request", "params": {}}
        with self._lock:
            records = self._records()
            record = records.get(key) or {"setting": FORWARD_PORT_AUTO, "port": 0}
            if record["setting"] == setting:
                return {}
            if setting == FORWARD_PORT_AUTO:
                self._keep(key, FORWARD_PORT_AUTO, 0, protocol)
                return {}
            if setting in self._held(records, key, protocol):
                return {"code": "port_taken", "params": {"port": setting}}
            self._keep(key, setting, setting, protocol)
        return {}

    def take(
        self, key: str, own_port: int, protocol: str = FORWARD_PROTOCOL_TCP
    ) -> int:
        """The port one entry's forward listens on, an auto pick kept.

        Args:
            key: The entry's service key.
            own_port: The entry's published port, which auto takes first;
                0 for an entry with none.
            protocol: The entry's protocol, ``tcp`` or ``udp``.

        Returns:
            The port number.

        Raises:
            LocalPortTakenError: When a fixed port is listened on by
                another program.
            OSError: When auto finds no free port.
        """
        with self._lock:
            records = self._records()
            record = records.get(key)
            is_kept_free = (
                self._is_udp_free
                if protocol == FORWARD_PROTOCOL_UDP
                else self._is_kept_free
            )
            if record and record["port"]:
                if is_kept_free(record["port"]):
                    if record.get("protocol", FORWARD_PROTOCOL_TCP) != protocol:
                        self._keep(key, record["setting"], record["port"], protocol)
                    return record["port"]
                if record["setting"] != FORWARD_PORT_AUTO:
                    raise LocalPortTakenError(record["port"])
            held = self._held(records, key, protocol)
            port = self._pick(own_port, held, protocol)
            self._keep(key, FORWARD_PORT_AUTO, port, protocol)
            return port

    def _pick(self, own_port: int, held: set, protocol: str) -> int:
        """The entry's own port, else the first free one from the floor up."""
        is_free = (
            self._is_udp_free if protocol == FORWARD_PROTOCOL_UDP else self._is_free
        )
        if 0 < own_port <= FORWARD_PORT_MAX and own_port not in held:
            if is_free(own_port):
                return own_port
        for port in range(FORWARD_AUTO_FIRST_PORT, FORWARD_PORT_MAX + 1):
            if port not in held and is_free(port):
                return port
        raise OSError("no free loopback port")

    def _records(self) -> dict:
        """Every entry's record; the lock is held."""
        if self._store is None:
            return dict(self._memory)
        return self._store.local_ports()

    def _keep(self, key: str, setting, port: int, protocol: str) -> None:
        """Write one entry's record; the lock is held."""
        if self._store is None:
            self._memory[key] = {"setting": setting, "port": port, "protocol": protocol}
        else:
            self._store.set_local_port(key, setting, port, protocol)

    @staticmethod
    def _held(records: dict, key: str, protocol: str) -> set:
        """The ports every other entry of one protocol holds."""
        return {
            record["port"]
            for other, record in records.items()
            if other != key
            and record["port"]
            and record.get("protocol", FORWARD_PROTOCOL_TCP) == protocol
        }


class ForwardListener:
    """One loopback listener whose every connection is one ``connect`` stream."""

    def __init__(self, *, open_stream, local_port: int, kind: str, log=print):
        """
        Args:
            open_stream: ``open_stream()`` opens one ``connect`` stream to
                the far end and returns it; raises
                :class:`~neutrino_client.exceptions.GatewayUnreachable` when
                the hub cannot be asked.
            local_port: The loopback number to listen on.
            kind: What is forwarded: an entry's type, or ``panel``.
            log: Callable used for progress messages.
        """
        self.kind = kind
        self.local_port = 0
        self._open_stream = open_stream
        self._bind_port = local_port
        self._log = log
        self._listener = None
        self._is_closed = False
        self._lock = threading.Lock()
        self._connections: set = set()

    @property
    def is_active(self) -> bool:
        """Whether the listener is still listening."""
        return self._listener is not None and not self._is_closed

    def start(self) -> int:
        """Listen on the loopback and start accepting.

        Returns:
            The local port bound.

        Raises:
            OSError: When the port cannot be listened on.
        """
        listener = socket.create_server((FORWARD_BIND_HOST, self._bind_port))
        self._listener = listener
        self.local_port = listener.getsockname()[1]
        threading.Thread(
            target=self._accept, name="client_forward_accept", daemon=True
        ).start()
        return self.local_port

    def close(self) -> None:
        """Stop listening and close every connection, which ends its stream."""
        self._is_closed = True
        if self._listener is not None:
            _close_socket(self._listener)
        with self._lock:
            connections = list(self._connections)
            self._connections.clear()
        for connection in connections:
            _close_socket(connection)

    def _accept(self) -> None:
        while not self._is_closed:
            try:
                connection, _address = self._listener.accept()
            except OSError:
                break
            if self._is_closed:
                _close_socket(connection)
                break
            threading.Thread(
                target=self._serve,
                args=(connection,),
                name="client_forward_connection",
                daemon=True,
            ).start()

    def _serve(self, connection) -> None:
        try:
            stream = self._open_stream()
        except GatewayUnreachable as error:
            self._log(f"no connect stream for 127.0.0.1:{self.local_port}: {error}")
            _close_socket(connection)
            return
        with self._lock:
            if self._is_closed:
                stream.close()
                _close_socket(connection)
                return
            self._connections.add(connection)
        relay_socket(connection, stream, self._log)
        with self._lock:
            self._connections.discard(connection)


# A UDP datagram's source port, in front of it in its frame.
UDP_SOURCE_BYTES = 2
# The largest datagram one UDP socket reads.
UDP_DATAGRAM_MAX_BYTES = 65535


class UdpForwardListener:
    """One loopback UDP socket whose datagrams ride one ``connect`` stream.

    Each datagram goes into the stream as ``<u16 source><datagram>``,
    ``source`` being the port it came from; a frame from the stream goes
    back to the address its ``source`` last came from. The stream is opened
    at the start, and again by the first datagram that finds none, at most
    once every ``CLIENT_UDP_REOPEN_INTERVAL_S``. A datagram is held only
    while an open waits for its first credit, at most
    ``CLIENT_UDP_HELD_DATAGRAMS_MAX`` of them; anywhere else a datagram the
    credit does not cover is dropped.

    The hub grants a stream's first credit before it judges the open, so a
    close with a code says the open was refused. The stream opened at the
    start that closes with a code before any datagram went into it, held
    ones included, is refused at Connect: the forward ends. A close with a
    code after a datagram went in leaves the forward listening. A stream
    that ends with the hub's socket, or with no code, is opened again by the
    next datagram and is told to nobody.
    """

    def __init__(
        self,
        *,
        open_stream,
        local_port: int,
        kind: str,
        log=print,
        on_refused=None,
        clock=time.monotonic,
    ):
        """
        Args:
            open_stream: ``open_stream()`` opens one ``connect`` stream to
                the far end and returns it; raises
                :class:`~neutrino_client.exceptions.GatewayUnreachable` when
                the hub cannot be asked.
            local_port: The loopback number to bind.
            kind: What is forwarded, an entry's type.
            log: Callable used for progress messages.
            on_refused: ``on_refused(refusal, is_ended)`` is told when the
                hub closes a stream with a code: ``refusal`` is ``{"code",
                "params"}``, and ``is_ended`` says the forward ended for it,
                the stream of the start having carried no datagram; None for
                nobody listening.
            clock: The monotonic clock the reopen interval is measured on.
        """
        self.kind = kind
        self.local_port = 0
        self._open_stream = open_stream
        self._bind_port = local_port
        self._log = log
        self._on_refused = on_refused if on_refused is not None else _nobody_told
        self._clock = clock
        self._socket = None
        self._is_closed = False
        self._lock = threading.Lock()
        self._stream = None
        self._is_waiting_credit = False
        self._held: list = []
        self._last_open_at = None
        # The stream opened at the start, while no datagram went into it.
        self._first_stream = None
        # The address each source last came from, the idlest first.
        self._sources: collections.OrderedDict = collections.OrderedDict()

    @property
    def is_active(self) -> bool:
        """Whether the socket is still bound."""
        return self._socket is not None and not self._is_closed

    def start(self) -> int:
        """Bind the loopback, open the stream and start carrying datagrams.

        Returns:
            The local port bound.

        Raises:
            GatewayUnreachable: When the hub cannot be asked for the stream.
            OSError: When the port cannot be bound.
        """
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.bind((FORWARD_BIND_HOST, self._bind_port))
        except OSError:
            udp.close()
            raise
        self._socket = udp
        self.local_port = udp.getsockname()[1]
        try:
            self._first_stream = self._open_now()
        except GatewayUnreachable:
            self.close()
            raise
        threading.Thread(
            target=self._receive_forever, name="client_udp_forward", daemon=True
        ).start()
        return self.local_port

    def close(self) -> None:
        """Unbind the socket and end the stream."""
        self._is_closed = True
        udp = self._socket
        if udp is not None:
            try:
                udp.close()
            except OSError:
                pass
        with self._lock:
            stream, self._stream = self._stream, None
            self._held = []
        if stream is not None:
            stream.close()

    def take_datagram(self, data: bytes, address) -> None:
        """Carry one datagram a local program sent to the forward.

        Args:
            data: The datagram.
            address: ``(host, port)`` it came from.
        """
        source = int(address[1])
        frame = source.to_bytes(UDP_SOURCE_BYTES, "big") + bytes(data)
        with self._lock:
            self._sources.pop(source, None)
            self._sources[source] = address
            while len(self._sources) > CLIENT_UDP_SOURCES_MAX:
                self._sources.popitem(last=False)
            stream = self._stream
            if stream is None or stream.is_done:
                stream = self._reopen()
                if stream is None:
                    return
            self._first_stream = None
            if self._is_waiting_credit:
                if len(self._held) < CLIENT_UDP_HELD_DATAGRAMS_MAX:
                    self._held.append(frame)
                return
        stream.try_send(frame)

    def take_frame(self, frame: bytes) -> None:
        """Send one frame from the stream to the local program it is for.

        Args:
            frame: ``<u16 source><datagram>``.
        """
        if len(frame) < UDP_SOURCE_BYTES:
            return
        source = int.from_bytes(frame[:UDP_SOURCE_BYTES], "big")
        with self._lock:
            address = self._sources.get(source)
            if address is not None:
                self._sources.move_to_end(source)
        udp = self._socket
        if address is None or udp is None:
            return
        try:
            udp.sendto(frame[UDP_SOURCE_BYTES:], address)
        except OSError:
            pass

    def _open_now(self):
        """Open a stream and start its reader; the caller holds no lock.

        Raises:
            GatewayUnreachable: When the hub cannot be asked.
        """
        with self._lock:
            self._last_open_at = self._clock()
            self._is_waiting_credit = True
        stream = self._open_stream()
        with self._lock:
            self._stream = stream
        self._watch(stream)
        return stream

    def _reopen(self):
        """Open the stream again for a datagram that found none; the lock is held.

        Returns:
            The new stream, or None while the last open is too recent or the
            hub cannot be asked.
        """
        now = self._clock()
        if (
            self._last_open_at is not None
            and now - self._last_open_at < CLIENT_UDP_REOPEN_INTERVAL_S
        ):
            return None
        self._last_open_at = now
        try:
            stream = self._open_stream()
        except GatewayUnreachable as error:
            self._log(f"no stream for udp 127.0.0.1:{self.local_port}: {error}")
            return None
        self._stream = stream
        self._is_waiting_credit = True
        self._held = []
        self._watch(stream)
        return stream

    def _watch(self, stream) -> None:
        """Start the threads that wait for a stream's credit and read it."""
        threading.Thread(
            target=self._flush_on_credit,
            args=(stream,),
            name="client_udp_credit",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._read_forever,
            args=(stream,),
            name="client_udp_stream",
            daemon=True,
        ).start()

    def _flush_on_credit(self, stream) -> None:
        """Send what was held once the stream's first credit comes."""
        is_credited = stream.wait_credit(CLIENT_STREAM_TIMEOUT_S)
        with self._lock:
            if self._stream is not stream:
                return
            held, self._held = self._held, []
            self._is_waiting_credit = False
        if not is_credited:
            return
        for frame in held:
            stream.try_send(frame)

    def _read_forever(self, stream) -> None:
        """Pass the stream's frames to their programs until it ends."""
        while True:
            frame = stream.read_frame(FORWARD_STREAM_WAIT_S)
            if frame is None:
                continue
            if not frame:
                break
            self.take_frame(frame)
        refusal = stream.refusal()
        with self._lock:
            is_current = self._stream is stream
            if is_current:
                self._stream = None
            is_ended = self._first_stream is stream and refusal is not None
            self._first_stream = None
        if refusal is None or not is_current or self._is_closed:
            return
        self._log(f"the hub refused udp 127.0.0.1:{self.local_port}: {refusal}")
        if is_ended:
            self.close()
        self._on_refused(refusal, is_ended)

    def _receive_forever(self) -> None:
        udp = self._socket
        while not self._is_closed:
            try:
                data, address = udp.recvfrom(UDP_DATAGRAM_MAX_BYTES)
            except OSError:
                if self._is_closed:
                    return
                continue
            self.take_datagram(data, address)


def _nobody_told(*_args) -> None:
    """Nobody listening."""


class ForwardListenerRegistry:
    """Every forward this client runs, by service key, over every hub."""

    def __init__(
        self, *, open_connect, ports=None, log=print, on_change=None, on_refused=None
    ):
        """
        Args:
            open_connect: ``open_connect(hub_id, args)`` opens one
                ``connect`` stream on that hub with the open's arguments
                (``{"id"}`` or ``{"is_panel": true}``) and returns it;
                raises :class:`~neutrino_client.exceptions.GatewayUnreachable`
                when the hub cannot be asked.
            ports: The :class:`PortLocalTable` the forwards take their port
                from; None keeps one in memory.
            log: Callable used for progress messages.
            on_change: Called after a forward starts or stops; None for
                nobody listening.
            on_refused: ``on_refused(hub_id, entry_id, refusal)`` is told
                when the hub closes a UDP forward's stream with a code; the
                forward is gone by then when the stream of its start had
                carried no datagram. None for nobody listening.
        """
        self._open_connect = open_connect
        self._on_refused = on_refused if on_refused is not None else _nobody_told
        self.ports = ports if ports is not None else PortLocalTable()
        self._log = log
        self._on_change = on_change if on_change is not None else _nobody
        self._lock = threading.Lock()
        self._listeners: dict = {}

    def ensure(
        self,
        *,
        hub_id: str,
        entry_id: str,
        own_port: int,
        kind: str,
        local_port: int = 0,
        protocol: str = FORWARD_PROTOCOL_TCP,
    ) -> int:
        """Make one entry's forward when it has none, and say where it listens.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry's id, or ``FORWARD_PANEL_ID`` for the panel.
            own_port: The entry's own port, which an auto pick takes first;
                0 for none.
            kind: The entry's type, or ``panel``.
            local_port: A loopback number asked for this once, outside the
                table; 0 takes the entry's from the table.
            protocol: ``tcp`` for a listener whose every connection is a
                stream, ``udp`` for one UDP socket on one stream.

        Returns:
            The loopback port the forward listens on.

        Raises:
            GatewayUnreachable: When the hub cannot be asked for a UDP
                forward's stream.
            OSError: When no port is to be had or it cannot be listened on.
        """
        key = service_key(hub_id, entry_id)
        args = {"is_panel": True} if entry_id == FORWARD_PANEL_ID else {"id": entry_id}

        def open_stream():
            return self._open_connect(hub_id, args)

        with self._lock:
            listener = self._listeners.get(key)
            if listener is not None and listener.is_active:
                return listener.local_port
            port = local_port or self.ports.take(key, own_port, protocol)
            if protocol == FORWARD_PROTOCOL_UDP:

                def refused(refusal: dict, is_ended: bool) -> None:
                    if is_ended:
                        self._forget(key, listener)
                    self._on_refused(hub_id, entry_id, refusal)

                listener = UdpForwardListener(
                    open_stream=open_stream,
                    local_port=port,
                    kind=kind,
                    log=self._log,
                    on_refused=refused,
                )
            else:
                listener = ForwardListener(
                    open_stream=open_stream, local_port=port, kind=kind, log=self._log
                )
            bound = listener.start()
            self._listeners[key] = listener
        self._log(
            f"forwarding {FORWARD_BIND_HOST}:{bound}/{protocol} to {key} through the hub"
        )
        self._on_change()
        return bound

    def _forget(self, key: str, listener) -> None:
        """Drop a forward that ended by itself, when it is still the key's."""
        with self._lock:
            if self._listeners.get(key) is listener:
                self._listeners.pop(key, None)
        self._on_change()

    def port_of(self, hub_id: str, entry_id: str) -> int:
        """Where one entry's forward listens.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry's id.

        Returns:
            The loopback port; 0 when the entry is not forwarded.
        """
        with self._lock:
            listener = self._listeners.get(service_key(hub_id, entry_id))
        if listener is None or not listener.is_active:
            return 0
        return listener.local_port

    def forwards(self) -> dict:
        """Every forward listening now.

        Returns:
            ``{service_key: local_port}``.
        """
        with self._lock:
            return {
                key: listener.local_port
                for key, listener in self._listeners.items()
                if listener.is_active
            }

    def stop(self, hub_id: str, entry_id: str) -> bool:
        """End one entry's forward, its connections and their streams.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry's id.

        Returns:
            Whether a forward was running.
        """
        key = service_key(hub_id, entry_id)
        with self._lock:
            listener = self._listeners.pop(key, None)
        if listener is None:
            return False
        listener.close()
        self._log(f"stopped forwarding {FORWARD_BIND_HOST}:{listener.local_port}")
        self._on_change()
        return True

    def release(self) -> int:
        """End every forward.

        Returns:
            How many forwards were ended.
        """
        return self._end(lambda key, listener: True)

    def release_hub(self, hub_id: str) -> int:
        """End every forward of one hub, the panel's among them.

        Args:
            hub_id: The hub whose forwards end.

        Returns:
            How many forwards were ended.
        """
        return self._end(lambda key, listener: hub_of_key(key) == hub_id)

    def release_kind(self, kind: str, hub_id: str = "") -> int:
        """End every forward of one kind, of one hub or of all.

        Args:
            kind: The entry type, or ``panel``.
            hub_id: The hub; empty for every hub.

        Returns:
            How many forwards were ended.
        """
        return self._end(
            lambda key, listener: listener.kind == kind
            and (not hub_id or hub_of_key(key) == hub_id)
        )

    def drop_withdrawn(self, *, hub_id: str, entries: list) -> int:
        """End the port and web forwards of one hub whose entry its list no longer has.

        Args:
            hub_id: The hub whose list arrived.
            entries: That hub's service list as it stands now.

        Returns:
            How many forwards were ended.
        """
        listed = {service_key(hub_id, str(entry.get("id", ""))) for entry in entries}
        return self._end(
            lambda key, listener: hub_of_key(key) == hub_id
            and listener.kind in FORWARD_LISTED_KINDS
            and key not in listed
        )

    def _end(self, is_ended) -> int:
        """End the forwards ``is_ended(key, listener)`` picks."""
        with self._lock:
            ended = {
                key: listener
                for key, listener in self._listeners.items()
                if is_ended(key, listener)
            }
            for key in ended:
                self._listeners.pop(key, None)
        for listener in ended.values():
            listener.close()
        if ended:
            self._on_change()
        return len(ended)
