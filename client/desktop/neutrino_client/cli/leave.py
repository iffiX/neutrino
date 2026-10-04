"""``nclient leave``: leave one hub.

The binding goes first, and the hub is told once after, from a thread of
its own; its answer, or none, changes nothing. The binding file has one
writer at a time, so a running resident is asked to leave and lets go of
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


def main(hub: str = "") -> int:
    """Leave one hub.

    Args:
        hub: The hub to leave, by its name, its id or its binding's id;
            empty names the one hub joined.

    Returns:
        Process exit status: 0 when the hub is left, 1 otherwise.

    Raises:
        OSError: When no resident runs and the binding file cannot be
            written.
    """
    state = wording.resident_state()
    if state is None:
        return _leave_here(hub)
    return _leave_through_resident(state, hub)


def _leave_here(hub: str) -> int:
    """Leave from this process, with no resident to do it.

    Args:
        hub: What the person named, empty for the one hub joined.

    Returns:
        Process exit status.
    """
    binding = wording.choose_hub(enrollment.bindings(), hub)
    if binding is None:
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


def _leave_through_resident(state: dict, hub: str) -> int:
    """Ask the running resident to leave, so one process writes the file.

    Args:
        state: The resident's state.
        hub: What the person named, empty for the one hub joined.

    Returns:
        Process exit status.
    """
    rows = [row for row in state.get("hubs") or [] if isinstance(row, dict)]
    row = wording.choose_hub(rows, hub)
    if row is None:
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
