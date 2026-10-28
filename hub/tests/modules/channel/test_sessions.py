"""The session registry over the local channel: one session per binding.

A fake local channel records what a session sends and lets a test play the
transport. What these pin: a frame goes out as ``{frame, session}``, a
state push is one ``state`` frame that remembers the hash, a refusal is the
``session_close`` command, a stream the hub opens is one ``open``
connection whose records come back, the presence the registry keeps after a
session ends, a replaced session left to the transport, the reports kept
per binding, and that a thread's call rides the loop and comes back or is
given a code.
"""

import asyncio
import threading

import pytest

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
)
from neutrino_hub.modules.channel.sessions import (
    ChannelSession,
    ChannelSessionRegistry,
    version_of_software,
)

DEVICE = "device-one"


class FakeLocalChannel:
    """What a session writes through, recorded."""

    def __init__(self):
        self.frames: list = []
        self.commands: list = []
        self.opened: list = []
        self.refuse_command: "str | None" = None

    async def send_frame(self, session, frame, *, is_last=False):
        self.frames.append((session, frame, is_last))

    async def send_command(self, command, **fields):
        self.commands.append((command, fields))
        if self.refuse_command:
            raise StreamRefusedError(self.refuse_command, {})
        return {}

    async def open_stream(self, session, open_body, *, peer_key=""):
        self.opened.append((session, open_body, peer_key))
        return FakeOpenedStream(open_body)


class FakeOpenedStream:
    def __init__(self, open_body):
        self.kind = open_body["kind"]
        self.args = {key: value for key, value in open_body.items() if key != "kind"}
        self.is_accepted = True
        self.is_abandoned = False
        self.close_info = {"code": "", "params": {"exit_code": 0}}
        self._items = [("data", b"out"), None]

    async def recv(self):
        return self._items.pop(0)

    async def send_bytes(self, data):
        self.sent = data


def session(channel, key=DEVICE, role=CHANNEL_ROLE_AGENT, session_id="s1"):
    return ChannelSession(
        key=key,
        role=role,
        session_id=session_id,
        channel=channel,
        loop=asyncio.get_running_loop(),
        name="box",
        software="neutrino_agent/0.6.0",
        address="192.168.100.7",
        listener="main",
    )


def run(coroutine_function):
    return asyncio.run(coroutine_function())


def test_a_frame_goes_out_on_the_sessions_control_stream():
    async def scenario():
        channel = FakeLocalChannel()
        held = session(channel)
        await held.send_json({"type": "welcome", "id": "hub"})
        await held.send_json({"type": "left"}, is_last=True)
        return channel.frames

    assert run(scenario) == [
        ("s1", {"type": "welcome", "id": "hub"}, False),
        ("s1", {"type": "left"}, True),
    ]


def test_push_state_is_one_state_frame_and_remembers_the_hash():
    async def scenario():
        channel = FakeLocalChannel()
        held = session(channel)
        await held.push_state({"hash": "h1", "modules": {}})
        return channel.frames, held.offered_hash

    frames, offered = run(scenario)
    assert frames == [("s1", {"type": "state", "hash": "h1", "modules": {}}, False)]
    assert offered == "h1"


def test_a_refusal_is_the_session_close_command_and_ends_the_session():
    async def scenario():
        channel = FakeLocalChannel()
        held = session(channel)
        await held.refuse("binding_unknown", {})
        await held.refuse("binding_unknown", {})
        return channel.commands, held.is_closed

    commands, is_closed = run(scenario)
    assert commands == [
        ("session_close", {"session": "s1", "code": "binding_unknown", "params": {}})
    ]
    assert is_closed


def test_closing_streams_names_the_binding_the_kind_the_machine_the_row_and_the_shell():
    async def scenario():
        channel = FakeLocalChannel()
        held = session(channel, key="client-a", role=CHANNEL_ROLE_CLIENT)
        await held.close_streams(
            kind="terminal",
            code="session_not_owned",
            params={"session_id": "x"},
            device_id=DEVICE,
            row_id=f"terminal_{DEVICE}",
            session_id="x",
        )
        return channel.commands

    assert run(scenario) == [
        (
            "streams_close",
            {
                "binding_id": "client-a",
                "kind": "terminal",
                "device_id": DEVICE,
                "key": f"terminal_{DEVICE}",
                "session_id": "x",
                "code": "session_not_owned",
                "params": {"session_id": "x"},
            },
        )
    ]


def test_a_stream_the_hub_opens_rides_one_open_connection():
    async def scenario():
        channel = FakeLocalChannel()
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        registry.attach(session(channel))
        info = await registry.run_stream(
            DEVICE, "command", {"module": "agent", "verb": "reboot"}, on_chunk=None
        )
        return channel.opened, info

    opened, info = run(scenario)
    assert opened == [
        ("s1", {"kind": "command", "module": "agent", "verb": "reboot"}, DEVICE)
    ]
    assert info == {"code": "", "params": {"exit_code": 0}}


def test_a_closed_session_sends_nothing_and_opens_nothing():
    async def scenario():
        channel = FakeLocalChannel()
        held = session(channel)
        held.mark_ended()
        refusals = []
        for call in (held.send_json({"type": "state"}), held.open_stream("file", {})):
            try:
                await call
            except AgentOfflineError:
                refusals.append(True)
        return refusals, channel.frames, channel.opened

    assert run(scenario) == ([True, True], [], [])


def test_attach_leaves_a_replaced_session_to_the_transport_and_marks_it_ended():
    async def scenario():
        channel = FakeLocalChannel()
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        first = session(channel, session_id="s1")
        second = session(channel, session_id="s2")
        registry.attach(first)
        registry.attach(second)
        is_first_current = registry.detach(first)
        return (
            channel.commands,
            first.is_closed,
            registry.get(DEVICE) is second,
            is_first_current,
        )

    commands, is_first_closed, is_second_current, is_first_current = run(scenario)
    assert commands == []
    assert is_first_closed
    assert is_second_current
    assert is_first_current is False


def test_a_detach_stamps_the_binding_and_keeps_its_software():
    async def scenario():
        channel = FakeLocalChannel()
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        held = session(channel)
        registry.attach(held)
        is_online_before = registry.is_online(DEVICE)
        registry.detach(held)
        return (
            is_online_before,
            registry.is_online(DEVICE),
            registry.last_seen_at(DEVICE) is not None,
            registry.version_of(DEVICE),
            registry.by_session_id("s1"),
        )

    assert run(scenario) == (True, False, True, "0.6.0", None)


def test_the_registry_finds_a_session_by_the_transports_id():
    async def scenario():
        channel = FakeLocalChannel()
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        held = session(channel, session_id="s7")
        registry.attach(held)
        return registry.by_session_id("s7") is held, registry.by_session_id("s8")

    assert run(scenario) == (True, None)


def test_reports_are_kept_per_binding_and_counted():
    async def scenario():
        channel = FakeLocalChannel()
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        held = session(channel)
        registry.attach(held)
        held.record_report({"state_hash": "h2", "modules": {"samba": {}}})
        held.note_report_recorded()
        return registry.reports(), held.state_hash, registry.report_serial_of(DEVICE)

    reports, state_hash, serial = run(scenario)
    assert reports == {DEVICE: {"state_hash": "h2", "modules": {"samba": {}}}}
    assert state_hash == "h2"
    assert serial == 1


def test_a_binding_with_no_session_is_offline_to_every_ask():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        refused = []
        for call in (
            registry.push_state(DEVICE, {"hash": "h"}),
            registry.open_stream(DEVICE, "file", {}),
        ):
            try:
                await call
            except AgentOfflineError:
                refused.append(True)
        return refused, registry.send_json_from_thread(DEVICE, {"type": "x"})

    assert run(scenario) == ([True, True], False)


def test_a_registry_holds_one_role_and_takes_no_other():
    async def scenario():
        registry = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        with pytest.raises(ValueError):
            registry.attach(session(FakeLocalChannel()))

    run(scenario)


def test_a_push_from_a_thread_rides_the_loop_and_comes_back():
    channel = FakeLocalChannel()
    registry = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:

        async def attach():
            registry.attach(session(channel))

        asyncio.run_coroutine_threadsafe(attach(), loop).result(5)
        registry.push_state_from_thread(DEVICE, {"hash": "h3"})
        assert channel.frames == [("s1", {"type": "state", "hash": "h3"}, False)]
        assert registry.close_streams_from_thread(
            DEVICE, kind="web", code="permission_denied", params={"kind": "web"}
        )
        assert channel.commands[0][0] == "streams_close"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()


def test_a_thread_that_waits_too_long_gets_a_code():
    channel = FakeLocalChannel()
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:

        async def make():
            return session(channel)

        held = asyncio.run_coroutine_threadsafe(make(), loop).result(5)

        async def forever():
            await asyncio.sleep(10)

        with pytest.raises(StreamRefusedError) as refused:
            held.call(forever(), timeout=0.05)
        assert refused.value.code == "agent_never_reported"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()


def test_the_version_is_what_follows_the_slash():
    assert version_of_software("neutrino_agent/0.6.0") == "0.6.0"
    assert version_of_software("neutrino_agent") == ""
