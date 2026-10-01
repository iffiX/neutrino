"""What the panel's terminal and a client's shell share: the output, the end,
and the resize.

The output is the stream's data items and nothing else; the end is settled
by whichever side stops first, the shell stream closed either way; a resize
is one ``command {agent, resize}`` stream naming the agent's shell. The
sessions are the online reports' ``machine.sessions``, normalized and
oldest first; a session verb is answered by the agent's close, and one the
agent never closes by ``agent_never_reported``. Which sessions a viewer sees:
its own and the shared ones on machines it has terminal rights on, each
saying whether the viewer owns it; a persist is refused only for a session
reported under another owner.
"""

import asyncio
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web import shell_bridge
from neutrino_hub.web.shell_bridge import (
    device_of_session,
    is_persist_refused,
    persist_flags,
    reported_sessions,
    sessions_for,
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


@pytest.fixture
def viewers(tmp_path, monkeypatch):
    """Two machines, three clients and the sessions the machines report."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    devices = DeviceRegistry()
    lepton = devices.create("lepton")
    xenon = devices.create("xenon")
    clients = ClientRegistry()
    alice = clients.create("alice")
    bob = clients.create("bob")
    carol = clients.create("carol")
    clients.set_permission(bob, ["terminal"], {"terminal": [xenon.id]})
    clients.set_disabled(carol, True)
    agent_sessions = FakeChannelSessions(online=[lepton.id, xenon.id])
    reports = {
        lepton.id: held(
            ("s1", "hub", False),
            ("s2", f"client:{alice}", False),
            ("s3", f"client:{bob}", True),
        ),
        xenon.id: held(("s4", "hub", True), ("s5", f"client:{alice}", True)),
    }
    monkeypatch.setattr(agent_sessions, "reports", lambda: reports)
    runtime = SimpleNamespace(agent_sessions=agent_sessions, device_hostname={})
    return runtime, alice, bob, carol, lepton


def held(*sessions) -> dict:
    """A report holding sessions given as ``(id, owner, is_shared)``."""
    return {
        "machine": {
            "sessions": [
                {
                    "session_id": session_id,
                    "started_at": int(session_id[1:]),
                    "owner": owner,
                    "is_shared": is_shared,
                }
                for session_id, owner, is_shared in sessions
            ]
        }
    }


def seen(rows: list) -> list:
    return [(row["session_id"], row["is_owned"]) for row in rows]


def test_the_panel_sees_its_own_sessions_and_every_shared_one(viewers):
    runtime, *_ = viewers

    assert seen(sessions_for(runtime, "hub")) == [
        ("s1", True),
        ("s3", False),
        ("s4", True),
        ("s5", False),
    ]


def test_a_client_sees_its_own_sessions_and_the_shared_ones(viewers):
    runtime, alice, *_ = viewers

    rows = sessions_for(runtime, f"client:{alice}")

    assert seen(rows) == [("s2", True), ("s3", False), ("s4", False), ("s5", True)]
    assert rows[0]["device_name"] == "lepton"


def test_a_client_sees_shared_sessions_only_where_it_has_terminal_rights(viewers):
    runtime, _, bob, carol, _ = viewers

    assert seen(sessions_for(runtime, f"client:{bob}")) == [
        ("s3", True),
        ("s4", False),
        ("s5", False),
    ]
    assert sessions_for(runtime, f"client:{carol}") == []


def test_a_persist_is_refused_only_on_a_session_another_viewer_owns(viewers):
    runtime, alice, _, _, lepton = viewers
    sessions = runtime.agent_sessions

    assert is_persist_refused(sessions, lepton.id, "s2", "hub") is True
    assert is_persist_refused(sessions, lepton.id, "s2", f"client:{alice}") is False
    assert is_persist_refused(sessions, lepton.id, "new", "hub") is False


def test_a_persist_names_only_the_flags_it_was_given():
    assert persist_flags({"is_shared": 1}) == {"is_shared": True}
    assert persist_flags({"is_persistent": False, "data": "x"}) == {
        "is_persistent": False
    }


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
