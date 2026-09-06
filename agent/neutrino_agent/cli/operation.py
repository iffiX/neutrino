"""``nagent operation``: the one operation stream, from a terminal.

The hub holds one operation stream per device and every surface renders
its copy — the panel's drawer, the agent's page, and this command. It
prints the current or last operation's standing and output; ``--follow``
keeps polling until the operation closes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import sys
import time

from neutrino_agent.cli import wording
from neutrino_agent.constants import AGENT_CLI_FOLLOW_INTERVAL_S

OPERATION_NONE = "nothing has run on this machine yet"
OPERATION_GONE = "the operation is gone; the machine was disconnected"


def main(*, is_followed: bool) -> int:
    """Print the current or last operation, following it when asked.

    Args:
        is_followed: Keep polling until the operation closes.

    Returns:
        Process exit status: 0 when the operation is done or still open
        without ``--follow``, 1 when it failed or the agent went away.
    """
    state = wording.read_state()
    if state is None:
        return 1
    operation = state.get("operation")
    if not operation:
        print(OPERATION_NONE)
        return 0
    print(f"{wording.operation_title(operation)} — {wording.word_operation(operation)}")
    printed = wording.stream_output(operation, 0)
    if not is_followed:
        return 1 if operation.get("state") == "failed" else 0
    return _follow(operation, printed)


def _follow(operation: dict, printed: int) -> int:
    """Poll the stream until the operation closes.

    A replaced operation — the hub opened a new order mid-watch — gets its
    own heading and its output from the start.

    Args:
        operation: The operation as it stood when the watch began.
        printed: How much of its output is printed already.

    Returns:
        Process exit status: 0 on done, 1 on failed or lost.
    """
    while str(operation.get("state", "")) not in ("done", "failed"):
        time.sleep(AGENT_CLI_FOLLOW_INTERVAL_S)
        state = wording.read_state()
        if state is None:
            return 1
        fresh = state.get("operation")
        if not fresh:
            print(OPERATION_GONE, file=sys.stderr)
            return 1
        if _heading(fresh) != _heading(operation):
            printed = 0
            print(f"{wording.operation_title(fresh)} — {wording.word_operation(fresh)}")
        operation = fresh
        printed = wording.stream_output(operation, printed)
    if operation.get("state") == "done":
        print(wording.CLI_OPERATION_WORDS["done"])
        return 0
    print(wording.CLI_OPERATION_WORDS["failed"], file=sys.stderr)
    return 1


def _heading(operation: dict) -> tuple:
    """What identifies one operation across polls, output aside."""
    return (
        operation.get("kind", ""),
        operation.get("action", ""),
        operation.get("title", ""),
    )
