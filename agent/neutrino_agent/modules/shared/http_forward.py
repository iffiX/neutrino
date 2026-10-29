"""What every forwarder in front of a module's page shares.

A forwarder is a thread of the agent that listens on one port and judges
each request before the page behind it sees it. This module holds what
does not depend on the page: the one-time token a client opens the page
with, reading one request's head, answering with the forwarder's own
words, relaying a request and its answer, a WebSocket included, and
:class:`InstanceForwarder`, the listener itself, which asks the module's
hooks what each request is allowed and how the page is reached.

A token is ``base64url(expiry || nonce || HMAC-SHA256(secret, expiry ||
nonce))``, checked here against the hub's time with no call to the hub. A
login cookie, which a module's rule trades a token for, is
``base64url(expiry || HMAC-SHA256(key, expiry))`` with a key the module
derives from the instance's secret. A browser's connection stays open across
requests: each request goes through the checks again, a ``Host`` that is
not loopback's or the instance's local name answered 421 and an ``Origin``
that is not the ``Host``'s answered 403, and is passed on unchanged over one
connection to the page kept for that browser's connection, its body cut at
its ``Content-Length``; a WebSocket is passed on unchanged and relayed both
ways until either side closes. A page whose login is a cookie of its own
with a fixed name gets it renamed both ways: the entry's cookie name toward
the browser, the page's own toward the page. Both of a forwarder's connections send at
once, with ``TCP_NODELAY``. Closing a forwarder ends every connection it
serves, both of its sockets.

Not pure: opens sockets.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import binascii
import contextlib
import functools
import hashlib
import hmac
import os
import socket
import socketserver
import threading
import urllib.parse
from dataclasses import dataclass

from neutrino_agent.constants import (
    AGENT_FORWARD_CHUNK_BYTES,
    AGENT_FORWARD_HEAD_LIMIT_BYTES,
    AGENT_FORWARD_IDLE_TIMEOUT_S,
    AGENT_FORWARD_LISTEN_HOST,
    AGENT_FORWARD_READY_POLL_S,
    AGENT_FORWARD_RETRY_S,
    AGENT_FORWARD_TOKEN_EXPIRY_BYTES,
    AGENT_FORWARD_TOKEN_HORIZON_S,
    AGENT_FORWARD_TOKEN_MAC_BYTES,
    AGENT_FORWARD_TOKEN_NONCE_BYTES,
    AGENT_FORWARD_TOKEN_PARAMETER,
    AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
)
from neutrino_agent.modules.shared.hub_clock import hub_time

HEAD_END = b"\r\n\r\n"
# The answers a forwarder writes itself.
STATUS_LINES = {
    200: b"HTTP/1.1 200 OK",
    302: b"HTTP/1.1 302 Found",
    401: b"HTTP/1.1 401 Unauthorized",
    403: b"HTTP/1.1 403 Forbidden",
    411: b"HTTP/1.1 411 Length Required",
    421: b"HTTP/1.1 421 Misdirected Request",
    502: b"HTTP/1.1 502 Bad Gateway",
}
# The names a ``Host`` may carry, its port aside, beside the instance's own
# local name.
HTTP_FORWARD_LOOPBACK_HOSTS = ("127.0.0.1", "[::1]", "localhost")
# A login cookie's value: the expiry eight bytes big-endian, then the
# HMAC-SHA256 over it.
HTTP_FORWARD_COOKIE_EXPIRY_BYTES = 8
HTTP_FORWARD_COOKIE_MAC_BYTES = 32


def mint_token(secret: str, *, expiry: int, nonce: bytes) -> str:
    """One token for an instance, as the hub mints it.

    Args:
        secret: The instance's token secret.
        expiry: When it stops working, in seconds since the epoch.
        nonce: Random bytes, as many as a token carries.

    Returns:
        ``base64url(expiry || nonce || HMAC-SHA256(secret, expiry || nonce))``
        without padding.
    """
    body = int(expiry).to_bytes(AGENT_FORWARD_TOKEN_EXPIRY_BYTES, "big") + bytes(nonce)
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + mac).rstrip(b"=").decode("ascii")


def take_token(token: str, *, secret: str, now: float, spent: dict) -> bool:
    """Whether a token verifies and was never spent; spends it if so.

    The caller holds its own lock around the call.

    Args:
        token: What ``?tkn=`` held.
        secret: The instance's token secret.
        now: Seconds since the epoch.
        spent: Nonce to expiry of every token accepted; an entry past its
            expiry is dropped, and the token's own nonce is added.

    Returns:
        True for a token signed with the secret, whose expiry is ahead and
        no further than the horizon, and whose nonce was not accepted before.
    """
    try:
        raw = unpadded_decode(token)
    except (ValueError, binascii.Error):
        return False
    body_size = AGENT_FORWARD_TOKEN_EXPIRY_BYTES + AGENT_FORWARD_TOKEN_NONCE_BYTES
    if len(raw) != body_size + AGENT_FORWARD_TOKEN_MAC_BYTES:
        return False
    body, mac = raw[:body_size], raw[body_size:]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        return False
    expiry = int.from_bytes(body[:AGENT_FORWARD_TOKEN_EXPIRY_BYTES], "big")
    nonce = body[AGENT_FORWARD_TOKEN_EXPIRY_BYTES:]
    if not now < expiry <= now + AGENT_FORWARD_TOKEN_HORIZON_S:
        return False
    for held, until in list(spent.items()):
        if until <= now:
            del spent[held]
    if nonce in spent:
        return False
    spent[nonce] = expiry
    return True


def unpadded_decode(text: str) -> bytes:
    """base64url without its padding, decoded.

    Raises:
        binascii.Error: When the text is not base64url.
    """
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint_login(key: bytes, expiry: int) -> str:
    """One login cookie's value.

    Args:
        key: The key the module derives from the instance's secret.
        expiry: When it stops working, in seconds since the epoch.

    Returns:
        ``base64url(expiry || HMAC-SHA256(key, expiry))`` without padding.
    """
    body = int(expiry).to_bytes(HTTP_FORWARD_COOKIE_EXPIRY_BYTES, "big")
    mac = hmac.new(key, body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + mac).rstrip(b"=").decode("ascii")


def is_login_valid(login: str, key: bytes, now: float) -> bool:
    """Whether a login cookie is signed with the key and still current.

    Args:
        login: The cookie's value.
        key: The key the module derives from the instance's secret.
        now: Seconds since the epoch.

    Returns:
        True when the signature matches and the expiry is ahead.
    """
    try:
        raw = unpadded_decode(login)
    except (ValueError, binascii.Error):
        return False
    if len(raw) != HTTP_FORWARD_COOKIE_EXPIRY_BYTES + HTTP_FORWARD_COOKIE_MAC_BYTES:
        return False
    body, mac = (
        raw[:HTTP_FORWARD_COOKIE_EXPIRY_BYTES],
        raw[HTTP_FORWARD_COOKIE_EXPIRY_BYTES:],
    )
    expected = hmac.new(key, body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        return False
    return int.from_bytes(body, "big") > now


class ConnectionReader:
    """One connection's bytes read through a buffer: heads, lines and lengths.

    Attributes:
        socket: The connection.
    """

    def __init__(self, connection: socket.socket, buffered: bytes = b""):
        """
        Args:
            connection: The connection.
            buffered: Bytes already read from it.
        """
        self.socket = connection
        self._buffer = bytearray(buffered)

    def read_head(self) -> "bytes | None":
        """The next head, through its blank line.

        Returns:
            The head; None when the connection ended first or the head ran
            past the limit.

        Raises:
            OSError: When the connection fails.
        """
        while True:
            end = self._buffer.find(HEAD_END)
            if end >= 0:
                head = bytes(self._buffer[: end + len(HEAD_END)])
                del self._buffer[: end + len(HEAD_END)]
                return head
            if len(self._buffer) > AGENT_FORWARD_HEAD_LIMIT_BYTES:
                return None
            if not self._fill():
                return None

    def read_line(self) -> bytes:
        """The next line with its ending; empty when the connection ended first.

        Raises:
            OSError: When the connection fails.
        """
        while True:
            end = self._buffer.find(b"\r\n")
            if end >= 0:
                line = bytes(self._buffer[: end + 2])
                del self._buffer[: end + 2]
                return line
            if len(self._buffer) > AGENT_FORWARD_HEAD_LIMIT_BYTES:
                return b""
            if not self._fill():
                return b""

    def copy_exact(self, size: int, target: socket.socket) -> bool:
        """Copy so many bytes to another connection.

        Args:
            size: How many.
            target: Where they go.

        Returns:
            False when this connection ended first.

        Raises:
            OSError: When either connection fails.
        """
        remaining = int(size)
        while remaining > 0:
            if not self._buffer and not self._fill():
                return False
            piece = bytes(self._buffer[:remaining])
            del self._buffer[: len(piece)]
            target.sendall(piece)
            remaining -= len(piece)
        return True

    def copy_to_end(self, target: socket.socket) -> None:
        """Copy every byte to another connection until this one ends.

        Raises:
            OSError: When either connection fails.
        """
        while True:
            if self._buffer:
                target.sendall(bytes(self._buffer))
                self._buffer.clear()
            if not self._fill():
                return

    def take_buffer(self) -> bytes:
        """What was read past the last head or line, handed over and forgotten."""
        held = bytes(self._buffer)
        self._buffer.clear()
        return held

    def _fill(self) -> bool:
        """Read more into the buffer; False once the connection ended."""
        chunk = self.socket.recv(AGENT_FORWARD_CHUNK_BYTES)
        if not chunk:
            return False
        self._buffer += chunk
        return True


def set_no_delay(connection: socket.socket) -> None:
    """Send what the connection is given at once, for a TCP connection.

    Args:
        connection: The connection; a Unix socket takes nothing.
    """
    try:
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        return


def read_head(client: socket.socket) -> tuple:
    """``(head, rest)`` of a request; head None when it ended or ran past the limit.

    Raises:
        OSError: When the connection fails.
    """
    reader = ConnectionReader(client)
    head = reader.read_head()
    if head is None:
        return None, b""
    return head, reader.take_buffer()


def parse_head(head: bytes) -> "tuple | None":
    """The method, the target and the headers of a request's head, None when malformed."""
    lines = head.decode("latin-1").split("\r\n")
    words = lines[0].split(" ")
    if len(words) != 3:
        return None
    headers = []
    for line in lines[1:]:
        if not line:
            continue
        name, separator, value = line.partition(":")
        if not separator:
            return None
        headers.append((name.strip(), value.strip()))
    return words[0], words[1], headers


def parse_status(head: bytes) -> "tuple | None":
    """The version, the status and the headers of an answer's head, None when malformed."""
    lines = head.decode("latin-1").split("\r\n")
    words = lines[0].split(" ", 2)
    if len(words) < 2 or not words[1].isdigit():
        return None
    headers = []
    for line in lines[1:]:
        if not line:
            continue
        name, separator, value = line.partition(":")
        if not separator:
            return None
        headers.append((name.strip(), value.strip()))
    return words[0], int(words[1]), headers


def header(headers: list, name: str) -> str:
    """The first value of one header, empty when the request has none.

    Args:
        headers: ``[(name, value)]`` as :func:`parse_head` gives them.
        name: The header's name in lower case.

    Returns:
        The value.
    """
    for held, value in headers:
        if held.lower() == name:
            return value
    return ""


def header_tokens(headers: list, name: str) -> list:
    """The comma-separated words of every header of one name, in lower case.

    Args:
        headers: ``[(name, value)]``.
        name: The header's name in lower case.

    Returns:
        The words, in order.
    """
    return [
        token.strip().lower()
        for held, value in headers
        if held.lower() == name
        for token in value.split(",")
        if token.strip()
    ]


def cookie_values(headers: list, name: str) -> list:
    """Every value one cookie holds across a request's ``Cookie`` headers.

    Args:
        headers: ``[(name, value)]`` as :func:`parse_head` gives them.
        name: The cookie's name.

    Returns:
        The values, in order.
    """
    values = []
    for held, value in headers:
        if held.lower() != "cookie":
            continue
        for pair in value.split(";"):
            key, _, found = pair.strip().partition("=")
            if key == name:
                values.append(found)
    return values


def renamed_request_cookies(head: bytes, *, kept: str, page: str) -> bytes:
    """A request's head with the browser's cookie renamed to the page's own name.

    Args:
        head: The request's head, through its blank line.
        kept: The name the browser keeps the page's login under.
        page: The page's own fixed name for it.

    Returns:
        The head with every ``kept`` cookie named ``page``, every ``page``
        cookie the browser held dropped, and a ``Cookie`` header left with
        none taken out.
    """
    lines = head[: -len(HEAD_END)].split(b"\r\n")
    kept_lines = [lines[0]]
    for line in lines[1:]:
        name, separator, value = line.partition(b":")
        if separator and name.strip().lower() == b"cookie":
            pairs = []
            for pair in value.decode("latin-1").split(";"):
                key, equals, found = pair.strip().partition("=")
                if not key or key == page:
                    continue
                pairs.append((page if key == kept else key) + equals + found)
            if not pairs:
                continue
            line = b"Cookie: " + "; ".join(pairs).encode("latin-1")
        kept_lines.append(line)
    return b"\r\n".join(kept_lines) + HEAD_END


def renamed_set_cookies(head: bytes, *, page: str, kept: str) -> bytes:
    """An answer's head with the page's own cookie renamed to the name the browser keeps it under.

    Args:
        head: The answer's head, through its blank line.
        page: The page's own fixed name for its login cookie.
        kept: The name the browser keeps it under.

    Returns:
        The head with every ``Set-Cookie`` of ``page`` naming ``kept``;
        every other line as it was.
    """
    lines = head[: -len(HEAD_END)].split(b"\r\n")
    for index, line in enumerate(lines[1:], start=1):
        name, separator, value = line.partition(b":")
        if not separator or name.strip().lower() != b"set-cookie":
            continue
        text = value.decode("latin-1").strip()
        cookie, equals, rest = text.partition("=")
        if equals and cookie.strip() == page:
            lines[index] = b"Set-Cookie: " + (kept + "=" + rest).encode("latin-1")
    return b"\r\n".join(lines) + HEAD_END


def split_target(target: str) -> tuple:
    """The path and the query of a request's target, in either form a client sends."""
    if "://" in target.split("?", 1)[0]:
        parts = urllib.parse.urlsplit(target)
        return parts.path or "/", parts.query
    path, _, query = target.partition("?")
    return path, query


def host_name(host: str) -> str:
    """A ``Host`` header's name without its port, in lower case.

    Args:
        host: The header's value, such as ``127.0.0.1:24100`` or
            ``[::1]:24100``.

    Returns:
        The name, an IPv6 address kept in its brackets.
    """
    text = host.strip().lower()
    if text.startswith("["):
        return text.split("]", 1)[0] + "]"
    return text.split(":", 1)[0]


def check_origin(headers: list, local_name: str = "") -> int:
    """The status a request is refused with for where it comes from, 0 when it passes.

    Args:
        headers: ``[(name, value)]`` as :func:`parse_head` gives them.
        local_name: The instance's app's local name, a name its ``Host``
            may carry beside the loopback names.

    Returns:
        421 for a ``Host`` that names neither loopback nor the local name,
        403 for an ``Origin`` that names another scheme, host or port than
        the ``Host``, 0 otherwise.
    """
    host = header(headers, "host")
    names = set(HTTP_FORWARD_LOOPBACK_HOSTS)
    if local_name:
        names.add(local_name.strip().lower())
    if not host or host_name(host) not in names:
        return 421
    origin = header(headers, "origin")
    if origin and _origin_place(origin) != _host_place(host):
        return 403
    return 0


def _host_place(host: str) -> str:
    """A ``Host`` as an origin's place: ``http://`` and the host, its default port dropped."""
    text = host.strip().lower()
    if text.endswith(":80"):
        text = text[: -len(":80")]
    return "http://" + text


def _origin_place(origin: str) -> str:
    """An ``Origin`` in the same form, its default port dropped."""
    text = origin.strip().lower().rstrip("/")
    if text.startswith("http://") and text.endswith(":80"):
        text = text[: -len(":80")]
    return text


def is_upgrade(headers: list) -> bool:
    """Whether a request asks for a WebSocket or another protocol."""
    return header(headers, "upgrade") != "" and "upgrade" in header_tokens(
        headers, "connection"
    )


def is_closing(version: str, headers: list) -> bool:
    """Whether a request or an answer ends its connection after it.

    Args:
        version: ``HTTP/1.1`` or ``HTTP/1.0``.
        headers: Its headers.

    Returns:
        True for ``Connection: close``, and for HTTP/1.0 without
        ``Connection: keep-alive``.
    """
    tokens = header_tokens(headers, "connection")
    if "close" in tokens:
        return True
    return version.upper() == "HTTP/1.0" and "keep-alive" not in tokens


def answer(
    client: socket.socket,
    status: int,
    body: bytes = b"",
    *,
    content_type: str = "text/plain; charset=utf-8",
    extra: "list | None" = None,
    is_closing: bool = True,
) -> None:
    """Write one whole answer of the forwarder's own.

    Args:
        client: The browser's connection.
        status: One of :data:`STATUS_LINES`.
        body: What the answer carries; empty writes the status's words.
        content_type: The body's type.
        extra: More ``(name, value)`` headers.
        is_closing: Whether the answer ends the connection, which it then
            says with ``Connection: close``.

    Raises:
        OSError: When the connection fails.
    """
    if not body:
        body = STATUS_LINES[status].split(b" ", 1)[1] + b"\n"
    lines = [
        STATUS_LINES[status],
        f"Content-Type: {content_type}".encode("latin-1"),
        f"Content-Length: {len(body)}".encode("latin-1"),
    ]
    if is_closing:
        lines.append(b"Connection: close")
    lines += [f"{name}: {value}".encode("latin-1") for name, value in extra or []]
    client.sendall(b"\r\n".join(lines) + HEAD_END + body)


def relay_answer(
    upstream: ConnectionReader, client: socket.socket, method: str, rename=None
):
    """Pass the page's answer to one request back to the browser.

    An interim answer is passed on and the final one read after it. The
    body follows its length, its chunks, or the end of the connection.

    Args:
        upstream: The connection to the page, read through its buffer.
        client: The browser's connection.
        method: The request's method, ``HEAD`` taking an answer with no body.
        rename: Called with each answer's head, returning the head the
            browser is sent; None sends it as the page wrote it.

    Returns:
        True when both connections can carry the next request; False when
        the answer ended the page's connection or said it would; None when
        the page ended the connection before the first byte of an answer.

    Raises:
        OSError: When either connection fails, or the answer is malformed.
    """
    is_first = True
    while True:
        head = upstream.read_head()
        if head is None:
            if is_first:
                return None
            raise ConnectionError("the page ended its answer early")
        is_first = False
        parsed = parse_status(head)
        if parsed is None:
            raise ConnectionError("the page answered with no status")
        version, status, headers = parsed
        client.sendall(rename(head) if rename is not None else head)
        if 100 <= status < 200 and status != 101:
            continue
        break
    if method.upper() == "HEAD" or status in (204, 304) or 100 <= status < 200:
        return not is_closing(version, headers)
    if "chunked" in header_tokens(headers, "transfer-encoding"):
        _relay_chunks(upstream, client)
        return not is_closing(version, headers)
    length_text = header(headers, "content-length")
    if length_text:
        if not upstream.copy_exact(int(length_text), client):
            raise ConnectionError("the page ended its answer early")
        return not is_closing(version, headers)
    upstream.copy_to_end(client)
    return False


def _relay_chunks(upstream: ConnectionReader, client: socket.socket) -> None:
    """Pass a chunked body on, chunk by chunk, through its trailer.

    Raises:
        OSError: When either connection fails or a chunk is malformed.
    """
    while True:
        line = upstream.read_line()
        if not line:
            raise ConnectionError("the page ended its chunks early")
        client.sendall(line)
        size = int(line.split(b";", 1)[0].strip() or b"0", 16)
        if size == 0:
            while True:
                trailer = upstream.read_line()
                if not trailer:
                    raise ConnectionError("the page ended its trailer early")
                client.sendall(trailer)
                if trailer == b"\r\n":
                    return
        if not upstream.copy_exact(size + 2, client):
            raise ConnectionError("the page ended a chunk early")


def _copy(source: socket.socket, target: socket.socket) -> None:
    """Copy bytes one way until the source ends or either side fails."""
    try:
        while True:
            chunk = source.recv(AGENT_FORWARD_CHUNK_BYTES)
            if not chunk:
                return
            target.sendall(chunk)
    except OSError:
        return


def _relay_both_ways(client: socket.socket, upstream: socket.socket) -> None:
    """Relay a WebSocket both ways until either side closes."""
    client.settimeout(AGENT_FORWARD_IDLE_TIMEOUT_S)
    upstream.settimeout(AGENT_FORWARD_IDLE_TIMEOUT_S)
    sender = threading.Thread(
        target=_copy_then_shut, args=(client, upstream), daemon=True
    )
    sender.start()
    _copy_then_shut(upstream, client)
    sender.join(timeout=1.0)


def _copy_then_shut(source: socket.socket, target: socket.socket) -> None:
    """Copy one way, then end the target's sending side."""
    _copy(source, target)
    try:
        target.shutdown(socket.SHUT_WR)
    except OSError:
        return


class ForwarderServer(socketserver.ThreadingTCPServer):
    """One listening socket whose every connection one callable judges."""

    # Windows lets a second socket take a port held with this set.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def __init__(self, address, handle):
        """
        Args:
            address: ``(host, port)`` to listen on.
            handle: Called with each accepted connection, which is closed
                after it returns.

        Raises:
            OSError: When the address cannot be bound.
        """
        self.handle_connection = handle
        super().__init__(address, _ForwarderConnection)


class _ForwarderConnection(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.server.handle_connection(self.request)


@dataclass(frozen=True)
class ForwardRequest:
    """One request as the forwarder read it, before the page sees it.

    Attributes:
        method: The request's method.
        path: Its path, without the query.
        query: Its query, name to the values in their order.
        headers: ``((name, value), ...)`` as the request carried them.
        token: What ``?tkn=`` held, empty for none.
        take_token: Spends the token: True when it verifies and was never
            spent, so a module's rule may trade it for its own login. A
            ``secret`` keyword checks it under that secret in place of the
            instance's own.
    """

    method: str
    path: str
    query: dict
    headers: tuple
    token: str
    take_token: object

    def header(self, name: str) -> str:
        """The first value of one header, empty when the request has none.

        Args:
            name: The header's name in lower case.

        Returns:
            The value.
        """
        return header(list(self.headers), name)

    def cookie_values(self, name: str) -> list:
        """Every value one cookie holds across the request's ``Cookie`` headers.

        Args:
            name: The cookie's name.

        Returns:
            The values, in order.
        """
        return cookie_values(list(self.headers), name)


@dataclass(frozen=True)
class ForwardDecision:
    """What the forwarder does with one request.

    Attributes:
        status: 0 passes the request on to the page; another status is
            answered by the forwarder itself, one of :data:`STATUS_LINES`.
        body: What an answer carries; empty writes the status's words.
        content_type: The body's type.
        headers: More ``(name, value)`` headers of the answer.
    """

    status: int = 0
    body: bytes = b""
    content_type: str = "text/plain; charset=utf-8"
    headers: tuple = ()


RELAY = ForwardDecision()
# What a request's turn answers once the browser's connection is to end.
_CLOSED = object()


def refused() -> ForwardDecision:
    """The decision that answers 401."""
    return ForwardDecision(status=401)


def answered(
    status: int,
    body: bytes = b"",
    *,
    content_type: str = "text/plain; charset=utf-8",
    headers: tuple = (),
) -> ForwardDecision:
    """The decision that answers with the forwarder's own words.

    Args:
        status: One of :data:`STATUS_LINES`.
        body: What the answer carries; empty writes the status's words.
        content_type: The body's type.
        headers: More ``(name, value)`` headers.

    Returns:
        The decision.
    """
    return ForwardDecision(
        status=status, body=body, content_type=content_type, headers=tuple(headers)
    )


class InstanceForwarder:
    """Stands in front of one instance's page on the instance's port.

    The module's hooks decide what the page needs before the forwarder
    listens, what each request is allowed, and how the page is reached;
    the token check, the listener and the relay are the forwarder's own.
    """

    def __init__(
        self,
        *,
        name: str,
        record: dict,
        hooks,
        listen_host: str = AGENT_FORWARD_LISTEN_HOST,
        clock=hub_time,
        log=print,
        ready_poll_s: float = AGENT_FORWARD_READY_POLL_S,
        retry_s: float = AGENT_FORWARD_RETRY_S,
    ):
        """
        Args:
            name: The module's name, which the thread, the log lines and
                the failure codes carry.
            record: The instance's record: ``account``, ``port``, the
                secret its tokens are signed with, and what the hooks read.
            hooks: The module's hooks: ``on_first_start``, ``admit``,
                ``connect`` and ``forwarder_fields``, and ``page_cookie``
                where the page's login cookie has a fixed name of its own.
            listen_host: The address the forwarder listens on.
            clock: The hub's time in seconds since the epoch, which a
                token's expiry is judged by.
            log: Callable used for progress messages.
            ready_poll_s: How often the page is asked whether it answers.
            retry_s: How long a refused first start or a failed bind waits
                before it is tried again.
        """
        self.name = name
        self.record = dict(record)
        self.account = str(record.get("account", "") or "")
        self.port = int(record.get("port", 0) or 0)
        self._hooks = hooks
        self._listen_host = listen_host
        self._clock = clock
        self._log = log
        self._ready_poll_s = ready_poll_s
        self._retry_s = retry_s
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._server: "ForwarderServer | None" = None
        # Every socket of the connections being served: each browser's
        # connection and each connection to the page opened for one.
        self._sockets: set = set()
        self._spent: dict = {}
        self._code = ""
        self._params: dict = {}
        self._thread = threading.Thread(
            target=self._run, name=f"{name}_{self.account}", daemon=True
        )

    @property
    def is_listening(self) -> bool:
        """Whether the forwarder answers on its port."""
        with self._lock:
            return self._server is not None

    @property
    def failure(self) -> tuple:
        """Why the forwarder does not listen: ``(code, params)``, empty when it does."""
        with self._lock:
            return self._code, dict(self._params)

    @property
    def listen_address(self) -> tuple:
        """The address and the port the forwarder listens on, once it does."""
        with self._lock:
            server = self._server
        return server.server_address[:2] if server is not None else ("", 0)

    def matches(self, record: dict) -> bool:
        """Whether this forwarder serves one instance record as it stands.

        Args:
            record: The instance's record.

        Returns:
            True when every field the hooks name as the forwarder's is the
            same.
        """
        return all(
            record.get(field) == self.record.get(field)
            for field in self._hooks.forwarder_fields
        )

    def start(self) -> None:
        """Begin waiting for the page, then listen."""
        self._thread.start()

    def close(self) -> None:
        """Stop listening, stop waiting, and end every connection being served."""
        self._closed.set()
        with self._lock:
            server, self._server = self._server, None
            served = list(self._sockets)
        if server is not None:
            server.shutdown()
            server.server_close()
        for connection in served:
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)

    def handle(self, client: socket.socket) -> None:
        """Judge each request a connection carries, and answer or pass it on.

        The connection stays open across requests while both sides allow
        it, each request going through the checks and the module's rule
        again and on to the page over one connection kept for it. A
        WebSocket is relayed both ways once passed on. Every connection to
        the page opened for it is closed when it ends. A closed forwarder
        serves nothing, and its close ends the connection.

        Args:
            client: The browser's connection, closed by the caller.
        """
        opened = [client]
        if not self._track(client):
            return
        set_no_delay(client)
        client.settimeout(AGENT_FORWARD_IDLE_TIMEOUT_S)
        reader = ConnectionReader(client)
        kept: "ConnectionReader | None" = None
        try:
            while True:
                kept = self._serve_one(client, reader, kept, opened)
                if kept is _CLOSED:
                    return
        except OSError:
            return
        finally:
            for upstream in opened[1:]:
                with contextlib.suppress(OSError):
                    upstream.close()
            with self._lock:
                self._sockets.difference_update(opened)

    def _track(self, connection: socket.socket) -> bool:
        """Count a socket among those the forwarder's close ends.

        Returns:
            False once the forwarder is closed, the socket left uncounted.
        """
        with self._lock:
            if self._closed.is_set():
                return False
            self._sockets.add(connection)
            return True

    def _close_upstream(self, upstream: socket.socket, opened: list) -> None:
        """Close a connection to the page, and stop counting it."""
        upstream.close()
        opened.remove(upstream)
        with self._lock:
            self._sockets.discard(upstream)

    def _serve_one(
        self, client: socket.socket, reader: ConnectionReader, kept, opened: list
    ):
        """Serve the next request on a browser's connection.

        Args:
            client: The browser's connection.
            reader: Its bytes, read through a buffer.
            kept: The connection to the page kept for it, None while none is.
            opened: Every socket the browser's connection used so far, the
                connections to the page opened for it added.

        Returns:
            The connection to the page to keep for the next request, None
            while none is kept, or :data:`_CLOSED` once the browser's
            connection is to end.

        Raises:
            OSError: When either connection fails.
        """
        head = reader.read_head()
        if head is None:
            return _CLOSED
        request = parse_head(head)
        if request is None:
            return _CLOSED
        method, target, headers = request
        version = head.split(b"\r\n", 1)[0].rsplit(b" ", 1)[-1].decode("latin-1")
        has_body = bool(header(headers, "transfer-encoding")) or header(
            headers, "content-length"
        ) not in ("", "0")
        refusal = check_origin(headers, str(self.record.get("local_name", "") or ""))
        if refusal:
            answer(client, refusal)
            return _CLOSED
        decision = self._hooks.admit(
            self._request(method, target, headers), self.record
        )
        if decision.status:
            is_ending = has_body or is_closing(version, headers)
            answer(
                client,
                decision.status,
                decision.body,
                content_type=decision.content_type,
                extra=list(decision.headers),
                is_closing=is_ending,
            )
            return _CLOSED if is_ending else kept
        head = self._passed_head(head)
        if is_upgrade(headers):
            if kept is not None:
                kept.socket.close()
            upstream = self._open_upstream(opened)
            if upstream is None:
                answer(client, 502)
                return _CLOSED
            with upstream:
                upstream.sendall(head + reader.take_buffer())
                _relay_both_ways(client, upstream)
            return _CLOSED
        if header(headers, "transfer-encoding"):
            answer(client, 411)
            return _CLOSED
        try:
            length = int(header(headers, "content-length") or 0)
        except ValueError:
            answer(client, 411)
            return _CLOSED
        is_reused = kept is not None
        if kept is None:
            kept = self._open_reader(opened)
            if kept is None:
                answer(client, 502)
                return _CLOSED
        outcome = self._pass_on(kept, client, reader, head, length, method)
        if outcome is None and is_reused and length == 0:
            self._close_upstream(kept.socket, opened)
            kept = self._open_reader(opened)
            if kept is None:
                answer(client, 502)
                return _CLOSED
            outcome = self._pass_on(kept, client, reader, head, length, method)
        if outcome is None:
            kept.socket.close()
            answer(client, 502)
            return _CLOSED
        if not outcome or is_closing(version, headers):
            kept.socket.close()
            return _CLOSED
        return kept

    def _pass_on(
        self,
        upstream: ConnectionReader,
        client: socket.socket,
        reader: ConnectionReader,
        head: bytes,
        length: int,
        method: str,
    ):
        """Send one request to the page, its body cut at its length, and relay the answer.

        Returns:
            What :func:`relay_answer` returns; None as well when the page's
            connection failed before the request was sent.

        Raises:
            OSError: When the browser's connection fails, or the page's
                after its answer began.
        """
        try:
            upstream.socket.sendall(head)
        except OSError:
            return None
        if not reader.copy_exact(length, upstream.socket):
            raise ConnectionError("the browser ended its request early")
        rename = self._answer_head if self._cookie_names() else None
        return relay_answer(upstream, client, method, rename)

    def _cookie_names(self) -> tuple:
        """``(page, kept)``: the page's own cookie name and the entry's, or empty when none is renamed."""
        page = str(getattr(self._hooks, "page_cookie", "") or "")
        kept = str(self.record.get("cookie_name", "") or "")
        return (page, kept) if page and kept else ()

    def _passed_head(self, head: bytes) -> bytes:
        """A request's head as the page is sent it: the entry's cookie under the page's own name."""
        names = self._cookie_names()
        if not names:
            return head
        return renamed_request_cookies(head, kept=names[1], page=names[0])

    def _answer_head(self, head: bytes) -> bytes:
        """An answer's head as the browser is sent it: the page's cookie under the entry's name."""
        page, kept = self._cookie_names()
        return renamed_set_cookies(head, page=page, kept=kept)

    def _request(self, method: str, target: str, headers: list) -> ForwardRequest:
        """One request as the module's rule reads it."""
        path, query_text = split_target(target)
        query = urllib.parse.parse_qs(query_text, keep_blank_values=True)
        tokens = query.get(AGENT_FORWARD_TOKEN_PARAMETER) or [""]
        return ForwardRequest(
            method=method,
            path=path,
            query=query,
            headers=tuple(headers),
            token=tokens[0],
            take_token=functools.partial(self.take_token, tokens[0]),
        )

    def _open_upstream(self, opened: list) -> "socket.socket | None":
        """A connection to the page, sending at once, added to ``opened``.

        Returns:
            The connection; None when the page does not answer or the
            forwarder is closed.
        """
        try:
            upstream = self._hooks.connect(self.record)
        except OSError:
            return None
        opened.append(upstream)
        if not self._track(upstream):
            upstream.close()
            return None
        set_no_delay(upstream)
        upstream.settimeout(AGENT_FORWARD_IDLE_TIMEOUT_S)
        return upstream

    def _open_reader(self, opened: list) -> "ConnectionReader | None":
        """A connection to the page read through a buffer, added to ``opened``; None when it does not answer."""
        upstream = self._open_upstream(opened)
        return ConnectionReader(upstream) if upstream is not None else None

    def take_token(self, token: str, *, secret: "str | None" = None) -> bool:
        """Whether a token verifies and was never spent; spends it if so.

        Args:
            token: What ``?tkn=`` held.
            secret: The secret it is checked under; None is this instance's
                own.

        Returns:
            True for a token signed with the secret, whose expiry is ahead
            and no further than the horizon, and whose nonce was not
            accepted before; False for an empty secret.
        """
        now = self._clock()
        if secret is None:
            secret = str(self.record.get(self._hooks.secret_field, "") or "")
        if not secret:
            return False
        with self._lock:
            return take_token(token, secret=secret, now=now, spent=self._spent)

    def _run(self) -> None:
        """Wait for the page and its first start, then listen until closed."""
        while not self._closed.is_set():
            try:
                code = self._hooks.on_first_start(self.record)
            except OSError:
                self._closed.wait(self._ready_poll_s)
                continue
            if code:
                self._fail(code, {"account": self.account})
                self._closed.wait(self._retry_s)
                continue
            try:
                server = ForwarderServer((self._listen_host, self.port), self.handle)
            except OSError:
                self._fail(
                    f"{self.name}_port_taken",
                    {"account": self.account, "port": self.port},
                )
                self._closed.wait(self._retry_s)
                continue
            with self._lock:
                if self._closed.is_set():
                    server.server_close()
                    return
                self._server = server
                self._code, self._params = "", {}
            self._log(f"{self._who} answers on port {self.port}")
            server.serve_forever(poll_interval=0.5)
            return

    def _fail(self, code: str, params: dict) -> None:
        with self._lock:
            is_new = self._code != code
            self._code, self._params = code, dict(params)
        if is_new:
            self._log(f"{self._who} {code}")

    @property
    def _who(self) -> str:
        """The module and the account the log lines name; the module alone for no account."""
        return f"{self.name}: {self.account}" if self.account else f"{self.name}:"
