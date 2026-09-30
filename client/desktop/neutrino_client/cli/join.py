"""``nclient join``: join the hub an enrollment link names.

A hub joined is one more hub, never a replacement: the binding joins the
ones already held. The binding file has one writer at a time, so a running
resident is asked to join and adopts the hub at once; with none running the
enrollment runs here and the hint says how to open one.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import sys

from neutrino_client.cli import wording
from neutrino_client.core import enrollment

LINK_PROMPT = "paste the enrollment link: "


def main(link: str) -> int:
    """Join the hub the link names.

    Args:
        link: The enrollment link; empty asks for one at a prompt.

    Returns:
        Process exit status: 0 when the hub is joined, 1 otherwise.
    """
    link = link.strip()
    if not link:
        try:
            link = input(LINK_PROMPT).strip()
        except EOFError:
            link = ""
    if not link:
        print(wording.word_code("link_missing"), file=sys.stderr)
        return 1
    state = wording.resident_state()
    if state is None:
        return _join_here(link)
    return _join_through_resident(state, link)


def _join_here(link: str) -> int:
    """Enroll from this process, with no resident to do it.

    Args:
        link: The enrollment link.

    Returns:
        Process exit status.
    """
    try:
        binding = enrollment.enroll(link)
    except enrollment.EnrollmentError as error:
        print(wording.word_code(error.code, error.params), file=sys.stderr)
        return 1
    print(f"joined {binding['gateway_url']}")
    print(wording.word_code("resident_not_running"), file=sys.stderr)
    return 0


def _join_through_resident(state: dict, link: str) -> int:
    """Ask the running resident to join, so one process writes the file.

    Args:
        state: The resident's state, as read before the join.
        link: The enrollment link.

    Returns:
        Process exit status.
    """
    answer = wording.request("POST", "/api/join", {"link": link})
    if answer is None:
        return 1
    _status, reply = answer
    refusal = reply.get("error") if isinstance(reply.get("error"), dict) else reply
    if refusal.get("code"):
        print(
            wording.word_code(str(refusal["code"]), refusal.get("params")),
            file=sys.stderr,
        )
        return 1
    print(f"joined {_joined_url(state, reply)}")
    return 0


def _joined_url(before: dict, after: dict) -> str:
    """The address of the hub this join added.

    Args:
        before: The state as it was before the join.
        after: The state the join answered with.

    Returns:
        The gateway url of the binding the join brought, empty when the
        resident reports no hub.
    """
    held = {str(row.get("binding_id", "")) for row in _hub_rows(before)}
    rows = _hub_rows(after)
    fresh = [row for row in rows if str(row.get("binding_id", "")) not in held]
    if fresh:
        return str(fresh[0].get("gateway_url", ""))
    return str(rows[-1].get("gateway_url", "")) if rows else ""


def _hub_rows(state: dict) -> list:
    """The hubs one state payload lists."""
    return [hub for hub in state.get("hubs") or [] if isinstance(hub, dict)]
