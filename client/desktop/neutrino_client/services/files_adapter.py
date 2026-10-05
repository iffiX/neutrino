"""The files adapter on Windows, the resident's half: addresses and the SOCKS endpoint.

Every machine that provides a ``file`` entry takes one address on the
adapter's network, from the second up, kept per hub and machine in the
store, so a drive letter keeps naming the same machine. The SOCKS endpoint
listens on the loopback behind a user name and password made at each start;
it accepts a connection to ``<address>:445`` of a machine the table knows and
hands it to a connector naming a ``file`` entry of that machine, and refuses
anything else. The files daemon, a service running as SYSTEM, runs tun2socks
on the adapter towards that endpoint when the resident asks it ``up``.

A connector is ``connector(hub_id, entry_id)``, which opens one ``connect``
stream to the entry and returns it with ``recv(size)`` (empty at its end),
``sendall(data)`` and ``close()``; a ``close`` from another thread ends a
``recv`` that waits. It raises when the hub refuses or cannot be reached.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import hmac
import ipaddress
import secrets
import socket
import threading

from neutrino_client.constants import (
    CLIENT_FILES_ADAPTER_ADDRESS,
    CLIENT_FILES_NETWORK,
    CLIENT_FILES_PROBE_ADDRESS,
    CLIENT_FILES_RELAY_CHUNK_BYTES,
    CLIENT_FILES_SERVICE_WINDOWS,
    CLIENT_FILES_SHARE_PORT,
    CLIENT_FILES_SOCKS_HANDSHAKE_TIMEOUT_S,
)
from neutrino_client.control.easytier_socket import ask_easytier_daemon
from neutrino_client.exceptions import PlatformUnsupportedError, ShareAttachError
from neutrino_client.services.base import is_unhealthy

FILES_ENDPOINT_HOST = "127.0.0.1"
FILES_ENDPOINT_BACKLOG = 64
FILES_REFUSAL_CODE = "files_adapter_unavailable"
FILES_IN_USE_CODE = "files_adapter_in_use"
# The SOCKS5 words the endpoint speaks (RFC 1928, RFC 1929).
SOCKS_VERSION = 5
SOCKS_AUTH_VERSION = 1
SOCKS_METHOD_PASSWORD = 2
SOCKS_METHOD_NONE_ACCEPTABLE = 0xFF
SOCKS_AUTH_SUCCEEDED = 0
SOCKS_AUTH_FAILED = 1
SOCKS_COMMAND_CONNECT = 1
SOCKS_ADDRESS_IPV4 = 1
SOCKS_REPLY_SUCCEEDED = 0
SOCKS_REPLY_FAILURE = 1
SOCKS_REPLY_NOT_ALLOWED = 2
SOCKS_REPLY_HOST_UNREACHABLE = 4
SOCKS_REPLY_REFUSED = 5
SOCKS_REPLY_COMMAND_UNSUPPORTED = 7
SOCKS_REPLY_ADDRESS_UNSUPPORTED = 8
# The bound address a reply names: none worth telling.
SOCKS_REPLY_BOUND = b"\x01\x00\x00\x00\x00\x00\x00"
# What the endpoint's user name and password are made of.
FILES_USER_BYTES = 8
FILES_PASSWORD_BYTES = 32


def files_machine(entry: dict) -> str:
    """The machine a ``file`` entry's share is on, as the address table keys it.

    Args:
        entry: The entry, as the merged service list carries it.

    Returns:
        Its ``device_id``; else, for an entry a managed machine provides,
        the ``device_name`` the hub gives it, since the payload's host
        follows the way the hub was reached; else the payload's host, as
        for a declared record.
    """
    device_id = entry.get("device_id")
    if isinstance(device_id, str) and device_id:
        return device_id
    device_name = entry.get("device_name")
    if entry.get("source") != "declared" and isinstance(device_name, str):
        if device_name:
            return device_name
    payload = entry.get("payload") or {}
    return str(payload.get("host", "")) if isinstance(payload, dict) else ""


def files_addresses() -> list:
    """Every address a machine may take on the adapter's network, in order.

    Returns:
        The addresses from the second of the network up, the daemon's probe
        address left out, as text.
    """
    network = ipaddress.ip_network(CLIENT_FILES_NETWORK)
    return [
        str(address)
        for address in network.hosts()
        if str(address)
        not in (CLIENT_FILES_ADAPTER_ADDRESS, CLIENT_FILES_PROBE_ADDRESS)
    ]


def _unavailable(detail: str) -> ShareAttachError:
    """The one refusal a mount through the adapter meets."""
    return ShareAttachError(FILES_REFUSAL_CODE, detail=detail)


def _no_entries() -> list:
    """No hub publishing anything."""
    return []


def _none_held() -> set:
    """No mount naming any address."""
    return set()


def _received(connection, size: int) -> bytes:
    """Exactly ``size`` bytes from a socket.

    Raises:
        ConnectionError: When the peer ends first.
    """
    data = b""
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("the SOCKS client ended early")
        data += chunk
    return data


def _reply(client, code: int) -> None:
    """Send one SOCKS reply naming no bound address."""
    client.sendall(bytes((SOCKS_VERSION, code, 0)) + SOCKS_REPLY_BOUND)


def _close_socket(connection) -> None:
    """Shut a socket both ways and close it. Best-effort."""
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass


def _relay(client, far) -> None:
    """Carry bytes both ways until either side ends, then close both."""
    closed = threading.Event()
    lock = threading.Lock()

    def close_both() -> None:
        with lock:
            if closed.is_set():
                return
            closed.set()
        _close_socket(client)
        try:
            far.close()
        except Exception:  # noqa: BLE001 - the far end is closing anyway
            pass

    def outward() -> None:
        try:
            while True:
                data = client.recv(CLIENT_FILES_RELAY_CHUNK_BYTES)
                if not data:
                    return
                far.sendall(data)
        except Exception:  # noqa: BLE001 - either side failing ends the relay
            return
        finally:
            close_both()

    sender = threading.Thread(target=outward, name="files_outward", daemon=True)
    sender.start()
    try:
        while True:
            data = far.recv(CLIENT_FILES_RELAY_CHUNK_BYTES)
            if not data:
                break
            client.sendall(data)
    except Exception:  # noqa: BLE001 - either side failing ends the relay
        pass
    finally:
        close_both()
    sender.join()


class FilesAddressPlan:
    """The adapter address each machine takes, kept per hub and machine in the store."""

    def __init__(self, *, store, held_of=None):
        """
        Args:
            store: The :class:`~neutrino_client.services.store.ClientServiceStore`.
            held_of: Returns the addresses a mount record names now, which
                are never given to another machine; None holds none.
        """
        self._store = store
        self._held_of = held_of if held_of is not None else _none_held
        self._lock = threading.Lock()

    def address_for(self, hub_id: str, machine: str) -> str:
        """The address a machine takes, given one when it has none.

        A machine with no address takes the lowest free one; with none free,
        the lowest one no mount names is taken from the machine that held it.

        Args:
            hub_id: The hub the machine is reached through.
            machine: The machine, as :func:`files_machine` names it.

        Returns:
            The address.

        Raises:
            ShareAttachError: ``files_adapter_unavailable`` when every
                address is named by a mount.
        """
        with self._lock:
            table = self._store.files_addresses()
            for address, record in table.items():
                if record == {"hub_id": hub_id, "machine": machine}:
                    return address
            usable = files_addresses()
            free = [address for address in usable if address not in table]
            if not free:
                held = set(self._held_of())
                free = [address for address in usable if address not in held]
            if not free:
                raise _unavailable("addresses_exhausted")
            self._store.set_files_address(free[0], hub_id, machine)
            return free[0]

    def target_of(self, address: str) -> "tuple[str, str] | None":
        """The machine an address names.

        Args:
            address: An address on the adapter's network.

        Returns:
            ``(hub_id, machine)``, or None when no machine takes it.
        """
        record = self._store.files_addresses().get(address)
        if record is None:
            return None
        return record["hub_id"], record["machine"]

    def forget_hub(self, hub_id: str) -> None:
        """Drop the addresses of a hub's machines that no mount names.

        Args:
            hub_id: The hub left.
        """
        with self._lock:
            held = set(self._held_of())
            gone = [
                address
                for address, record in self._store.files_addresses().items()
                if record["hub_id"] == hub_id and address not in held
            ]
            self._store.remove_files_addresses(gone)


class FilesSocksEndpoint:
    """The resident's SOCKS5 listener tun2socks hands the adapter's connections to."""

    def __init__(self, *, plan, connector, entries_of=None, log=print):
        """
        Args:
            plan: The :class:`FilesAddressPlan` the targets are read from.
            connector: ``connector(hub_id, entry_id)`` opens one ``connect``
                stream to a ``file`` entry, as this module's docstring says.
            entries_of: Returns the merged service list, each entry stamped
                with ``hub_id``; None gives no entry.
            log: Callable used for progress messages; it never sees the
                password.
        """
        self._plan = plan
        self._connector = connector
        self._entries_of = entries_of if entries_of is not None else _no_entries
        self._log = log
        self._lock = threading.Lock()
        self._listener: "socket.socket | None" = None
        self._port = 0
        self._user = ""
        self._password = ""
        self._open: set = set()

    @property
    def port(self) -> int:
        """The loopback port the endpoint listens on, 0 while it does not."""
        return self._port

    @property
    def user(self) -> str:
        """The user name made at this start."""
        return self._user

    @property
    def password(self) -> str:
        """The password made at this start."""
        return self._password

    @property
    def is_running(self) -> bool:
        """Whether the endpoint listens."""
        return self._listener is not None

    def start(self) -> None:
        """Listen on a free loopback port behind a fresh user name and password.

        Does nothing while it already listens.

        Raises:
            OSError: When the loopback refuses a listener.
        """
        with self._lock:
            if self._listener is not None:
                return
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.bind((FILES_ENDPOINT_HOST, 0))
                listener.listen(FILES_ENDPOINT_BACKLOG)
            except OSError:
                listener.close()
                raise
            self._listener = listener
            self._port = listener.getsockname()[1]
            self._user = secrets.token_hex(FILES_USER_BYTES)
            self._password = secrets.token_urlsafe(FILES_PASSWORD_BYTES)
        threading.Thread(
            target=self._accept_forever,
            args=(listener,),
            name="files_socks",
            daemon=True,
        ).start()
        self._log(f"files endpoint listens on {FILES_ENDPOINT_HOST}:{self._port}")

    def stop(self) -> None:
        """Stop listening and end every connection it carries. Idempotent."""
        with self._lock:
            listener = self._listener
            self._listener = None
            self._port = 0
            self._user = ""
            self._password = ""
            carried = list(self._open)
        if listener is None:
            return
        _close_socket(listener)
        for connection in carried:
            _close_socket(connection)
        self._log("files endpoint stopped")

    def serve(self, client) -> None:
        """Answer one SOCKS client, then carry its bytes until either side ends.

        Args:
            client: The accepted socket; it is closed before this returns.
        """
        with self._lock:
            self._open.add(client)
        try:
            far = self._handshake(client)
            if far is not None:
                _relay(client, far)
        except (OSError, ValueError) as error:
            self._log(f"files endpoint: {error}")
        finally:
            with self._lock:
                self._open.discard(client)
            _close_socket(client)

    def _accept_forever(self, listener) -> None:
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            threading.Thread(
                target=self.serve, args=(client,), name="files_relay", daemon=True
            ).start()

    def _handshake(self, client):
        """Greet, check the login, read the target and open the far end.

        Returns:
            The far end, or None when the client was refused.
        """
        client.settimeout(CLIENT_FILES_SOCKS_HANDSHAKE_TIMEOUT_S)
        version, count = _received(client, 2)
        if version != SOCKS_VERSION:
            return None
        methods = _received(client, count)
        if SOCKS_METHOD_PASSWORD not in methods:
            client.sendall(bytes((SOCKS_VERSION, SOCKS_METHOD_NONE_ACCEPTABLE)))
            return None
        client.sendall(bytes((SOCKS_VERSION, SOCKS_METHOD_PASSWORD)))
        auth_version, user_size = _received(client, 2)
        user = _received(client, user_size)
        (password_size,) = _received(client, 1)
        password = _received(client, password_size)
        is_known = (
            auth_version == SOCKS_AUTH_VERSION
            and bool(self._user)
            and hmac.compare_digest(user, self._user.encode("ascii"))
            and hmac.compare_digest(password, self._password.encode("ascii"))
        )
        if not is_known:
            self._log("files endpoint: a client gave the wrong login")
            client.sendall(bytes((SOCKS_AUTH_VERSION, SOCKS_AUTH_FAILED)))
            return None
        client.sendall(bytes((SOCKS_AUTH_VERSION, SOCKS_AUTH_SUCCEEDED)))
        _, command, _, address_type = _received(client, 4)
        if command != SOCKS_COMMAND_CONNECT:
            _reply(client, SOCKS_REPLY_COMMAND_UNSUPPORTED)
            return None
        if address_type != SOCKS_ADDRESS_IPV4:
            _reply(client, SOCKS_REPLY_ADDRESS_UNSUPPORTED)
            return None
        address = socket.inet_ntoa(_received(client, 4))
        port = int.from_bytes(_received(client, 2), "big")
        target = self._plan.target_of(address)
        if port != CLIENT_FILES_SHARE_PORT or target is None:
            if address != CLIENT_FILES_PROBE_ADDRESS:
                self._log(f"files endpoint refused {address}:{port}")
            _reply(client, SOCKS_REPLY_NOT_ALLOWED)
            return None
        hub_id, machine = target
        entry_id = self._entry_of(hub_id, machine)
        if not entry_id:
            self._log(f"files endpoint: {hub_id} publishes no share on {machine}")
            _reply(client, SOCKS_REPLY_HOST_UNREACHABLE)
            return None
        try:
            far = self._connector(hub_id, entry_id)
        except Exception as error:  # noqa: BLE001 - any refusal is one reply
            self._log(
                f"files endpoint: {hub_id} refused {entry_id}: "
                f"{getattr(error, 'code', '') or type(error).__name__}"
            )
            _reply(client, SOCKS_REPLY_REFUSED)
            return None
        try:
            _reply(client, SOCKS_REPLY_SUCCEEDED)
            client.settimeout(None)
        except OSError:
            far.close()
            raise
        return far

    def _entry_of(self, hub_id: str, machine: str) -> str:
        """The id of a ``file`` entry the machine provides, healthy ones first."""
        found = sorted(
            (is_unhealthy(entry), str(entry.get("id", "")))
            for entry in self._entries_of()
            if entry.get("type") == "file"
            and entry.get("hub_id") == hub_id
            and files_machine(entry) == machine
        )
        return found[0][1] if found else ""


class FilesAdapter:
    """The resident's hold on the files daemon: up before a mount, down after the last."""

    def __init__(self, *, platform, plan, endpoint, ask=None, log=print):
        """
        Args:
            platform: The machine's platform, which names the daemon's pipe.
            plan: The :class:`FilesAddressPlan`.
            endpoint: The :class:`FilesSocksEndpoint`.
            ask: ``ask(address, request)`` sends one request to the daemon
                and returns its answer; None is the daemons' own pipe client.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._plan = plan
        self._endpoint = endpoint
        self._ask = ask if ask is not None else ask_easytier_daemon
        self._log = log
        self._lock = threading.Lock()
        self._is_asked_up = False

    def host(self, hub_id: str, machine: str) -> str:
        """The address to mount a machine's share at, the adapter brought up for it.

        Args:
            hub_id: The hub the machine is reached through.
            machine: The machine, as :func:`files_machine` names it.

        Returns:
            The machine's address on the adapter.

        Raises:
            ShareAttachError: ``files_adapter_unavailable`` with what failed
                when the service is missing, stopped or refuses, or every
                address is taken.
        """
        address = self._plan.address_for(hub_id, machine)
        with self._lock:
            self._bring_up()
        return address

    def down(self) -> None:
        """Ask the daemon down when it still serves this resident. Best-effort."""
        with self._lock:
            if not self._is_asked_up:
                return
            self._is_asked_up = False
            try:
                pipe = self._platform.files_daemon_address()
                status = self._ask(pipe, {"verb": "status"})
                if status.get("port") != self._endpoint.port:
                    return
                self._ask(pipe, {"verb": "down"})
            except (OSError, ValueError, PlatformUnsupportedError) as error:
                self._log(f"files adapter: down was not heard: {error}")
                return
            self._log("files adapter down")

    def stop(self) -> None:
        """Take the adapter down and stop the endpoint, for a quit."""
        self.down()
        self._endpoint.stop()

    def _bring_up(self) -> None:
        """Start the endpoint and ask the daemon up for it, under the lock."""
        try:
            self._endpoint.start()
        except OSError as error:
            raise _unavailable(f"the endpoint cannot listen: {error}")
        try:
            pipe = self._platform.files_daemon_address()
        except PlatformUnsupportedError:
            raise _unavailable("unsupported_platform")
        request = {
            "verb": "up",
            "port": self._endpoint.port,
            "user": self._endpoint.user,
            "password": self._endpoint.password,
        }
        try:
            answer = self._ask(pipe, request)
        except (OSError, ValueError) as error:
            self._log(f"files adapter: the service does not answer: {error}")
            raise _unavailable(f"{CLIENT_FILES_SERVICE_WINDOWS} does not answer")
        if answer.get("code") == FILES_IN_USE_CODE:
            self._log("files adapter: in use by another account on this machine")
            raise ShareAttachError("files_adapter_in_use")
        if answer.get("code"):
            params = answer.get("params") or {}
            raise _unavailable(str(params.get("detail") or answer.get("code")))
        if answer.get("is_up") is not True:
            raise _unavailable("not_up")
        if not self._is_asked_up:
            self._log(f"files adapter up for port {self._endpoint.port}")
        self._is_asked_up = True
