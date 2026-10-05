"""One TCP connection to a service on this machine, over one stream.

The hub opens ``connect {port, protocol}`` for a client that asked for a
service this machine publishes; this module serves ``tcp``, the protocol an
open that names none asks for, and says what is published on each protocol. The agent dials ``127.0.0.1:<port>``, or the address a
container port is published on when it names one, and nothing else: a port
the machine does not publish at that moment is refused
``port_not_published {port}`` before anything is dialled. Bytes go both
ways, out no faster than the hub's credit allows and in no faster than this
side grants. End of file on the socket closes the stream once what was read
is sent; the hub's close shuts the socket. There is no half-close.

Not pure: dials sockets.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import errno
import ipaddress
import socket
import threading
import urllib.parse

from neutrino_agent.constants import (
    AGENT_CODE_CONNECT_FAILED,
    AGENT_CODE_PORT_NOT_PUBLISHED,
    AGENT_CONNECT_DIAL_TIMEOUT_S,
    AGENT_CONNECT_LOOPBACK,
    AGENT_CONNECT_REFUSED,
    AGENT_CONNECT_TCP,
    AGENT_CONNECT_TIMEOUT,
    AGENT_CONNECT_UNREACHABLE,
    AGENT_WS_CHUNK_BYTES,
    AGENT_WS_STREAM_CREDIT_BYTES,
)
from neutrino_agent.exceptions import StreamClosed, StreamRefused

# The port the file share answers SMB on, on every system.
SMB_PORT = 445
# The port a web url stands for when it names none, by its scheme.
SCHEME_PORTS = {"http": 80, "https": 443}
# The module states under which the hub has configured a module.
CONFIGURED_STATES = ("stopped", "running")
# The modules whose configured instances each answer on their own port.
INSTANCE_MODULES = ("vscode", "cloudcli", "code_server")
# How long the hub's side waits for an item before it looks again.
POLL_S = 0.5


def published_ports(
    modules: dict,
    desired_modules: dict,
    desktop: dict,
    protocol: str = AGENT_CONNECT_TCP,
) -> dict:
    """Every port this machine publishes now on one protocol, each to the
    address it is dialled on.

    Args:
        modules: The modules section of this machine's report, ``{name:
            {state, details, ...}}``.
        desired_modules: The modules section of the hub's last state,
            ``{name: {want, config, ...}}``.
        desktop: The desktop section of this machine's report.
        protocol: ``tcp`` or ``udp``.

    Returns:
        Port to address. On TCP: 445 while the file share reports a share,
        the desktop's direct port while it is shared, the port of the url
        the Gitea module reports, each configured editor or CloudCLI
        instance's port, and each port a container publishes on TCP. On
        UDP: each port a container publishes on UDP, and nothing else. A
        container's port goes to the one address it is published on when
        it names one; every other to loopback. A binding that names no
        protocol is TCP.
    """
    if protocol != AGENT_CONNECT_TCP:
        return _container_ports(modules, protocol)
    ports: dict = {}
    samba = _configured(modules.get("samba"))
    if samba is not None and samba.get("shares"):
        ports[SMB_PORT] = AGENT_CONNECT_LOOPBACK
    if isinstance(desktop, dict) and desktop.get("is_shared"):
        port = _port(desktop.get("port"))
        if port:
            ports[port] = AGENT_CONNECT_LOOPBACK
    gitea = _configured(modules.get("gitea"))
    if gitea is not None:
        port = url_port(str(gitea.get("url", "") or ""))
        if port:
            ports[port] = AGENT_CONNECT_LOOPBACK
    for name in INSTANCE_MODULES:
        entry = desired_modules.get(name)
        if not isinstance(entry, dict) or entry.get("want") not in CONFIGURED_STATES:
            continue
        config = entry.get("config") if isinstance(entry.get("config"), dict) else {}
        for instance in config.get("instances") or []:
            port = _port(instance.get("port") if isinstance(instance, dict) else 0)
            if port:
                ports[port] = AGENT_CONNECT_LOOPBACK
    ports.update(_container_ports(modules, protocol))
    return ports


def url_port(url: str) -> int:
    """The port a url names, 80 or 443 by its scheme when it names none.

    Args:
        url: The url.

    Returns:
        The port; 0 for a url that names neither a port nor a known scheme.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return 0
    return port or SCHEME_PORTS.get(parts.scheme, 0)


def dial_address(address: str) -> str:
    """Where a port published on one address is dialled.

    Args:
        address: The address a container port is published on, empty for
            every address.

    Returns:
        Loopback for every address and for no address; the address itself
        otherwise.
    """
    try:
        if ipaddress.ip_address(address).is_unspecified:
            return AGENT_CONNECT_LOOPBACK
    except ValueError:
        return AGENT_CONNECT_LOOPBACK
    return address


def dial_reason(error: OSError) -> str:
    """The ``connect_failed`` reason one failed dial gives.

    Args:
        error: What the dial raised.

    Returns:
        ``refused`` when nothing answers at the port, ``timeout`` when the
        dial ran out of time, ``unreachable`` for anything else.
    """
    if isinstance(error, ConnectionRefusedError) or error.errno == errno.ECONNREFUSED:
        return AGENT_CONNECT_REFUSED
    if isinstance(error, (socket.timeout, TimeoutError)) or error.errno in (
        errno.ETIMEDOUT,
    ):
        return AGENT_CONNECT_TIMEOUT
    return AGENT_CONNECT_UNREACHABLE


class ConnectStream:
    """Serves one ``connect`` stream: a dial, then bytes both ways."""

    def __init__(self, channel, args: dict, *, published, dial=None):
        """
        Args:
            channel: The stream's :class:`StreamChannel`.
            args: The open's arguments, ``{port, protocol}``, ``protocol``
                ``tcp`` or absent.
            published: Called with nothing for :func:`published_ports` now.
            dial: Called with ``(address, timeout)`` for the connected
                socket; None takes :func:`socket.create_connection`.
        """
        self._channel = channel
        self._port = args.get("port")
        self._protocol = args.get("protocol", AGENT_CONNECT_TCP)
        self._published = published
        self._dial = dial or socket.create_connection
        self._socket: "socket.socket | None" = None
        self._is_done = threading.Event()

    def open(self) -> None:
        """Dial the port when the machine publishes it.

        Raises:
            StreamRefused: ``port_not_published {port}`` for a port the
                machine does not publish now on TCP, or for an open naming
                another protocol; ``connect_failed {reason}`` when the dial
                fails.
        """
        port = self._port
        ports = self._published() if self._protocol == AGENT_CONNECT_TCP else {}
        if isinstance(port, bool) or not isinstance(port, int) or port not in ports:
            raise StreamRefused(AGENT_CODE_PORT_NOT_PUBLISHED, {"port": port})
        try:
            self._socket = self._dial(
                (ports[port], port), timeout=AGENT_CONNECT_DIAL_TIMEOUT_S
            )
        except OSError as error:
            raise StreamRefused(
                AGENT_CODE_CONNECT_FAILED, {"reason": dial_reason(error)}
            )
        self._socket.settimeout(None)

    def run(self) -> dict:
        """Carry bytes both ways until either end ends.

        Returns:
            ``{"code": "", "params": {}}``: the socket's end of file, or the
            hub's close.
        """
        connection = self._socket
        feeder = threading.Thread(
            target=self._feed,
            args=(connection,),
            name=f"agent_connect_input_{self._channel.id}",
            daemon=True,
        )
        try:
            self._channel.offer_credit(AGENT_WS_STREAM_CREDIT_BYTES)
            feeder.start()
            self._pump(connection)
        finally:
            self._is_done.set()
            with contextlib.suppress(OSError):
                connection.close()
            if feeder.is_alive():
                feeder.join(timeout=POLL_S * 4)
        return {"code": "", "params": {}}

    def _pump(self, connection: socket.socket) -> None:
        """Send what the socket reads up the stream, until its end of file."""
        while not self._is_done.is_set():
            try:
                data = connection.recv(AGENT_WS_CHUNK_BYTES)
            except OSError:
                return
            if not data:
                return
            try:
                self._channel.send_bytes(data)
            except StreamClosed:
                return

    def _feed(self, connection: socket.socket) -> None:
        """Write the hub's bytes into the socket, granting credit as they go."""
        while not self._is_done.is_set():
            item = self._channel.recv(timeout=POLL_S)
            if item is None:
                continue
            if item[0] == "close":
                break
            if item[0] != "data":
                continue
            try:
                connection.sendall(item[1])
                self._channel.offer_credit(len(item[1]))
            except OSError:
                break
        self._is_done.set()
        with contextlib.suppress(OSError):
            connection.shutdown(socket.SHUT_RDWR)


def _container_ports(modules: dict, protocol: str) -> dict:
    """The ports the Podman module's containers publish on one protocol."""
    ports: dict = {}
    podman = _configured(modules.get("podman"))
    for container in (podman or {}).get("containers") or []:
        if not isinstance(container, dict):
            continue
        for binding in container.get("host_bindings") or []:
            if not isinstance(binding, dict):
                continue
            if str(binding.get("protocol", "") or AGENT_CONNECT_TCP) != protocol:
                continue
            port = _port(binding.get("port"))
            if port:
                ports[port] = dial_address(str(binding.get("address", "") or ""))
    return ports


def _configured(status) -> "dict | None":
    """A reported module's details while the hub has configured it, else None."""
    if not isinstance(status, dict) or status.get("state") not in CONFIGURED_STATES:
        return None
    details = status.get("details")
    return details if isinstance(details, dict) else {}


def _port(value) -> int:
    """A port number, 0 for anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if 0 < value < 65536 else 0
