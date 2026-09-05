"""The ports service: forwarding a published port to this machine.

A published port forwards to ``127.0.0.1`` on a click — a standard-library
relay on the same number when it is free and otherwise on a free one the row
names. A forward binds the loopback the whole machine shares, so it is
machine state every scope sees and any scope may toggle. Runtime state only:
forwards die with the agent process.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import socket
import threading

FORWARD_BIND_HOST = "127.0.0.1"
FORWARD_BUFFER_BYTES = 65536
FORWARD_CONNECT_TIMEOUT_S = 10


def _pump(source, destination) -> None:
    """Copy one direction until it ends, then pass the end of stream on."""
    while True:
        try:
            data = source.recv(FORWARD_BUFFER_BYTES)
        except OSError:
            break
        if not data:
            break
        try:
            destination.sendall(data)
        except OSError:
            break
    try:
        destination.shutdown(socket.SHUT_WR)
    except OSError:
        pass


class PortsService:
    """Starts, stops and lists this machine's loopback port forwards."""

    def __init__(self, *, log=print):
        """
        Args:
            log: Callable used for progress messages.
        """
        self._log = log
        self._lock = threading.Lock()
        self._relays: dict = {}

    def forward(self, *, offer_id: str, host: str, port: int) -> dict:
        """Start forwarding one published port to the loopback.

        Args:
            offer_id: The offer's id in the catalog.
            host: The address the published port answers on.
            port: The published port number, preferred locally too.

        Returns:
            Empty on success, ``{"code", "params"}`` when nothing can bind.
        """
        with self._lock:
            relay = self._relays.get(offer_id)
            if relay is not None and relay.is_active:
                return {}
            relay = _ForwardRelay(host=host, port=port)
            try:
                local_port = relay.start()
            except OSError as error:
                return {
                    "code": "forward_failed",
                    "params": {"detail": str(error)[:200]},
                }
            self._relays[offer_id] = relay
        self._log(f"forwarding {FORWARD_BIND_HOST}:{local_port} to {host}:{port}")
        return {}

    def stop(self, *, offer_id: str) -> dict:
        """Stop one forward, closing its listener and every connection.

        Args:
            offer_id: The offer whose forward to stop.

        Returns:
            Empty; stopping what is not running is nothing.
        """
        with self._lock:
            relay = self._relays.pop(offer_id, None)
        if relay is not None:
            relay.close()
            self._log(f"stopped forwarding to {relay.host}:{relay.port}")
        return {}

    def rows(self) -> dict:
        """The forwards this machine is running, for the state payload.

        Returns:
            Offer id to ``{"local_port", "is_active"}``.
        """
        with self._lock:
            return {
                offer_id: {
                    "local_port": relay.local_port,
                    "is_active": relay.is_active,
                }
                for offer_id, relay in self._relays.items()
            }


class _ForwardRelay:
    """One listening loopback port relayed to one published port."""

    def __init__(self, *, host: str, port: int):
        """
        Args:
            host: The address the published port answers on.
            port: The published port number, preferred locally too.
        """
        self.host = host
        self.port = port
        self.local_port = 0
        self._listener = None
        self._is_closed = False
        self._lock = threading.Lock()
        self._connections: set = set()

    @property
    def is_active(self) -> bool:
        """Whether the relay is still listening."""
        return self._listener is not None and not self._is_closed

    def start(self) -> int:
        """Bind the loopback and start accepting.

        Returns:
            The local port bound: the published number when free, any free
            one otherwise.

        Raises:
            OSError: When not even an unnumbered bind succeeds.
        """
        try:
            listener = socket.create_server((FORWARD_BIND_HOST, self.port))
        except OSError:
            listener = socket.create_server((FORWARD_BIND_HOST, 0))
        self._listener = listener
        self.local_port = listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()
        return self.local_port

    def close(self) -> None:
        """Stop listening and close every open connection."""
        self._is_closed = True
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        with self._lock:
            connections = list(self._connections)
            self._connections.clear()
        for connection in connections:
            try:
                connection.close()
            except OSError:
                pass

    def _accept(self) -> None:
        while not self._is_closed:
            try:
                connection, _address = self._listener.accept()
            except OSError:
                break
            threading.Thread(
                target=self._serve, args=(connection,), daemon=True
            ).start()

    def _serve(self, connection) -> None:
        try:
            upstream = socket.create_connection(
                (self.host, self.port), timeout=FORWARD_CONNECT_TIMEOUT_S
            )
        except OSError:
            connection.close()
            return
        upstream.settimeout(None)
        with self._lock:
            self._connections.add(connection)
            self._connections.add(upstream)
        outbound = threading.Thread(
            target=_pump, args=(connection, upstream), daemon=True
        )
        outbound.start()
        _pump(upstream, connection)
        outbound.join()
        with self._lock:
            self._connections.discard(connection)
            self._connections.discard(upstream)
        for side in (connection, upstream):
            try:
                side.close()
            except OSError:
                pass
