"""``nclient rdp``: the desktops the machines share.

``list`` prints one line per machine sharing its desktop; ``connect`` is
the Remote desktops page's **Connect**: the seat password read from the
hub, the forward made and the viewer started, waited for until it runs.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.cli import names, wording
from neutrino_client.services.base import service_key


def main_list(*, hub: str = "") -> int:
    """Print each machine sharing its desktop: who must act there, and its viewer.

    Args:
        hub: What ``--hub`` named; empty lists every hub's.

    Returns:
        0, or 1 when the client does not answer or ``--hub`` names nothing.
    """
    state = wording.read_state()
    if state is None:
        return 1
    is_known, hub_id = names.scope(state, hub)
    if not is_known:
        return 1
    for entry in names.entries(state, "rdp", hub_id):
        attention = str((entry.get("payload") or {}).get("attention", "") or "")
        seat = wording.word_code(attention) if attention else wording.line("none")
        viewer = wording.line("rdp_open") if _is_viewing(state, entry) else ""
        wording.say(f"{names.machine_label(entry)}  {seat}  {viewer}".rstrip())
    return 0


def main_connect(machine: str, *, hub: str = "") -> int:
    """Open the viewer on one machine's desktop, as **Connect** does.

    Args:
        machine: The machine as ``list`` names it.
        hub: What ``--hub`` named.

    Returns:
        0 once the viewer runs, 1 for a refusal.
    """
    state = wording.read_state()
    if state is None:
        return 1
    entry = names.choose_rdp(state, machine, hub)
    if entry is None:
        return 1
    if _is_viewing(state, entry):
        wording.refuse("rdp_viewer_open")
        return 1
    body = {"hub_id": entry.get("hub_id", ""), "id": entry.get("id", "")}
    if wording.post("/api/services/rdp", dict(body, action="connect")) is None:
        return 1

    def is_started(fresh: dict) -> bool:
        return not (_row(fresh, entry) or {}).get("job")

    fresh = wording.settled_state(is_started)
    if fresh is None:
        return 1
    failure = wording.refusal_of((_row(fresh, entry) or {}).get("last_error") or {})
    if failure is not None:
        wording.refuse(failure["code"], failure["params"])
        return 1
    wording.say(wording.line("rdp_opening", machine=names.machine_label(entry)))
    return 0


def _row(state: dict, entry: dict) -> "dict | None":
    """The entry's row in a state, None when it is gone."""
    for row in names.entries(state, "rdp", str(entry.get("hub_id", ""))):
        if row.get("id") == entry.get("id"):
            return row
    return None


def _is_viewing(state: dict, entry: dict) -> bool:
    """Whether a viewer this client started runs on the entry."""
    key = service_key(str(entry.get("hub_id", "")), str(entry.get("id", "")))
    return bool(((state.get("viewers") or {}).get(key) or {}).get("is_running"))
