"""What the panel's terminal and a client's shell share: the output, the end,
and the resize.

The output is the stream's data items and nothing else; the end is settled
by whichever side stops first, the shell stream closed either way; a resize
is one ``command {agent, resize}`` stream naming the agent's shell. The
sessions are the online reports' ``machine.sessions``, normalized and
oldest first; a session verb is answered by the agent's close, and one the
agent never closes by ``agent_never_reported``.
"""

import asyncio

from neutrino_hub.web import shell_bridge
from neutrino_hub.web.shell_bridge import (
    device_of_session,
    reported_sessions,
    resize_shell,
    session_command,
    settle_shell,
    shell_output,
)
from tests.conftest import FakeChannelSessions, ScriptedChannelStream

DEVICE = "device-one"


def test_the_output_is_the_data_items_until_the_close():
    async def scenario():
        stream = ScriptedChannelStream("shell", {})
        stream._deliver(("data", b"one"))
        stream._deliver(("other", b"skipped"))
        stream._deliver(("data", b"two"))
        await stream.close("", {"exit_code": 0})

        return [chunk async for chunk in shell_output(stream)]

    assert asyncio.run(scenario()) == [b"one", b"two"]


def test_a_shell_that_ends_first_settles_with_its_close():
    async def scenario():
        stream = ScriptedChannelStream("shell", {})
        viewer = asyncio.Event()
        reader = asyncio.create_task(viewer.wait())
        pump = asyncio.create_task(stream.wait_closed())
        stream.finish({"code": "", "params": {"exit_code": 3}})

        info = await settle_shell(stream, reader, pump)
        return info, reader.cancelled()

    info, is_reader_stopped = asyncio.run(scenario())

    assert info == {"code": "", "params": {"exit_code": 3}}
    assert is_reader_stopped


def test_a_viewer_that_ends_first_settles_with_none_and_closes_the_shell():
    async def scenario():
        stream = ScriptedChannelStream("shell", {})
        reader = asyncio.create_task(asyncio.sleep(0))
        pump = asyncio.create_task(stream.wait_closed())

        info = await settle_shell(stream, reader, pump)
        return info, stream.is_close_asked, pump.cancelled()

    info, is_close_asked, is_pump_stopped = asyncio.run(scenario())

    assert info is None
    assert is_close_asked
    assert is_pump_stopped


def test_a_resize_opens_one_command_naming_the_shell():
    sessions = FakeChannelSessions(online=[DEVICE])

    async def scenario():
        await resize_shell(sessions, DEVICE, 4, 120, 40)

    asyncio.run(scenario())

    (stream,) = sessions.streams
    assert stream.kind == "command"
    assert stream.args == {
        "module": "agent",
        "verb": "resize",
        "shell": 4,
        "cols": 120,
        "rows": 40,
    }


def test_the_sessions_are_every_online_report_s_oldest_first(monkeypatch):
    sessions = FakeChannelSessions(online=[DEVICE, "device-two"])
    reports = {
        DEVICE: {
            "machine": {
                "sessions": [
                    {"session_id": "b", "started_at": 1790762400},
                    {"account": "root"},
                    "nonsense",
                ]
            }
        },
        "device-two": {
            "machine": {
                "sessions": [
                    {
                        "session_id": "a",
                        "started_at": 1790758800,
                        "is_persistent": 1,
                    }
                ]
            }
        },
        "device-three": {"machine": {}},
    }
    monkeypatch.setattr(sessions, "reports", lambda: reports)

    listed = reported_sessions(sessions)

    assert [(row["device_id"], row["session_id"]) for row in listed] == [
        ("device-two", "a"),
        (DEVICE, "b"),
    ]
    assert listed[0]["is_persistent"] is True
    assert listed[1]["title"] == ""
    assert device_of_session(sessions, "b") == DEVICE
    assert device_of_session(sessions, "gone") == ""


def test_a_session_verb_is_answered_by_the_agents_close():
    sessions = FakeChannelSessions(online=[DEVICE])
    sessions.scripts["command"] = lambda args: (
        [],
        {"code": "session_unknown", "params": {"session_id": args["session_id"]}},
    )

    info = asyncio.run(
        session_command(sessions, DEVICE, "stop_session", {"session_id": "s"})
    )

    (command,) = sessions.streams
    assert command.args == {
        "module": "agent",
        "verb": "stop_session",
        "session_id": "s",
    }
    assert info == {"code": "session_unknown", "params": {"session_id": "s"}}


def test_a_session_verb_the_agent_never_closes_is_never_reported(monkeypatch):
    sessions = FakeChannelSessions(online=[DEVICE])
    monkeypatch.setattr(shell_bridge, "CHANNEL_CALL_TIMEOUT_S", 0.01)

    info = asyncio.run(
        session_command(
            sessions, DEVICE, "persist", {"session_id": "s", "is_persistent": True}
        )
    )

    assert info == {"code": "agent_never_reported", "params": {}}
