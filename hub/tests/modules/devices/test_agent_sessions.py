"""The session registry: one socket per device, streams multiplexed on it.

A fake socket records what the hub sends and lets a test play the agent:
answer an open, deliver lines and bytes, grant credit, close. What these
pin is the framing the agent side must match, the credit rule on bytes, the
replaced-socket close, the presence the registry keeps in memory after a
session ends, and that a socket going away fails every stream on it with
``agent_offline`` rather than leaving a caller waiting.
"""

import asyncio
import json
import threading

import pytest

from neutrino_hub.modules.devices import agent_sessions
from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.devices.agent_sessions import (
    AgentSession,
    AgentSessionRegistry,
)
from neutrino_hub.modules.devices.constants import (
    AGENT_SESSION_KIND_AGENT,
    AGENT_SESSION_KIND_CLIENT,
    AGENT_WS_CHUNK_BYTES,
    AGENT_WS_CLOSE_REPLACED,
)

MAC = "aa:bb:cc:dd:ee:ff"


class FakeWebSocket:
    """Records every frame the hub sends; a dead one refuses to send."""

    def __init__(self):
        self.texts: list = []
        self.binaries: list = []
        self.closes: list = []
        self.is_dead = False

    async def send_text(self, text: str) -> None:
        if self.is_dead:
            raise RuntimeError("socket closed")
        self.texts.append(json.loads(text))

    async def send_bytes(self, data: bytes) -> None:
        if self.is_dead:
            raise RuntimeError("socket closed")
        self.binaries.append(data)

    async def close(self, code: int, reason: str = "") -> None:
        self.closes.append((code, reason))

    def sent(self, kind: str) -> list:
        return [message for message in self.texts if message["type"] == kind]


def session(key: str = MAC, socket: "FakeWebSocket | None" = None) -> AgentSession:
    return AgentSession(
        key=key,
        websocket=socket or FakeWebSocket(),
        loop=asyncio.get_running_loop(),
        hostname="box",
        platform={"os": "linux"},
        address="192.168.100.7",
        version="0.2.0",
    )


def answer_open(made: AgentSession, socket: FakeWebSocket, **fields) -> str:
    """Play the agent answering the last open with ``opened``.

    Returns:
        The stream id the hub assigned.
    """
    stream_id = socket.sent("open")[-1]["stream"]
    made.dispatch_text({"type": "opened", "stream": stream_id, **fields})
    return stream_id


async def open_answered(made: AgentSession, socket: FakeWebSocket, kind: str, args):
    """Open a stream while the agent answers it at once."""
    task = asyncio.ensure_future(made.open_stream(kind, args))
    await asyncio.sleep(0)
    answer_open(made, socket)
    return await task


def run(coroutine_function):
    return asyncio.run(coroutine_function())


# --- opening ---


def test_an_open_names_the_stream_the_kind_and_the_credit():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)

        stream = await open_answered(made, socket, "order", {"id": "o1"})

        (opened,) = socket.sent("open")
        assert opened == {
            "type": "open",
            "stream": stream.id,
            "kind": "order",
            "args": {"id": "o1"},
            "credit": agent_sessions.AGENT_WS_STREAM_CREDIT_BYTES,
        }
        assert len(stream.id) == 8
        assert not stream.is_closed

    run(scenario)


def test_a_refused_open_raises_the_agents_code():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        task = asyncio.ensure_future(made.open_stream("shell", {}))
        await asyncio.sleep(0)
        stream_id = socket.sent("open")[-1]["stream"]
        made.dispatch_text(
            {
                "type": "refused",
                "stream": stream_id,
                "code": "stream_unknown",
                "params": {"kind": "shell"},
            }
        )

        with pytest.raises(StreamRefusedError) as refused:
            await task

        assert refused.value.code == "stream_unknown"
        assert refused.value.params == {"kind": "shell"}

    run(scenario)


def test_an_open_nobody_answers_times_out_with_a_code(monkeypatch):
    monkeypatch.setattr(agent_sessions, "AGENT_WS_OPEN_TIMEOUT_S", 0.05)

    async def scenario():
        made = session()

        with pytest.raises(StreamRefusedError) as refused:
            await made.open_stream("order", {})

        assert refused.value.code == "stream_open_timeout"

    run(scenario)


# --- what rides a stream ---


def test_events_and_the_close_arrive_in_order_then_none():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await open_answered(made, socket, "order", {})
        made.dispatch_text({"type": "event", "stream": stream.id, "line": "one"})
        made.dispatch_text({"type": "event", "stream": stream.id, "line": "two"})
        made.dispatch_text(
            {"type": "close", "stream": stream.id, "state": "done", "output": "x"}
        )

        first = await stream.recv()
        second = await stream.recv()
        end = await stream.recv()

        assert first[0] == "event" and first[1]["line"] == "one"
        assert second[1]["line"] == "two"
        assert end is None
        assert stream.is_closed
        assert stream.close_info == {"state": "done", "output": "x"}
        assert await stream.wait_closed() == {"state": "done", "output": "x"}

    run(scenario)


def test_binary_frames_route_by_their_id_prefix_and_earn_credit_back():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await open_answered(made, socket, "file_download", {})
        other = await open_answered(made, socket, "file_download", {})
        made.dispatch_bytes(stream.id.encode() + b"payload")
        made.dispatch_bytes(other.id.encode() + b"elsewhere")
        made.dispatch_bytes(b"deadbeef" + b"nobody")

        kind, data = await stream.recv()

        assert (kind, data) == ("data", b"payload")
        # Reading the bytes is what grants the agent room for more.
        assert socket.sent("credit")[-1] == {
            "type": "credit",
            "stream": stream.id,
            "bytes": len(b"payload"),
        }
        assert (await other.recv())[1] == b"elsewhere"

    run(scenario)


def test_sending_bytes_waits_for_credit_and_chunks_within_it():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await open_answered(made, socket, "file_upload", {})
        payload = bytes(range(256)) * ((AGENT_WS_CHUNK_BYTES // 256) + 8)
        sending = asyncio.ensure_future(stream.send_bytes(payload))
        await asyncio.sleep(0.01)
        # Nothing moves until the agent grants room.
        assert socket.binaries == []

        made.dispatch_text({"type": "credit", "stream": stream.id, "bytes": 1000})
        await asyncio.sleep(0.01)
        assert len(socket.binaries) == 1
        assert socket.binaries[0] == stream.id.encode() + payload[:1000]

        made.dispatch_text(
            {"type": "credit", "stream": stream.id, "bytes": len(payload)}
        )
        await sending

        frames = [frame[len(stream.id) :] for frame in socket.binaries]
        assert b"".join(frames) == payload
        assert all(len(frame) <= AGENT_WS_CHUNK_BYTES for frame in frames)
        assert any(len(frame) == AGENT_WS_CHUNK_BYTES for frame in frames)

    run(scenario)


def test_resize_and_close_go_out_as_their_own_frames():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await open_answered(made, socket, "shell", {})

        await stream.resize(120, 40)
        await stream.close()

        assert socket.sent("resize") == [
            {"type": "resize", "stream": stream.id, "cols": 120, "rows": 40}
        ]
        assert socket.sent("close") == [{"type": "close", "stream": stream.id}]

    run(scenario)


def test_a_message_about_a_stream_nobody_opened_is_ignored():
    async def scenario():
        made = session()

        assert made.dispatch_text({"type": "event", "stream": "nope", "line": "x"})
        assert not made.dispatch_text({"type": "report", "metrics": {}})

    run(scenario)


# --- the socket going away ---


def test_closing_the_session_fails_every_stream_and_pending_open():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await open_answered(made, socket, "order", {})
        pending = asyncio.ensure_future(made.open_stream("command", {}))
        await asyncio.sleep(0)

        await made.close(AGENT_WS_CLOSE_REPLACED, "replaced")

        assert stream.is_closed and stream.is_abandoned
        assert stream.close_info["code"] == "agent_offline"
        with pytest.raises(StreamRefusedError) as refused:
            await pending
        assert refused.value.code == "agent_offline"
        assert socket.closes == [(AGENT_WS_CLOSE_REPLACED, "replaced")]
        with pytest.raises(AgentOfflineError):
            await made.send_json({"type": "state"})

    run(scenario)


def test_a_send_that_fails_reads_as_the_agent_offline():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        socket.is_dead = True

        with pytest.raises(AgentOfflineError):
            await made.send_json({"type": "state"})

    run(scenario)


# --- the registry ---


def test_attach_replaces_an_older_socket_with_the_replaced_code():
    async def scenario():
        registry = AgentSessionRegistry()
        first_socket = FakeWebSocket()
        first = session(socket=first_socket)
        second = session()

        await registry.attach(first)
        await registry.attach(second)

        assert registry.get(MAC) is second
        assert first_socket.closes == [(AGENT_WS_CLOSE_REPLACED, "replaced")]
        assert first.is_closed
        assert registry.is_online(MAC)
        assert registry.keys() == [MAC]

    run(scenario)


def test_detaching_a_replaced_socket_leaves_the_device_online():
    async def scenario():
        registry = AgentSessionRegistry()
        first = session()
        second = session()
        await registry.attach(first)
        await registry.attach(second)

        assert registry.detach(first) is False
        assert registry.is_online(MAC)
        assert registry.last_seen_at(MAC) is None
        assert registry.detach(second) is True
        assert not registry.is_online(MAC)

    run(scenario)


def test_a_detach_stamps_the_device_and_keeps_the_version():
    async def scenario():
        registry = AgentSessionRegistry()
        made = session()
        await registry.attach(made)

        assert registry.version_of(MAC) == "0.2.0"
        assert registry.last_seen_at(MAC) is None
        registry.detach(made)

        assert registry.last_seen_at(MAC)
        assert registry.version_of(MAC) == "0.2.0"

    run(scenario)


def test_a_device_this_hub_has_not_seen_has_no_version_and_no_stamp():
    async def scenario():
        registry = AgentSessionRegistry()

        assert registry.version_of(MAC) == ""
        assert registry.last_seen_at(MAC) is None
        assert registry.version_of(MAC.upper()) == ""

    run(scenario)


def test_a_device_coming_back_is_online_with_no_stamp_again():
    async def scenario():
        registry = AgentSessionRegistry()
        first = session()
        await registry.attach(first)
        registry.detach(first)
        assert registry.last_seen_at(MAC)

        await registry.attach(session())

        assert registry.last_seen_at(MAC) is None

    run(scenario)


def test_reports_are_kept_per_device():
    async def scenario():
        registry = AgentSessionRegistry()
        made = session()
        await registry.attach(made)
        made.record_report(
            {"type": "report", "metrics": {"cpu_percent": 3}, "state_hash": "h"}
        )

        assert registry.reports()[MAC]["metrics"] == {"cpu_percent": 3}
        assert made.state_hash == "h"

    run(scenario)


def test_a_device_with_no_socket_is_offline_to_every_ask():
    async def scenario():
        registry = AgentSessionRegistry()

        with pytest.raises(AgentOfflineError) as offline:
            await registry.open_stream(MAC, "order", {})
        assert offline.value.code == "agent_offline"
        with pytest.raises(AgentOfflineError):
            await registry.push_state(MAC, "h", {})
        with pytest.raises(AgentOfflineError):
            await registry.run_command(MAC, "reboot")
        with pytest.raises(AgentOfflineError):
            registry.run_command_from_thread(MAC, "reboot")

    run(scenario)


def test_push_state_is_one_state_frame():
    async def scenario():
        registry = AgentSessionRegistry()
        socket = FakeWebSocket()
        await registry.attach(session(socket=socket))

        await registry.push_state(MAC, "h1", {"modules": {}})

        assert socket.sent("state") == [
            {"type": "state", "hash": "h1", "desired": {"modules": {}}}
        ]

    run(scenario)


def test_run_command_collects_the_lines_and_returns_the_close():
    async def scenario():
        registry = AgentSessionRegistry()
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)
        lines: list = []
        running = asyncio.ensure_future(
            registry.run_command(MAC, "reboot", {"when": "now"}, lines.append)
        )
        await asyncio.sleep(0)
        stream_id = answer_open(made, socket)
        made.dispatch_text({"type": "event", "stream": stream_id, "line": "going"})
        made.dispatch_text(
            {
                "type": "close",
                "stream": stream_id,
                "exit_code": 0,
                "code": "",
                "params": {},
                "output": "bye",
            }
        )

        info = await running

        assert socket.sent("open")[0]["args"] == {
            "action": "reboot",
            "args": {"when": "now"},
        }
        assert lines == ["going"]
        assert info == {"exit_code": 0, "code": "", "params": {}, "output": "bye"}

    run(scenario)


def test_a_command_cut_off_by_the_socket_reads_as_the_agent_offline():
    async def scenario():
        registry = AgentSessionRegistry()
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)
        running = asyncio.ensure_future(registry.run_command(MAC, "reboot"))
        await asyncio.sleep(0)
        answer_open(made, socket)

        registry.detach(made)

        with pytest.raises(AgentOfflineError):
            await running

    run(scenario)


def test_an_order_from_a_thread_rides_the_loop_and_comes_back():
    async def scenario():
        registry = AgentSessionRegistry()
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)
        lines: list = []
        result: dict = {}

        def worker():
            result["info"] = registry.run_order_from_thread(
                MAC, {"id": "o1", "module": "fakedesk"}, on_line=lines.append
            )

        thread = threading.Thread(target=worker)
        thread.start()
        while not socket.sent("open"):
            await asyncio.sleep(0.01)
        stream_id = answer_open(made, socket)
        made.dispatch_text({"type": "event", "stream": stream_id, "line": "step"})
        made.dispatch_text(
            {"type": "close", "stream": stream_id, "state": "done", "output": "ok"}
        )
        while thread.is_alive():
            await asyncio.sleep(0.01)

        assert socket.sent("open")[0]["kind"] == "order"
        assert socket.sent("open")[0]["args"] == {"id": "o1", "module": "fakedesk"}
        assert lines == ["step"]
        assert result["info"]["state"] == "done"

    run(scenario)


def test_a_thread_that_waits_too_long_gets_a_code_and_the_call_is_cancelled():
    async def scenario():
        registry = AgentSessionRegistry()
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)
        outcome: dict = {}

        def worker():
            try:
                registry.run_command_from_thread(MAC, "reboot", timeout=0.05)
            except StreamRefusedError as refused:
                outcome["code"] = refused.code

        thread = threading.Thread(target=worker)
        thread.start()
        while thread.is_alive():
            await asyncio.sleep(0.01)

        assert outcome["code"] == "agent_never_reported"

    run(scenario)


# --- the two kinds ---


def test_a_session_is_an_agent_unless_told_otherwise():
    async def scenario():
        assert session().kind == AGENT_SESSION_KIND_AGENT
        made = AgentSession(
            key="C1D2",
            kind=AGENT_SESSION_KIND_CLIENT,
            websocket=FakeWebSocket(),
            loop=asyncio.get_running_loop(),
        )
        assert made.kind == AGENT_SESSION_KIND_CLIENT
        assert made.key == "c1d2"

    run(scenario)


def test_a_client_registry_keys_clients_by_id_and_takes_no_agent():
    async def scenario():
        clients = AgentSessionRegistry(kind=AGENT_SESSION_KIND_CLIENT)
        agents = AgentSessionRegistry()
        socket = FakeWebSocket()
        made = AgentSession(
            key="c1",
            kind=AGENT_SESSION_KIND_CLIENT,
            websocket=socket,
            loop=asyncio.get_running_loop(),
            version="0.2.0",
        )
        await clients.attach(made)

        assert clients.is_online("c1")
        assert clients.sessions() == [made]
        assert clients.version_of("c1") == "0.2.0"
        assert not agents.is_online("c1")
        with pytest.raises(ValueError):
            await agents.attach(made)
        with pytest.raises(ValueError):
            await clients.attach(session())

    run(scenario)


def test_a_frame_from_a_thread_lands_on_the_session_without_waiting():
    async def scenario():
        registry = AgentSessionRegistry()
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)

        assert registry.send_json_from_thread(MAC, {"type": "catalog", "hash": "h"})
        assert not registry.send_json_from_thread("11:22:33:44:55:66", {"type": "x"})
        for _ in range(10):
            await asyncio.sleep(0)
        assert socket.sent("catalog") == [{"type": "catalog", "hash": "h"}]

    run(scenario)
