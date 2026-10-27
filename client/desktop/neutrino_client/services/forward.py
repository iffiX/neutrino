"""The local forwards: a loopback listener per forwarded entry, held by the transport.

Every entry the client forwards, and the hub's own panel, listens on
``127.0.0.1`` at the port the one local port table gives it; the transport
holds the listener, started with ``forward_start``, and carries every
connection it accepts as one ``connect`` stream, or a UDP entry's datagrams
on one stream. The hub alone dials the service. While a hub has no session
the transport's listener accepts nothing new and stays bound.

An app's ``web`` or ``port`` entry, and an ``ssh`` entry, forwards at its
fixed number: the person's own from the table, else the hub's
``local_port``. Another program listening on it, or another entry of the
same protocol holding it, refuses the forward ``port_taken`` and the number
never moves by itself.
A forward of no app, ``ai``, ``rdp``, a ``file`` and the panel, takes the
first free port from ``FORWARD_AUTO_FIRST_PORT`` to ``FORWARD_AUTO_LAST_PORT``
and keeps the pick, picked again when another program holds it. The
listeners are the transport's and end with it; they are held here by
service key, so two hubs publishing the same entry id never collide, and
started again when a transport that ended is back.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import errno
import os
import socket
import threading

from neutrino_client.constants import CLIENT_STREAM_KIND_CONNECT
from neutrino_client.exceptions import GatewayUnreachable, LocalPortTakenError
from neutrino_client.platforms import win32
from neutrino_client.services.base import hub_of_key, service_key
from neutrino_client.services.store import STORE_LOCAL_PORT_AUTO

FORWARD_BIND_HOST = "127.0.0.1"
# A local port's setting when the client picks the number.
FORWARD_PORT_AUTO = STORE_LOCAL_PORT_AUTO
# The protocols a port entry is forwarded on; an entry that names none is TCP.
FORWARD_PROTOCOL_TCP = "tcp"
FORWARD_PROTOCOL_UDP = "udp"
# Where a forward of no app picks its port.
FORWARD_AUTO_FIRST_PORT = 20000
FORWARD_AUTO_LAST_PORT = 23999
FORWARD_PORT_MAX = 65535
# The numbers a person's own setting may name.
FORWARD_FIXED_PORT_MIN = 1024
# The entry id the hub's panel is forwarded under; no published entry has it.
FORWARD_PANEL_ID = ":panel"
FORWARD_KIND_PANEL = "panel"
# The kinds that forward at a fixed number, an app's entries and the ssh
# entries, each ending when its entry leaves the hub's list.
FORWARD_FIXED_PORT_KINDS = ("web", "port", "ssh")
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
    the client forwards already is bound with the reuse option off Windows,
    so the client's own closed connections still lingering on it do not
    count while another program's listener does. On Windows a UDP port is
    not bound: the system's table of UDP endpoints is read instead.

    Args:
        port: The port number.
        is_kept: Whether the client held the port before.
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


def forward_refusal(error: OSError) -> dict:
    """The typed refusal a forward that cannot listen answers with.

    Args:
        error: What making the forward raised.

    Returns:
        ``port_taken`` with the port for a number another program or entry
        holds, ``hub_unreachable`` while the transport cannot be asked,
        ``forward_failed`` with the detail otherwise.
    """
    if isinstance(error, LocalPortTakenError):
        return {"code": "port_taken", "params": {"port": error.port}}
    if isinstance(error, GatewayUnreachable):
        return {"code": "hub_unreachable", "params": {"detail": str(error)[:200]}}
    return {"code": "forward_failed", "params": {"detail": str(error)[:200]}}


def is_fixed_port_kind(kind: str) -> bool:
    """Whether a forward of this kind listens at its entry's fixed number.

    Args:
        kind: The entry's type, or ``panel``.

    Returns:
        True for ``web``, ``port`` and ``ssh``.
    """
    return kind in FORWARD_FIXED_PORT_KINDS


class ConnectStreamSocket:
    """An open ``connect`` stream with a socket's ``recv``, ``sendall`` and ``close``.

    A ``close`` from another thread ends a ``recv`` that waits.
    """

    def __init__(self, stream):
        """
        Args:
            stream: The open ``connect`` stream.
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
        """Send every byte once the far side accepted the stream.

        Raises:
            GatewayUnreachable: When the stream was refused or has ended.
        """
        self._stream.send(data)

    def close(self) -> None:
        """End the stream from this side. Idempotent."""
        self._stream.close()


def _nobody(*_args) -> None:
    """Nobody listening."""


def _no_binding(_hub_id: str) -> str:
    """No hub joined."""
    return ""


class PortLocalTable:
    """The one table of the loopback ports this client's forwards take.

    It keeps the numbers the person set for app entries, and the picks of
    the forwards of no app, each with its protocol. An app entry with no
    number of the person's forwards at the hub's. A number is held per
    protocol: a TCP entry and a UDP entry may hold the same one.
    """

    def __init__(self, *, store=None, is_free=None):
        """
        Args:
            store: The :class:`~neutrino_client.services.store.ClientServiceStore`
                the table is kept in; None keeps it in memory.
            is_free: ``is_free(port, is_kept, protocol)`` says whether
                nothing listens on the port on any address; None asks the
                system.
        """
        self._store = store
        self._is_free = is_free if is_free is not None else is_port_free
        self._lock = threading.Lock()
        self._memory: dict = {}

    def setting(self, key: str):
        """One entry's own setting.

        Args:
            key: The entry's service key.

        Returns:
            The person's number, ``"auto"`` for a forward of no app that
            picked one, or None while the table holds nothing for it.
        """
        with self._lock:
            record = self._records().get(key)
        return record["setting"] if record else None

    def app_port(self, key: str, hub_port: int) -> int:
        """The number an app's entry or an ``ssh`` entry forwards on.

        Args:
            key: The entry's service key.
            hub_port: The hub's ``local_port`` for it.

        Returns:
            The person's number, else the hub's.
        """
        setting = self.setting(key)
        return setting if isinstance(setting, int) else int(hub_port or 0)

    def is_held(self, port: int, protocol: str, key: str) -> bool:
        """Whether another entry of a protocol holds a number in the table.

        Args:
            port: The number.
            protocol: ``tcp`` or ``udp``.
            key: The entry asking, which holds nothing against itself.

        Returns:
            True when another record of that protocol holds it.
        """
        with self._lock:
            return port in self._held(self._records(), key, protocol)

    def check_own(
        self,
        key: str,
        port: int,
        protocol: str,
        hub_numbers: dict,
        ignored: tuple = (),
    ) -> dict:
        """Judge a number the person sets for one app entry, writing nothing.

        Args:
            key: The entry's service key.
            port: The number.
            protocol: The entry's protocol, ``tcp`` or ``udp``.
            hub_numbers: ``{service key: (hub port, protocol)}`` of the other
                entries, whose hub numbers count as held while they have no
                number of the person's.
            ignored: Keys whose records do not count, the entries changed
                in the same Save.

        Returns:
            Empty when it can be kept; ``local_port_invalid {port}`` for a
            number out of range, ``port_taken {port}`` for one another entry
            of the same protocol holds in the table or as its hub number.
        """
        if isinstance(port, bool) or not isinstance(port, int):
            return {"code": "local_port_invalid", "params": {"port": port}}
        if not FORWARD_FIXED_PORT_MIN <= port <= FORWARD_PORT_MAX:
            return {"code": "local_port_invalid", "params": {"port": port}}
        with self._lock:
            records = self._records()
        held = self._held(
            {
                other: record
                for other, record in records.items()
                if other not in ignored
            },
            key,
            protocol,
        )
        for other, (number, other_protocol) in hub_numbers.items():
            if other == key or other_protocol != protocol:
                continue
            if not isinstance(records.get(other, {}).get("setting"), int):
                held.add(number)
        if port in held:
            return {"code": "port_taken", "params": {"port": port}}
        return {}

    def set_own(self, key: str, port: "int | None", protocol: str) -> None:
        """Keep the person's number for one app entry, or go back to the hub's.

        Args:
            key: The entry's service key.
            port: The number, judged by :meth:`check_own` first; None goes
                back to the hub's.
            protocol: The entry's protocol, ``tcp`` or ``udp``.
        """
        with self._lock:
            if port is None:
                self._forget(key)
            else:
                self._keep(key, port, port, protocol)

    def take_auto(self, key: str, protocol: str = FORWARD_PROTOCOL_TCP) -> int:
        """The port a forward of no app listens on, the pick kept.

        A kept pick another program holds now is picked again.

        Args:
            key: The forward's service key.
            protocol: ``tcp`` or ``udp``.

        Returns:
            The port number.

        Raises:
            OSError: When no port of the range is free.
        """
        with self._lock:
            records = self._records()
            record = records.get(key)
            if record and record["port"] and record.get("protocol") == protocol:
                if self._is_free(record["port"], True, protocol):
                    return record["port"]
            held = self._held(records, key, protocol)
            for port in range(FORWARD_AUTO_FIRST_PORT, FORWARD_AUTO_LAST_PORT + 1):
                if port not in held and self._is_free(port, False, protocol):
                    self._keep(key, FORWARD_PORT_AUTO, port, protocol)
                    return port
        raise OSError("no free loopback port from 20000 to 23999")

    def probe(self, port: int, protocol: str, is_kept: bool) -> bool:
        """Whether a number is free on every address of the machine now.

        Args:
            port: The number.
            protocol: ``tcp`` or ``udp``.
            is_kept: Whether the client held it before.

        Returns:
            True when nothing listens on it.
        """
        return self._is_free(port, is_kept, protocol)

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

    def _forget(self, key: str) -> None:
        """Drop one entry's record; the lock is held."""
        if self._store is None:
            self._memory.pop(key, None)
        else:
            self._store.remove_local_port(key)

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


class ForwardListenerRegistry:
    """Every forward this client runs, by service key, each a listener of the transport's."""

    def __init__(
        self,
        *,
        command=None,
        binding_of=None,
        ports=None,
        log=print,
        on_change=None,
        on_refused=None,
    ):
        """
        Args:
            command: ``command(name, fields)`` sends one command to the
                transport and returns its answer, raising
                :class:`~neutrino_client.exceptions.GatewayUnreachable` when
                it cannot; None has no transport.
            binding_of: ``binding_of(hub_id)`` names the binding the hub's
                session is dialled under, empty for a hub not joined; None
                knows no hub.
            ports: The :class:`PortLocalTable` the forwards take their port
                from; None keeps one in memory.
            log: Callable used for progress messages.
            on_change: Called after a forward starts or stops; None for
                nobody listening.
            on_refused: ``on_refused(hub_id, entry_id, refusal)`` is told
                when a forward ended with a code; None for nobody listening.
        """
        self._command = command
        self._binding_of = binding_of if binding_of is not None else _no_binding
        self.ports = ports if ports is not None else PortLocalTable()
        self._log = log
        self._on_change = on_change if on_change is not None else _nobody
        self._on_refused = on_refused if on_refused is not None else _nobody
        self._lock = threading.Lock()
        # Every forward the transport listens for: key to its record.
        self._forwards: dict = {}

    def ensure(
        self,
        *,
        hub_id: str,
        entry_id: str,
        kind: str,
        own_port: int = 0,
        protocol: str = FORWARD_PROTOCOL_TCP,
    ) -> int:
        """Make one entry's forward when it has none, and say where it listens.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry's id, or ``FORWARD_PANEL_ID`` for the panel.
            kind: The entry's type, or ``panel``.
            own_port: For an app's entry or an ``ssh`` entry, the hub's
                ``local_port``; ignored for any other forward.
            protocol: ``tcp`` for a listener whose every connection is a
                stream, ``udp`` for one UDP socket on one stream.

        Returns:
            The loopback port the forward listens on.

        Raises:
            LocalPortTakenError: When a fixed number is held by another
                program or another entry of the same protocol.
            GatewayUnreachable: When the transport cannot be asked, or the
                hub is not joined.
            OSError: When no port is to be had, or the transport cannot
                listen on it.
        """
        key = service_key(hub_id, entry_id)
        with self._lock:
            held = self._forwards.get(key)
            if held is not None:
                return held["port"]
            port = self._port_for(key, kind, own_port, protocol)
            record = {
                "hub_id": hub_id,
                "entry_id": entry_id,
                "kind": kind,
                "protocol": protocol,
                "port": port,
            }
            self._start(record)
            self._forwards[key] = record
        self._log(
            f"forwarding {FORWARD_BIND_HOST}:{port}/{protocol} to {key} through the hub"
        )
        self._on_change()
        return port

    def port_of(self, hub_id: str, entry_id: str) -> int:
        """Where one entry's forward listens.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry's id.

        Returns:
            The loopback port; 0 when the entry is not forwarded.
        """
        with self._lock:
            record = self._forwards.get(service_key(hub_id, entry_id))
        return record["port"] if record else 0

    def forwards(self) -> dict:
        """Every forward listening now.

        Returns:
            ``{service_key: local_port}``.
        """
        with self._lock:
            return {key: record["port"] for key, record in self._forwards.items()}

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
            record = self._forwards.pop(key, None)
        if record is None:
            return False
        self._stop(record)
        self._log(f"stopped forwarding {FORWARD_BIND_HOST}:{record['port']}")
        self._on_change()
        return True

    def take_end(self, line: dict) -> None:
        """Take the transport's ``forward_end``: that listener stopped.

        Args:
            line: ``{listen, protocol, code, params}``.
        """
        listen = str(line.get("listen", "") or "")
        protocol = str(line.get("protocol", "") or "") or FORWARD_PROTOCOL_TCP
        with self._lock:
            found = [
                (key, record)
                for key, record in self._forwards.items()
                if _listen(record["port"]) == listen and record["protocol"] == protocol
            ]
            for key, _record in found:
                self._forwards.pop(key, None)
        if not found:
            return
        code = str(line.get("code", "") or "")
        params = line.get("params")
        for _key, record in found:
            self._log(f"the forward at {listen}/{protocol} ended: {code or 'no code'}")
            if code:
                self._on_refused(
                    record["hub_id"],
                    record["entry_id"],
                    {
                        "code": code,
                        "params": params if isinstance(params, dict) else {},
                    },
                )
        self._on_change()

    def restart(self) -> None:
        """Start every forward again, as a transport that came back has none.

        A forward that cannot start again ends, told with its refusal.
        """
        with self._lock:
            records = list(self._forwards.items())
        for key, record in records:
            try:
                self._start(record)
            except OSError as error:
                with self._lock:
                    if self._forwards.get(key) is record:
                        self._forwards.pop(key, None)
                self._on_refused(
                    record["hub_id"], record["entry_id"], forward_refusal(error)
                )
        self._on_change()

    def release(self) -> int:
        """End every forward.

        Returns:
            How many forwards were ended.
        """
        return self._end(lambda key, record: True)

    def release_hub(self, hub_id: str) -> int:
        """End every forward of one hub, the panel's among them.

        Args:
            hub_id: The hub whose forwards end.

        Returns:
            How many forwards were ended.
        """
        return self._end(lambda key, record: hub_of_key(key) == hub_id)

    def release_kind(self, kind: str, hub_id: str = "") -> int:
        """End every forward of one kind, of one hub or of all.

        Args:
            kind: The entry type, or ``panel``.
            hub_id: The hub; empty for every hub.

        Returns:
            How many forwards were ended.
        """
        return self._end(
            lambda key, record: record["kind"] == kind
            and (not hub_id or hub_of_key(key) == hub_id)
        )

    def drop_withdrawn(self, *, hub_id: str, entries: list) -> int:
        """End the fixed-number forwards of one hub whose entry its list no longer has.

        Args:
            hub_id: The hub whose list arrived.
            entries: That hub's service list as it stands now.

        Returns:
            How many forwards were ended.
        """
        listed = {service_key(hub_id, str(entry.get("id", ""))) for entry in entries}
        return self._end(
            lambda key, record: hub_of_key(key) == hub_id
            and is_fixed_port_kind(record["kind"])
            and key not in listed
        )

    def _port_for(self, key: str, kind: str, own_port: int, protocol: str) -> int:
        """The number a new forward listens on; the lock is held.

        Raises:
            LocalPortTakenError: When a fixed number is held.
            OSError: When no pick of the range is free.
        """
        if not is_fixed_port_kind(kind):
            return self.ports.take_auto(key, protocol)
        port = self.ports.app_port(key, own_port)
        if not 0 < port <= FORWARD_PORT_MAX:
            raise OSError(f"the hub names no local port for {key}")
        is_live = any(
            record["port"] == port and record["protocol"] == protocol
            for record in self._forwards.values()
        )
        if is_live or self.ports.is_held(port, protocol, key):
            raise LocalPortTakenError(port)
        if not self.ports.probe(port, protocol, True):
            raise LocalPortTakenError(port)
        return port

    def _start(self, record: dict) -> None:
        """Have the transport listen for one forward.

        Raises:
            LocalPortTakenError: When the transport cannot bind the number.
            GatewayUnreachable: When the transport cannot be asked, or the
                hub is not joined.
            OSError: When the transport refuses with any other code.
        """
        if self._command is None:
            raise GatewayUnreachable("the client's transport is not running")
        binding = self._binding_of(record["hub_id"])
        if not binding:
            raise GatewayUnreachable("this person has not joined that hub")
        if record["entry_id"] == FORWARD_PANEL_ID:
            open_record = {"kind": CLIENT_STREAM_KIND_CONNECT, "is_panel": True}
        else:
            open_record = {"kind": CLIENT_STREAM_KIND_CONNECT, "id": record["entry_id"]}
        answer = self._command(
            "forward_start",
            {
                "binding": binding,
                "listen": _listen(record["port"]),
                "protocol": record["protocol"],
                "open": open_record,
            },
        )
        code = str(answer.get("code", "") or "")
        if code == "port_taken":
            raise LocalPortTakenError(record["port"])
        if code:
            raise OSError(f"the transport refused the forward: {code}")

    def _stop(self, record: dict) -> None:
        """Have the transport close one forward's listener; a refusal is logged."""
        if self._command is None:
            return
        try:
            self._command(
                "forward_stop",
                {"listen": _listen(record["port"]), "protocol": record["protocol"]},
            )
        except GatewayUnreachable as error:
            self._log(f"could not stop the forward at {record['port']}: {error}")

    def _end(self, is_ended) -> int:
        """End the forwards ``is_ended(key, record)`` picks."""
        with self._lock:
            ended = {
                key: record
                for key, record in self._forwards.items()
                if is_ended(key, record)
            }
            for key in ended:
                self._forwards.pop(key, None)
        for record in ended.values():
            self._stop(record)
        if ended:
            self._on_change()
        return len(ended)


def _listen(port: int) -> str:
    """The address a forward's listener binds."""
    return f"{FORWARD_BIND_HOST}:{port}"
