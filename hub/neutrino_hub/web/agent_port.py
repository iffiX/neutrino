"""The agent port's connections, from accept to the protocol that serves them.

uvicorn serves the agent port over plain TCP with this protocol in front:
each accepted connection is counted, closed when it sends no byte within
``CHANNEL_FIRST_BYTE_TIMEOUT_S``, given its TLS handshake under
``CHANNEL_TLS_HANDSHAKE_TIMEOUT_S`` from its first byte and its admission
under ``CHANNEL_ADMISSION_TIMEOUT_S``, and only then handed to uvicorn's own
HTTP protocol on the TLS transport. The port listens on two sockets, IPv4 and
IPv6, and one protocol class and one count serve both. The counts are the runtime's
:class:`neutrino_hub.modules.channel.port_guard.ChannelPortGuard`. The
middleware here refuses a join or a leave whose body is past
``CHANNEL_REQUEST_BYTES_MAX`` before the application reads it.

Not pure: holds sockets.
"""

import asyncio
import functools
import json
import logging
import os
import socket
import ssl
import sys

import uvicorn
from uvicorn.config import STARTUP_FAILURE
from uvicorn.protocols.http.auto import AutoHTTPProtocol

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ADMISSION_TIMEOUT_S,
    CHANNEL_CLOSE_FIRST_BYTE,
    CHANNEL_CLOSE_HANDSHAKE,
    CHANNEL_CODE_REQUEST_TOO_LARGE,
    CHANNEL_FIRST_BYTE_TIMEOUT_S,
    CHANNEL_REQUEST_BYTES_MAX,
    CHANNEL_TLS_HANDSHAKE_TIMEOUT_S,
)
from neutrino_hub.modules.channel.port_guard import ChannelPortGuard
from neutrino_hub.utils.peer_address import unmapped

LOGGER = logging.getLogger(__name__)

# The backstop asyncio's own handshake timer is given beyond the port's.
AGENT_PORT_HANDSHAKE_SLACK_S = 1.0
# The wildcard addresses: the IPv4 one the port is served on by default, and
# the IPv6 one served beside it.
AGENT_PORT_ANY_IPV4 = "0.0.0.0"
AGENT_PORT_ANY_IPV6 = "::"


def agent_port_sockets(host: str, port: int) -> list:
    """The agent port's listening sockets.

    The IPv4 wildcard is served beside the IPv6 one, a socket for each
    family, the IPv6 one set to take IPv6 alone. Any other host is served on
    its own socket.

    Args:
        host: The address to bind.
        port: The port; 0 picks one, which the IPv6 socket then shares.

    Returns:
        The bound sockets, the IPv4 one first. A machine where the IPv6
        socket cannot be made gets the IPv4 one alone, and the log says so
        in one line.

    Raises:
        OSError: If the socket for ``host`` cannot be bound.
    """
    first = _bound_socket(host, port)
    sockets = [first]
    if host == AGENT_PORT_ANY_IPV4:
        shared = first.getsockname()[1]
        try:
            sockets.append(_bound_socket(AGENT_PORT_ANY_IPV6, shared))
        except OSError as error:
            LOGGER.warning(
                "the agent port serves IPv4 alone: no IPv6 socket on port %d (%s)",
                shared,
                error,
            )
    return sockets


def _bound_socket(host: str, port: int) -> socket.socket:
    """One TCP socket bound to an address, an IPv6 one taking IPv6 alone.

    Args:
        host: The address.
        port: The port.

    Returns:
        The bound socket, not yet listening.

    Raises:
        OSError: If the socket cannot be made or bound.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if os.name == "posix":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


class AgentPortServer(uvicorn.Server):
    """uvicorn's server on the agent port's own sockets."""

    async def serve(self, sockets=None) -> None:
        """Bind the port's sockets and serve on them.

        Args:
            sockets: Sockets already bound; None binds
                :func:`agent_port_sockets` on the configured host and port.
        """
        if sockets is None:
            try:
                sockets = agent_port_sockets(self.config.host, self.config.port)
            except OSError as error:
                LOGGER.error("the agent port cannot be bound: %s", error)
                sys.exit(STARTUP_FAILURE)
            LOGGER.info(
                "the agent port listens on %s",
                ", ".join(_named(sock.getsockname()) for sock in sockets),
            )
        await super().serve(sockets=sockets)


def _named(address: tuple) -> str:
    """A socket's address as ``host:port``, an IPv6 host in brackets."""
    host = str(address[0])
    return f"[{host}]:{address[1]}" if ":" in host else f"{host}:{address[1]}"


def agent_port_context(certificate_path: str, key_path: str) -> ssl.SSLContext:
    """The server context the agent port's handshakes use.

    Args:
        certificate_path: The agent certificate.
        key_path: Its unsealed key.

    Returns:
        The context.

    Raises:
        OSError: If either file cannot be read.
        ssl.SSLError: If they are not a certificate and its key.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate_path, key_path)
    return context


def agent_port_protocol(*, guard: ChannelPortGuard, ssl_context: ssl.SSLContext):
    """The protocol class uvicorn is handed for the agent port.

    Args:
        guard: The port's counts.
        ssl_context: The server context.

    Returns:
        A callable uvicorn builds one protocol per connection with.
    """
    return functools.partial(AgentPortProtocol, guard=guard, ssl_context=ssl_context)


class AgentPortProtocol(asyncio.Protocol):
    """One connection on the agent port until its TLS handshake is done."""

    def __init__(
        self,
        *,
        guard: ChannelPortGuard,
        ssl_context: ssl.SSLContext,
        config,
        server_state,
        app_state,
        _loop=None,
        serve_protocol=AutoHTTPProtocol,
        first_byte_timeout_s: float = CHANNEL_FIRST_BYTE_TIMEOUT_S,
        handshake_timeout_s: float = CHANNEL_TLS_HANDSHAKE_TIMEOUT_S,
        admission_timeout_s: float = CHANNEL_ADMISSION_TIMEOUT_S,
    ):
        """
        Args:
            guard: The port's counts.
            ssl_context: The server context.
            config: uvicorn's configuration, handed on.
            server_state: uvicorn's server state, handed on.
            app_state: uvicorn's application state, handed on.
            _loop: The event loop, as uvicorn names it.
            serve_protocol: The HTTP protocol class the connection is handed
                to once its handshake is done.
            first_byte_timeout_s: The time from accept to the first byte.
            handshake_timeout_s: The TLS handshake's time from the first byte.
            admission_timeout_s: The time from accept to an admitted hello.
        """
        self._guard = guard
        self._ssl_context = ssl_context
        self._serve_arguments = {
            "config": config,
            "server_state": server_state,
            "app_state": app_state,
            "_loop": _loop,
        }
        self._loop = _loop or asyncio.get_event_loop()
        self._serve_protocol = serve_protocol
        self._first_byte_timeout_s = first_byte_timeout_s
        self._handshake_timeout_s = handshake_timeout_s
        self._admission_timeout_s = admission_timeout_s
        self._watched_fd = None
        self._silence_timer = None
        self._raw = None
        self._key = None
        self._pending = bytearray()
        self._is_lost = False
        self._is_eof = False
        self._served = None

    def connection_made(self, transport) -> None:
        """Count the connection and wait for its first byte.

        Args:
            transport: The accepted TCP transport.
        """
        self._raw = transport
        # Nothing is read until the handshake takes the socket: a ClientHello
        # read here would never reach the TLS layer.
        transport.pause_reading()
        peer = transport.get_extra_info("peername") or ("", 0)
        self._key = (unmapped(str(peer[0])), int(peer[1]))
        self._guard.accepted(self._key, transport.abort, transport.is_closing)
        self._loop.call_later(
            self._admission_timeout_s, self._guard.expire, self._key, transport.abort
        )
        self._watch_first_byte()

    def data_received(self, data: bytes) -> None:
        """Hold what arrives after the handshake and before the hand-over.

        Args:
            data: Decrypted bytes.
        """
        if self._served is not None:
            self._served.data_received(data)
            return
        self._pending += data

    def eof_received(self):
        """Pass the end of input on, or remember it for the hand-over."""
        if self._served is not None:
            return self._served.eof_received()
        self._is_eof = True
        return None

    def connection_lost(self, exc) -> None:
        """Forget the connection when it ends before the hand-over.

        Args:
            exc: Why it ended, None for a clean end.
        """
        self._is_lost = True
        self._unwatch()
        if self._served is not None:
            self._served.connection_lost(exc)
            return
        self._guard.closed(self._key)

    def _watch_first_byte(self) -> None:
        """Start the handshake when the first byte is waiting on the socket,
        and close the socket when none comes in time.

        A duplicate of the socket's descriptor is watched, so the byte stays
        in the kernel for the TLS layer to read. A loop that cannot watch a
        descriptor starts the handshake at once.
        """
        try:
            self._watched_fd = os.dup(self._raw.get_extra_info("socket").fileno())
            self._loop.add_reader(self._watched_fd, self._first_byte)
        except (AttributeError, NotImplementedError, OSError):
            self._unwatch()
            self._loop.create_task(self._handshake())
            return
        self._silence_timer = self._loop.call_later(
            self._first_byte_timeout_s, self._silent
        )

    def _first_byte(self) -> None:
        """The first byte is waiting: begin the handshake."""
        self._unwatch()
        if not self._is_lost:
            self._loop.create_task(self._handshake())

    def _silent(self) -> None:
        """No byte came in time: close the socket."""
        self._unwatch()
        self._raw.abort()
        self._guard.timed_out(
            self._key, CHANNEL_CLOSE_FIRST_BYTE, self._first_byte_timeout_s
        )

    def _unwatch(self) -> None:
        """Stop waiting for the first byte."""
        if self._silence_timer is not None:
            self._silence_timer.cancel()
            self._silence_timer = None
        if self._watched_fd is not None:
            self._loop.remove_reader(self._watched_fd)
            os.close(self._watched_fd)
            self._watched_fd = None

    async def _handshake(self) -> None:
        """Run the TLS handshake in time, then hand the connection over."""
        try:
            tls = await asyncio.wait_for(
                self._loop.start_tls(
                    self._raw,
                    self,
                    self._ssl_context,
                    server_side=True,
                    ssl_handshake_timeout=self._handshake_timeout_s
                    + AGENT_PORT_HANDSHAKE_SLACK_S,
                ),
                self._handshake_timeout_s,
            )
        except (TimeoutError, asyncio.TimeoutError):
            self._raw.abort()
            self._guard.timed_out(
                self._key, CHANNEL_CLOSE_HANDSHAKE, self._handshake_timeout_s
            )
            return
        except (OSError, ConnectionError, RuntimeError, ValueError):
            self._raw.abort()
            self._guard.closed(self._key)
            return
        if self._is_lost or tls is None:
            self._raw.abort()
            self._guard.closed(self._key)
            return
        self._guard.handshaken(self._key)
        served = self._serve_protocol(**self._serve_arguments)
        tls.set_protocol(served)
        served.connection_made(tls)
        self._served = served
        if self._pending:
            pending = bytes(self._pending)
            self._pending.clear()
            served.data_received(pending)
        if self._is_eof:
            served.eof_received()


class ChannelRequestLimitMiddleware:
    """Refuses an HTTP body past the agent port's limit before the
    application reads it: at once when ``Content-Length`` says so, else as
    soon as the bytes read pass it."""

    def __init__(self, app, *, limit: int = CHANNEL_REQUEST_BYTES_MAX):
        """
        Args:
            app: The ASGI application behind it.
            limit: The most bytes a body may hold.
        """
        self._app = app
        self._limit = limit

    async def __call__(self, scope, receive, send) -> None:
        """Read an HTTP request's body up to the limit, then pass it on.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self._limit:
            await self._refuse(send)
            return
        messages = []
        size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            size += len(message.get("body", b""))
            if size > self._limit:
                await self._refuse(send)
                return
            if not message.get("more_body", False):
                break
        queued = iter(messages)

        async def replay():
            return next(queued, None) or await receive()

        await self._app(scope, replay, send)

    async def _refuse(self, send) -> None:
        """Answer 413 with the port's code."""
        body = json.dumps(
            {
                "detail": {
                    "code": CHANNEL_CODE_REQUEST_TOO_LARGE,
                    "params": {"limit": self._limit},
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
