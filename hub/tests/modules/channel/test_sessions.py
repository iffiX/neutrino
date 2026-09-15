"""The session registry: one socket per binding, streams multiplexed on it.

A fake socket records what the hub sends and lets a test play the peer:
open a stream, deliver bytes, grant credit, close. What these pin is the
framing both sides must match, the even ids the hub allots, the first
credit that opens every window, the close as the one place a result goes,
a peer-opened stream handed to its kind's handler or closed
``kind_unknown``, the replaced-socket close, the presence the registry
keeps in memory after a session ends, and that a socket going away fails
every stream on it with ``agent_offline`` rather than leaving a caller
waiting.
"""

import asyncio
import json
import threading

import pytest

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CHUNK_BYTES,
    CHANNEL_CLOSE_REFUSED,
    CHANNEL_CLOSE_REPLACED,
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
    CHANNEL_STREAM_CREDIT_BYTES,
)
from neutrino_hub.modules.channel.sessions import (
    ChannelSession,
    ChannelSessionRegistry,
    version_of_software,
)

DEVICE = "device-one"


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


def session(
    key: str = DEVICE,
    socket: "FakeWebSocket | None" = None,
    role: str = CHANNEL_ROLE_AGENT,
) -> ChannelSession:
    return ChannelSession(
        key=key,
        role=role,
        websocket=socket or FakeWebSocket(),
        loop=asyncio.get_running_loop(),
        name="box",
        software="neutrino_agent/0.3.0",
        address="192.168.100.7",
    )


def frame(stream_id: int, data: bytes) -> bytes:
    """A binary frame as the peer sends it."""
    return stream_id.to_bytes(4, "big") + data


def run(coroutine_function):
    return asyncio.run(coroutine_function())


# --- opening ---


def test_an_open_carries_the_kinds_arguments_and_the_first_credit_follows():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)

        stream = await made.open_stream("command", {"action": "reboot", "args": {}})

        assert socket.texts == [
            {
                "type": "open",
                "stream": stream.id,
                "kind": "command",
                "action": "reboot",
                "args": {},
            },
            {
                "type": "credit",
                "stream": stream.id,
                "bytes": CHANNEL_STREAM_CREDIT_BYTES,
            },
        ]
        assert not stream.is_closed

    run(scenario)


def test_the_hub_allots_even_ids_counting_upward():
    async def scenario():
        made = session()

        ids = [(await made.open_stream("shell", {})).id for _ in range(3)]

        assert ids == [0, 2, 4]

    run(scenario)


def test_an_open_waits_for_no_answer():
    """The peer's close is the answer; nothing else is."""

    async def scenario():
        made = session()

        stream = await asyncio.wait_for(made.open_stream("order", {}), 0.5)

        assert stream.close_info is None

    run(scenario)


# --- what rides a stream ---


def test_bytes_arrive_in_order_then_the_close_then_none():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await made.open_stream("command", {"action": "x"})
        made.dispatch_bytes(frame(stream.id, b"one\n"))
        made.dispatch_bytes(frame(stream.id, b"two\n"))
        made.dispatch_text(
            {
                "type": "close",
                "stream": stream.id,
                "code": "",
                "params": {"exit_code": 0, "output": "x"},
            }
        )

        first = await stream.recv()
        second = await stream.recv()
        end = await stream.recv()

        assert first == ("data", b"one\n")
        assert second == ("data", b"two\n")
        assert end is None
        assert stream.is_closed
        assert stream.close_info == {
            "code": "",
            "params": {"exit_code": 0, "output": "x"},
        }
        assert await stream.wait_closed() == stream.close_info

    run(scenario)


def test_binary_frames_route_by_their_u32_prefix_and_earn_credit_back():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await made.open_stream("file_download", {})
        other = await made.open_stream("file_download", {})
        made.dispatch_bytes(frame(stream.id, b"payload"))
        made.dispatch_bytes(frame(other.id, b"elsewhere"))
        made.dispatch_bytes(frame(77, b"nobody"))
        made.dispatch_bytes(b"\x00")

        kind, data = await stream.recv()

        assert (kind, data) == ("data", b"payload")
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
        stream = await made.open_stream("file_upload", {})
        payload = bytes(range(256)) * ((CHANNEL_CHUNK_BYTES // 256) + 8)
        sending = asyncio.ensure_future(stream.send_bytes(payload))
        await asyncio.sleep(0.01)
        assert socket.binaries == []

        made.dispatch_text({"type": "credit", "stream": stream.id, "bytes": 1000})
        await asyncio.sleep(0.01)
        assert len(socket.binaries) == 1
        assert socket.binaries[0] == frame(stream.id, payload[:1000])

        made.dispatch_text(
            {"type": "credit", "stream": stream.id, "bytes": len(payload)}
        )
        await sending

        frames = [held[4:] for held in socket.binaries]
        assert b"".join(frames) == payload
        assert all(len(held) <= CHANNEL_CHUNK_BYTES for held in frames)
        assert any(len(held) == CHANNEL_CHUNK_BYTES for held in frames)

    run(scenario)


def test_a_close_from_this_side_carries_its_result_and_ends_the_stream():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await made.open_stream("shell", {"cols": 80, "rows": 24})

        await stream.close("", {"done": True})
        await stream.close("again", {})

        assert socket.sent("close") == [
            {"type": "close", "stream": stream.id, "code": "", "params": {"done": True}}
        ]
        assert stream.is_closed
        assert await stream.recv() is None

    run(scenario)


def test_a_stream_the_peer_closed_gets_no_close_back():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await made.open_stream("command", {})
        made.dispatch_text({"type": "close", "stream": stream.id, "params": {}})

        await stream.close()

        assert socket.sent("close") == []

    run(scenario)


def test_only_close_and_credit_are_stream_messages():
    async def scenario():
        made = session()

        assert made.dispatch_text({"type": "close", "stream": 9, "params": {}})
        assert made.dispatch_text({"type": "credit", "stream": 9, "bytes": 1})
        assert not made.dispatch_text({"type": "report", "state_hash": ""})
        assert not made.dispatch_text({"type": "opened", "stream": 0})
        assert not made.dispatch_text({"type": "event", "stream": 0})

    run(scenario)


# --- streams the peer opens ---


def test_a_peer_opened_stream_is_handed_to_its_kinds_handler_with_credit():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        served: list = []

        async def handler(owner, stream):
            served.append((owner, stream.kind, stream.args))
            await stream.close("", {"sha256": "abc"})

        made.stream_handlers["package"] = handler

        stream = await made.accept_stream(
            {"type": "open", "stream": 1, "kind": "package", "module": "samba"}
        )
        await asyncio.sleep(0.01)

        assert stream.id == 1
        assert served == [(made, "package", {"module": "samba"})]
        assert socket.sent("credit") == [
            {"type": "credit", "stream": 1, "bytes": CHANNEL_STREAM_CREDIT_BYTES}
        ]
        assert socket.sent("close") == [
            {"type": "close", "stream": 1, "code": "", "params": {"sha256": "abc"}}
        ]

    run(scenario)


def test_a_kind_with_no_handler_is_closed_kind_unknown():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)

        stream = await made.accept_stream({"type": "open", "stream": 3, "kind": "log"})

        assert stream is None
        assert socket.sent("close") == [
            {
                "type": "close",
                "stream": 3,
                "code": "kind_unknown",
                "params": {"kind": "log"},
            }
        ]
        assert socket.sent("credit") == []

    run(scenario)


def test_an_open_with_no_usable_id_is_dropped():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        made.stream_handlers["package"] = None

        assert await made.accept_stream({"type": "open", "kind": "package"}) is None
        assert (
            await made.accept_stream({"type": "open", "stream": "1", "kind": "x"})
            is None
        )
        assert socket.texts == []

    run(scenario)


def test_a_handler_that_ends_without_closing_leaves_a_closed_stream():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)

        async def handler(owner, stream):
            return None

        made.stream_handlers["service"] = handler

        stream = await made.accept_stream(
            {"type": "open", "stream": 1, "kind": "service"}
        )
        await asyncio.sleep(0.01)

        assert stream.is_closed
        assert socket.sent("close") == [
            {"type": "close", "stream": 1, "code": "", "params": {}}
        ]

    run(scenario)


# --- the state and the refusal ---


def test_push_state_is_one_state_frame_and_remembers_the_hash():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)

        await made.push_state({"hash": "h1", "modules": {}, "desktop": {}})

        assert socket.sent("state") == [
            {"type": "state", "hash": "h1", "modules": {}, "desktop": {}}
        ]
        assert made.offered_hash == "h1"

    run(scenario)


def test_a_refusal_is_the_refused_frame_then_the_refused_close():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)

        await made.refuse("binding_unknown", {})

        assert socket.sent("refused") == [
            {"type": "refused", "code": "binding_unknown", "params": {}}
        ]
        assert socket.closes == [(CHANNEL_CLOSE_REFUSED, "binding_unknown")]
        assert made.is_closed

    run(scenario)


# --- the socket going away ---


def test_closing_the_session_fails_every_stream_as_offline():
    async def scenario():
        socket = FakeWebSocket()
        made = session(socket=socket)
        stream = await made.open_stream("order", {})
        sending = asyncio.ensure_future(stream.send_bytes(b"x"))
        await asyncio.sleep(0)

        await made.close(CHANNEL_CLOSE_REPLACED, "replaced")

        assert stream.is_closed and stream.is_abandoned
        assert stream.close_info["code"] == "agent_offline"
        with pytest.raises(AgentOfflineError):
            await sending
        assert socket.closes == [(CHANNEL_CLOSE_REPLACED, "replaced")]
        with pytest.raises(AgentOfflineError):
            await made.send_json({"type": "state"})

    run(scenario)


def test_a_send_that_fails_reads_as_the_peer_offline():
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
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        first_socket = FakeWebSocket()
        first = session(socket=first_socket)
        second = session()

        await registry.attach(first)
        await registry.attach(second)

        assert registry.get(DEVICE) is second
        assert first_socket.closes == [(CHANNEL_CLOSE_REPLACED, "replaced")]
        assert first_socket.sent("refused") == []
        assert first.is_closed
        assert registry.is_online(DEVICE)
        assert registry.keys() == [DEVICE]

    run(scenario)


def test_detaching_a_replaced_socket_leaves_the_binding_online():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        first = session()
        second = session()
        await registry.attach(first)
        await registry.attach(second)

        assert registry.detach(first) is False
        assert registry.is_online(DEVICE)
        assert registry.last_seen_at(DEVICE) is None
        assert registry.detach(second) is True
        assert not registry.is_online(DEVICE)

    run(scenario)


def test_a_detach_stamps_the_binding_and_keeps_its_software():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        made = session()
        await registry.attach(made)

        assert registry.software_of(DEVICE) == "neutrino_agent/0.3.0"
        assert registry.version_of(DEVICE) == "0.3.0"
        assert registry.last_seen_at(DEVICE) is None
        registry.detach(made)

        assert registry.last_seen_at(DEVICE)
        assert registry.version_of(DEVICE) == "0.3.0"

    run(scenario)


def test_a_binding_this_hub_has_not_seen_has_no_version_and_no_stamp():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)

        assert registry.version_of(DEVICE) == ""
        assert registry.last_seen_at(DEVICE) is None

    run(scenario)


def test_the_version_is_what_follows_the_slash():
    assert version_of_software("neutrino_client/0.3.0") == "0.3.0"
    assert version_of_software("0.3.0") == ""
    assert version_of_software("") == ""


def test_attached_sessions_share_the_registrys_handlers():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        made = session()
        await registry.attach(made)

        async def handler(owner, stream):
            await stream.close()

        registry.stream_handlers["package"] = handler

        assert made.stream_handlers["package"] is handler

    run(scenario)


def test_reports_are_kept_per_binding():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        made = session()
        await registry.attach(made)
        made.record_report(
            {"type": "report", "machine": {"metrics": {"cpu": 3}}, "state_hash": "h"}
        )

        assert registry.reports()[DEVICE]["machine"] == {"metrics": {"cpu": 3}}
        assert made.state_hash == "h"

    run(scenario)


def test_a_binding_with_no_socket_is_offline_to_every_ask():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)

        with pytest.raises(AgentOfflineError) as offline:
            await registry.open_stream(DEVICE, "order", {})
        assert offline.value.code == "agent_offline"
        with pytest.raises(AgentOfflineError):
            await registry.push_state(DEVICE, {"hash": "h"})
        with pytest.raises(AgentOfflineError):
            await registry.run_stream(DEVICE, "command", {})
        with pytest.raises(AgentOfflineError):
            registry.run_stream_from_thread(DEVICE, "command", {})

    run(scenario)


def test_run_stream_hands_chunks_on_and_returns_the_close():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)
        chunks: list = []
        running = asyncio.ensure_future(
            registry.run_stream(
                DEVICE, "command", {"action": "reboot"}, on_chunk=chunks.append
            )
        )
        await asyncio.sleep(0)
        stream_id = socket.sent("open")[0]["stream"]
        made.dispatch_bytes(frame(stream_id, b"going\n"))
        made.dispatch_text(
            {
                "type": "close",
                "stream": stream_id,
                "code": "",
                "params": {"exit_code": 0, "output": "bye"},
            }
        )

        info = await running

        assert socket.sent("open")[0]["action"] == "reboot"
        assert chunks == [b"going\n"]
        assert info == {"code": "", "params": {"exit_code": 0, "output": "bye"}}

    run(scenario)


def test_run_stream_sends_its_payload_under_credit_before_the_close():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)
        running = asyncio.ensure_future(
            registry.run_stream(DEVICE, "file_upload", {"path": "/x"}, payload=b"abc")
        )
        await asyncio.sleep(0.01)
        stream_id = socket.sent("open")[0]["stream"]
        assert socket.binaries == []
        made.dispatch_text({"type": "credit", "stream": stream_id, "bytes": 10})
        await asyncio.sleep(0.01)
        made.dispatch_text({"type": "close", "stream": stream_id, "params": {}})

        info = await running

        assert socket.binaries == [frame(stream_id, b"abc")]
        assert info == {"code": "", "params": {}}

    run(scenario)


def test_a_stream_cut_off_by_the_socket_reads_as_the_peer_offline():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        made = session()
        await registry.attach(made)
        running = asyncio.ensure_future(registry.run_stream(DEVICE, "command", {}))
        await asyncio.sleep(0)

        registry.detach(made)

        with pytest.raises(AgentOfflineError):
            await running

    run(scenario)


def test_a_stream_from_a_thread_rides_the_loop_and_comes_back():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)
        chunks: list = []
        result: dict = {}

        def worker():
            result["info"] = registry.run_stream_from_thread(
                DEVICE,
                "order",
                {"id": "o1", "module": "fakedesk"},
                on_chunk=chunks.append,
            )

        thread = threading.Thread(target=worker)
        thread.start()
        while not socket.sent("open"):
            await asyncio.sleep(0.01)
        stream_id = socket.sent("open")[0]["stream"]
        made.dispatch_bytes(frame(stream_id, b"step\n"))
        made.dispatch_text(
            {"type": "close", "stream": stream_id, "params": {"state": "done"}}
        )
        while thread.is_alive():
            await asyncio.sleep(0.01)

        assert socket.sent("open")[0] == {
            "type": "open",
            "stream": stream_id,
            "kind": "order",
            "id": "o1",
            "module": "fakedesk",
        }
        assert chunks == [b"step\n"]
        assert result["info"]["params"]["state"] == "done"

    run(scenario)


def test_a_thread_that_waits_too_long_gets_a_code_and_the_call_is_cancelled():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        made = session()
        await registry.attach(made)
        outcome: dict = {}

        def worker():
            try:
                registry.run_stream_from_thread(DEVICE, "command", {}, timeout=0.05)
            except StreamRefusedError as refused:
                outcome["code"] = refused.code

        thread = threading.Thread(target=worker)
        thread.start()
        while thread.is_alive():
            await asyncio.sleep(0.01)

        assert outcome["code"] == "agent_never_reported"

    run(scenario)


def test_a_refusal_from_a_thread_turns_a_live_socket_away():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)
        done = threading.Event()

        def worker():
            registry.refuse_from_thread(DEVICE, "binding_unknown")
            registry.refuse_from_thread("nobody", "binding_unknown")
            done.set()

        threading.Thread(target=worker).start()
        while not done.is_set():
            await asyncio.sleep(0.01)

        assert socket.sent("refused") == [
            {"type": "refused", "code": "binding_unknown", "params": {}}
        ]
        assert socket.closes == [(CHANNEL_CLOSE_REFUSED, "binding_unknown")]

    run(scenario)


def test_a_registry_holds_one_role_and_takes_no_other():
    async def scenario():
        clients = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        agents = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        made = session(key="c1", role=CHANNEL_ROLE_CLIENT)
        await clients.attach(made)

        assert clients.is_online("c1")
        assert clients.sessions() == [made]
        assert not agents.is_online("c1")
        with pytest.raises(ValueError):
            await agents.attach(made)
        with pytest.raises(ValueError):
            await clients.attach(session())

    run(scenario)


def test_a_frame_from_a_thread_lands_on_the_session_without_waiting():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        socket = FakeWebSocket()
        made = session(socket=socket)
        await registry.attach(made)

        assert registry.send_json_from_thread(DEVICE, {"type": "state", "hash": "h"})
        assert not registry.send_json_from_thread("nobody", {"type": "x"})
        for _ in range(10):
            await asyncio.sleep(0)
        assert socket.sent("state") == [{"type": "state", "hash": "h"}]

    run(scenario)


def test_a_wait_for_a_report_ends_with_the_next_one_counted():
    async def scenario():
        made = session()
        made.note_report_recorded()
        before = made.report_serial

        async def report_later():
            await asyncio.sleep(0.01)
            made.record_report({"modules": {}})
            made.note_report_recorded()

        asyncio.create_task(report_later())
        is_newer = await made.wait_for_report(before, timeout=2.0)

        assert is_newer
        assert made.report_serial == before + 1

    run(scenario)


def test_a_wait_with_no_report_ends_at_its_timeout():
    async def scenario():
        made = session()

        assert await made.wait_for_report(made.report_serial, timeout=0.02) is False

    run(scenario)
