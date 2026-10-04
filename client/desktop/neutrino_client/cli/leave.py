"""``nclient leave``: leave one hub.

The command asks before it leaves, and ``--yes`` leaves without asking. The
binding goes first, and the hub is told once after, from a thread of its
own; its answer, or none, changes nothing. The binding file has one writer
at a time, so a running resident is asked to leave and lets go of
everything that hub published; with none running the leaving happens here.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import sys
import threading

from neutrino_client.cli import wording
from neutrino_client.core import enrollment
from neutrino_client.exceptions import (
    GatewayRefused,
    GatewayUnreachable,
    GatewayUntrusted,
)

LEAVE_WORDS = "left {hub}; this person can join it again with a fresh link"
LEAVE_QUESTION = "leave {hub}? Its forwards, mounts and viewers end [y/N] "


def main(hub: str = "", is_forced: bool = False) -> int:
    """Leave one hub, after asking unless told not to.

    Args:
        hub: The hub to leave, by its name, its id or its binding's id;
            empty names the one hub joined.
        is_forced: Leave without asking.

    Returns:
        Process exit status: 0 when the hub is left, 1 otherwise, the
        answer being no among the reasons.

    Raises:
        OSError: When no resident runs and the binding file cannot be
            written.
    """
    state = wording.resident_state()
    if state is None:
        return _leave_here(hub, is_forced)
    return _leave_through_resident(state, hub, is_forced)


def _is_agreed(row: dict, is_forced: bool) -> bool:
    """Whether the person agreed to leave the hub one row names."""
    if is_forced:
        return True
    if wording.is_confirmed(LEAVE_QUESTION.format(hub=wording.hub_name(row))):
        return True
    print(wording.NOTHING_CHANGED)
    return False


def _leave_here(hub: str, is_forced: bool) -> int:
    """Leave from this process, with no resident to do it.

    Args:
        hub: What the person named, empty for the one hub joined.
        is_forced: Leave without asking.

    Returns:
        Process exit status.
    """
    binding = wording.choose_hub(enrollment.bindings(), hub)
    if binding is None:
        return 1
    if not _is_agreed(binding, is_forced):
        return 1
    enrollment.remove_binding(binding["id"])
    print(LEAVE_WORDS.format(hub=wording.hub_name(binding)))
    if binding.get("is_pending") is not True:
        threading.Thread(
            target=_tell_hub_left, args=(binding,), name="client_leave"
        ).start()
    return 0


def _tell_hub_left(binding: dict) -> None:
    """Post the leave to the hub; any answer, or none, is let go."""
    try:
        enrollment.leave(binding)
    except (GatewayRefused, GatewayUnreachable, GatewayUntrusted):
        pass


def _leave_through_resident(state: dict, hub: str, is_forced: bool) -> int:
    """Ask the running resident to leave, so one process writes the file.

    Args:
        state: The resident's state.
        hub: What the person named, empty for the one hub joined.
        is_forced: Leave without asking.

    Returns:
        Process exit status.
    """
    rows = [row for row in state.get("hubs") or [] if isinstance(row, dict)]
    row = wording.choose_hub(rows, hub)
    if row is None:
        return 1
    if not _is_agreed(row, is_forced):
        return 1
    hub_id = str(row.get("hub_id") or row.get("binding_id", ""))
    answer = wording.request("POST", "/api/leave", {"hub_id": hub_id})
    if answer is None:
        return 1
    _status, reply = answer
    if reply.get("code"):
        print(
            wording.word_code(str(reply["code"]), reply.get("params")), file=sys.stderr
        )
        return 1
    print(LEAVE_WORDS.format(hub=wording.hub_name(row)))
    return 0
