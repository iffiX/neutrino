"""The relays a container reaches the agent's loopback listeners through.

Every container on the machine reaches the agent's ``127.0.0.1``
listeners, the AI gateway forward and the forwarders of the programs run as
an account, at ``host.containers.internal`` on the same port. That name is
the gateway of the container's Podman bridge on Linux and the computer's
address on WSL's vEthernet adapter on Windows, and the platform reads those
addresses. The agent listens on each of them for each listener, a relay on
a Linux bridge bound to the bridge with ``SO_BINDTODEVICE``, and relays
every connection to ``127.0.0.1`` on the same port. A relay is known by its
interface's name and index, its address and its port, so a bridge made
again under a new index has its relays opened again.

Every report interval the relays are made to match the addresses and the
listeners, and the firewall to match the relays. The platform reads and
changes the firewall when a relay opened or closed, when its last try
failed, and at least once a minute while the agent holds rules; with no
relay and no rule found, it is left alone. A stop closes every relay and
takes the agent's rules away.

Not pure: listens on sockets, dials loopback, and changes the firewall
through the platform.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import socket
import subprocess
import threading
import time

from neutrino_agent.constants import (
    AGENT_CONNECT_DIAL_TIMEOUT_S,
    AGENT_RELAY_BACKLOG,
    AGENT_RELAY_FIREWALL_RECHECK_S,
    AGENT_RELAY_TARGET_HOST,
    AGENT_REPORT_INTERVAL_S,
    AGENT_WS_CHUNK_BYTES,
)
from neutrino_agent.platforms.base import RelayAddress, RelayRule


def gateway_port_of(document) -> int:
    """The gateway port a state asks the agent to relay, on the hub's own machine.

    Args:
        document: The state, ``{ai_tools, ...}``; anything but a dict names
            none.

    Returns:
        The ``ai_tools`` section's ``gateway_port`` when it is a port, else
        0.
    """
    section = document.get("ai_tools") if isinstance(document, dict) else None
    port = section.get("gateway_port") if isinstance(section, dict) else None
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        return 0
    return port


def open_listener(address: RelayAddress, port: int) -> socket.socket:
    """Listen on one address and port, bound to the address's interface where it has an index.

    Args:
        address: Where to listen.
        port: The port.

    Returns:
        The listening socket.

    Raises:
        OSError: When the address or the port cannot be had.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if address.index > 0:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_BINDTODEVICE,
                address.interface.encode("utf-8") + b"\0",
            )
        listener.bind((address.address, port))
        listener.listen(AGENT_RELAY_BACKLOG)
    except OSError:
        listener.close()
        raise
    return listener


def _shut(connection: socket.socket, how: int) -> None:
    """Shut one side of a socket down, waking a thread blocked on it."""
    with contextlib.suppress(OSError):
        connection.shutdown(how)


def _close(connection: socket.socket) -> None:
    """Shut a socket down both ways and close it."""
    _shut(connection, socket.SHUT_RDWR)
    with contextlib.suppress(OSError):
        connection.close()


def _pump(source: socket.socket, target: socket.socket) -> None:
    """Copy one direction until it ends: its end shuts the target's sending
    side, and an error shuts both sockets."""
    while True:
        try:
            data = source.recv(AGENT_WS_CHUNK_BYTES)
            if not data:
                break
            target.sendall(data)
        except OSError:
            _shut(source, socket.SHUT_RDWR)
            _shut(target, socket.SHUT_RDWR)
            return
    _shut(target, socket.SHUT_WR)


class ContainerRelay:
    """One relay: a listener on one container-facing address, each connection carried to loopback."""

    def __init__(
        self,
        *,
        listener: socket.socket,
        port: int,
        target_host: str = AGENT_RELAY_TARGET_HOST,
        dial_timeout_s: float = AGENT_CONNECT_DIAL_TIMEOUT_S,
    ):
        """
        Args:
            listener: The listening socket, already bound.
            port: The port dialled on the target.
            target_host: Where each connection is carried.
            dial_timeout_s: How long a dial to the target may take.
        """
        self._listener = listener
        self._port = port
        self._target_host = target_host
        self._dial_timeout_s = dial_timeout_s
        self._lock = threading.Lock()
        self._is_closed = False
        self._connections: set = set()

    def start(self) -> None:
        """Begin accepting."""
        threading.Thread(
            target=self._accept, name=f"agent_relay_{self._port}", daemon=True
        ).start()

    def close(self) -> None:
        """Stop listening and end every connection the relay carries."""
        with self._lock:
            self._is_closed = True
            connections = list(self._connections)
            self._connections.clear()
        _close(self._listener)
        for connection in connections:
            _close(connection)

    def _accept(self) -> None:
        """Accept until the listener is closed."""
        while True:
            try:
                client, _address = self._listener.accept()
            except OSError:
                return
            with self._lock:
                if self._is_closed:
                    _close(client)
                    return
                self._connections.add(client)
            threading.Thread(
                target=self._serve,
                args=(client,),
                name=f"agent_relay_{self._port}_connection",
                daemon=True,
            ).start()

    def _serve(self, client: socket.socket) -> None:
        """Carry one connection to the target, both ways, until both ends end."""
        try:
            upstream = socket.create_connection(
                (self._target_host, self._port), timeout=self._dial_timeout_s
            )
        except OSError:
            self._forget(client)
            _close(client)
            return
        upstream.settimeout(None)
        with self._lock:
            if self._is_closed:
                _close(upstream)
                _close(client)
                return
            self._connections.add(upstream)
        downward = threading.Thread(
            target=_pump,
            args=(upstream, client),
            name=f"agent_relay_{self._port}_down",
            daemon=True,
        )
        downward.start()
        _pump(client, upstream)
        downward.join()
        self._forget(client, upstream)
        _close(upstream)
        _close(client)

    def _forget(self, *connections) -> None:
        """Stop holding connections that ended."""
        with self._lock:
            for connection in connections:
                self._connections.discard(connection)


class ContainerRelays:
    """Every relay the machine's containers reach the agent through, with the firewall's rules for them."""

    def __init__(
        self,
        *,
        platform,
        ports,
        log=print,
        interval_s: float = AGENT_REPORT_INTERVAL_S,
        recheck_s: float = AGENT_RELAY_FIREWALL_RECHECK_S,
        clock=time.monotonic,
        listen=open_listener,
        relay_factory=ContainerRelay,
    ):
        """
        Args:
            platform: The machine's platform, which reads the addresses and
                changes the firewall.
            ports: Called with nothing; returns the ports of the agent's
                loopback listeners to relay now.
            log: Callable used for progress messages.
            interval_s: How often the relays are made to match.
            recheck_s: How long the agent goes, while it holds rules, before
                it reads the firewall again with no relay changed; also how
                long a failed firewall change waits to be tried again.
            clock: The monotonic clock.
            listen: Opens a listener on ``(RelayAddress, port)``, as
                :func:`open_listener` does.
            relay_factory: Makes a relay from ``listener`` and ``port``.
        """
        self._platform = platform
        self._ports = ports
        self._log = log
        self._interval_s = interval_s
        self._recheck_s = recheck_s
        self._clock = clock
        self._listen = listen
        self._relay_factory = relay_factory
        self._lock = threading.Lock()
        self._relays: dict = {}
        # The failure last written per relay; the same one is not written again.
        self._noted: dict = {}
        # The rules the firewall was last given, whether that worked, and when.
        self._ruled: "frozenset | None" = None
        self._is_ruled = False
        self._ruled_at = 0.0
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None

    @property
    def relays(self) -> set:
        """``(interface, index, address, port)`` of every relay open now."""
        with self._lock:
            return set(self._relays)

    def start(self) -> None:
        """Make the relays match now, then again every interval, on a thread of their own."""
        with self._lock:
            if self._thread is not None:
                return
            self._is_stopped.clear()
            self._thread = threading.Thread(
                target=self._run, name="agent_relays", daemon=True
            )
            thread = self._thread
        thread.start()

    def stop(self) -> None:
        """Close every relay and take the agent's firewall rules away, once a
        pass under way has ended, each of its commands within its timeout."""
        self._is_stopped.set()
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is not None:
            thread.join()
        with self._lock:
            relays = list(self._relays.items())
            self._relays.clear()
        for key, (relay, _prefix) in relays:
            relay.close()
            self._log(f"relay closed: {self._describe(key)}")
        if relays or self._ruled:
            self._sync_rules(frozenset(), is_due=True)

    def sync(self) -> None:
        """Open the relays the addresses and the listeners ask for, close the
        others, and bring the firewall's rules along."""
        try:
            addresses = list(self._platform.read_relay_addresses())
        except OSError as error:
            self._note("addresses", f"relays: the addresses were not read: {error}")
            addresses = []
        ports = sorted({int(port) for port in self._ports() if port})
        wanted = {
            (address.interface, address.index, address.address, port): (address, port)
            for address in addresses
            for port in ports
        }
        with self._lock:
            stale = [key for key in self._relays if key not in wanted]
            closing = [(key, self._relays.pop(key)) for key in stale]
            missing = [key for key in wanted if key not in self._relays]
        for key, (relay, _prefix) in closing:
            relay.close()
            self._log(f"relay closed: {self._describe(key)}")
        for key in sorted(missing):
            address, port = wanted[key]
            try:
                listener = self._listen(address, port)
            except OSError as error:
                self._note(key, f"relay {self._describe(key)} not opened: {error}")
                continue
            relay = self._relay_factory(listener=listener, port=port)
            with self._lock:
                self._relays[key] = (relay, address.prefix)
            relay.start()
            self._noted.pop(key, None)
            self._log(f"relay open: {self._describe(key)}")
        self._sync_rules(self._rules(), is_due=False)

    def _run(self) -> None:
        """Make the relays match every interval until the stop."""
        while not self._is_stopped.is_set():
            self.sync()
            self._is_stopped.wait(timeout=self._interval_s)

    def _rules(self) -> frozenset:
        """The firewall rule of every relay open now."""
        with self._lock:
            held = list(self._relays.items())
        return frozenset(
            RelayRule(interface=key[0], address=key[2], prefix=prefix, port=key[3])
            for key, (_relay, prefix) in held
        )

    def _sync_rules(self, rules: frozenset, *, is_due: bool) -> None:
        """Hand the platform the rules when they changed, when the last try
        failed or the agent holds rules and the recheck is due, or when told to.

        Args:
            rules: The rules of the relays open now.
            is_due: Whether to hand them over whatever happened before.
        """
        now = self._clock()
        is_recheck = now - self._ruled_at >= self._recheck_s and (
            bool(rules) or not self._is_ruled
        )
        if not is_due and rules == self._ruled and not is_recheck:
            return
        self._ruled, self._ruled_at = rules, now
        try:
            changed = self._platform.sync_relay_rules(rules)
        except (OSError, subprocess.SubprocessError) as error:
            self._is_ruled = False
            self._note("firewall", f"relays: the firewall rules were not set: {error}")
            return
        self._is_ruled = True
        self._noted.pop("firewall", None)
        for line in changed:
            self._log(f"relays: {line}")

    def _note(self, key, line: str) -> None:
        """Write a failure to the log unless it is the one written last for the same thing."""
        if self._noted.get(key) != line:
            self._noted[key] = line
            self._log(line)

    @staticmethod
    def _describe(key: tuple) -> str:
        """One relay as a log line names it."""
        interface, _index, address, port = key
        return f"{address}:{port} on {interface}"
