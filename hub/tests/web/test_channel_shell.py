"""A client's shell, bridged to a device's agent shell over the channel.

What these pin: an allowed client reaches the agent with its size, bytes
cross both ways, the agent's exit code closes the client's stream; a client
without ``terminal`` is refused ``permission_denied`` before any agent stream
opens; a device with no channel is ``agent_offline``; a resize reaches the
agent naming the agent's own shell id, and one naming no open shell is
``shell_unknown``; the ``session_id`` a client generated rides the agent's
open stamped ``owner: client:<id>`` with its ``is_shared``, and ``persist``
and ``stop_session`` reach the machine holding the session unchanged, found
by the client's own bridge or by the reports, ``session_unknown`` when no
machine holds it; a ``persist`` on a session another viewer owns is
``session_not_owned`` and reaches no machine, a ``stop_session`` on one is
sent; a ``shell`` on a session another client owns and has not shared is
``session_not_owned`` and reaches no machine, and joins once it is shared;
the owner rejoins its own; an unshare closes every other client's stream on
the session and not the owner's, and holds for the next join before any
report; a session opened a moment ago is not joined by its id.

The ``exec`` stream: an allowed client reaches the agent's own ``exec``
with ``argv``, ``is_tty``, ``cols`` and ``rows`` and no session; the
client's stdin and its ``eof`` go up in order, the agent's frames come down
with their ``fd`` byte, a frame with nothing after it dropped, and the
agent's close, ``exit_code`` or refusal, is the client's; a client without
``exec``, the default's case, or outside its ``exec`` device list is refused
``permission_denied {kind: exec}`` before any agent stream opens, and the
``terminal`` list does not narrow it; a client that closes first closes the
agent's stream; a ``resize`` naming an ``exec`` with ``is_tty`` reaches the
agent and one naming an ``exec`` without it is closed empty.
"""

import asyncio

import pytest

from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web.channel_shell import (
    serve_command_stream,
    serve_exec_stream,
    serve_shell_stream,
)
from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.web.shell_bridge import ShellSessionLedger
from tests.conftest import FakeChannelSessions, ScriptedChannelStream

DEVICE = "device-one"


class FakeSession:
    def __init__(self, key: str):
        self.key = key
        self.shells: dict = {}
        self.execs: dict = {}


class FakeRuntime:
    def __init__(self, online=(DEVICE,)):
        self.agent_sessions = FakeChannelSessions(online=online)
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.shell_ledger = ShellSessionLedger()


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


async def settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def until(predicate) -> None:
    for _ in range(300):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("never happened")


def test_an_allowed_client_reaches_the_agent_and_bytes_cross_both_ways(config_dir):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    session = FakeSession(client_id)

    async def scenario():
        stream = ScriptedChannelStream(
            "shell", {"device_id": DEVICE, "cols": 132, "rows": 43}, 1
        )
        serving = asyncio.create_task(serve_shell_stream(runtime, session, stream))
        await until(lambda: session.shells)
        (shell,) = runtime.agent_sessions.streams
        bridged = dict(session.shells)

        stream._deliver(("data", b"ls\n"))
        shell._deliver(("data", b"file\n"))
        await settle()
        shell.finish({"code": "", "params": {"exit_code": 7}})
        await serving
        return stream, shell, bridged

    stream, shell, bridged = asyncio.run(scenario())

    assert (shell.kind, shell.args) == ("shell", {"cols": 132, "rows": 43})
    assert bridged == {1: (DEVICE, shell.id, "")}
    assert shell.sent_bytes() == b"ls\n"
    assert stream.sent_bytes() == b"file\n"
    assert stream.close_info == {"code": "", "params": {"exit_code": 7}}
    assert session.shells == {}


def test_a_client_that_closes_its_shell_closes_the_agents(config_dir):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    session = FakeSession(client_id)

    async def scenario():
        stream = ScriptedChannelStream("shell", {"device_id": DEVICE}, 1)
        serving = asyncio.create_task(serve_shell_stream(runtime, session, stream))
        await until(lambda: session.shells)
        await stream.close()
        await serving
        return runtime.agent_sessions.streams[0]

    shell = asyncio.run(scenario())

    assert shell.args == {"cols": 80, "rows": 24}
    assert shell.is_close_asked


def test_a_client_without_terminal_is_refused_before_any_agent_stream(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_permission(client_id, ["web"])
    runtime = FakeRuntime()

    async def scenario():
        stream = ScriptedChannelStream("shell", {"device_id": DEVICE}, 1)
        await serve_shell_stream(runtime, FakeSession(client_id), stream)
        return stream

    stream = asyncio.run(scenario())

    assert stream.close_info == {
        "code": "permission_denied",
        "params": {"kind": "terminal"},
    }
    assert runtime.agent_sessions.streams == []


def test_a_device_outside_the_terminal_filter_is_refused_before_any_agent_stream(
    config_dir,
):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_permission(client_id, ["terminal"], {"terminal": ["another"]})
    runtime = FakeRuntime()

    async def scenario():
        stream = ScriptedChannelStream("shell", {"device_id": DEVICE}, 1)
        await serve_shell_stream(runtime, FakeSession(client_id), stream)
        return stream

    stream = asyncio.run(scenario())

    assert stream.close_info == {
        "code": "permission_denied",
        "params": {"kind": "terminal"},
    }
    assert runtime.agent_sessions.streams == []


def test_a_disabled_or_forgotten_client_is_refused(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_disabled(client_id, True)
    runtime = FakeRuntime()

    async def scenario(key):
        stream = ScriptedChannelStream("shell", {"device_id": DEVICE}, 1)
        await serve_shell_stream(runtime, FakeSession(key), stream)
        return stream.close_info["code"]

    assert asyncio.run(scenario(client_id)) == "client_disabled"
    assert asyncio.run(scenario("nobody")) == "binding_unknown"
    assert runtime.agent_sessions.streams == []


def test_a_device_with_no_channel_is_agent_offline(config_dir):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime(online=())

    async def scenario():
        stream = ScriptedChannelStream("shell", {"device_id": DEVICE}, 1)
        await serve_shell_stream(runtime, FakeSession(client_id), stream)
        return stream

    stream = asyncio.run(scenario())

    assert stream.close_info == {"code": "agent_offline", "params": {"device": DEVICE}}


def test_a_resize_reaches_the_agent_naming_its_own_shell_id(config_dir):
    runtime = FakeRuntime()
    session = FakeSession("alice")
    session.shells[3] = (DEVICE, 8, "")

    async def scenario():
        stream = ScriptedChannelStream(
            "command",
            {"module": "agent", "verb": "resize", "shell": 3, "cols": 100, "rows": 30},
            5,
        )
        await serve_command_stream(runtime, session, stream)
        return stream

    stream = asyncio.run(scenario())

    (command,) = runtime.agent_sessions.streams
    assert command.args == {
        "module": "agent",
        "verb": "resize",
        "shell": 8,
        "cols": 100,
        "rows": 30,
    }
    assert stream.close_info == {"code": "", "params": {}}


def test_a_resize_naming_no_open_shell_is_shell_unknown(config_dir):
    runtime = FakeRuntime()

    async def scenario(args):
        stream = ScriptedChannelStream("command", args, 5)
        await serve_command_stream(runtime, FakeSession("alice"), stream)
        return stream.close_info

    unknown = asyncio.run(
        scenario({"module": "agent", "verb": "resize", "shell": 9, "cols": 1})
    )
    other = asyncio.run(scenario({"module": "agent", "verb": "reboot"}))

    assert unknown == {"code": "shell_unknown", "params": {"shell": 9}}
    assert other["code"] == "verb_unknown"
    assert runtime.agent_sessions.streams == []


def reporting(sessions: dict) -> dict:
    """Latest reports naming each device's shell sessions by id."""
    return {
        device: {"machine": {"sessions": [{"session_id": sid} for sid in held]}}
        for device, held in sessions.items()
    }


def closing_empty(args):
    return [], {"code": "", "params": {}}


def test_the_session_id_rides_the_agents_open(config_dir):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    session = FakeSession(client_id)

    async def scenario():
        stream = ScriptedChannelStream(
            "shell", {"device_id": DEVICE, "session_id": "s-1"}, 1
        )
        serving = asyncio.create_task(serve_shell_stream(runtime, session, stream))
        await until(lambda: session.shells)
        bridged = dict(session.shells)
        await stream.close()
        await serving
        return runtime.agent_sessions.streams[0], bridged

    shell, bridged = asyncio.run(scenario())

    assert shell.args == {
        "cols": 80,
        "rows": 24,
        "session_id": "s-1",
        "owner": f"client:{client_id}",
        "is_shared": False,
    }
    assert bridged == {1: (DEVICE, shell.id, "s-1")}


def test_a_shared_open_says_so_to_the_agent(config_dir):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    session = FakeSession(client_id)

    async def scenario():
        stream = ScriptedChannelStream(
            "shell",
            {"device_id": DEVICE, "session_id": "s-1", "is_shared": True},
            1,
        )
        serving = asyncio.create_task(serve_shell_stream(runtime, session, stream))
        await until(lambda: session.shells)
        await stream.close()
        await serving
        return runtime.agent_sessions.streams[0]

    assert asyncio.run(scenario()).args["is_shared"] is True


def test_a_persist_on_a_session_another_viewer_owns_is_session_not_owned(
    config_dir, monkeypatch
):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    runtime.agent_sessions.scripts["command"] = closing_empty
    reports = {
        DEVICE: {"machine": {"sessions": [{"session_id": "s-2", "owner": "hub"}]}}
    }
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)

    async def scenario(verb: str):
        stream = ScriptedChannelStream(
            "command",
            {"module": "agent", "verb": verb, "session_id": "s-2", "is_shared": True},
            5,
        )
        await serve_command_stream(runtime, FakeSession(client_id), stream)
        return stream

    persist = asyncio.run(scenario("persist"))
    assert persist.close_info == {
        "code": "session_not_owned",
        "params": {"session_id": "s-2"},
    }
    assert runtime.agent_sessions.streams == []

    stop = asyncio.run(scenario("stop_session"))
    assert stop.close_info == {"code": "", "params": {}}
    assert [stream.args["verb"] for stream in runtime.agent_sessions.streams] == [
        "stop_session"
    ]


def test_a_persist_reaches_the_machine_its_bridge_names(config_dir):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    runtime.agent_sessions.scripts["command"] = closing_empty
    session = FakeSession(client_id)
    session.shells[3] = (DEVICE, 8, "s-1")

    async def scenario():
        stream = ScriptedChannelStream(
            "command",
            {
                "module": "agent",
                "verb": "persist",
                "session_id": "s-1",
                "is_persistent": True,
            },
            5,
        )
        await serve_command_stream(runtime, session, stream)
        return stream

    stream = asyncio.run(scenario())

    (command,) = runtime.agent_sessions.streams
    assert command.args == {
        "module": "agent",
        "verb": "persist",
        "session_id": "s-1",
        "is_persistent": True,
    }
    assert stream.close_info == {"code": "", "params": {}}


def test_a_stop_reaches_the_machine_whose_report_lists_the_session(
    config_dir, monkeypatch
):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    runtime.agent_sessions.scripts["command"] = closing_empty
    monkeypatch.setattr(
        runtime.agent_sessions, "reports", lambda: reporting({DEVICE: ["s-2"]})
    )

    async def scenario():
        stream = ScriptedChannelStream(
            "command",
            {"module": "agent", "verb": "stop_session", "session_id": "s-2"},
            5,
        )
        await serve_command_stream(runtime, FakeSession(client_id), stream)
        return stream

    stream = asyncio.run(scenario())

    (command,) = runtime.agent_sessions.streams
    assert command.args == {
        "module": "agent",
        "verb": "stop_session",
        "session_id": "s-2",
    }
    assert stream.close_info == {"code": "", "params": {}}


def test_the_agents_refusal_of_a_session_verb_is_the_clients(config_dir, monkeypatch):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    runtime.agent_sessions.scripts["command"] = lambda args: (
        [],
        {"code": "session_unknown", "params": {"session_id": "s-2"}},
    )
    monkeypatch.setattr(
        runtime.agent_sessions, "reports", lambda: reporting({DEVICE: ["s-2"]})
    )

    async def scenario():
        stream = ScriptedChannelStream(
            "command",
            {"module": "agent", "verb": "stop_session", "session_id": "s-2"},
            5,
        )
        await serve_command_stream(runtime, FakeSession(client_id), stream)
        return stream.close_info

    assert asyncio.run(scenario()) == {
        "code": "session_unknown",
        "params": {"session_id": "s-2"},
    }


def test_a_session_no_machine_holds_is_session_unknown(config_dir):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()

    async def scenario():
        stream = ScriptedChannelStream(
            "command",
            {"module": "agent", "verb": "stop_session", "session_id": "gone"},
            5,
        )
        await serve_command_stream(runtime, FakeSession(client_id), stream)
        return stream.close_info

    assert asyncio.run(scenario()) == {
        "code": "session_unknown",
        "params": {"session_id": "gone"},
    }
    assert runtime.agent_sessions.streams == []


def test_a_session_verb_on_a_machine_outside_the_terminal_filter_is_refused(
    config_dir, monkeypatch
):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_permission(client_id, ["terminal"], {"terminal": ["another"]})
    runtime = FakeRuntime()
    monkeypatch.setattr(
        runtime.agent_sessions, "reports", lambda: reporting({DEVICE: ["s-2"]})
    )

    async def scenario():
        stream = ScriptedChannelStream(
            "command",
            {"module": "agent", "verb": "persist", "session_id": "s-2"},
            5,
        )
        await serve_command_stream(runtime, FakeSession(client_id), stream)
        return stream.close_info

    assert asyncio.run(scenario()) == {
        "code": "permission_denied",
        "params": {"kind": "terminal"},
    }
    assert runtime.agent_sessions.streams == []


def test_a_client_resuming_a_session_asks_the_agent_to_resume_it(config_dir):
    client_id = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    session = FakeSession(client_id)

    async def scenario():
        stream = ScriptedChannelStream(
            "shell", {"device_id": DEVICE, "session_id": "s-1", "is_resumed": True}, 1
        )
        serving = asyncio.create_task(serve_shell_stream(runtime, session, stream))
        await until(lambda: session.shells)
        await stream.close()
        await serving
        return runtime.agent_sessions.streams[0]

    shell = asyncio.run(scenario())

    assert shell.args == {
        "cols": 80,
        "rows": 24,
        "session_id": "s-1",
        "owner": f"client:{client_id}",
        "is_shared": False,
        "is_resumed": True,
    }


class ViewerSession(FakeSession):
    """A client's socket holding shells, recording the streams the hub closes."""

    def __init__(self, key: str):
        super().__init__(key)
        self.loop = None
        self.closed: list = []

    async def close_stream(self, stream_id, code, params=None) -> bool:
        self.closed.append((stream_id, code, dict(params or {})))
        return True

    def close_stream_from_thread(self, stream_id, code, params=None) -> bool:
        self.closed.append((stream_id, code, dict(params or {})))
        return True


class Viewers:
    """The clients' sockets, as the hub's registry lists them."""

    def __init__(self, *sessions):
        self._sessions = list(sessions)

    def sessions(self) -> list:
        return list(self._sessions)


def owned(session_id: str, owner: str, is_shared: bool) -> dict:
    """A report holding one session on the device."""
    return {
        DEVICE: {
            "machine": {
                "sessions": [
                    {"session_id": session_id, "owner": owner, "is_shared": is_shared}
                ]
            }
        }
    }


def shell_open(session_id: str, **fields) -> dict:
    return {"device_id": DEVICE, "session_id": session_id, **fields}


async def joined(runtime, session, args: dict) -> tuple:
    """Serve one shell open until it reaches the agent or is refused."""
    stream = ScriptedChannelStream("shell", args, 1)
    serving = asyncio.create_task(serve_shell_stream(runtime, session, stream))
    await until(lambda: session.shells or stream.close_info is not None)
    reached = bool(session.shells)
    if reached:
        await stream.close()
    await serving
    return reached, stream.close_info


def test_a_join_of_another_clients_unshared_session_is_refused_until_shared(
    config_dir, monkeypatch
):
    registry = ClientRegistry()
    alice = registry.create("alice")
    bob = registry.create("bob")
    runtime = FakeRuntime()
    reports = owned("s-a", f"client:{alice}", False)
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)

    refused = asyncio.run(
        joined(runtime, FakeSession(bob), shell_open("s-a", is_resumed=True))
    )
    assert refused == (
        False,
        {"code": "session_not_owned", "params": {"session_id": "s-a"}},
    )
    assert runtime.agent_sessions.streams == []

    reports.update(owned("s-a", f"client:{alice}", True))
    reached, _ = asyncio.run(
        joined(runtime, FakeSession(bob), shell_open("s-a", is_resumed=True))
    )
    assert reached
    (shell,) = runtime.agent_sessions.streams
    assert shell.args["session_id"] == "s-a"


def test_the_owner_rejoins_its_own_unshared_session(config_dir, monkeypatch):
    alice = ClientRegistry().create("alice")
    runtime = FakeRuntime()
    reports = owned("s-a", f"client:{alice}", False)
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)

    reached, _ = asyncio.run(
        joined(runtime, FakeSession(alice), shell_open("s-a", is_resumed=True))
    )

    assert reached
    assert runtime.agent_sessions.streams[0].args["is_resumed"] is True


def test_an_unshare_closes_the_other_clients_streams_and_holds_before_the_report(
    config_dir, monkeypatch
):
    registry = ClientRegistry()
    alice = registry.create("alice")
    bob = registry.create("bob")
    runtime = FakeRuntime()
    runtime.agent_sessions.scripts["command"] = closing_empty
    reports = owned("s-a", f"client:{alice}", True)
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)
    owner = ViewerSession(alice)
    owner.shells[2] = (DEVICE, 10, "s-a")
    viewer = ViewerSession(bob)
    viewer.shells[4] = (DEVICE, 11, "s-a")
    viewer.shells[6] = (DEVICE, 12, "s-other")
    runtime.client_sessions = Viewers(owner, viewer)

    async def unshare():
        for held in (owner, viewer):
            held.loop = asyncio.get_running_loop()
        stream = ScriptedChannelStream(
            "command",
            {
                "module": "agent",
                "verb": "persist",
                "session_id": "s-a",
                "is_shared": False,
            },
            5,
        )
        await serve_command_stream(runtime, owner, stream)
        return stream.close_info

    assert asyncio.run(unshare()) == {"code": "", "params": {}}
    assert viewer.closed == [(4, "session_not_owned", {"session_id": "s-a"})]
    assert owner.closed == []

    again = asyncio.run(
        joined(runtime, FakeSession(bob), shell_open("s-a", is_resumed=True))
    )
    assert again[1] == {"code": "session_not_owned", "params": {"session_id": "s-a"}}
    assert [stream.kind for stream in runtime.agent_sessions.streams] == ["command"]


def test_a_session_opened_a_moment_ago_is_not_joined_by_its_id(config_dir):
    registry = ClientRegistry()
    alice = registry.create("alice")
    bob = registry.create("bob")
    runtime = FakeRuntime()

    opened = asyncio.run(joined(runtime, FakeSession(alice), shell_open("s-new")))
    guessed = asyncio.run(joined(runtime, FakeSession(bob), shell_open("s-new")))

    assert opened[0] is True
    assert guessed == (
        False,
        {"code": "session_not_owned", "params": {"session_id": "s-new"}},
    )
    assert len(runtime.agent_sessions.streams) == 1


ARGV = ["sh", "-c", "echo out; echo err >&2; exit 7"]


def exec_allowed(kinds=("exec",), devices=None) -> str:
    """A client whose own permission names the kinds."""
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_permission(client_id, list(kinds), devices)
    return client_id


def exec_open(**fields) -> dict:
    return {"device_id": DEVICE, "argv": ARGV, **fields}


async def refused_exec(runtime, client_id, args) -> dict:
    stream = ScriptedChannelStream("exec", args, 1)
    await serve_exec_stream(runtime, FakeSession(client_id), stream)
    return stream.close_info


def test_an_exec_reaches_the_agent_and_relays_stdin_eof_and_both_outputs(
    config_dir,
):
    client_id = exec_allowed()
    runtime = FakeRuntime()
    session = FakeSession(client_id)

    async def scenario():
        stream = ScriptedChannelStream(
            "exec", exec_open(is_tty=False, cols=100, rows=30), 1
        )
        serving = asyncio.create_task(serve_exec_stream(runtime, session, stream))
        await until(lambda: session.execs)
        (command,) = runtime.agent_sessions.streams
        bridged = dict(session.execs)

        stream._deliver(("data", b"hello"))
        stream._deliver(("eof", b""))
        command._deliver(("data", b"\x01out\n"))
        command._deliver(("data", b"\x02err\n"))
        command._deliver(("data", b"\x02"))
        await settle()
        command.finish({"code": "", "params": {"exit_code": 7}})
        await serving
        return stream, command, bridged

    stream, command, bridged = asyncio.run(scenario())

    assert (command.kind, command.args) == (
        "exec",
        {"argv": ARGV, "is_tty": False, "cols": 100, "rows": 30},
    )
    assert bridged == {1: (DEVICE, command.id, False)}
    assert command.sent == [b"hello"]
    assert command.eofs == [1]
    assert stream.sent == [b"\x01out\n", b"\x02err\n"]
    assert stream.close_info == {"code": "", "params": {"exit_code": 7}}
    assert session.execs == {} and session.shells == {}


def test_an_exec_with_a_tty_names_it_and_its_size(config_dir):
    client_id = exec_allowed()
    runtime = FakeRuntime()
    runtime.agent_sessions.scripts["exec"] = lambda args: (
        [("data", b"\x01top\r\n")],
        {"code": "", "params": {"exit_code": 0}},
    )

    async def scenario():
        stream = ScriptedChannelStream(
            "exec", exec_open(argv=["top"], is_tty=True, cols=132, rows=43), 1
        )
        await serve_exec_stream(runtime, FakeSession(client_id), stream)
        return stream

    stream = asyncio.run(scenario())

    (command,) = runtime.agent_sessions.streams
    assert command.args == {"argv": ["top"], "is_tty": True, "cols": 132, "rows": 43}
    assert stream.sent == [b"\x01top\r\n"]
    assert stream.close_info == {"code": "", "params": {"exit_code": 0}}


def test_the_agents_refusal_closes_the_clients_exec(config_dir):
    client_id = exec_allowed()
    runtime = FakeRuntime()
    runtime.agent_sessions.scripts["exec"] = lambda args: (
        [],
        {"code": "shell_program_unusable", "params": {"path": "nope"}},
    )

    closed = asyncio.run(refused_exec(runtime, client_id, exec_open(argv=["nope"])))

    assert closed == {"code": "shell_program_unusable", "params": {"path": "nope"}}


def test_a_client_without_exec_is_refused_before_any_agent_stream(config_dir):
    registry = ClientRegistry()
    by_default = registry.create("alice")
    shell_only = exec_allowed(kinds=("terminal",))
    runtime = FakeRuntime()

    refusals = [
        asyncio.run(refused_exec(runtime, client_id, exec_open()))
        for client_id in (by_default, shell_only)
    ]

    assert refusals == [{"code": "permission_denied", "params": {"kind": "exec"}}] * 2
    assert runtime.agent_sessions.streams == []


def test_the_exec_device_list_applies_and_the_terminal_list_does_not(config_dir):
    outside = exec_allowed(devices={"exec": ["another"]})
    inside = exec_allowed(
        kinds=("terminal", "exec"),
        devices={"terminal": ["another"], "exec": [DEVICE]},
    )
    runtime = FakeRuntime()
    runtime.agent_sessions.scripts["exec"] = lambda args: (
        [],
        {"code": "", "params": {"exit_code": 0}},
    )

    refused = asyncio.run(refused_exec(runtime, outside, exec_open()))
    allowed = asyncio.run(refused_exec(runtime, inside, exec_open()))

    assert refused == {"code": "permission_denied", "params": {"kind": "exec"}}
    assert allowed == {"code": "", "params": {"exit_code": 0}}
    assert len(runtime.agent_sessions.streams) == 1


def test_an_exec_on_a_device_with_no_channel_is_agent_offline(config_dir):
    client_id = exec_allowed()
    runtime = FakeRuntime(online=())

    closed = asyncio.run(refused_exec(runtime, client_id, exec_open()))

    assert closed == {"code": "agent_offline", "params": {"device": DEVICE}}


def test_a_client_that_closes_its_exec_closes_the_agents(config_dir):
    client_id = exec_allowed()
    runtime = FakeRuntime()
    session = FakeSession(client_id)

    async def scenario():
        stream = ScriptedChannelStream("exec", exec_open(), 1)
        serving = asyncio.create_task(serve_exec_stream(runtime, session, stream))
        await until(lambda: session.execs)
        await stream.close()
        await serving
        return runtime.agent_sessions.streams[0]

    command = asyncio.run(scenario())

    assert command.is_close_asked
    assert session.execs == {}


def test_a_resize_reaches_an_exec_with_a_tty_and_not_one_without(config_dir):
    runtime = FakeRuntime()
    session = FakeSession("alice")
    session.execs[3] = (DEVICE, 8, True)
    session.execs[5] = (DEVICE, 10, False)

    async def scenario(shell):
        stream = ScriptedChannelStream(
            "command",
            {"module": "agent", "verb": "resize", "shell": shell, "cols": 90},
            7,
        )
        await serve_command_stream(runtime, session, stream)
        return stream.close_info

    sized = asyncio.run(scenario(3))
    ignored = asyncio.run(scenario(5))

    (command,) = runtime.agent_sessions.streams
    assert command.args == {
        "module": "agent",
        "verb": "resize",
        "shell": 8,
        "cols": 90,
        "rows": 24,
    }
    assert sized == ignored == {"code": "", "params": {}}
