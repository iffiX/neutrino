"""What the panel's terminal and a client's shell share: the output, the end,
and the resize.

The output is the stream's data items and nothing else; the end is settled
by whichever side stops first, the shell stream closed either way; a resize
is one ``command {agent, resize}`` stream naming the agent's shell.
"""

import asyncio

from neutrino_hub.web.shell_bridge import resize_shell, settle_shell, shell_output
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
