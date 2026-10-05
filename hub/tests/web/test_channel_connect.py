"""A client's ``connect`` stream, carried to a machine's agent or to a socket
the hub dials itself.

What these pin: a refusal from the judge closes the stream before anything
is dialled, with the count of the socket's other ``connect`` streams and the
panel's HTTP port handed to it; an entry a machine provides opens that
agent's ``connect {port}`` and bytes cross both ways, the agent's close,
refusals included, being the client's; a client that closes closes the
agent's stream; a machine with no socket is ``agent_offline``; a socket the
hub dials carries bytes both ways and its end of file closes the stream
empty; a dial that fails is ``connect_failed`` with ``refused``, ``timeout``
or ``unreachable``; the far end's bytes reach the client only as far as
the client's credit allows; and a UDP entry opens its agent's ``connect
{port, protocol: udp}`` with frames crossing unchanged, or has the hub
answer for a declared record from a socket of its own.
"""

import asyncio
import errno
import json
import socket

import pytest

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.channel.sessions import ChannelSession, ChannelStream
from neutrino_hub.modules.clients.services import ConnectTarget
from neutrino_hub.web import channel_connect
from neutrino_hub.web.channel_connect import dial_reason, serve_connect_stream
from neutrino_hub.web.channel_udp import frame_of, split_frame
from tests.conftest import FakeChannelSessions, ScriptedChannelStream

DEVICE = "device-one"


class FakeSession:
    def __init__(self, key: str = "client-one"):
        self.key = key
        self.connects: dict = {}


class FakeRuntime:
    def __init__(self, online=(DEVICE,)):
        self.agent_sessions = FakeChannelSessions(online=online)
        self.settings = {"listen_port": 8090}


class Judge:
    """The judge: answers with the verdict a test sets, and records its asks."""

    def __init__(self):
        self.asks: list = []
        self.verdict = (
            "",
            {},
            ConnectTarget(DEVICE, "", 8000, kind="web", provider=DEVICE),
        )

    def __call__(self, runtime, client_id, args, *, open_count, panel_port):
        self.asks.append((client_id, dict(args), open_count, panel_port))
        return self.verdict


@pytest.fixture
def judged(monkeypatch) -> Judge:
    judge = Judge()
    monkeypatch.setattr(channel_connect, "connect_target", judge)
    return judge


async def until(predicate) -> None:
    for _ in range(300):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("never happened")


def free_port() -> int:
    """A loopback port nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_refusal_closes_the_stream_before_anything_is_dialled(judged):
    judged.verdict = ("connect_limit", {"limit": 256}, None)
    runtime = FakeRuntime()
    session = FakeSession()
    session.connects.update({3: ("web", ""), 5: ("web", "")})

    async def scenario():
        stream = ScriptedChannelStream("connect", {"id": "x"}, 7)
        await serve_connect_stream(runtime, session, stream)
        return stream

    stream = asyncio.run(scenario())

    assert stream.close_info == {"code": "connect_limit", "params": {"limit": 256}}
    assert judged.asks == [("client-one", {"id": "x"}, 2, 8090)]
    assert runtime.agent_sessions.streams == []
    assert set(session.connects) == {3, 5}


def test_a_machines_entry_opens_its_agents_connect_and_bytes_cross(judged):
    runtime = FakeRuntime()
    session = FakeSession()

    async def scenario():
        stream = ScriptedChannelStream("connect", {"id": "vscode_dev_alice"}, 1)
        serving = asyncio.create_task(serve_connect_stream(runtime, session, stream))
        await until(lambda: runtime.agent_sessions.streams)
        (far,) = runtime.agent_sessions.streams
        held = dict(session.connects)
        stream._deliver(("data", b"GET / HTTP/1.1\r\n\r\n"))
        far._deliver(("data", b"HTTP/1.1 200 OK\r\n"))
        await until(lambda: far.sent and stream.sent)
        far.finish({"code": "", "params": {}})
        await serving
        return stream, far, held

    stream, far, held = asyncio.run(scenario())

    assert (far.kind, far.args) == ("connect", {"port": 8000})
    assert far.sent_bytes() == b"GET / HTTP/1.1\r\n\r\n"
    assert stream.sent_bytes() == b"HTTP/1.1 200 OK\r\n"
    assert stream.close_info == {"code": "", "params": {}}
    assert held == {1: ("web", DEVICE)}
    assert session.connects == {}


@pytest.mark.parametrize(
    "info",
    [
        {"code": "port_not_published", "params": {"port": 8000}},
        {"code": "connect_failed", "params": {"reason": "refused"}},
        {"code": "agent_offline", "params": {"device": DEVICE}},
    ],
)
def test_the_agents_close_is_the_clients(judged, info):
    runtime = FakeRuntime()
    runtime.agent_sessions.scripts["connect"] = lambda args: ([], info)

    async def scenario():
        stream = ScriptedChannelStream("connect", {"id": "x"}, 1)
        await serve_connect_stream(runtime, FakeSession(), stream)
        return stream

    assert asyncio.run(scenario()).close_info == info


def test_a_client_that_closes_its_stream_closes_the_agents(judged):
    runtime = FakeRuntime()

    async def scenario():
        stream = ScriptedChannelStream("connect", {"id": "x"}, 1)
        serving = asyncio.create_task(
            serve_connect_stream(runtime, FakeSession(), stream)
        )
        await until(lambda: runtime.agent_sessions.streams)
        stream._deliver(("data", b"last"))
        await stream.close()
        await serving
        return runtime.agent_sessions.streams[0]

    far = asyncio.run(scenario())

    assert far.sent_bytes() == b"last"
    assert far.is_close_asked
    assert far.close_info == {"code": "", "params": {}}


def test_a_machine_with_no_socket_is_agent_offline(judged):
    runtime = FakeRuntime(online=())

    async def scenario():
        stream = ScriptedChannelStream("connect", {"id": "x"}, 1)
        await serve_connect_stream(runtime, FakeSession(), stream)
        return stream

    assert asyncio.run(scenario()).close_info == {
        "code": "agent_offline",
        "params": {"device": DEVICE},
    }


def test_a_socket_the_hub_dials_carries_bytes_and_its_end_closes_the_stream(
    judged,
):
    runtime = FakeRuntime()

    async def scenario():
        async def answer(reader, writer):
            data = await reader.readexactly(4)
            writer.write(data.upper())
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(answer, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        judged.verdict = ("", {}, ConnectTarget("", "127.0.0.1", port))
        stream = ScriptedChannelStream("connect", {"is_panel": True}, 1)
        serving = asyncio.create_task(
            serve_connect_stream(runtime, FakeSession(), stream)
        )
        stream._deliver(("data", b"ping"))
        await asyncio.wait_for(serving, 5)
        server.close()
        await server.wait_closed()
        return stream

    stream = asyncio.run(scenario())

    assert stream.sent_bytes() == b"PING"
    assert stream.close_info == {"code": "", "params": {}}


def test_a_dial_nothing_answers_is_connect_failed_refused(judged):
    runtime = FakeRuntime()
    judged.verdict = ("", {}, ConnectTarget("", "127.0.0.1", free_port()))

    async def scenario():
        stream = ScriptedChannelStream("connect", {"id": "nas"}, 1)
        await serve_connect_stream(runtime, FakeSession(), stream)
        return stream

    assert asyncio.run(scenario()).close_info == {
        "code": "connect_failed",
        "params": {"reason": "refused"},
    }


def test_a_dial_that_outlasts_its_timeout_is_connect_failed_timeout(
    judged, monkeypatch
):
    runtime = FakeRuntime()
    judged.verdict = ("", {}, ConnectTarget("", "192.0.2.1", 80))
    monkeypatch.setattr(channel_connect, "CHANNEL_CONNECT_DIAL_TIMEOUT_S", 0.05)

    async def never(host, port):
        await asyncio.sleep(10)

    monkeypatch.setattr(channel_connect.asyncio, "open_connection", never)

    async def scenario():
        stream = ScriptedChannelStream("connect", {"id": "nas"}, 1)
        await serve_connect_stream(runtime, FakeSession(), stream)
        return stream

    assert asyncio.run(scenario()).close_info == {
        "code": "connect_failed",
        "params": {"reason": "timeout"},
    }


@pytest.mark.parametrize(
    "error, reason",
    [
        (ConnectionRefusedError(errno.ECONNREFUSED, "refused"), "refused"),
        (TimeoutError(errno.ETIMEDOUT, "timed out"), "timeout"),
        (OSError(errno.EHOSTUNREACH, "no route"), "unreachable"),
        (OSError(errno.ENETUNREACH, "no network"), "unreachable"),
        (socket.gaierror(-2, "name unknown"), "unreachable"),
    ],
)
def test_each_failed_dial_names_its_reason(error, reason):
    assert dial_reason(error) == reason


class RecordingSocket:
    """The client's websocket: every frame the hub sends, in order."""

    def __init__(self):
        self.frames: list = []

    async def send_text(self, text: str) -> None:
        self.frames.append(json.loads(text))

    async def send_bytes(self, data: bytes) -> None:
        self.frames.append(bytes(data))


def test_the_far_ends_bytes_reach_the_client_only_as_its_credit_allows(judged):
    runtime = FakeRuntime()

    async def scenario():
        websocket = RecordingSocket()
        session = ChannelSession(
            key="client-one",
            role=CHANNEL_ROLE_CLIENT,
            websocket=websocket,
            loop=asyncio.get_running_loop(),
        )
        session.connects = {}
        stream = ChannelStream(session, 1, "connect", {"id": "x"})
        serving = asyncio.create_task(serve_connect_stream(runtime, session, stream))
        await until(lambda: runtime.agent_sessions.streams)
        (far,) = runtime.agent_sessions.streams
        far._deliver(("data", b"a" * 10))
        far._deliver(("data", b"b" * 10))
        await asyncio.sleep(0.05)
        before = [frame for frame in websocket.frames if isinstance(frame, bytes)]
        stream._grant(15)
        await asyncio.sleep(0.05)
        partway = [frame for frame in websocket.frames if isinstance(frame, bytes)]
        stream._grant(100)
        far.finish({"code": "", "params": {}})
        await asyncio.wait_for(serving, 5)
        after = [frame for frame in websocket.frames if isinstance(frame, bytes)]
        return before, partway, after, websocket.frames[-1]

    before, partway, after, last = asyncio.run(scenario())

    stream_id = (1).to_bytes(4, "big")
    assert before == []
    assert b"".join(frame[4:] for frame in partway) == b"a" * 10 + b"b" * 5
    assert all(frame[:4] == stream_id for frame in after)
    assert b"".join(frame[4:] for frame in after) == b"a" * 10 + b"b" * 10
    assert last == {"type": "close", "stream": 1, "code": "", "params": {}}


def test_a_udp_entry_opens_its_agents_udp_connect_and_frames_cross(judged):
    judged.verdict = (
        "",
        {},
        ConnectTarget(DEVICE, "", 53, kind="port", provider=DEVICE, protocol="udp"),
    )
    runtime = FakeRuntime()
    session = FakeSession()

    async def scenario():
        stream = ScriptedChannelStream("connect", {"id": "dns_udp"}, 1)
        serving = asyncio.create_task(serve_connect_stream(runtime, session, stream))
        await until(lambda: runtime.agent_sessions.streams)
        (far,) = runtime.agent_sessions.streams
        held = dict(session.connects)
        stream._deliver(("data", frame_of(40001, b"query")))
        far._deliver(("data", frame_of(40001, b"reply")))
        await until(lambda: far.sent and stream.sent)
        far.finish({"code": "", "params": {}})
        await serving
        return stream, far, held

    stream, far, held = asyncio.run(scenario())

    assert (far.kind, far.args) == ("connect", {"port": 53, "protocol": "udp"})
    assert [split_frame(frame) for frame in far.sent] == [(40001, b"query")]
    assert [split_frame(frame) for frame in stream.sent] == [(40001, b"reply")]
    assert held == {1: ("port", DEVICE)}
    assert session.connects == {}


def test_a_declared_udp_record_is_answered_from_the_hubs_own_socket(judged):
    runtime = FakeRuntime()

    class Echo(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, address):
            self.transport.sendto(data.upper(), address)

    async def scenario():
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            Echo, local_addr=("127.0.0.1", 0)
        )
        port = transport.get_extra_info("sockname")[1]
        judged.verdict = (
            "",
            {},
            ConnectTarget("", "127.0.0.1", port, kind="port", protocol="udp"),
        )
        stream = ScriptedChannelStream("connect", {"id": "dns"}, 1)
        serving = asyncio.create_task(
            serve_connect_stream(runtime, FakeSession(), stream)
        )
        stream._deliver(("data", frame_of(40001, b"ping")))
        await until(lambda: stream.sent)
        await stream.close()
        await asyncio.wait_for(serving, 5)
        transport.close()
        return stream

    stream = asyncio.run(scenario())

    assert [split_frame(frame) for frame in stream.sent] == [(40001, b"PING")]
    assert runtime.agent_sessions.streams == []
