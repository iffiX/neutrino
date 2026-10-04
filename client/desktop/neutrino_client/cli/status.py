"""``nclient status``: what this person is bound to, and whether it works.

Three things break independently: the person joined no hub, the resident is
not running, or a hub cannot be reached from here. This says which: the
version, one line per hub joined with its state and which one the AI tools
point at, then the resident's.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import wording
from neutrino_client.core import enrollment
from neutrino_client.core.session import (
    CONNECTION_CONNECTED,
    CONNECTION_PENDING,
    CONNECTION_REPLACED,
)

RESIDENT_RUNNING = "running"
RESIDENT_NOT_RUNNING = "not running; open it: nclient gui"
EXIT_MARK = "exit"


def main(is_json: bool = False) -> int:
    """Report the three things that break independently.

    Args:
        is_json: Print one JSON object instead of the lines.

    Returns:
        Process exit status: 0 when bound, running and every hub connected,
        1 otherwise.
    """
    if is_json:
        return _status_as_json()
    print(f"neutrino-client {CLIENT_VERSION}")
    state = wording.resident_state()
    if state is not None:
        return _status_from_resident(state)
    return _status_from_bindings()


def _status_as_json() -> int:
    """Print the status as one JSON object.

    The object is ``{"version", "is_running", "hubs"}``, each hub
    ``{"hub_id", "hub_name", "gateway_url", "connection",
    "reached_through", "is_exit", "last_error"}``; ``connection`` and
    ``reached_through`` are empty and ``last_error`` None when no resident
    runs to say them.

    Returns:
        Process exit status, as for the lines.
    """
    state = wording.resident_state()
    if state is None:
        exit_hub_id = enrollment.exit_hub_id()
        hubs = [
            {
                "hub_id": str(binding.get("hub_id", "")),
                "hub_name": str(binding.get("hub_name", "")),
                "gateway_url": str(binding.get("gateway_url", "")),
                "connection": "",
                "reached_through": "",
                "is_exit": bool(exit_hub_id) and binding.get("hub_id") == exit_hub_id,
                "last_error": None,
            }
            for binding in enrollment.bindings()
        ]
    else:
        hubs = [
            {
                "hub_id": str(hub.get("hub_id", "")),
                "hub_name": str(hub.get("hub_name", "")),
                "gateway_url": str(hub.get("gateway_url", "")),
                "connection": str(hub.get("connection", "")),
                "reached_through": str(hub.get("reached_through", "") or ""),
                "is_exit": bool(hub.get("is_exit")),
                "last_error": hub.get("last_error") or None,
            }
            for hub in state.get("hubs") or []
            if isinstance(hub, dict)
        ]
    print(
        json.dumps(
            {
                "version": CLIENT_VERSION,
                "is_running": state is not None,
                "hubs": hubs,
            },
            sort_keys=True,
        )
    )
    is_clean = state is not None and bool(hubs)
    return (
        0
        if is_clean and all(hub["connection"] == CONNECTION_CONNECTED for hub in hubs)
        else 1
    )


def _status_from_bindings() -> int:
    """Report from the binding file, with no resident to ask.

    Returns:
        Process exit status: always 1, because no resident runs.
    """
    held = enrollment.bindings()
    exit_hub_id = enrollment.exit_hub_id()
    if not held:
        print(f"hub        {wording.NOT_JOINED}")
    cells = []
    for binding in held:
        cells.append(
            (
                str(binding.get("hub_name", "")),
                str(binding.get("gateway_url", "")),
                "",
                bool(exit_hub_id) and binding.get("hub_id") == exit_hub_id,
            )
        )
    for line in _hub_lines(cells):
        print(line)
    print(f"resident   {RESIDENT_NOT_RUNNING}")
    return 1


def _status_from_resident(state: dict) -> int:
    """Report from the running resident's own account of itself.

    Args:
        state: The page's state payload.

    Returns:
        Process exit status: 0 when bound and every hub connected, 1
        otherwise.
    """
    hubs = [hub for hub in state.get("hubs") or [] if isinstance(hub, dict)]
    if not hubs:
        print(f"hub        {wording.NOT_JOINED}")
        print(f"resident   {RESIDENT_RUNNING}")
        return 1
    is_clean = True
    cells = []
    for hub in hubs:
        connection = str(hub.get("connection", ""))
        cells.append(
            (
                str(hub.get("hub_name", "")),
                str(hub.get("gateway_url", "")),
                f"{connection}{_why(hub)}",
                bool(hub.get("is_exit")),
            )
        )
        is_clean = is_clean and connection == CONNECTION_CONNECTED
    for line in _hub_lines(cells):
        print(line)
    print(f"resident   {RESIDENT_RUNNING}")
    return 0 if is_clean else 1


def _hub_lines(cells: list) -> list:
    """One line per hub, its columns aligned across the hubs joined.

    Args:
        cells: ``(name, url, state, is_exit)`` per hub, in the order joined.

    Returns:
        The lines to print.
    """
    name_width = max((len(name) for name, _url, _state, _is_exit in cells), default=0)
    url_width = max((len(url) for _name, url, _state, _is_exit in cells), default=0)
    lines = []
    for name, url, state, is_exit in cells:
        mark = f"  {EXIT_MARK}" if is_exit else ""
        line = f"hub        {name:<{name_width}}  {url:<{url_width}}  {state}{mark}"
        lines.append(line.rstrip())
    return lines


def _why(hub: dict) -> str:
    """What the resident last had to say about one hub's socket, if anything.

    Args:
        hub: The hub's row of the state payload.

    Returns:
        The wording after a colon, empty when there is nothing to add.
    """
    if hub.get("connection") in (CONNECTION_REPLACED, CONNECTION_PENDING):
        return f": {wording.word_state(str(hub['connection']))}"
    error = hub.get("last_error")
    if not isinstance(error, dict) or not error.get("code"):
        return ""
    return f": {wording.word_code(str(error['code']), error.get('params'))}"
