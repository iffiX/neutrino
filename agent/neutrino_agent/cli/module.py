"""``nagent module``: the Modules panel, from a terminal.

``list`` shows every row the page shows, in the same six-token table.
``install`` and ``uninstall`` post the page's own ask to the running agent
— the click rides up with the next heartbeat, the hub decides, and the
answer comes back as an order — then follow the hub's one operation stream
to done or failed. The SSH server's uninstall asks first, because losing
SSH can lock a person out.

The agent reports errors as ``{"code", "params"}``; the wording lives in
``wording.py``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import sys
import time

from neutrino_agent.cli import wording
from neutrino_agent.constants import (
    AGENT_CLI_FOLLOW_INTERVAL_S,
    AGENT_CLI_FOLLOW_PATIENCE_S,
    AGENT_MODULE_INSTALLER_USER,
)

MODULE_BUILT_IN = "built in"
MODULE_LIST_WAITING = "waiting for the gateway to send its module list"
MODULE_OPERATION_HELD = (
    "an operation is already running on this machine; watch it: "
    "nagent operation --follow"
)
# The page's own words for a vendor-installed row, so both surfaces refuse
# the same way.
MODULE_USER_TIER = "install it on this machine yourself; the hub only manages it"
MODULE_NEVER_STARTED = (
    "the hub has not started the operation; is it reachable? nagent status"
)
MODULE_NOTHING_CHANGED = "nothing was changed"

UNINSTALL_SSH_TITLE = "Uninstall the SSH server?"
UNINSTALL_SSH_BODY = (
    "SSH stops answering on this machine; the agent channel keeps managing it."
)


def main_list() -> int:
    """Print one row per module, as the page shows them.

    Returns:
        Process exit status: 0 with rows, 1 while there is nothing to list.
    """
    state = wording.read_state()
    if state is None:
        return 1
    if not state.get("is_connected"):
        print(wording.NOT_JOINED)
        return 1
    modules = [row for row in state.get("modules", []) if isinstance(row, dict)]
    if not modules:
        print(MODULE_LIST_WAITING)
        return 1
    name_width = max(len(str(row.get("name", ""))) for row in modules)
    title_width = max(len(str(row.get("title", ""))) for row in modules)
    for row in modules:
        line = (
            f"{str(row.get('name', '')):<{name_width}}  "
            f"{str(row.get('title', '')):<{title_width}}  {_row_note(row)}"
        )
        print(line.rstrip())
    return 0


def main_switch(name: str, *, is_enabled: bool, is_waited: bool, is_confirmed: bool):
    """Ask the hub to install or uninstall one module, as the page does.

    Args:
        name: The module name, as ``module list`` prints it.
        is_enabled: True to install, False to uninstall.
        is_waited: Follow the operation stream to done or failed.
        is_confirmed: Skip the SSH server's uninstall confirmation.

    Returns:
        Process exit status: 0 on done, 1 on failed or refused, 2 when the
        name resolves to nothing.
    """
    state = wording.read_state()
    if state is None:
        return 1
    if not state.get("is_connected"):
        print(wording.NOT_JOINED, file=sys.stderr)
        return 1
    row = _find_module(state, name)
    if row is None:
        print(f"no module named {name} on this machine's list", file=sys.stderr)
        return 2
    verb = "install" if is_enabled else "uninstall"
    if row.get("is_native"):
        if is_enabled:
            print(f"{name} is {MODULE_BUILT_IN} on this machine")
            return 0
        print(f"{name} is {MODULE_BUILT_IN}; there is nothing to uninstall")
        return 1
    if not row.get("is_supported"):
        print(f"{name} is {wording.word_state('unsupported')}", file=sys.stderr)
        return 1
    # Refused here rather than posted: the hub takes no order for one of
    # these, and an ask it drops would read as accepted and then never
    # happen.
    if row.get("installer") == AGENT_MODULE_INSTALLER_USER:
        print(f"{name}: {MODULE_USER_TIER}", file=sys.stderr)
        return 1
    if row.get("state") in ("installing", "uninstalling"):
        print(
            f"{name} is mid-step ({wording.word_state(str(row.get('state')))}); "
            "watch it: nagent operation --follow",
            file=sys.stderr,
        )
        return 1
    if wording.is_operation_running(state.get("operation")):
        print(MODULE_OPERATION_HELD, file=sys.stderr)
        return 1
    if is_enabled == (row.get("state") == "installed"):
        print(f"{name} is already {wording.word_state(str(row.get('state')))}")
        return 0
    if not is_enabled and row.get("kind") == "openssh" and not is_confirmed:
        if not _confirm_ssh_uninstall():
            print(MODULE_NOTHING_CHANGED)
            return 1
    answer = wording.request(
        "POST", "/api/module", {"name": name, "is_enabled": is_enabled}
    )
    if answer is None:
        return 1
    _, reply = answer
    if reply.get("code"):
        print(
            wording.word_code(str(reply.get("code")), reply.get("params")),
            file=sys.stderr,
        )
        return 1
    if not is_waited:
        print(f"{name}: {wording.CLI_OPERATION_ACTION_WORDS[verb]}")
        return 0
    return _follow(name, initial_operation=reply.get("operation"))


def _row_note(row: dict) -> str:
    """One module row's standing, worded.

    Args:
        row: The state payload's module row.

    Returns:
        The words after the name and title.
    """
    if not row.get("is_supported"):
        return wording.word_state("unsupported")
    if row.get("is_native"):
        return MODULE_BUILT_IN
    note = wording.word_state(str(row.get("state", "")))
    failure = wording.word_code(str(row.get("code", "")), row.get("params"))
    return f"{note} — {failure}" if failure else note


def _find_module(state: dict, name: str) -> "dict | None":
    """The named module's row, or None.

    Args:
        state: The state payload.
        name: The module name.

    Returns:
        The row, or None when the list does not carry it.
    """
    for row in state.get("modules", []):
        if isinstance(row, dict) and row.get("name") == name:
            return row
    return None


def _confirm_ssh_uninstall() -> bool:
    """Ask the person the question the page's dialog asks.

    Returns:
        True when they answered yes.
    """
    print(UNINSTALL_SSH_TITLE)
    print(UNINSTALL_SSH_BODY)
    try:
        answer = input("Uninstall? [y/N] ")
    except EOFError:
        answer = ""
    return answer.strip().lower() in ("y", "yes")


def _follow(name: str, *, initial_operation: "dict | None") -> int:
    """Follow the hub's operation stream for one posted ask.

    The posted click rides a heartbeat up before the hub opens an order, so
    the stream is watched for an operation that differs from the one that
    stood at post time — for as long as an optimistic step may stand.

    Args:
        name: The module the ask names, for the failure wording.
        initial_operation: The operation object at post time, or None.

    Returns:
        Process exit status: 0 on done, 1 on failed or lost.
    """
    printed = 0
    has_started = False
    patience_ends = time.monotonic() + AGENT_CLI_FOLLOW_PATIENCE_S
    while True:
        time.sleep(AGENT_CLI_FOLLOW_INTERVAL_S)
        state = wording.read_state()
        if state is None:
            return 1
        operation = state.get("operation")
        if not has_started:
            if not operation or operation == initial_operation:
                if time.monotonic() >= patience_ends:
                    print(MODULE_NEVER_STARTED, file=sys.stderr)
                    return 1
                continue
            has_started = True
            print(
                f"{wording.operation_title(operation)} — "
                f"{wording.word_operation(operation)}"
            )
        printed = wording.stream_output(operation, printed)
        operation_state = str(operation.get("state", ""))
        if operation_state == "done":
            print(wording.CLI_OPERATION_WORDS["done"])
            return 0
        if operation_state == "failed":
            row = _find_module(state, name)
            failure = ""
            if row is not None:
                failure = wording.word_code(str(row.get("code", "")), row.get("params"))
            worded = wording.CLI_OPERATION_WORDS["failed"]
            print(f"{worded} — {failure}" if failure else worded, file=sys.stderr)
            return 1
