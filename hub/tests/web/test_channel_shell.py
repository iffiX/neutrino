"""A client's shell, bridged to a device's agent shell over the channel.

What these pin: an allowed client reaches the agent with its size, bytes
cross both ways, the agent's exit code closes the client's stream; a client
without ``terminal`` is refused ``permission_denied`` before any agent stream
opens; a device with no channel is ``agent_offline``; a resize reaches the
agent naming the agent's own shell id, and one naming no open shell is
``shell_unknown``.
"""

import asyncio

import pytest

from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web.channel_shell import serve_command_stream, serve_shell_stream
from tests.conftest import FakeChannelSessions, ScriptedChannelStream

DEVICE = "device-one"


class FakeSession:
    def __init__(self, key: str):
        self.key = key
        self.shells: dict = {}


class FakeRuntime:
    def __init__(self, online=(DEVICE,)):
        self.agent_sessions = FakeChannelSessions(online=online)


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
    assert bridged == {1: (DEVICE, shell.id)}
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
    session.shells[3] = (DEVICE, 8)

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
