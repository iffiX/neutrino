"""The port service type: forwarding a published port to this machine.

A published port forwards to ``127.0.0.1`` on a click, through a
standard-library relay on the port the one local port table gives the
entry: ``auto`` or a fixed number per entry, kept in the client's store, no
number held by two entries. The forwards themselves are runtime state and
die with the resident. Forwards are held by service key, so two hubs
publishing the same entry id never collide.
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
from neutrino_client.services.store import STORE_LOCAL_PORT_AUTO

FORWARD_BIND_HOST = "127.0.0.1"
FORWARD_BUFFER_BYTES = 65536
FORWARD_CONNECT_TIMEOUT_S = 10
# A local port's setting when the client picks the number.
FORWARD_PORT_AUTO = STORE_LOCAL_PORT_AUTO
# Where an auto pick looks when the entry's own number is not to be had.
FORWARD_AUTO_FIRST_PORT = 20000
FORWARD_PORT_MAX = 65535
# The numbers a fixed setting may name.
FORWARD_FIXED_PORT_MIN = 1024


def is_loopback_port_free(port: int) -> bool:
    """Whether a loopback port can be listened on now.

    Args:
        port: The port number.

    Returns:
        True when a listener binds it.
    """
    try:
        probe = socket.create_server((FORWARD_BIND_HOST, port))
    except (OSError, OverflowError):
        return False
    probe.close()
    return True


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


class PortLocalTable:
    """The one table of the loopback ports this client's forwards take.

    Every forwardable entry is ``auto`` or a fixed number. Auto takes the
    entry's own port when no other entry holds it and it is free on the
    loopback, else the first free one from ``FORWARD_AUTO_FIRST_PORT`` up,
    and the pick is kept for every later forward. No number is held by two
    entries.
    """

    def __init__(self, *, store=None, is_free=None):
        """
        Args:
            store: The :class:`~neutrino_client.services.store.ClientServiceStore`
                the table is kept in; None keeps it in memory.
            is_free: ``is_free(port)`` says whether the loopback port can be
                listened on; None asks the system.
        """
        self._store = store
        self._is_free = is_free if is_free is not None else is_loopback_port_free
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

    def configure(self, key: str, setting) -> dict:
        """Set one entry's local port.

        Args:
            key: The entry's service key.
            setting: ``"auto"``, or a fixed number from
                ``FORWARD_FIXED_PORT_MIN`` to ``FORWARD_PORT_MAX``.

        Returns:
            Empty when kept; ``unknown_request`` for a setting of another
            shape, ``port_taken`` with the port for a number another entry
            holds.
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
                self._keep(key, FORWARD_PORT_AUTO, 0)
                return {}
            if setting in self._held(records, key):
                return {"code": "port_taken", "params": {"port": setting}}
            self._keep(key, setting, setting)
        return {}

    def take(self, key: str, own_port: int) -> int:
        """The port one entry's forward listens on, an auto pick kept.

        Args:
            key: The entry's service key.
            own_port: The entry's published port, which auto takes first.

        Returns:
            The port number.

        Raises:
            OSError: When auto finds no free port.
        """
        with self._lock:
            records = self._records()
            record = records.get(key)
            if record and record["port"]:
                return record["port"]
            held = self._held(records, key)
            port = self._pick(own_port, held)
            self._keep(key, FORWARD_PORT_AUTO, port)
            return port

    def _pick(self, own_port: int, held: set) -> int:
        """The entry's own port, else the first free one from the floor up."""
        if 0 < own_port <= FORWARD_PORT_MAX and own_port not in held:
            if self._is_free(own_port):
                return own_port
        for port in range(FORWARD_AUTO_FIRST_PORT, FORWARD_PORT_MAX + 1):
            if port not in held and self._is_free(port):
                return port
        raise OSError("no free loopback port")

    def _records(self) -> dict:
        """Every entry's record; the lock is held."""
        if self._store is None:
            return dict(self._memory)
        return self._store.local_ports()

    def _keep(self, key: str, setting, port: int) -> None:
        """Write one entry's record; the lock is held."""
        if self._store is None:
            self._memory[key] = {"setting": setting, "port": port}
        else:
            self._store.set_local_port(key, setting, port)

    @staticmethod
    def _held(records: dict, key: str) -> set:
        """The ports every other entry holds."""
        return {
            record["port"]
            for other, record in records.items()
            if other != key and record["port"]
        }


class PortServiceHandler(ServiceTypeHandler):
    """Starts, stops and lists this machine's loopback port forwards."""

    service_type = "port"

    def __init__(self, *, log=print, on_change=None, ports=None):
        """
        Args:
            log: Callable used for progress messages.
            on_change: Called after a forward starts or stops; None for
                nobody listening.
            ports: The :class:`PortLocalTable` the forwards take their port
                from; None keeps one in memory.
        """
        self._log = log
        self._ports = ports if ports is not None else PortLocalTable()
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
                loopback number this once, outside the table.

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
            local_port = int(body.get("local_port") or 0)
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
            local_port: The loopback number to listen on; 0 takes the
                entry's from the table.

        Returns:
            Empty on success, ``{"code", "params"}`` when the port cannot
            be listened on.
        """
        key = service_key(hub_id, entry_id)
        with self._lock:
            relay = self._relays.get(key)
            if relay is not None and relay.is_active:
                return {}
            try:
                local_port = local_port or self._ports.take(key, port)
                relay = _ForwardRelay(host=host, port=port, local_port=local_port)
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
            local_port: The loopback number to listen on.
        """
        self.host = host
        self.port = port
        self.local_port = 0
        self._bind_port = local_port
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
            The local port bound.

        Raises:
            OSError: When the port cannot be listened on.
        """
        listener = socket.create_server((FORWARD_BIND_HOST, self._bind_port))
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
