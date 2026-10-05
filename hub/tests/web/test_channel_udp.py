"""A UDP ``port`` entry's one ``connect`` stream, between a client and the
hub as the far end or an agent.

What these pin: a declared record's UDP echo on a real loopback socket
reached through the stream, two sources each getting their own replies over
sockets of their own; a reply dropped, not queued, when the client has no
credit, and the client's frame granted back all the same; a host that does
not resolve closing the stream ``connect_failed``; a frame shorter than its
source dropped; frames between a client and an agent relayed unchanged and
dropped, with the credit granted back, when the next side has none; and the
table of sources forgetting one after the idle time and giving the idlest
away for a 65th.
"""

import asyncio
import json

import pytest

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
    CHANNEL_UDP_IDLE_TIMEOUT_S,
    CHANNEL_UDP_SOURCES_MAX,
)
from neutrino_hub.modules.channel.sessions import ChannelSession, ChannelStream
from neutrino_hub.web.channel_connect import dial_reason
from neutrino_hub.web.channel_udp import (
    UdpSourceTable,
    frame_of,
    relay_to_agent,
    relay_to_socket,
    split_frame,
)


class RecordingSocket:
    """One side's websocket: every frame the hub sends it."""

    def __init__(self):
        self.frames: list = []

    async def send_text(self, text: str) -> None:
        self.frames.append(json.loads(text))

    async def send_bytes(self, data: bytes) -> None:
        self.frames.append(bytes(data))

    def datagrams(self) -> list:
        """Each binary frame as ``(source, datagram)``, the stream id dropped."""
        return [
            split_frame(frame[4:]) for frame in self.frames if isinstance(frame, bytes)
        ]

    def credits(self) -> list:
        return [
            frame["bytes"]
            for frame in self.frames
            if isinstance(frame, dict) and frame.get("type") == "credit"
        ]


def stream_on(role: str, kind_args: dict, stream_id: int = 1) -> tuple:
    """A stream on a session of its own, with its recording socket."""
    socket = RecordingSocket()
    session = ChannelSession(
        key=f"{role}-1",
        role=role,
        websocket=socket,
        loop=asyncio.get_running_loop(),
    )
    stream = ChannelStream(session, stream_id, "connect", kind_args)
    session._streams[stream_id] = stream
    return stream, socket


async def until(predicate, timeout_s: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("never happened")
        await asyncio.sleep(0.01)


class Echo(asyncio.DatagramProtocol):
    """A UDP service on loopback answering each datagram with ``echo:`` in front."""

    def __init__(self):
        self.peers: list = []

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        self.peers.append(address)
        self.transport.sendto(b"echo:" + data, address)


async def echo_server() -> tuple:
    loop = asyncio.get_running_loop()
    transport, echo = await loop.create_datagram_endpoint(
        Echo, local_addr=("127.0.0.1", 0)
    )
    return transport, echo, transport.get_extra_info("sockname")[1]


def test_a_declared_records_echo_answers_each_source_on_its_own_socket():
    async def scenario():
        transport, echo, port = await echo_server()
        stream, socket = stream_on(CHANNEL_ROLE_CLIENT, {"id": "dns"})
        stream._grant(10_000)
        relay = asyncio.ensure_future(
            relay_to_socket(stream, "127.0.0.1", port, reason_of=dial_reason)
        )
        stream._deliver(("data", frame_of(40001, b"one")))
        stream._deliver(("data", frame_of(40002, b"two")))
        stream._deliver(("data", frame_of(40001, b"three")))
        await until(lambda: len(socket.datagrams()) == 3)
        await stream.close()
        await asyncio.wait_for(relay, 3)
        transport.close()
        return socket, echo

    socket, echo = asyncio.run(scenario())

    assert sorted(socket.datagrams()) == [
        (40001, b"echo:one"),
        (40001, b"echo:three"),
        (40002, b"echo:two"),
    ]
    assert len(set(echo.peers)) == 2
    assert echo.peers[0] == echo.peers[2]


def test_a_reply_with_no_client_credit_is_dropped_and_the_frame_granted_back():
    async def scenario():
        transport, echo, port = await echo_server()
        stream, socket = stream_on(CHANNEL_ROLE_CLIENT, {"id": "dns"})
        relay = asyncio.ensure_future(
            relay_to_socket(stream, "127.0.0.1", port, reason_of=dial_reason)
        )
        frame = frame_of(40001, b"ping")
        stream._deliver(("data", frame))
        await until(lambda: echo.peers)
        await asyncio.sleep(0.1)
        await stream.close()
        await asyncio.wait_for(relay, 3)
        transport.close()
        return socket, len(frame)

    socket, size = asyncio.run(scenario())

    assert socket.datagrams() == []
    assert socket.credits() == [size]


def test_a_frame_shorter_than_its_source_is_dropped():
    async def scenario():
        transport, echo, port = await echo_server()
        stream, socket = stream_on(CHANNEL_ROLE_CLIENT, {"id": "dns"})
        stream._grant(10_000)
        relay = asyncio.ensure_future(
            relay_to_socket(stream, "127.0.0.1", port, reason_of=dial_reason)
        )
        stream._deliver(("data", b"\x01"))
        stream._deliver(("data", frame_of(40001, b"")))
        await until(lambda: socket.datagrams())
        await stream.close()
        await asyncio.wait_for(relay, 3)
        transport.close()
        return socket, echo

    socket, echo = asyncio.run(scenario())

    assert socket.datagrams() == [(40001, b"echo:")]
    assert len(echo.peers) == 1


def test_a_record_whose_host_does_not_resolve_is_connect_failed():
    async def scenario():
        stream, socket = stream_on(CHANNEL_ROLE_CLIENT, {"id": "dns"})
        await relay_to_socket(stream, "no-such-host.invalid", 53, reason_of=dial_reason)
        return stream

    stream = asyncio.run(scenario())

    assert stream.close_info == {
        "code": "connect_failed",
        "params": {"reason": "unreachable"},
    }


def test_frames_between_a_client_and_an_agent_pass_unchanged_or_are_dropped():
    async def scenario():
        client, client_socket = stream_on(CHANNEL_ROLE_CLIENT, {"id": "dns"})
        agent, agent_socket = stream_on(CHANNEL_ROLE_AGENT, {"port": 53}, 2)
        agent._grant(10_000)
        relay = asyncio.ensure_future(relay_to_agent(client, agent))
        query = frame_of(40001, b"query")
        client._deliver(("data", query))
        await until(lambda: agent_socket.datagrams())
        reply = frame_of(40001, b"reply")
        agent._deliver(("data", reply))
        await until(lambda: agent_socket.credits())
        client._grant(10_000)
        agent._deliver(("data", reply))
        await until(lambda: client_socket.datagrams())
        agent.close_info = None
        await client.close()
        await asyncio.wait_for(relay, 3)
        return client_socket, agent_socket, len(query), len(reply), agent

    client_socket, agent_socket, query_size, reply_size, agent = asyncio.run(scenario())

    assert agent_socket.datagrams() == [(40001, b"query")]
    assert client_socket.datagrams() == [(40001, b"reply")]
    assert client_socket.credits() == [query_size]
    assert agent_socket.credits() == [reply_size, reply_size]
    assert agent.is_closed


class Endpoint:
    def __init__(self, source: int, closed: list):
        self.source = source
        self._closed = closed

    def send(self, datagram: bytes) -> None:
        return

    def close(self) -> None:
        self._closed.append(self.source)


def table_of(closed: list) -> UdpSourceTable:
    async def open_socket(source: int):
        return Endpoint(source, closed)

    return UdpSourceTable(open_socket=open_socket)


def test_a_source_is_forgotten_after_the_idle_time_and_a_later_one_reopened():
    closed: list = []
    table = table_of(closed)

    async def scenario():
        await table.endpoint(1, now=100.0)
        await table.endpoint(2, now=100.0)
        table.touch(2, now=100.0 + CHANNEL_UDP_IDLE_TIMEOUT_S - 1)
        forgotten = table.sweep(now=100.0 + CHANNEL_UDP_IDLE_TIMEOUT_S)
        reopened = await table.endpoint(1, now=200.0)
        return forgotten, reopened

    forgotten, reopened = asyncio.run(scenario())

    assert forgotten == [1]
    assert closed == [1]
    assert reopened.source == 1
    assert sorted(table.sockets) == [1, 2]


def test_one_more_source_than_the_limit_replaces_the_idlest():
    closed: list = []
    table = table_of(closed)

    async def scenario():
        for source in range(CHANNEL_UDP_SOURCES_MAX):
            await table.endpoint(source, now=float(source))
        table.touch(0, now=1000.0)
        await table.endpoint(9999, now=1001.0)

    asyncio.run(scenario())

    assert CHANNEL_UDP_SOURCES_MAX == 64
    assert len(table.sockets) == CHANNEL_UDP_SOURCES_MAX
    assert closed == [1]
    assert 0 in table.sockets and 9999 in table.sockets


@pytest.mark.parametrize(
    "data, split",
    [
        (b"\x9c\x41hello", (40001, b"hello")),
        (b"\x00\x35", (53, b"")),
        (b"\x01", None),
        (b"", None),
    ],
)
def test_a_frame_is_its_source_then_its_datagram(data, split):
    assert split_frame(data) == split
