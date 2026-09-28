"""What every bridge to an agent's shell stream shares.

The panel's terminal socket and a client's ``shell`` stream both drive one
agent shell: its output read as it arrives, its end settled when either side
stops, and a later size sent on a ``command {agent, resize}`` stream the
agent closes itself.
"""

import asyncio
import contextlib

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_STREAM_COMMAND,
    CHANNEL_VERB_RESIZE,
)

# The size a shell opens at when the viewer names none.
DEFAULT_COLUMNS = 80
DEFAULT_ROWS = 24


async def shell_output(stream):
    """The shell's output as it arrives, until the stream closes.

    Args:
        stream: The agent's shell stream.

    Yields:
        Each chunk of bytes the agent sent.
    """
    while True:
        item = await stream.recv()
        if item is None:
            return
        if item[0] == "data":
            yield item[1]


async def settle_shell(stream, reader: asyncio.Task, pump: asyncio.Task):
    """Wait for either side to end, then stop both and close the shell stream.

    Args:
        stream: The agent's shell stream.
        reader: The task forwarding the viewer's input; its end means the
            viewer went away.
        pump: The task forwarding the shell's output; its end means the
            shell exited, the agent refused it, or the agent went away.

    Returns:
        What the shell stream closed with, ``{code, params}``, when the shell
        ended first; None when the viewer did.
    """
    done, _ = await asyncio.wait({reader, pump}, return_when=asyncio.FIRST_COMPLETED)
    info = dict(stream.close_info or {}) if pump in done else None
    with contextlib.suppress(AgentOfflineError):
        await stream.close()
    for task in (reader, pump):
        task.cancel()
    for task in (reader, pump):
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return info


async def resize_shell(sessions, device_id: str, shell_id: int, cols: int, rows: int):
    """Tell the agent a shell's new size, on a command stream it closes itself.

    Args:
        sessions: The agents' sessions.
        device_id: The device.
        shell_id: The agent shell stream's id.
        cols: Columns.
        rows: Rows.

    Raises:
        AgentOfflineError: When the device has no channel.
    """
    await sessions.open_stream(
        device_id,
        CHANNEL_STREAM_COMMAND,
        {
            "module": CHANNEL_COMMAND_MODULE_AGENT,
            "verb": CHANNEL_VERB_RESIZE,
            "shell": shell_id,
            "cols": cols,
            "rows": rows,
        },
    )
