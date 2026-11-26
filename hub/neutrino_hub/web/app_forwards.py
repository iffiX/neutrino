"""The hub's app forwards: a listener of its own in front of one web entry.

The Services page's Open starts one for a browser that reached the panel
directly (protocol.md, "The app forwards"). A forward listens where the
panel listens, at the first free port of its range, and joins each
connection to the entry's far end: the hub transport's loopback forward to a
machine's port, or a declared app's host. It reads each request's head,
writes ``Host`` and ``Origin`` as loopback's, takes the panel's session
cookie out, and passes every other byte on unread. A forward with no open
connection for the idle time ends.

Not pure: listens and dials.
"""

import asyncio
import functools
import ssl
import time
from dataclasses import dataclass, field

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.web.constants import (
    WEB_APP_FORWARD_HEAD_BYTES_MAX,
    WEB_APP_FORWARD_IDLE_S,
    WEB_APP_FORWARD_PORT_MAX,
    WEB_APP_FORWARD_PORT_MIN,
    WEB_APP_FORWARD_SWEEP_S,
    WEB_SESSION_COOKIE_PREFIX,
)

# The host every request's Host and Origin are written with.
LOOPBACK_HOST = "127.0.0.1"
# The bytes one read of a relayed stream takes at most.
COPY_CHUNK_BYTES = 65536
# The connections a forward's listening socket queues before it accepts them.
LISTEN_BACKLOG = 128
# Each scheme's port an address means when it names none.
SCHEME_PORTS = {"http": "80", "https": "443"}
# The status lines of the answers a forward gives itself.
STATUS_LINES = {
    403: b"HTTP/1.1 403 Forbidden",
    411: b"HTTP/1.1 411 Length Required",
    502: b"HTTP/1.1 502 Bad Gateway",
}


@dataclass(frozen=True)
class AppForwardTarget:
    """The far end one app forward joins its connections to.

    Attributes:
        entry_id: The web entry's id.
        scheme: ``http`` or ``https``, the entry's url's.
        device_id: The managed machine whose port the hub's transport
            forwards to; empty for a declared app.
        host: The declared app's host; empty for a machine's port.
        port: The port on the machine or at ``host``.
    """

    entry_id: str
    scheme: str
    device_id: str
    host: str
    port: int


@dataclass(frozen=True)
class RequestHead:
    """One request's head as a forward passes it on.

    Attributes:
        head: The head to send on, empty when the request is refused.
        status: The status the forward answers itself; 0 when it passes.
        length: The body's bytes, by its ``Content-Length``.
        is_upgrade: Whether the connection carries raw bytes after the head.
    """

    head: bytes
    status: int = 0
    length: int = 0
    is_upgrade: bool = False


@dataclass
class AppForward:
    """One listener of the hub's in front of a web entry.

    Attributes:
        target: Where its connections go.
        port: The port it listens on.
        server: The listening server.
        open_count: The connections open on it now.
        last_active_at: When a connection last opened or closed, by the
            table's clock.
    """

    target: AppForwardTarget
    port: int
    server: object = field(default=None, repr=False)
    open_count: int = 0
    last_active_at: float = 0.0


def rewrite_request_head(head: bytes, *, scheme: str, port: int) -> RequestHead:
    """One request's head written for the app behind a forward.

    Args:
        head: The request line and the headers, up to the blank line.
        scheme: The forward's scheme, ``http`` or ``https``.
        port: The forward's port.

    Returns:
        The head with ``Host`` as ``127.0.0.1:<port>``, the forward's own
        ``Origin`` written the same way, and every cookie whose name starts
        with ``neutrino_session_`` taken out; or a refusal, 403 for another
        ``Origin`` and 411 for ``Transfer-Encoding`` or an unreadable
        ``Content-Length``.
    """
    lines = head.split(b"\r\n")
    request_line, fields = lines[0], [line for line in lines[1:] if line]
    headers = [_split_field(line) for line in fields]
    received_host = _value(headers, b"host")
    place = f"{LOOPBACK_HOST}:{port}"
    written = [request_line]
    for name, value, line in headers:
        lowered = name.lower()
        if lowered == b"host":
            continue
        if lowered == b"origin":
            if _origin_place(value) != _host_place(scheme, received_host):
                return RequestHead(head=b"", status=403)
            written.append(b"Origin: " + f"{scheme}://{place}".encode("latin-1"))
            continue
        if lowered == b"cookie":
            kept = _kept_cookies(value)
            if kept:
                written.append(b"Cookie: " + kept)
            continue
        written.append(line)
    written.insert(1, b"Host: " + place.encode("latin-1"))
    if _value(headers, b"transfer-encoding"):
        return RequestHead(head=b"", status=411)
    try:
        length = int(_value(headers, b"content-length") or b"0")
    except ValueError:
        return RequestHead(head=b"", status=411)
    if length < 0:
        return RequestHead(head=b"", status=411)
    connection = [
        token.strip().lower()
        for token in _value(headers, b"connection").split(b",")
        if token.strip()
    ]
    is_upgrade = bool(_value(headers, b"upgrade")) and b"upgrade" in connection
    return RequestHead(
        head=b"\r\n".join(written) + b"\r\n\r\n",
        length=length,
        is_upgrade=is_upgrade,
    )


def upstream_tls_context() -> ssl.SSLContext:
    """The TLS an https entry's forward opens to the app: no certificate checked.

    Returns:
        A client context over HTTP/1.1 that accepts any certificate.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_alpn_protocols(["http/1.1"])
    return context


def _split_field(line: bytes) -> tuple:
    """``(name, value, line)`` of one header line."""
    name, _, value = line.partition(b":")
    return name.strip(), value.strip(), line


def _value(headers: list, name: bytes) -> bytes:
    """The first value of one header, empty when the head has none."""
    for held, value, _ in headers:
        if held.lower() == name:
            return value
    return b""


def _kept_cookies(value: bytes) -> bytes:
    """A ``Cookie`` value without the panel's session cookies."""
    prefix = WEB_SESSION_COOKIE_PREFIX.encode("latin-1")
    kept = [
        pair.strip()
        for pair in value.split(b";")
        if pair.strip() and not pair.strip().startswith(prefix)
    ]
    return b"; ".join(kept)


def _host_place(scheme: str, host: bytes) -> str:
    """A ``Host`` as an origin's place, its scheme's default port dropped."""
    text = host.decode("latin-1").strip().lower()
    default = ":" + SCHEME_PORTS.get(scheme, "")
    if text.endswith(default):
        text = text[: -len(default)]
    return f"{scheme}://{text}"


def _origin_place(origin: bytes) -> str:
    """An ``Origin`` in the same form, its scheme's default port dropped."""
    text = origin.decode("latin-1").strip().lower().rstrip("/")
    for scheme, port in SCHEME_PORTS.items():
        if text.startswith(f"{scheme}://") and text.endswith(f":{port}"):
            return text[: -len(f":{port}")]
    return text


async def _copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy one side to the other until the side read ends."""
    while True:
        chunk = await reader.read(COPY_CHUNK_BYTES)
        if not chunk:
            return
        writer.write(chunk)
        await writer.drain()


async def _copy_exact(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, size: int
) -> bool:
    """Copy one body of ``size`` bytes; False when its side ended early."""
    left = size
    while left > 0:
        chunk = await reader.read(min(left, COPY_CHUNK_BYTES))
        if not chunk:
            return False
        writer.write(chunk)
        await writer.drain()
        left -= len(chunk)
    return True


async def _answer(writer: asyncio.StreamWriter, status: int) -> None:
    """Answer one request with a bodiless status and close the connection."""
    writer.write(
        STATUS_LINES[status] + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    )
    try:
        await writer.drain()
    except ConnectionError:
        pass


def _close(writer: "asyncio.StreamWriter | None") -> None:
    """Close one side, whatever state it is in."""
    if writer is None:
        return
    try:
        writer.close()
    except (OSError, RuntimeError):
        pass


class AppForwardTable:
    """The app forwards the Services page's Open starts, by entry id."""

    def __init__(
        self,
        *,
        hub_forwards,
        tls_context_of,
        listen_host: str,
        clock=time.monotonic,
        port_min: int = WEB_APP_FORWARD_PORT_MIN,
        port_max: int = WEB_APP_FORWARD_PORT_MAX,
        idle_s: float = WEB_APP_FORWARD_IDLE_S,
        sweep_s: float = WEB_APP_FORWARD_SWEEP_S,
        upstream_tls=upstream_tls_context,
    ):
        """
        Args:
            hub_forwards: The :class:`HubForwardTable` whose loopback
                forwards reach a machine's port.
            tls_context_of: Returns the server context an https entry's
                forward ends the browser's TLS with, the panel's served one.
            listen_host: The address the forwards listen on, the panel's.
            clock: The monotonic clock idleness is measured by.
            port_min: The range's first port.
            port_max: The range's last port.
            idle_s: How long a forward with no open connection stays.
            sweep_s: How often the forwards are checked for idleness.
            upstream_tls: Returns the client context an https entry's
                forward opens to the app with.
        """
        self.listen_host = listen_host
        self._hub_forwards = hub_forwards
        self._tls_context_of = tls_context_of
        self._clock = clock
        self._port_min = port_min
        self._port_max = port_max
        self._idle_s = idle_s
        self._sweep_s = sweep_s
        self._upstream_tls = upstream_tls
        # Each forward, by its entry's id.
        self._forwards: dict = {}
        self._lock = asyncio.Lock()
        self._sweeper: "asyncio.Task | None" = None

    async def open(self, target: AppForwardTarget) -> int:
        """Start the forward of one entry, or keep the one it has.

        Call on the panel's loop.

        Args:
            target: Where the forward's connections go.

        Returns:
            The port the forward listens on.

        Raises:
            OSError: When no port of the range is free.
            RuntimeError: When an https entry's forward has no TLS context.
        """
        async with self._lock:
            held = self._forwards.get(target.entry_id)
            if held is not None and held.target == target:
                held.last_active_at = self._clock()
                return held.port
            if held is not None:
                await self._end(held)
            forward = await self._listen(target)
            self._forwards[target.entry_id] = forward
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.get_running_loop().create_task(self._sweep_loop())
        return forward.port

    def port_of(self, entry_id: str) -> int:
        """The port one entry's forward listens on.

        Args:
            entry_id: The web entry's id.

        Returns:
            The port, 0 while the entry has no forward.
        """
        held = self._forwards.get(entry_id)
        return held.port if held is not None else 0

    async def sweep(self) -> list:
        """End every forward with no open connection for the idle time.

        Returns:
            The ids of the entries whose forward ended.
        """
        now = self._clock()
        ended = []
        async with self._lock:
            for entry_id, forward in list(self._forwards.items()):
                if forward.open_count > 0:
                    continue
                if now - forward.last_active_at < self._idle_s:
                    continue
                del self._forwards[entry_id]
                await self._end(forward)
                ended.append(entry_id)
        return ended

    async def close_all(self) -> None:
        """End every forward."""
        async with self._lock:
            forwards = list(self._forwards.values())
            self._forwards.clear()
            for forward in forwards:
                await self._end(forward)
        if self._sweeper is not None:
            self._sweeper.cancel()

    async def _listen(self, target: AppForwardTarget) -> AppForward:
        """Listen at the first free port of the range.

        Raises:
            OSError: When no port of the range is free.
            RuntimeError: When an https entry's forward has no TLS context.
        """
        context = None
        if target.scheme == "https":
            context = self._tls_context_of()
            if context is None:
                raise RuntimeError("the panel serves no TLS context")
        held = {forward.port for forward in self._forwards.values()}
        for port in range(self._port_min, self._port_max + 1):
            if port in held:
                continue
            forward = AppForward(target=target, port=port, last_active_at=self._clock())
            try:
                forward.server = await asyncio.start_server(
                    functools.partial(self._serve, forward),
                    self.listen_host,
                    port,
                    ssl=context,
                    limit=WEB_APP_FORWARD_HEAD_BYTES_MAX,
                    backlog=LISTEN_BACKLOG,
                )
            except OSError:
                continue
            return forward
        raise OSError(f"no free port from {self._port_min} to {self._port_max}")

    async def _end(self, forward: AppForward) -> None:
        """Close a forward's listener, and the transport forward behind it."""
        if forward.server is not None:
            forward.server.close()
        target = forward.target
        if target.device_id:
            await asyncio.to_thread(
                self._hub_forwards.stop, target.device_id, target.port
            )

    async def _sweep_loop(self) -> None:
        """Check the forwards every sweep interval while any is held."""
        while self._forwards:
            await asyncio.sleep(self._sweep_s)
            await self.sweep()

    async def _serve(
        self,
        forward: AppForward,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Join one browser connection to the entry's far end."""
        forward.open_count += 1
        forward.last_active_at = self._clock()
        upstream = None
        try:
            try:
                upstream = await self._dial(forward.target)
            except (OSError, AgentOfflineError, StreamRefusedError):
                await _answer(writer, 502)
                return
            answers = asyncio.create_task(_copy(upstream[0], writer))
            requests = asyncio.create_task(
                self._relay_requests(forward, reader, writer, upstream[1])
            )
            done, pending = await asyncio.wait(
                {answers, requests}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)
        finally:
            _close(upstream[1] if upstream is not None else None)
            _close(writer)
            forward.open_count -= 1
            forward.last_active_at = self._clock()

    async def _dial(self, target: AppForwardTarget) -> tuple:
        """Open a connection to the entry's far end.

        Raises:
            OSError: When the far end does not answer.
            AgentOfflineError: When the transport is not reached.
            StreamRefusedError: With the transport's code.
        """
        host, port = target.host, target.port
        if target.device_id:
            listen = await asyncio.to_thread(
                self._hub_forwards.address, target.device_id, target.port
            )
            host, _, number = listen.rpartition(":")
            port = int(number)
        context = self._upstream_tls() if target.scheme == "https" else None
        return await asyncio.open_connection(
            host, port, ssl=context, server_hostname="" if context else None
        )

    async def _relay_requests(
        self,
        forward: AppForward,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        upstream: asyncio.StreamWriter,
    ) -> None:
        """Pass each request on, its head written for the app."""
        target = forward.target
        while True:
            try:
                head = await reader.readuntil(b"\r\n\r\n")
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                return
            request = rewrite_request_head(
                head, scheme=target.scheme, port=forward.port
            )
            if request.status:
                await _answer(writer, request.status)
                return
            upstream.write(request.head)
            await upstream.drain()
            if request.is_upgrade:
                await _copy(reader, upstream)
                return
            if not await _copy_exact(reader, upstream, request.length):
                return
