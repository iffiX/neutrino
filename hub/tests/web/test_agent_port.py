"""The agent port's connections, on a real loop and real sockets.

Each accepted connection is counted before its TLS handshake, closed when it
sends no first byte, or when the handshake or the admission takes too long,
none of which counts as a failed admission, and handed to the HTTP protocol
once the handshake is done, with what arrived before the hand-over. A body
past the port's limit is refused before the application reads it.
"""

import asyncio
import ssl

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


async def serving(tmp_path, guard, **timeouts):
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

    server = await loop.create_server(protocol, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def is_closed_by_peer(reader, within_s: float) -> bool:
    try:
        data = await asyncio.wait_for(reader.read(1), within_s)
    except (ConnectionError, ssl.SSLError):
        return True
    return data == b""


def test_a_finished_handshake_is_handed_to_the_http_protocol(tmp_path):
    async def scenario():
        guard = ChannelPortGuard()
        server, port = await serving(tmp_path, guard)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=client_context()
        )
        writer.write(b"hello")
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(5), 5)
        writer.close()
        server.close()
        return answer

    assert asyncio.run(scenario()) == b"HELLO"


def test_a_socket_that_sends_no_byte_is_closed_and_not_counted(tmp_path):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(tmp_path, guard, first_byte_timeout_s=0.2)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
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


def test_a_handshake_that_stalls_after_its_first_byte_is_closed_and_not_counted(
    tmp_path,
):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(
            tmp_path, guard, first_byte_timeout_s=0.2, handshake_timeout_s=0.5
        )
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"\x16")
        await writer.drain()
        await asyncio.sleep(0.3)
        is_open_after_first_byte_time = not reader.at_eof()
        is_closed = await is_closed_by_peer(reader, 3)
        writer.close()
        server.close()
        return is_open_after_first_byte_time, is_closed, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (True, True, 0)


def test_a_connection_never_admitted_is_closed_at_its_admission_time(tmp_path):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(tmp_path, guard, admission_timeout_s=0.3)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=client_context()
        )
        is_closed = await is_closed_by_peer(reader, 3)
        writer.close()
        server.close()
        return is_closed, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (True, 0)


def test_silent_sockets_at_the_cap_leave_room_for_a_real_handshake(tmp_path):
    """The port full of bare sockets: each new one closes the oldest bare
    one, and a peer that finished TLS keeps its place."""

    async def scenario():
        guard = ChannelPortGuard()
        server, port = await serving(tmp_path, guard)
        silent = [
            await asyncio.open_connection("127.0.0.1", port)
            for _ in range(CHANNEL_UNADMITTED_MAX)
        ]
        await asyncio.sleep(0.1)
        full = guard.unadmitted_count
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port, ssl=client_context()), 5
        )
        more = [await asyncio.open_connection("127.0.0.1", port) for _ in range(8)]
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


def test_an_admitted_connection_outlives_the_admission_time(tmp_path):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(tmp_path, guard, admission_timeout_s=0.2)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=client_context()
        )
        local = writer.get_extra_info("sockname")
        guard.admit(("127.0.0.1", local[1]))
        await asyncio.sleep(0.4)
        writer.write(b"still")
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(5), 5)
        writer.close()
        server.close()
        return answer, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (b"STILL", 0)


def test_a_failed_handshake_is_closed_and_not_counted(tmp_path):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(tmp_path, guard)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        is_closed = await is_closed_by_peer(reader, 3)
        writer.close()
        server.close()
        return is_closed, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (True, 0)


def test_the_oldest_open_handshake_is_closed_to_make_room(tmp_path):
    async def scenario():
        guard = ChannelPortGuard(unadmitted_max=2)
        server, port = await serving(tmp_path, guard)
        first_reader, first = await asyncio.open_connection("127.0.0.1", port)
        await asyncio.sleep(0.05)
        _, second = await asyncio.open_connection("127.0.0.1", port)
        await asyncio.sleep(0.05)
        _, third = await asyncio.open_connection("127.0.0.1", port)
        is_closed = await is_closed_by_peer(first_reader, 3)
        for writer in (first, second, third):
            writer.close()
        server.close()
        return is_closed, guard.pause_remaining_s()

    assert asyncio.run(scenario()) == (True, 0)


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
