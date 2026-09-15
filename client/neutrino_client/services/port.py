"""The port service type: forwarding a published port to this machine.

A published port forwards to ``127.0.0.1`` on a click: a standard-library
relay on the same number when it is free and otherwise on a free one the row
names. Runtime state only: forwards die with the resident. Forwards are held
by service key, so two hubs publishing the same entry id never collide.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import socket
import threading

from neutrino_client.services.base import (
    ServiceTypeHandler,
    find_entry,
    hub_of_key,
    service_key,
)

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


def _nobody() -> None:
    """Nobody listening for changes."""


class PortServiceHandler(ServiceTypeHandler):
    """Starts, stops and lists this machine's loopback port forwards."""

    service_type = "port"

    def __init__(self, *, log=print, on_change=None):
        """
        Args:
            log: Callable used for progress messages.
            on_change: Called after a forward starts or stops; None for
                nobody listening.
        """
        self._log = log
        self._lock = threading.Lock()
        # The running relays, by service key.
        self._relays: dict = {}
        self._on_change = on_change if on_change is not None else _nobody

    def act(self, *, entries: list, body: dict):
        """Connect or disconnect one published port's loopback forward.

        Args:
            entries: The merged service list.
            body: ``{"hub_id", "id", "is_enabled", "local_port"}``;
                ``local_port`` is optional and asks for a particular
                loopback number.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        hub_id = str(body.get("hub_id", ""))
        entry_id = str(body.get("id", ""))
        entry = find_entry(entries, self.service_type, hub_id, entry_id)
        if entry is None:
            return {"code": "unknown_request", "params": {}}
        if not body.get("is_enabled"):
            return self.stop(hub_id=hub_id, entry_id=entry_id)
        payload = entry.get("payload") or {}
        try:
            port = int(payload.get("port", 0))
            local_port = int(body.get("local_port") or port)
        except (TypeError, ValueError):
            return {"code": "unknown_request", "params": {}}
        return self.forward(
            hub_id=hub_id,
            entry_id=entry_id,
            host=str(payload.get("host", "")),
            port=port,
            local_port=local_port,
        )

    def state(self) -> dict:
        """The forwards this machine is running, for the state payload.

        Returns:
            ``{"forwards": {service_key: {"local_port", "is_active"}}}``.
        """
        with self._lock:
            return {
                "forwards": {
                    key: {"local_port": relay.local_port, "is_active": relay.is_active}
                    for key, relay in self._relays.items()
                }
            }

    def release(self) -> int:
        """Close every forward.

        Returns:
            How many forwards were closed.
        """
        with self._lock:
            relays = dict(self._relays)
            self._relays = {}
        return self._close_all(relays)

    def release_hub(self, hub_id: str) -> int:
        """Close every forward of one hub's entries.

        Args:
            hub_id: The hub whose forwards are closed.

        Returns:
            How many forwards were closed.
        """
        with self._lock:
            relays = {
                key: relay
                for key, relay in self._relays.items()
                if hub_of_key(key) == hub_id
            }
            for key in relays:
                self._relays.pop(key, None)
        closed = self._close_all(relays)
        if closed:
            self._on_change()
        return closed

    def forward(
        self,
        *,
        hub_id: str,
        entry_id: str,
        host: str,
        port: int,
        local_port: int = 0,
    ) -> dict:
        """Start forwarding one published port to the loopback.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry's id in that hub's list.
            host: The address the published port answers on.
            port: The published port number.
            local_port: The loopback number preferred; 0 means the
                published one.

        Returns:
            Empty on success, ``{"code", "params"}`` when nothing can bind.
        """
        key = service_key(hub_id, entry_id)
        with self._lock:
            relay = self._relays.get(key)
            if relay is not None and relay.is_active:
                return {}
            relay = _ForwardRelay(host=host, port=port, local_port=local_port or port)
            try:
                bound = relay.start()
            except OSError as error:
                return {
                    "code": "forward_failed",
                    "params": {"detail": str(error)[:200]},
                }
            self._relays[key] = relay
        self._log(f"forwarding {FORWARD_BIND_HOST}:{bound} to {host}:{port}")
        self._on_change()
        return {}

    def stop(self, *, hub_id: str, entry_id: str) -> dict:
        """Stop one forward, closing its listener and every connection.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry whose forward to stop.

        Returns:
            Empty; stopping what is not running is nothing.
        """
        with self._lock:
            relay = self._relays.pop(service_key(hub_id, entry_id), None)
        if relay is not None:
            relay.close()
            self._log(f"stopped forwarding to {relay.host}:{relay.port}")
            self._on_change()
        return {}

    @staticmethod
    def _close_all(relays: dict) -> int:
        for relay in relays.values():
            relay.close()
        return len(relays)


class _ForwardRelay:
    """One listening loopback port relayed to one published port."""

    def __init__(self, *, host: str, port: int, local_port: int):
        """
        Args:
            host: The address the published port answers on.
            port: The published port number.
            local_port: The loopback number preferred.
        """
        self.host = host
        self.port = port
        self.local_port = 0
        self._preferred_port = local_port
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
            The local port bound: the preferred number when free, any free
            one otherwise.

        Raises:
            OSError: When not even an unnumbered bind succeeds.
        """
        try:
            listener = socket.create_server((FORWARD_BIND_HOST, self._preferred_port))
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
                self._listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
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
            if self._is_closed:
                connection.close()
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
