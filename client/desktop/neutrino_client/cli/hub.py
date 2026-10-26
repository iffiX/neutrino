"""``nclient hub``: the hubs this client joined.

``list`` prints one line per hub with the state line the Hubs page draws;
``join`` and ``leave`` are the page's **Join a hub** and **Leave**, and
``open`` its **Panel**, waited for until the browser is told to open. A
hub is named by its name, its id or its number in ``list``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import math
import time

from neutrino_client import words
from neutrino_client.cli import names, wording
from neutrino_client.constants import CLIENT_REFUSAL_CODE_PROTOCOL_TOO_OLD

CONNECTION_CONNECTED = "connected"
CONNECTION_WAITING = "waiting"
CONNECTION_REPLACED = "replaced"
WAIT_JOIN_REFUSED = "join_refused"
WAIT_TOO_OLD = "too_old"


def main_list() -> int:
    """Print each hub: its number, its name and its state line.

    Returns:
        0, or 1 when the client does not answer.
    """
    state = wording.read_state()
    if state is None:
        return 1
    rows = names.hub_rows(state)
    if not rows:
        wording.say(wording.line("not_joined"))
        return 0
    width = max(len(wording.hub_name(row)) for row in rows)
    for position, row in enumerate(rows, start=1):
        wording.say(
            f"{position}  {wording.hub_name(row):<{width}}  {state_line(row)}".rstrip()
        )
    return 0


def main_join(link: str) -> int:
    """Join the hub a link names, as **Join a hub** does.

    Args:
        link: The enrollment link; empty asks for one at a prompt.

    Returns:
        0 once the binding is stored and its first round starts, 1 for a
        refusal.
    """
    link = link.strip() or wording.ask_text(wording.line("link_prompt"))
    if not link:
        wording.refuse("link_missing")
        return 1
    before = wording.read_state()
    if before is None:
        return 1
    reply = wording.post("/api/join", {"link": link})
    if reply is None:
        return 1
    wording.say(wording.line("joined", url=_joined_url(before, reply)))
    return 0


def main_leave(hub: str, *, is_forced: bool = False) -> int:
    """Leave one hub, as **Leave** does, after a question ``--yes`` answers.

    Args:
        hub: The hub's name, id or number.
        is_forced: Leave without asking.

    Returns:
        0 when the hub is left, 1 for a refusal or a no.
    """
    state = wording.read_state()
    if state is None:
        return 1
    row = wording.choose_hub(names.hub_rows(state), hub)
    if row is None:
        return 1
    name = wording.hub_name(row)
    if not is_forced and not wording.is_confirmed(
        wording.line("leave_question", hub=name)
    ):
        wording.say(wording.line("nothing_changed"))
        return 1
    hub_id = str(row.get("hub_id") or row.get("binding_id", ""))
    if wording.post("/api/leave", {"hub_id": hub_id}) is None:
        return 1
    wording.say(wording.line("left", hub=name))
    return 0


def main_open(hub: str) -> int:
    """Open one hub's panel in the browser, as **Panel** does.

    Args:
        hub: The hub's name, id or number.

    Returns:
        0 once the browser was told to open, 1 for a refusal.
    """
    state = wording.read_state()
    if state is None:
        return 1
    row = wording.choose_hub(names.hub_rows(state), hub)
    if row is None:
        return 1
    hub_id = str(row.get("hub_id") or row.get("binding_id", ""))
    if wording.post("/api/panel/open", {"hub_id": hub_id}) is None:
        return 1

    def is_opened(fresh: dict) -> bool:
        return not (_hub_row(fresh, hub_id).get("jobs") or {}).get("is_opening_panel")

    fresh = wording.settled_state(is_opened)
    if fresh is None:
        return 1
    failure = wording.refusal_of(_hub_row(fresh, hub_id).get("last_error") or {})
    if failure is not None:
        wording.refuse(failure["code"], failure["params"])
        return 1
    wording.say(wording.line("panel_opening", hub=wording.hub_name(row)))
    return 0


def state_line(hub: dict) -> str:
    """One hub's state line, in the window's words and the client's language.

    Args:
        hub: The hub's row of the state payload.

    Returns:
        The state word, its way in and round trip while connected, or what
        ends a wait: the seconds until the next round, a refused join's
        reason, Reconnect, or the step that ends a wait on a client too old.
    """
    connection = str(hub.get("connection", ""))
    if connection == CONNECTION_CONNECTED:
        return _connected_line(hub)
    if connection == CONNECTION_WAITING:
        return _waiting_line(hub)
    if connection == CONNECTION_REPLACED:
        return f"{_word('ui.state.replaced', connection)} · {_word('ui.reconnect', '')}"
    return _word(f"ui.state.{connection}", connection)


def _connected_line(hub: dict) -> str:
    """A connected hub's word with its way in and its round trip."""
    way = str(hub.get("reached_through", "") or "")
    catalog = words.words(wording.language())
    if way and f"ui.through.{way}" in catalog:
        text = _word(
            "ui.state.connected_through",
            "",
            {"way": _word(f"ui.through.{way}", way)},
        )
    else:
        text = _word("ui.state.connected", CONNECTION_CONNECTED)
    rtt = hub.get("rtt_ms")
    if isinstance(rtt, (int, float)) and not isinstance(rtt, bool):
        text += " · " + _word("ui.state.rtt", "", {"ms": round(rtt)})
    return text


def _waiting_line(hub: dict) -> str:
    """A waiting hub's reason, then what ends the wait."""
    reason = str(hub.get("wait_reason", "") or "")
    text = _word(f"ui.state.{reason}", reason)
    code = hub.get("wait_code")
    if reason == WAIT_JOIN_REFUSED and isinstance(code, dict) and code.get("code"):
        return f"{text} · {wording.word_code(str(code['code']), code.get('params'))}"
    if (
        reason == WAIT_TOO_OLD
        and isinstance(code, dict)
        and code.get("code") == CLIENT_REFUSAL_CODE_PROTOCOL_TOO_OLD
    ):
        return f"{text} · {_word('ui.action.update_client', '')}"
    next_round_at = hub.get("next_round_at")
    if isinstance(next_round_at, bool) or not isinstance(next_round_at, (int, float)):
        return text
    left = math.ceil(next_round_at - time.time())
    if left <= 0:
        return _word("ui.state.connecting", "connecting")
    return f"{text} · {_word('ui.action.retry_in', '', {'s': left})}"


def _word(key: str, fallback: str, params: "dict | None" = None) -> str:
    """One catalog key's word in the client's language, or the fallback."""
    language = wording.language()
    if key not in words.words(language):
        return fallback
    return words.word(language, key, params or {})


def _hub_row(state: dict, hub_id: str) -> dict:
    """One hub's row by its id or its binding's, empty when it is gone."""
    for row in names.hub_rows(state):
        if hub_id in (row.get("hub_id"), row.get("binding_id")):
            return row
    return {}


def _joined_url(before: dict, after: dict) -> str:
    """The address of the hub a join added, empty when none was."""
    held = {str(row.get("binding_id", "")) for row in names.hub_rows(before)}
    rows = names.hub_rows(after)
    fresh = [row for row in rows if str(row.get("binding_id", "")) not in held]
    if fresh:
        return str(fresh[0].get("gateway_url", ""))
    return str(rows[-1].get("gateway_url", "")) if rows else ""
