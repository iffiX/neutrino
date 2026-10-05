"""The agent port's connections, on a real loop and real sockets.

Each accepted connection is counted before its TLS handshake, closed when it
sends no first byte, or when the handshake or the admission takes too long,
none of which counts as a failed admission, and handed to the HTTP protocol
once the handshake is done, with what arrived before the hand-over. A body
past the port's limit is refused before the application reads it. Every
limit holds on the IPv6 socket as on the IPv4 one, and the two count
together.
"""

import asyncio
import socket
import ssl

import pytest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from neutrino_hub.modules.channel.constants import (
    CHANNEL_REQUEST_BYTES_MAX,
    CHANNEL_UNADMITTED_MAX,
)
from neutrino_hub.modules.channel.port_guard import ChannelPortGuard
from neutrino_hub.web.agent_port import (
    AgentPortProtocol,
    ChannelRequestLimitMiddleware,
    agent_port_context,
    agent_port_sockets,
)
from tests.conftest import self_signed_pair


class Echo(asyncio.Protocol):
    """Stands in for uvicorn's HTTP protocol: answers each read in capitals."""

    def __init__(self, *, config, server_state, app_state, _loop):
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        self.transport.write(data.upper())


def client_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


# Both loopbacks: every limit is pinned on the IPv4 socket and the IPv6 one.
HOSTS = pytest.mark.parametrize("host", ["127.0.0.1", "::1"])


async def serving(tmp_path, guard, host="127.0.0.1", **timeouts):
    certificate, key, _ = self_signed_pair(tmp_path)
    context = agent_port_context(str(certificate), str(key))
    loop = asyncio.get_running_loop()

    def protocol():
        return AgentPortProtocol(
            guard=guard,
            ssl_context=context,
            config=None,
            server_state=None,
            app_state=None,
            _loop=loop,
            serve_protocol=Echo,
            **timeouts,
        )

    server = await loop.create_server(protocol, host, 0)
    return server, server.sockets[0].getsockname()[1]


async def is_closed_by_peer(reader, within_s: float) -> bool:
    try:
        data = await asyncio.wait_for(reader.read(1), within_s)
    except (ConnectionError, ssl.SSLError):
        return True
    return data == b""


@HOSTS
def test_a_finished_handshake_is_handed_to_the_http_protocol(tmp_path, host):
    async def scenario():
        guard = ChannelPortGuard()
        server, port = await serving(tmp_path, guard, host)
        reader, writer = await asyncio.open_connection(host, port, ssl=client_context())
        writer.write(b"hello")
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(5), 5)
        writer.close()
        server.close()
        return answer

    assert asyncio.run(scenario()) == b"HELLO"


@HOSTS
def test_a_socket_that_sends_no_byte_is_closed_and_not_counted(tmp_path, host):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(tmp_path, guard, host, first_byte_timeout_s=0.2)
        reader, writer = await asyncio.open_connection(host, port)
        started = asyncio.get_running_loop().time()
        is_closed = await is_closed_by_peer(reader, 3)
        waited = asyncio.get_running_loop().time() - started
        writer.close()
        server.close()
        return is_closed, waited, guard.pause_remaining_s(), guard.unadmitted_count

    is_closed, waited, paused_s, unadmitted = asyncio.run(scenario())

    assert is_closed
    assert waited < 2
    assert paused_s == 0
    assert unadmitted == 0


@HOSTS
def test_a_handshake_that_stalls_after_its_first_byte_is_closed_and_not_counted(
    tmp_path, host
):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(
            tmp_path, guard, host, first_byte_timeout_s=0.2, handshake_timeout_s=0.5
        )
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(b"\x16")
        await writer.drain()
        await asyncio.sleep(0.3)
        is_open_after_first_byte_time = not reader.at_eof()
        is_closed = await is_closed_by_peer(reader, 3)
        writer.close()
        server.close()
        return is_open_after_first_byte_time, is_closed, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (True, True, 0)


@HOSTS
def test_a_connection_never_admitted_is_closed_at_its_admission_time(tmp_path, host):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(tmp_path, guard, host, admission_timeout_s=0.3)
        reader, writer = await asyncio.open_connection(host, port, ssl=client_context())
        is_closed = await is_closed_by_peer(reader, 3)
        writer.close()
        server.close()
        return is_closed, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (True, 0)


@HOSTS
def test_silent_sockets_at_the_cap_leave_room_for_a_real_handshake(tmp_path, host):
    """The port full of bare sockets: each new one closes the oldest bare
    one, and a peer that finished TLS keeps its place."""

    async def scenario():
        guard = ChannelPortGuard()
        server, port = await serving(tmp_path, guard, host)
        silent = [
            await asyncio.open_connection(host, port)
            for _ in range(CHANNEL_UNADMITTED_MAX)
        ]
        await asyncio.sleep(0.1)
        full = guard.unadmitted_count
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=client_context()), 5
        )
        more = [await asyncio.open_connection(host, port) for _ in range(8)]
        await asyncio.sleep(0.1)
        writer.write(b"admit")
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(5), 5)
        count = guard.unadmitted_count
        for _, silent_writer in silent + more:
            silent_writer.close()
        writer.close()
        server.close()
        return full, answer, count

    full, answer, count = asyncio.run(scenario())

    assert full == CHANNEL_UNADMITTED_MAX
    assert answer == b"ADMIT"
    assert count <= CHANNEL_UNADMITTED_MAX


@HOSTS
def test_an_admitted_connection_outlives_the_admission_time(tmp_path, host):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(tmp_path, guard, host, admission_timeout_s=0.2)
        reader, writer = await asyncio.open_connection(host, port, ssl=client_context())
        local = writer.get_extra_info("sockname")
        guard.admit((host, local[1]))
        await asyncio.sleep(0.4)
        writer.write(b"still")
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(5), 5)
        writer.close()
        server.close()
        return answer, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (b"STILL", 0)


@HOSTS
def test_a_failed_handshake_is_closed_and_not_counted(tmp_path, host):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(tmp_path, guard, host)
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        is_closed = await is_closed_by_peer(reader, 3)
        writer.close()
        server.close()
        return is_closed, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (True, 0)


@HOSTS
def test_the_oldest_open_handshake_is_closed_to_make_room(tmp_path, host):
    async def scenario():
        guard = ChannelPortGuard(unadmitted_max=2)
        server, port = await serving(tmp_path, guard, host)
        first_reader, first = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.05)
        _, second = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.05)
        _, third = await asyncio.open_connection(host, port)
        is_closed = await is_closed_by_peer(first_reader, 3)
        for writer in (first, second, third):
            writer.close()
        server.close()
        return is_closed, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (True, 0)


def test_both_sockets_share_one_count(tmp_path):
    """A silent IPv4 socket is the oldest and is closed to make room for an
    IPv6 one: the cap is the port's, not a socket's."""

    async def scenario():
        guard = ChannelPortGuard(unadmitted_max=2)
        certificate, key, _ = self_signed_pair(tmp_path)
        context = agent_port_context(str(certificate), str(key))
        loop = asyncio.get_running_loop()

        def protocol():
            return AgentPortProtocol(
                guard=guard,
                ssl_context=context,
                config=None,
                server_state=None,
                app_state=None,
                _loop=loop,
                serve_protocol=Echo,
            )

        listeners = agent_port_sockets("0.0.0.0", 0)
        assert len(listeners) == 2
        servers = [await loop.create_server(protocol, sock=sock) for sock in listeners]
        port = listeners[0].getsockname()[1]
        first_reader, first = await asyncio.open_connection("127.0.0.1", port)
        await asyncio.sleep(0.05)
        _, second = await asyncio.open_connection("::1", port)
        await asyncio.sleep(0.05)
        _, third = await asyncio.open_connection("::1", port)
        is_closed = await is_closed_by_peer(first_reader, 3)
        for writer in (first, second, third):
            writer.close()
        for server in servers:
            server.close()
        return is_closed

    assert asyncio.run(scenario())


def test_the_wildcard_is_served_on_an_ipv4_and_an_ipv6_only_socket():
    listeners = agent_port_sockets("0.0.0.0", 0)
    try:
        ipv4, ipv6 = listeners
        assert ipv4.family == socket.AF_INET
        assert ipv6.family == socket.AF_INET6
        assert ipv6.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 1
        assert ipv6.getsockname()[1] == ipv4.getsockname()[1]
    finally:
        for sock in listeners:
            sock.close()


def test_a_machine_without_ipv6_serves_ipv4_and_says_so_once(monkeypatch, caplog):
    from neutrino_hub.web import agent_port

    real = agent_port._bound_socket

    def no_ipv6(host, port):
        if ":" in host:
            raise OSError(97, "Address family not supported by protocol")
        return real(host, port)

    monkeypatch.setattr(agent_port, "_bound_socket", no_ipv6)

    with caplog.at_level("WARNING", logger="neutrino_hub.web.agent_port"):
        listeners = agent_port_sockets("0.0.0.0", 0)
    for sock in listeners:
        sock.close()

    assert [sock.family for sock in listeners] == [socket.AF_INET]
    assert len(caplog.records) == 1
    assert "IPv4 alone" in caplog.records[0].getMessage()


def test_a_named_host_is_served_on_its_own_socket():
    listeners = agent_port_sockets("127.0.0.1", 0)
    for sock in listeners:
        sock.close()

    assert [sock.family for sock in listeners] == [socket.AF_INET]


class PeerTransport:
    """A transport whose peer is a dual-stack socket's mapped address."""

    def __init__(self, peer):
        self.peer = peer

    def pause_reading(self):
        pass

    def get_extra_info(self, name):
        return self.peer if name == "peername" else None

    def abort(self):
        pass

    def is_closing(self):
        return False


class RecordingGuard(ChannelPortGuard):
    def __init__(self):
        super().__init__()
        self.keys = []

    def accepted(self, key, close, is_closed):
        self.keys.append(key)


@pytest.mark.parametrize(
    ("peer", "key"),
    [
        (("::ffff:192.168.8.20", 5000, 0, 0), ("192.168.8.20", 5000)),
        (("::ffff:127.0.0.1", 5001, 0, 0), ("127.0.0.1", 5001)),
        (("2001:db8::20", 5002, 0, 0), ("2001:db8::20", 5002)),
        (("192.168.8.20", 5003), ("192.168.8.20", 5003)),
    ],
)
def test_a_mapped_peer_is_counted_by_its_ipv4_address(peer, key):
    async def scenario():
        guard = RecordingGuard()
        protocol = AgentPortProtocol(
            guard=guard,
            ssl_context=None,
            config=None,
            server_state=None,
            app_state=None,
            _loop=asyncio.get_running_loop(),
            serve_protocol=Echo,
            admission_timeout_s=60,
        )
        protocol.connection_made(PeerTransport(peer))
        protocol._unwatch()
        return guard.keys

    assert asyncio.run(scenario()) == [key]


class LateProtocol(AgentPortProtocol):
    """The port's protocol with its handshake starting a moment late, as on a
    loop that runs it a few iterations after the accept."""

    async def _handshake(self) -> None:
        await asyncio.sleep(0.2)
        await super()._handshake()


def test_a_client_hello_sent_before_the_handshake_starts_is_not_lost(tmp_path):
    async def scenario():
        certificate, key, _ = self_signed_pair(tmp_path)
        context = agent_port_context(str(certificate), str(key))
        loop = asyncio.get_running_loop()

        def protocol():
            return LateProtocol(
                guard=ChannelPortGuard(),
                ssl_context=context,
                config=None,
                server_state=None,
                app_state=None,
                _loop=loop,
                serve_protocol=Echo,
            )

        server = await loop.create_server(protocol, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port, ssl=client_context()), 5
        )
        writer.write(b"late")
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(4), 5)
        writer.close()
        server.close()
        return answer

    assert asyncio.run(scenario()) == b"LATE"


def limited_app(read: list) -> FastAPI:
    """An application behind the limit that records every body it parses."""
    app = FastAPI()
    app.add_middleware(ChannelRequestLimitMiddleware)

    @app.post("/api/channel/join")
    async def join(request: Request):
        body = await request.body()
        read.append(len(body))
        return {"size": len(body)}

    return app


def test_a_body_within_the_limit_reaches_the_route():
    read: list = []
    with TestClient(limited_app(read)) as client:
        answer = client.post("/api/channel/join", content=b"x" * 1000)

    assert answer.status_code == 200
    assert read == [1000]


def test_a_declared_length_past_the_limit_is_refused_unread():
    read: list = []
    with TestClient(limited_app(read)) as client:
        answer = client.post(
            "/api/channel/join", content=b"x" * (CHANNEL_REQUEST_BYTES_MAX + 1)
        )

    assert answer.status_code == 413
    assert answer.json()["detail"] == {
        "code": "request_too_large",
        "params": {"limit": CHANNEL_REQUEST_BYTES_MAX},
    }
    assert read == []


def test_a_streamed_body_past_the_limit_is_refused_unread():
    read: list = []

    def chunks():
        for _ in range(CHANNEL_REQUEST_BYTES_MAX // 1024 + 2):
            yield b"x" * 1024

    with TestClient(limited_app(read)) as client:
        answer = client.post("/api/channel/join", content=chunks())

    assert answer.status_code == 413
    assert read == []


@HOSTS
def test_a_loop_that_cannot_watch_a_socket_closes_a_silent_one_at_the_handshake_time(
    tmp_path, host, monkeypatch
):
    """Windows' loop has no ``add_reader``: the handshake starts at the
    accept, and its time stands in for the first-byte time on both sockets."""

    async def scenario():
        loop = asyncio.get_running_loop()

        def cannot_watch(*arguments):
            raise NotImplementedError

        monkeypatch.setattr(loop, "add_reader", cannot_watch)
        guard = ChannelPortGuard()
        server, port = await serving(
            tmp_path, guard, host, first_byte_timeout_s=60, handshake_timeout_s=0.3
        )
        reader, writer = await asyncio.open_connection(host, port)
        started = loop.time()
        is_closed = await is_closed_by_peer(reader, 5)
        waited = loop.time() - started
        writer.close()
        server.close()
        return is_closed, waited, guard.unadmitted_count

    is_closed, waited, unadmitted = asyncio.run(scenario())

    assert is_closed
    assert waited < 3
    assert unadmitted == 0
