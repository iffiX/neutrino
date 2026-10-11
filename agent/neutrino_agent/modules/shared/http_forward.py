"""What every forwarder in front of a module's page shares.

A forwarder is a thread of the agent that listens on one port and judges
each request before the page behind it sees it: CloudCLI's and
code-server's. This module holds what does not depend on the page: the
one-time token a client opens the page with, reading one request's head,
answering with the forwarder's own words, and relaying a request and its
answer, a WebSocket included.

A token is ``base64url(expiry || nonce || HMAC-SHA256(secret, expiry ||
nonce))``, checked here with no call to the hub. Each connection carries
one request: an ordinary request is passed on with ``Connection: close`` in
place of its own and its body cut at its ``Content-Length``; a WebSocket is
passed on unchanged and relayed both ways until either side closes.

Not pure: opens sockets.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import socket
import socketserver
import threading
import urllib.parse

from neutrino_agent.constants import (
    AGENT_FORWARD_CHUNK_BYTES,
    AGENT_FORWARD_HEAD_LIMIT_BYTES,
    AGENT_FORWARD_IDLE_TIMEOUT_S,
    AGENT_FORWARD_TOKEN_EXPIRY_BYTES,
    AGENT_FORWARD_TOKEN_HORIZON_S,
    AGENT_FORWARD_TOKEN_MAC_BYTES,
    AGENT_FORWARD_TOKEN_NONCE_BYTES,
)

HEAD_END = b"\r\n\r\n"
# The answers a forwarder writes itself.
STATUS_LINES = {
    200: b"HTTP/1.1 200 OK",
    302: b"HTTP/1.1 302 Found",
    401: b"HTTP/1.1 401 Unauthorized",
    411: b"HTTP/1.1 411 Length Required",
    502: b"HTTP/1.1 502 Bad Gateway",
}


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


def read_head(client: socket.socket) -> tuple:
    """``(head, rest)`` of a request; head None when it ended or ran past the limit.

    Raises:
        OSError: When the connection fails.
    """
    received = b""
    while HEAD_END not in received:
        if len(received) > AGENT_FORWARD_HEAD_LIMIT_BYTES:
            return None, b""
        chunk = client.recv(AGENT_FORWARD_CHUNK_BYTES)
        if not chunk:
            return None, b""
        received += chunk
    head, _, rest = received.partition(HEAD_END)
    return head + HEAD_END, rest


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


def split_target(target: str) -> tuple:
    """The path and the query of a request's target, in either form a client sends."""
    if "://" in target.split("?", 1)[0]:
        parts = urllib.parse.urlsplit(target)
        return parts.path or "/", parts.query
    path, _, query = target.partition("?")
    return path, query


def closing_head(head: bytes) -> bytes:
    """A request's head with ``Connection: close`` in place of its own."""
    lines = head[: -len(HEAD_END)].split(b"\r\n")
    kept = [lines[0]] + [
        line
        for line in lines[1:]
        if line.split(b":", 1)[0].strip().lower() not in (b"connection", b"keep-alive")
    ]
    return b"\r\n".join(kept + [b"Connection: close"]) + HEAD_END


def answer(
    client: socket.socket,
    status: int,
    body: bytes = b"",
    *,
    content_type: str = "text/plain; charset=utf-8",
    extra: "list | None" = None,
) -> None:
    """Write one whole answer of the forwarder's own and close the exchange.

    Args:
        client: The browser's connection.
        status: One of :data:`STATUS_LINES`.
        body: What the answer carries; empty writes the status's words.
        content_type: The body's type.
        extra: More ``(name, value)`` headers.

    Raises:
        OSError: When the connection fails.
    """
    if not body:
        body = STATUS_LINES[status].split(b" ", 1)[1] + b"\n"
    lines = [
        STATUS_LINES[status],
        f"Content-Type: {content_type}".encode("latin-1"),
        f"Content-Length: {len(body)}".encode("latin-1"),
        b"Connection: close",
    ]
    lines += [f"{name}: {value}".encode("latin-1") for name, value in extra or []]
    client.sendall(b"\r\n".join(lines) + HEAD_END + body)


def relay(
    client: socket.socket, head: bytes, rest: bytes, headers: list, connect
) -> None:
    """Pass one request on to the page and its answer back.

    A request whose body comes in chunks is refused 411, and a page that
    does not answer is 502.

    Args:
        client: The browser's connection.
        head: The request's head as read.
        rest: What was read past the head.
        headers: ``[(name, value)]`` as :func:`parse_head` gives them.
        connect: Returns a connected socket to the page; raises OSError
            when the page does not answer.

    Raises:
        OSError: When the browser's connection fails.
    """
    is_upgrade = header(headers, "upgrade") != "" and "upgrade" in [
        token.strip().lower() for token in header(headers, "connection").split(",")
    ]
    if not is_upgrade and header(headers, "transfer-encoding"):
        answer(client, 411)
        return
    try:
        upstream = connect()
    except OSError:
        answer(client, 502)
        return
    with upstream:
        if is_upgrade:
            upstream.sendall(head + rest)
            _relay_both_ways(client, upstream)
            return
        try:
            length = int(header(headers, "content-length") or 0)
        except ValueError:
            answer(client, 411)
            return
        upstream.sendall(closing_head(head) + rest[:length])
        remaining = length - min(len(rest), length)
        while remaining > 0:
            chunk = client.recv(min(remaining, AGENT_FORWARD_CHUNK_BYTES))
            if not chunk:
                return
            upstream.sendall(chunk)
            remaining -= len(chunk)
        upstream.settimeout(AGENT_FORWARD_IDLE_TIMEOUT_S)
        _copy(upstream, client)


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
