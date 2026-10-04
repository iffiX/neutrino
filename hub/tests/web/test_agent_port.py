"""The agent port's connections, on a real loop and real sockets.

Each accepted connection is counted before its TLS handshake, closed when
the handshake or the admission takes too long, which counts as a failed
admission, and handed to the HTTP protocol once the handshake is done, with
what arrived before the hand-over.
"""

import asyncio
import ssl

from neutrino_hub.modules.channel.port_guard import ChannelPortGuard
from neutrino_hub.web.agent_port import AgentPortProtocol, agent_port_context
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


def test_a_handshake_that_never_starts_is_closed_and_counted(tmp_path):
    async def scenario():
        guard = ChannelPortGuard(failures_max=1)
        server, port = await serving(tmp_path, guard, handshake_timeout_s=0.2)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        is_closed = await is_closed_by_peer(reader, 3)
        writer.close()
        server.close()
        return is_closed, guard.pause_remaining_s(), guard.unadmitted_count

    is_closed, paused_s, unadmitted = asyncio.run(scenario())

    assert is_closed
    assert paused_s > 0
    assert unadmitted == 0


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

    is_closed, paused_s = asyncio.run(scenario())

    assert is_closed
    assert paused_s > 0


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
