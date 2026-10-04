"""The agent port's connections, from accept to the protocol that serves them.

uvicorn serves the agent port over plain TCP with this protocol in front:
each accepted connection is counted, given its TLS handshake under
``CHANNEL_TLS_HANDSHAKE_TIMEOUT_S`` and its admission under
``CHANNEL_ADMISSION_TIMEOUT_S``, and only then handed to uvicorn's own HTTP
protocol on the TLS transport. The counts are the runtime's
:class:`neutrino_hub.modules.channel.port_guard.ChannelPortGuard`.

Not pure: holds sockets.
"""

import asyncio
import functools
import ssl

from uvicorn.protocols.http.auto import AutoHTTPProtocol

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ADMISSION_TIMEOUT_S,
    CHANNEL_TLS_HANDSHAKE_TIMEOUT_S,
)
from neutrino_hub.modules.channel.port_guard import ChannelPortGuard

# The backstop asyncio's own handshake timer is given beyond the port's.
AGENT_PORT_HANDSHAKE_SLACK_S = 1.0


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
            handshake_timeout_s: The TLS handshake's time.
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
        self._handshake_timeout_s = handshake_timeout_s
        self._admission_timeout_s = admission_timeout_s
        self._raw = None
        self._key = None
        self._pending = bytearray()
        self._is_lost = False
        self._is_eof = False
        self._served = None

    def connection_made(self, transport) -> None:
        """Count the connection and begin its handshake.

        Args:
            transport: The accepted TCP transport.
        """
        self._raw = transport
        peer = transport.get_extra_info("peername") or ("", 0)
        self._key = (str(peer[0]), int(peer[1]))
        self._guard.accepted(self._key, transport.abort, transport.is_closing)
        self._loop.call_later(
            self._admission_timeout_s, self._guard.expire, self._key, transport.abort
        )
        self._loop.create_task(self._handshake())

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
        if self._served is not None:
            self._served.connection_lost(exc)
            return
        self._guard.closed(self._key)

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
        except TimeoutError:
            self._raw.abort()
            self._guard.closed(self._key)
            self._guard.record_failure()
            return
        except (OSError, ConnectionError, RuntimeError, ValueError):
            self._raw.abort()
            self._guard.closed(self._key)
            return
        if self._is_lost or tls is None:
            self._raw.abort()
            self._guard.closed(self._key)
            return
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
