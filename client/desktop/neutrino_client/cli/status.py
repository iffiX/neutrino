"""``nclient status``: what this person is bound to, and whether it works.

Three things break independently: the person joined no hub, the resident is
not running, or a hub cannot be reached from here. This says which: the
version, one line per hub joined with its state line, as the window draws
it, and which one the AI tools point at, then the resident's.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import math
import time

from neutrino_client import CLIENT_VERSION, words
from neutrino_client.cli import wording
from neutrino_client.constants import CLIENT_DEFAULT_LANGUAGE
from neutrino_client.core import enrollment
from neutrino_client.core.session import (
    CONNECTION_CONNECTED,
    CONNECTION_REPLACED,
    CONNECTION_WAITING,
    WAIT_JOIN_REFUSED,
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
    ``{"hub_id", "hub_name", "gateway_url", "connection", "wait_reason",
    "wait_code", "next_round_at", "reached_through", "rtt_ms", "is_exit",
    "last_error"}``; ``connection``, ``wait_reason`` and
    ``reached_through`` are empty and the others None when no resident runs
    to say them.

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
                "wait_reason": "",
                "wait_code": None,
                "next_round_at": None,
                "reached_through": "",
                "rtt_ms": None,
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
                "wait_reason": str(hub.get("wait_reason", "") or ""),
                "wait_code": hub.get("wait_code") or None,
                "next_round_at": hub.get("next_round_at"),
                "reached_through": str(hub.get("reached_through", "") or ""),
                "rtt_ms": _rtt_ms(hub),
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
                _state_line(hub),
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


def _rtt_ms(hub: dict) -> "int | None":
    """One hub's round trip in whole milliseconds, or None when it has none.

    Args:
        hub: The hub's row of the state payload.

    Returns:
        The ``rtt_ms`` the resident reported, rounded; None when absent.
    """
    value = hub.get("rtt_ms")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(value)


def _tags(hub: dict) -> str:
    """A connected hub's two tags: the way the channel reached it and the round trip.

    Args:
        hub: The hub's row of the state payload.

    Returns:
        ``" · <way> · <ms> ms"``, the way left out while the hub has not
        named one this client has a word for, and the round trip before the
        first pong; empty unless the hub is connected.

    Raises:
        FileNotFoundError: When the word catalogs are not on this machine.
        ValueError: When a catalog is not a JSON object.
    """
    if hub.get("connection") != CONNECTION_CONNECTED:
        return ""
    tags = []
    way = str(hub.get("reached_through", "") or "")
    if way and f"ui.through.{way}" in words.words(CLIENT_DEFAULT_LANGUAGE):
        tags.append(words.word(CLIENT_DEFAULT_LANGUAGE, f"ui.through.{way}"))
    rtt_ms = _rtt_ms(hub)
    if rtt_ms is not None:
        tags.append(words.word(CLIENT_DEFAULT_LANGUAGE, "ui.state.rtt", {"ms": rtt_ms}))
    return "".join(f" · {tag}" for tag in tags)


def _state_line(hub: dict) -> str:
    """One hub's state line, in the window's English words.

    Args:
        hub: The hub's row of the state payload.

    Returns:
        The state word, then ``" · "`` and what ends a wait: the seconds
        until the next round, a refused join's reason, or Reconnect; a
        connected hub's word carries its tags. A connection this client has
        no word for prints as itself.

    Raises:
        FileNotFoundError: When the word catalogs are not on this machine.
        ValueError: When a catalog is not a JSON object.
    """
    connection = str(hub.get("connection", ""))
    if connection == CONNECTION_CONNECTED:
        return _word("ui.state.connected", connection) + _tags(hub)
    if connection == CONNECTION_WAITING:
        return _waiting_line(hub)
    if connection == CONNECTION_REPLACED:
        return f"{_word('ui.state.replaced', connection)} · {_word('ui.reconnect', '')}"
    return _word(f"ui.state.{connection}", connection)


def _waiting_line(hub: dict) -> str:
    """A waiting hub's state line: its reason, then what ends the wait.

    Args:
        hub: The hub's row of the state payload.

    Returns:
        The reason's word, with the seconds left while a countdown runs,
        the connecting word once it reached 0, or a refused join's reason.

    Raises:
        FileNotFoundError: When the word catalogs are not on this machine.
        ValueError: When a catalog is not a JSON object.
    """
    reason = str(hub.get("wait_reason", "") or "")
    line = _word(f"ui.state.{reason}", reason)
    code = hub.get("wait_code")
    if reason == WAIT_JOIN_REFUSED and isinstance(code, dict) and code.get("code"):
        refusal = str(code["code"])
        params = code.get("params") or {}
        why = _word(f"code.{refusal}", wording.word_code(refusal, params), params)
        return f"{line} · {why}"
    next_round_at = hub.get("next_round_at")
    if isinstance(next_round_at, bool) or not isinstance(next_round_at, (int, float)):
        return line
    left = math.ceil(next_round_at - time.time())
    if left <= 0:
        return _word("ui.state.connecting", "connecting")
    return f"{line} · {_word('ui.action.retry_in', '', {'s': left})}"


def _word(key: str, fallback: str, params: "dict | None" = None) -> str:
    """One key's English word, or the fallback when the catalog lacks it.

    Raises:
        FileNotFoundError: When the word catalogs are not on this machine.
        ValueError: When a catalog is not a JSON object.
    """
    if key not in words.words(CLIENT_DEFAULT_LANGUAGE):
        return fallback
    return words.word(CLIENT_DEFAULT_LANGUAGE, key, params or {})
