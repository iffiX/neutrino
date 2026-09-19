"""Measuring one node: whether its front door answers, and what it costs.

Two numbers per node, and nothing kept between calls — the health store owns
the window.

``connect_ms`` times a TCP connect to the node's own address and port.
``request_ms`` times a whole HTTP request through that node, over the SOCKS
inbound xray renders one account per node on: the account name is the node's
outbound tag, and one routing rule per account sends it out that node.

Every direct connection leaves under xray's own egress mark. Without it, a box
proxying its own traffic diverts the probe into its own TPROXY socket: the
handshake completes locally in no time at all, so every node reads alive at
0 ms whatever the node is doing. The loopback hop to the probe inbound takes no
mark: the router's output chain returns on the reserved address set, and
127.0.0.0/8 is in it.

A node's name is resolved at the direct resolver, never at the machine's own:
on a box whose names resolve through the proxy, that resolver is the proxy.
The lookup finishes before the clock starts.

A probed request does not verify TLS. A fault in this box's CA store would
otherwise read as every exit dying at once while the direct reference stayed
green.

The reference is fetched directly rather than through xray. One that rode xray
could not tell an uplink that is down from an xray that is down, and it has to
answer while xray is restarting.
"""

import ipaddress
import socket
import ssl
import struct
import time
import urllib.parse
from dataclasses import dataclass

from neutrino_hub.modules.xray.constants import (
    XRAY_EGRESS_MARK,
    XRAY_PROBE_LISTEN,
    XRAY_PROBE_PASSWORD,
    XRAY_PROBE_PORT,
    XRAY_PROBE_TIMEOUT_S,
)
from neutrino_hub.modules.xray.node_config import XrayNodeConfig

# One plain query for A records, answered by the direct resolver.
RESOLVE_TIMEOUT_S = 3.0
DNS_TYPE_A = 1
DNS_CLASS_IN = 1
DNS_FLAG_RECURSION_DESIRED = 0x0100
DNS_HEADER_LENGTH = 12
DNS_ANSWER_LIMIT_BYTES = 512

# The SOCKS5 wire, as the probe inbound speaks it.
SOCKS_VERSION = 5
SOCKS_AUTH_PASSWORD = 2
SOCKS_AUTH_VERSION = 1
SOCKS_AUTH_GRANTED = 0
SOCKS_COMMAND_CONNECT = 1
SOCKS_ADDRESS_IPV4 = 1
SOCKS_ADDRESS_DOMAIN = 3
SOCKS_ADDRESS_IPV6 = 4
SOCKS_REPLY_GRANTED = 0

# What a probed request sends and how much of the answer it reads. Only the
# status line is read; the body is never looked at.
PROBE_USER_AGENT = "neutrino-hub"
STATUS_LINE_LIMIT_BYTES = 512
STATUS_OK_FLOOR = 200
STATUS_OK_CEILING = 400


def resolve_direct(
    name: str, *, server: str, port: int = 53, timeout_s: float = RESOLVE_TIMEOUT_S
) -> "str | None":
    """Ask one resolver for a name's IPv4 address, past the proxy.

    Args:
        name: The hostname.
        server: The resolver's address.
        port: Its port.
        timeout_s: How long to wait for the answer.

    Returns:
        The first A record in the answer, or None when there is none.

    Raises:
        OSError: When the resolver does not answer in time.
    """
    query_id = int(time.monotonic_ns() & 0xFFFF)
    question = b"".join(
        bytes([len(label)]) + label.encode("idna")
        for label in name.strip(".").split(".")
    )
    query = (
        struct.pack("!HHHHHH", query_id, DNS_FLAG_RECURSION_DESIRED, 1, 0, 0, 0)
        + question
        + b"\x00"
        + struct.pack("!HH", DNS_TYPE_A, DNS_CLASS_IN)
    )
    connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _mark_as_egress(connection)
        connection.settimeout(timeout_s)
        connection.sendto(query, (server, port))
        while True:
            answer, _ = connection.recvfrom(DNS_ANSWER_LIMIT_BYTES)
            if answer[:2] == query[:2]:
                break
    finally:
        connection.close()
    return _first_a_record(answer)


@dataclass
class XrayNodeMeasurement:
    """What one probe of one node measured.

    Attributes:
        tag: The node's outbound tag.
        connect_ms: The TCP connect to the node's own address and port, in
            milliseconds; None when it did not answer.
        request_ms: A whole request through the node, in milliseconds; None
            when it failed.
        is_xray_reachable: Whether the probe inbound on loopback accepted the
            connection. False means nothing was measured about the node.
    """

    tag: str
    connect_ms: int | None
    request_ms: int | None
    is_xray_reachable: bool

    @property
    def is_success(self) -> bool:
        """Whether the request through the node completed."""
        return self.request_ms is not None


class XrayNodeProbe:
    """Takes one measurement of one node, and the direct reference beside it."""

    def __init__(self, *, timeout_s: float = XRAY_PROBE_TIMEOUT_S, resolver_of=None):
        """
        Args:
            timeout_s: One measurement's patience, start to finish.
            resolver_of: Called with nothing, answers ``(address, port)`` of
                the direct resolver a name is looked up at. None resolves
                nothing: a node named by a hostname then reads unreachable,
                and one at a literal address is probed as is.
        """
        self._timeout_s = timeout_s
        self._resolver_of = resolver_of

    def probe(self, node: XrayNodeConfig, *, url: str) -> XrayNodeMeasurement:
        """Measure one node's front door and one request through it.

        Args:
            node: The node to measure.
            url: The URL fetched through the node.

        Returns:
            The measurement. A refused connection, a timeout, a name that does
            not resolve and a status the server refused all read as a failed
            measurement rather than raising, since every one of them means the
            same thing to the operator.
        """
        connect_ms = self._connect_ms(node)
        request_ms, is_xray_reachable = self._request_ms(node.tag, url)
        return XrayNodeMeasurement(
            tag=node.tag,
            connect_ms=connect_ms,
            request_ms=request_ms,
            is_xray_reachable=is_xray_reachable,
        )

    def probe_reference(self, url: str) -> "int | None":
        """Fetch one URL straight out the uplink, past xray.

        Args:
            url: The reference URL.

        Returns:
            How long the fetch took in milliseconds, or None when it did not
            answer. None with every node failing is an uplink that is down;
            a number with every node failing is the nodes.
        """
        try:
            host, port, path, is_tls = _split_url(url)
        except ValueError:
            return None
        address = self._resolved(host)
        if address is None:
            return None
        started_at = time.monotonic()
        deadline = started_at + self._timeout_s
        try:
            connection = _direct_connection(address, port, timeout_s=self._timeout_s)
        except OSError:
            return None
        try:
            status = _fetch_status(
                connection,
                host=host,
                port=port,
                path=path,
                is_tls=is_tls,
                deadline=deadline,
            )
        except OSError:
            return None
        finally:
            connection.close()
        if not _is_status_ok(status):
            return None
        return int((time.monotonic() - started_at) * 1000)

    def _connect_ms(self, node: XrayNodeConfig) -> "int | None":
        """Time a TCP connect to the node's own address and port."""
        address = self._resolved(node.address)
        if address is None:
            return None
        started_at = time.monotonic()
        try:
            with _direct_connection(address, node.port, timeout_s=self._timeout_s):
                return int((time.monotonic() - started_at) * 1000)
        except OSError:
            return None

    def _request_ms(self, tag: str, url: str) -> "tuple[int | None, bool]":
        """Time one request through a node, and say whether xray answered."""
        try:
            host, port, path, is_tls = _split_url(url)
        except ValueError:
            return None, True
        try:
            channel = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            return None, False
        try:
            channel.settimeout(self._timeout_s)
            channel.connect((XRAY_PROBE_LISTEN, XRAY_PROBE_PORT))
        except OSError:
            channel.close()
            return None, False
        # The clock starts here: the loopback hop is microseconds and is not
        # the node's.
        started_at = time.monotonic()
        deadline = started_at + self._timeout_s
        try:
            _socks_connect(
                channel, account=tag, host=host, port=port, deadline=deadline
            )
            status = _fetch_status(
                channel,
                host=host,
                port=port,
                path=path,
                is_tls=is_tls,
                deadline=deadline,
            )
        except OSError:
            return None, True
        finally:
            channel.close()
        if not _is_status_ok(status):
            return None, True
        return int((time.monotonic() - started_at) * 1000), True

    def _resolved(self, name: str) -> "str | None":
        """The address to connect to, resolved at the direct resolver."""
        if _is_ip_address(name):
            return name
        if self._resolver_of is None:
            return None
        try:
            server, port = self._resolver_of()
            return resolve_direct(name, server=server, port=int(port))
        except (OSError, ValueError, TypeError):
            return None


def _split_url(url: str) -> "tuple[str, int, str, bool]":
    """The host, port, path and TLS answer a fetch needs.

    Args:
        url: The URL as ``config/`` carries it.

    Returns:
        Host, port, the path with its query, and whether it is TLS.

    Raises:
        ValueError: If the URL names no host.
    """
    parsed = urllib.parse.urlsplit(url)
    is_tls = parsed.scheme == "https"
    host = parsed.hostname or ""
    if not host:
        raise ValueError(f"probe url names no host: {url!r}")
    port = parsed.port or (443 if is_tls else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return host, port, path, is_tls


def _socks_connect(
    connection, *, account: str, host: str, port: int, deadline: float
) -> None:
    """Ask the probe inbound for a connection out one node's outbound.

    Args:
        connection: The socket already connected to the probe inbound.
        account: The SOCKS account name, which is the node's outbound tag.
        host: The host the node is to reach, sent as a domain so the exit
            resolves it the way a real connection through it would.
        port: Its port.
        deadline: When this measurement runs out of time.

    Raises:
        ConnectionError: If the inbound refuses the account or the connection.
        OSError: If the exchange runs out of time.
    """
    _send(connection, bytes([SOCKS_VERSION, 1, SOCKS_AUTH_PASSWORD]), deadline=deadline)
    greeting = _receive(connection, 2, deadline=deadline)
    if greeting != bytes([SOCKS_VERSION, SOCKS_AUTH_PASSWORD]):
        raise ConnectionError("the probe inbound did not offer password authentication")
    name = account.encode("utf-8")
    secret = XRAY_PROBE_PASSWORD.encode("utf-8")
    _send(
        connection,
        bytes([SOCKS_AUTH_VERSION, len(name)]) + name + bytes([len(secret)]) + secret,
        deadline=deadline,
    )
    answer = _receive(connection, 2, deadline=deadline)
    if answer != bytes([SOCKS_AUTH_VERSION, SOCKS_AUTH_GRANTED]):
        raise ConnectionError(f"the probe inbound refused the account {account!r}")
    target = _host_bytes(host)
    _send(
        connection,
        bytes(
            [SOCKS_VERSION, SOCKS_COMMAND_CONNECT, 0, SOCKS_ADDRESS_DOMAIN, len(target)]
        )
        + target
        + struct.pack("!H", port),
        deadline=deadline,
    )
    reply = _receive(connection, 4, deadline=deadline)
    if reply[0] != SOCKS_VERSION or reply[1] != SOCKS_REPLY_GRANTED:
        raise ConnectionError(f"the node refused a connection to {host}:{port}")
    _receive(connection, _bound_address_length(reply[3]) + 2, deadline=deadline)


def _bound_address_length(kind: int) -> int:
    """How many bytes of bound address follow a SOCKS5 reply header.

    Args:
        kind: The reply's address type.

    Returns:
        The byte count.

    Raises:
        ConnectionError: If the address type is not one of the three.
    """
    if kind == SOCKS_ADDRESS_IPV4:
        return 4
    if kind == SOCKS_ADDRESS_IPV6:
        return 16
    if kind == SOCKS_ADDRESS_DOMAIN:
        return 1
    raise ConnectionError(f"the probe inbound answered with address type {kind}")


def _fetch_status(
    connection, *, host: str, port: int, path: str, is_tls: bool, deadline: float
) -> int:
    """Send one GET over an open connection and read the status back.

    Args:
        connection: The connected socket, plain.
        host: The host header's value.
        port: The port, named in the host header when it is not the default.
        path: The path with its query.
        is_tls: Whether to wrap the connection in TLS first.
        deadline: When this measurement runs out of time.

    Returns:
        The status code.

    Raises:
        ConnectionError: If the answer carries no status line.
        OSError: If the exchange runs out of time.
    """
    stream = _tls_wrapped(connection, host) if is_tls else connection
    authority = host if port in (80, 443) else f"{host}:{port}"
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {authority}\r\n"
        f"User-Agent: {PROBE_USER_AGENT}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    _send(stream, request, deadline=deadline)
    return _status_code(_status_line(stream, deadline=deadline))


def _tls_wrapped(connection, host: str):
    """Wrap a connection in TLS without verifying anything.

    Args:
        connection: The connected socket.
        host: The name presented in the handshake.

    Returns:
        The wrapped socket.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context.wrap_socket(connection, server_hostname=host)


def _status_line(connection, *, deadline: float) -> bytes:
    """Read the first line of an HTTP answer.

    Args:
        connection: The connected socket.
        deadline: When this measurement runs out of time.

    Returns:
        The line, without its ending.

    Raises:
        ConnectionError: If the answer ends before a line does.
        OSError: If the read runs out of time.
    """
    line = b""
    while b"\n" not in line and len(line) < STATUS_LINE_LIMIT_BYTES:
        connection.settimeout(_remaining(deadline))
        piece = connection.recv(STATUS_LINE_LIMIT_BYTES)
        if not piece:
            break
        line += piece
    if b"\n" not in line:
        raise ConnectionError("the answer carried no status line")
    return line.split(b"\n", 1)[0].strip()


def _status_code(line: bytes) -> int:
    """The status code of an HTTP status line.

    Args:
        line: The line as it was read.

    Returns:
        The code.

    Raises:
        ConnectionError: If the line is not an HTTP status line.
    """
    fields = line.split()
    if len(fields) < 2 or not fields[0].startswith(b"HTTP/"):
        raise ConnectionError("the answer did not start with an HTTP status")
    try:
        return int(fields[1])
    except ValueError as error:
        raise ConnectionError("the answer carried no status code") from error


def _is_status_ok(status: int) -> bool:
    """Whether a status counts the measurement as a success."""
    return STATUS_OK_FLOOR <= status < STATUS_OK_CEILING


def _send(connection, payload: bytes, *, deadline: float) -> None:
    """Write a whole payload, with what is left of the deadline."""
    connection.settimeout(_remaining(deadline))
    connection.sendall(payload)


def _receive(connection, count: int, *, deadline: float) -> bytes:
    """Read exactly so many bytes, with what is left of the deadline.

    Args:
        connection: The connected socket.
        count: How many bytes to read.
        deadline: When this measurement runs out of time.

    Returns:
        The bytes.

    Raises:
        ConnectionError: If the other end closed first.
        OSError: If the read runs out of time.
    """
    buffer = b""
    while len(buffer) < count:
        connection.settimeout(_remaining(deadline))
        piece = connection.recv(count - len(buffer))
        if not piece:
            raise ConnectionError("the probe channel closed early")
        buffer += piece
    return buffer


def _remaining(deadline: float) -> float:
    """What is left of one measurement's patience.

    Args:
        deadline: When it runs out.

    Returns:
        The seconds left.

    Raises:
        TimeoutError: If the deadline has passed.
    """
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("the probe ran out of time")
    return left


def _host_bytes(host: str) -> bytes:
    """A host as the SOCKS request carries it."""
    if host.isascii():
        return host.encode("ascii")
    return host.encode("idna")


def _first_a_record(message: bytes) -> "str | None":
    """The first A record in a DNS answer.

    Args:
        message: The whole answer.

    Returns:
        Its address, or None when the answer holds no A record.
    """
    if len(message) < DNS_HEADER_LENGTH:
        return None
    _, _, question_count, answer_count, _, _ = struct.unpack(
        "!HHHHHH", message[:DNS_HEADER_LENGTH]
    )
    offset = DNS_HEADER_LENGTH
    for _ in range(question_count):
        offset = _skip_name(message, offset) + 4
    for _ in range(answer_count):
        offset = _skip_name(message, offset)
        if offset + 10 > len(message):
            return None
        record_type, _, _, length = struct.unpack(
            "!HHIH", message[offset : offset + 10]
        )
        offset += 10
        if record_type == DNS_TYPE_A and length == 4:
            return socket.inet_ntoa(message[offset : offset + 4])
        offset += length
    return None


def _skip_name(message: bytes, offset: int) -> int:
    """Where the name at an offset ends, compression pointers included.

    Args:
        message: The whole answer.
        offset: Where the name starts.

    Returns:
        The offset of what follows the name.
    """
    while offset < len(message):
        length = message[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            return offset + 2
        offset += length + 1
    return offset


def _is_ip_address(address: str) -> bool:
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return False
    return True


def _direct_connection(address: str, port: int, *, timeout_s: float):
    """Open a TCP connection that the proxy will not divert.

    Args:
        address: The address, resolved.
        port: Its port.
        timeout_s: How long to wait for the connect.

    Returns:
        The connected socket, for use as a context manager.

    Raises:
        OSError: If nothing answers in time.
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    connection = socket.socket(family, socket.SOCK_STREAM)
    try:
        _mark_as_egress(connection)
        connection.settimeout(timeout_s)
        connection.connect((address, port))
    except OSError:
        connection.close()
        raise
    return connection


def _mark_as_egress(connection: socket.socket) -> None:
    """Stamp the socket so the router's output chain lets it out.

    Best effort: the mark needs CAP_NET_ADMIN, which the panel has and a
    developer running the module by hand may not. Without it the probe still
    measures something — just the local proxy, when one is in the path — and
    that is better than refusing to probe at all.

    Args:
        connection: The socket, before it is connected.
    """
    try:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, XRAY_EGRESS_MARK)
    except (OSError, AttributeError):
        return
