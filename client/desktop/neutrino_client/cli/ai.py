"""``nclient ai``: where this computer's AI tools point.

``show`` prints each tool's gateway address and whether it is the hub's;
``set`` is the AI page's chip turned on: the hub's gateway forwarded and
written into the tools, and again to refresh them. A computer the agent is
installed on has its tools set from the hub's panel, and ``set`` is refused
``ai_tools_managed`` there.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.cli import names, wording

# The tools the gateway is written into, as ``show`` names them.
AI_TOOLS = ("claude", "codex", "gemini")
AI_LOOPBACK_HOST = "127.0.0.1"
AI_WORKING = "working"


def main_show(*, hub: str = "") -> int:
    """Print each tool's gateway address and whether it is the hub's.

    Args:
        hub: What ``--hub`` named; empty shows the exit hub's.

    Returns:
        0, or 1 when the client does not answer or ``--hub`` names nothing.
    """
    state = wording.read_state()
    if state is None:
        return 1
    is_known, hub_id = names.scope(state, hub)
    if not is_known:
        return 1
    entry = _gateway_entry(state, hub_id)
    ai = state.get("ai") or {}
    is_hubs = bool(ai.get("is_active")) and entry is not None and entry.get("forward")
    for tool in AI_TOOLS:
        if is_hubs:
            address = f"http://{AI_LOOPBACK_HOST}:{entry.get('forward')}"
            owner = f"{wording.line('ai_hub')} ({_hub_label(state, entry)})"
        else:
            address = wording.line("none")
            owner = wording.line("ai_own")
        wording.say(f"{tool:<8}{address}  {owner}")
    if ai.get("is_managed"):
        wording.say(wording.word_code("ai_tools_managed"))
    return 0


def main_set(*, hub: str = "") -> int:
    """Point the tools at the hub's gateway, as the AI page's chip does.

    Args:
        hub: The hub whose gateway the tools point at; empty keeps the
            exit hub, else the first hub publishing one.

    Returns:
        0 once the tools point at the gateway, 1 for a refusal.
    """
    state = wording.read_state()
    if state is None:
        return 1
    if (state.get("ai") or {}).get("is_managed"):
        wording.refuse("ai_tools_managed")
        return 1
    is_known, hub_id = names.scope(state, hub)
    if not is_known:
        return 1
    entry = _gateway_entry(state, hub_id)
    if entry is None:
        wording.say(wording.line("ai_none"), is_error=True)
        return 1
    if entry.get("hub_id") != state.get("exit_hub_id"):
        if wording.post("/api/exit/set", {"hub_id": entry.get("hub_id", "")}) is None:
            return 1
    body = {
        "hub_id": entry.get("hub_id", ""),
        "id": entry.get("id", ""),
        "is_enabled": True,
        "tool_configs": state.get("ai_tool_configs") or {},
    }
    if wording.post("/api/services/ai", body) is None:
        return 1
    fresh = wording.settled_state(_is_switched)
    if fresh is None:
        return 1
    failure = wording.refusal_of(_ai_row(fresh, entry).get("last_error") or {})
    status = fresh.get("ai") or {}
    if failure is None and status.get("code"):
        failure = {"code": str(status["code"]), "params": status.get("params") or {}}
    if failure is not None:
        wording.refuse(failure["code"], failure["params"])
        return 1
    forward = _ai_row(fresh, entry).get("forward")
    address = f"http://{AI_LOOPBACK_HOST}:{forward}" if forward else ""
    wording.say(wording.line("ai_set", address=address))
    return 0


def _gateway_entry(state: dict, hub_id: str) -> "dict | None":
    """The ``ai`` entry the tools point at: the named hub's, else the exit's.

    Args:
        state: The state payload.
        hub_id: The hub ``--hub`` named; empty takes the exit hub, else the
            first hub publishing a gateway.

    Returns:
        The entry, or None when no hub publishes one.
    """
    gateways = names.entries(state, "ai", hub_id)
    exit_hub_id = str(state.get("exit_hub_id", "") or "")
    for entry in gateways:
        if not hub_id and entry.get("hub_id") == exit_hub_id:
            return entry
    return gateways[0] if gateways else None


def _ai_row(state: dict, entry: dict) -> dict:
    """The ``ai`` entry's row in a state, empty when it is gone."""
    for row in names.entries(state, "ai", str(entry.get("hub_id", ""))):
        if row.get("id") == entry.get("id"):
            return row
    return {}


def _is_switched(state: dict) -> bool:
    """Whether no switch of the tools runs any more."""
    work = (state.get("ai") or {}).get("work") or {}
    if work.get("state") == AI_WORKING:
        return False
    return not any(row.get("job") for row in names.entries(state, "ai"))


def _hub_label(state: dict, entry: dict) -> str:
    """The name of the hub one entry came from."""
    for row in names.hub_rows(state):
        if row.get("hub_id") == entry.get("hub_id"):
            return wording.hub_name(row)
    return ""
