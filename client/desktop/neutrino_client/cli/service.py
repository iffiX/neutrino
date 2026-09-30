"""``nclient service``: the Services section, from a terminal.

The listing is nested the way the page nests it: one heading per hub
joined, then one panel per type, Web, Ports, AI, Files, Remote desktops,
each numbering its entries in the state's own order. Every verb takes
``--hub``, which one hub joined makes optional; an action addresses an
entry by its number within that hub, or by its id.

The resident reports refusals as ``{"code", "params"}``; the wording lives
in ``wording.py``. A share password is read from the terminal and travels
only in the one request that sends it, never on argv.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import sys

from neutrino_client.cli import wording
from neutrino_client.services.base import service_key

SERVICE_KIND_TITLES = (
    ("web", "Web"),
    ("port", "Ports"),
    ("ai", "AI"),
    ("file", "Files"),
    ("rdp", "Remote desktops"),
)

SERVICES_EMPTY = "nothing is published for this person yet"
SERVICE_UNHEALTHY = "not reachable now"
SERVICE_NO_AI = "no AI service is published for this person"
SERVICE_NO_RECORD = (
    "no saved login for this share; set one: nclient service file config"
)
SERVICE_AI_ON = "the tools point at the hub"
SERVICE_AI_OFF = "the tools are as they were"

FORWARD_HOST = "127.0.0.1"


def main_list(*, hub: str = "") -> int:
    """Print every published entry, by hub and then by kind.

    Args:
        hub: The hub to list, by its name, its id or its binding's id;
            empty lists every hub joined.

    Returns:
        Process exit status: 0 with the list (empty included), 1 while the
        person has joined no hub or named one nobody joined.
    """
    state = wording.read_state()
    if state is None:
        return 1
    if not state.get("is_connected"):
        print(wording.NOT_JOINED)
        return 1
    rows = _hub_rows(state)
    if hub:
        chosen = wording.choose_hub(rows, hub)
        if chosen is None:
            return 1
        rows = [chosen]
    for row in rows:
        print(_hub_heading(row))
        _print_hub_entries(state, str(row.get("hub_id", "")))
    return 0


def main_web_open(ref: str, *, hub: str = "") -> int:
    """Open the browser on one published link.

    Args:
        ref: The entry's number under its hub, or its id.
        hub: The hub the entry belongs to, by its name, its id or its
            binding's id; empty names the one hub joined.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    hub_id = _scope(state, hub)
    if hub_id is None:
        return 1
    entry = _resolve(state, "web", ref, hub_id)
    if entry is None:
        return 2
    if not entry.get("is_healthy"):
        print(f"{entry.get('title', '')}: {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    if _act("web", _address(entry)) is None:
        return 1
    print(f"opening {(entry.get('payload') or {}).get('url', '')}")
    return 0


def main_port(ref: str, *, is_enabled: bool, local_port: int = 0, hub: str = "") -> int:
    """Start or stop one published port's loopback forward.

    Args:
        ref: The entry's number under its hub, or its id.
        hub: The hub the entry belongs to, by its name, its id or its
            binding's id; empty names the one hub joined.
        is_enabled: True to forward, False to unforward.
        local_port: The loopback port to prefer; 0 means the published one.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    hub_id = _scope(state, hub)
    if hub_id is None:
        return 1
    entry = _resolve(state, "port", ref, hub_id)
    if entry is None:
        return 2
    forward = _forward_of(state, entry)
    if is_enabled and forward.get("is_active"):
        print(f"{FORWARD_HOST}:{forward.get('local_port')}")
        return 0
    if is_enabled and not entry.get("is_healthy"):
        print(f"{entry.get('title', '')}: {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    if not is_enabled and not forward.get("is_active"):
        print(f"no forward is running for {entry.get('title', '')}")
        return 0
    body = dict(_address(entry), is_enabled=is_enabled)
    if is_enabled and local_port:
        body["local_port"] = local_port
    reply = _act("port", body)
    if reply is None:
        return 1
    if is_enabled:
        fresh = _forward_of(reply, entry)
        print(f"{FORWARD_HOST}:{fresh.get('local_port')}")
    else:
        print(f"closed {FORWARD_HOST}:{forward.get('local_port')}")
    return 0


def main_file_config(ref: str, *, path: str, username: str, hub: str = "") -> int:
    """Save one share's login and path, and mount it there.

    The password is asked on the terminal, the way the page's form asks,
    and appears on no command line.

    Args:
        ref: The entry's number under its hub, or its id.
        hub: The hub the entry belongs to, by its name, its id or its
            binding's id; empty names the one hub joined.
        path: Where to mount the share.
        username: The share's own username.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    hub_id = _scope(state, hub)
    if hub_id is None:
        return 1
    entry = _resolve(state, "file", ref, hub_id)
    if entry is None:
        return 2
    if not entry.get("is_healthy"):
        print(f"{entry.get('title', '')}: {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    password = wording.ask_secret("Share password: ")
    body = dict(
        _address(entry),
        action="mount",
        username=username,
        password=password,
        path=path,
    )
    reply = _act("file", body)
    if reply is None:
        return 1
    record = _record_at(reply, entry, path)
    print(_record_line(record) if record else f"{path}: asked")
    return 0


def main_file_mount(ref: str, *, hub: str = "") -> int:
    """Mount one share again with the login its record keeps.

    Args:
        ref: The entry's number under its hub, or its id.
        hub: The hub the entry belongs to, by its name, its id or its
            binding's id; empty names the one hub joined.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    hub_id = _scope(state, hub)
    if hub_id is None:
        return 1
    entry = _resolve(state, "file", ref, hub_id)
    if entry is None:
        return 2
    records = _records(state, entry)
    if not records:
        print(SERVICE_NO_RECORD, file=sys.stderr)
        return 1
    record = records[0]
    if record.get("is_attached"):
        print(f"already mounted at {record.get('path', '')}")
        return 0
    reply = _act(
        "file",
        {
            "hub_id": entry.get("hub_id", ""),
            "action": "mount",
            "record_id": record.get("record_id"),
        },
    )
    if reply is None:
        return 1
    fresh = _record_at(reply, entry, str(record.get("path", "")))
    print(_record_line(fresh) if fresh else f"{record.get('path', '')}: asked")
    return 0


def main_file_unmount(ref: str, *, hub: str = "") -> int:
    """Unmount one share; its record and login stay for the next mount.

    Args:
        ref: The entry's number under its hub, or its id.
        hub: The hub the entry belongs to, by its name, its id or its
            binding's id; empty names the one hub joined.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    hub_id = _scope(state, hub)
    if hub_id is None:
        return 1
    entry = _resolve(state, "file", ref, hub_id)
    if entry is None:
        return 2
    records = _records(state, entry)
    if not records:
        print(f"nothing is mounted for {entry.get('title', '')}")
        return 0
    record = records[0]
    if record.get("state") == "detached":
        print(
            f"{record.get('path', '')}: {wording.CLIENT_MOUNT_STATE_WORDS['detached']}"
        )
        return 0
    reply = _act(
        "file",
        {
            "hub_id": entry.get("hub_id", ""),
            "action": "unmount",
            "record_id": record.get("record_id"),
        },
    )
    if reply is None:
        return 1
    fresh = _record_at(reply, entry, str(record.get("path", "")))
    print(_record_line(fresh) if fresh else f"{record.get('path', '')}: unmounted")
    return 0


def main_ai_show(*, hub: str = "") -> int:
    """Print the AI entry and where this person's tools point.

    Args:
        hub: The hub whose gateway to show, by its name, its id or its
            binding's id; empty shows the exit hub's.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    if hub:
        hub_id = _scope(state, hub)
        if hub_id is None:
            return 1
        published = _entries(state, "ai", hub_id)
        entry = published[0] if published else None
    else:
        entry = _exit_ai_entry(state)
    if entry is None:
        print(SERVICE_NO_AI, file=sys.stderr)
        return 1
    payload = entry.get("payload") or {}
    print(f"{entry.get('title', '')}  {payload.get('endpoint', '')}")
    print(f"  {_ai_line(state)}")
    return 0


def main_ai_apply(
    *,
    is_enabled: bool,
    claude_default: "str | None",
    claude_opus: "str | None",
    claude_sonnet: "str | None",
    claude_haiku: "str | None",
    codex_model: "str | None",
    codex_effort: "str | None",
    gemini_model: "str | None",
    hub: str = "",
) -> int:
    """Point the tools at the hub or put them back, exactly the page's Apply.

    A knob flag left out keeps the kept choice; an empty value returns it to
    the gateway default.

    Args:
        is_enabled: Whether the tools should point at the hub.
        claude_default: Claude Code's default model slot.
        claude_opus: Claude Code's opus slot.
        claude_sonnet: Claude Code's sonnet slot.
        claude_haiku: Claude Code's haiku slot.
        codex_model: Codex's model.
        codex_effort: Codex's reasoning effort.
        gemini_model: Gemini's model.
        hub: The hub to make the exit first, by name or id; empty keeps
            the exit as it is.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    if hub:
        state = _choose_exit(state, hub)
        if state is None:
            return 1
    entry = _exit_ai_entry(state)
    if entry is None:
        print(SERVICE_NO_AI, file=sys.stderr)
        return 1
    if is_enabled and not entry.get("is_healthy"):
        print(f"{entry.get('title', '')}: {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    models = [str(model) for model in (entry.get("payload") or {}).get("models", [])]
    chosen = {
        "claude": {
            "default": claude_default,
            "opus": claude_opus,
            "sonnet": claude_sonnet,
            "haiku": claude_haiku,
        },
        "codex": {"model": codex_model, "model_reasoning_effort": codex_effort},
        "gemini": {"model": gemini_model},
    }
    for tool, knobs in chosen.items():
        for knob, value in knobs.items():
            if knob == "model_reasoning_effort" or value is None:
                continue
            if value and value not in models:
                served = ", ".join(models) or "nothing"
                print(
                    f"no model {value} at the gateway; it serves: {served}",
                    file=sys.stderr,
                )
                return 2
    body = {
        "is_enabled": is_enabled,
        "tool_configs": _merged_tool_configs(state, chosen),
    }
    reply = _act("ai", body)
    if reply is None:
        return 1
    print(_ai_line(reply))
    return 0


def main_desktop_connect(ref: str, *, hub: str = "") -> int:
    """Open the viewer at one shared desktop.

    Args:
        ref: The entry's number under its hub, or its id.
        hub: The hub the entry belongs to, by its name, its id or its
            binding's id; empty names the one hub joined.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    hub_id = _scope(state, hub)
    if hub_id is None:
        return 1
    entry = _resolve(state, "rdp", ref, hub_id)
    if entry is None:
        return 2
    if not entry.get("is_healthy"):
        print(f"{entry.get('title', '')}: {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    reply = _act("rdp", dict(_address(entry), action="connect"))
    if reply is None:
        return 1
    print(f"opening {entry.get('title', '')}")
    return 0


def _hub_heading(row: dict) -> str:
    """One hub's heading: what it is called, and where it is.

    Args:
        row: The hub's row of the state payload.

    Returns:
        The line the hub's panels sit under.
    """
    name = str(row.get("hub_name", ""))
    url = str(row.get("gateway_url", ""))
    return f"{name}  {url}".strip() if name else url


def _print_hub_entries(state: dict, hub_id: str) -> None:
    """One hub's panels, numbered per kind under its heading.

    Args:
        state: The state payload.
        hub_id: The hub whose entries these are.
    """
    if not _entries(state, hub_id=hub_id):
        print(f"  {SERVICES_EMPTY}")
        return
    for kind, heading in SERVICE_KIND_TITLES:
        rows = _entries(state, kind, hub_id)
        if not rows:
            continue
        print(f"  {heading}")
        title_width = max(len(str(entry.get("title", ""))) for entry in rows)
        for position, entry in enumerate(rows, start=1):
            print(f"    {position}  {_entry_line(state, kind, entry, title_width)}")
            if kind == "file":
                for record in _records(state, entry):
                    print(f"       {_record_line(record)}")


def _ai_line(state: dict) -> str:
    """Where the tools point, with the row's standing.

    Args:
        state: The state payload.

    Returns:
        The line to print.
    """
    row = state.get("ai") or {}
    standing = wording.word_state(str(row.get("state", "unknown")))
    failure = wording.word_code(str(row.get("code", "")), row.get("params"))
    if failure:
        standing = f"{standing}: {failure}"
    work = row.get("work") or {}
    if work.get("state") == "working":
        standing = wording.CLIENT_WORK_WORDS.get(str(work.get("step", "")), "working")
    where = SERVICE_AI_ON if row.get("is_active") else SERVICE_AI_OFF
    switch = "on" if row.get("is_enabled") else "off"
    return f"{switch}  {where}  ({standing})"


def _exit_ai_entry(state: dict) -> "dict | None":
    """The exit hub's AI entry, or None while no hub publishes one.

    Args:
        state: The state payload.

    Returns:
        The entry; with no exit named, the first AI entry published.
    """
    rows = _entries(state, "ai")
    exit_hub_id = str(state.get("exit_hub_id", "") or "")
    for entry in rows:
        if entry.get("hub_id") == exit_hub_id:
            return entry
    return rows[0] if rows and not exit_hub_id else None


def _hub_rows(state: dict) -> list:
    """The hubs one state payload lists, in the order joined."""
    return [hub for hub in state.get("hubs") or [] if isinstance(hub, dict)]


def _scope(state: dict, needle: str) -> "str | None":
    """The hub one action addresses.

    Args:
        state: The state payload.
        needle: The hub's name, id or binding id; empty names the one hub
            joined.

    Returns:
        The hub's id, or None after the refusal was printed.
    """
    row = wording.choose_hub(_hub_rows(state), needle)
    if row is None:
        return None
    return str(row.get("hub_id", ""))


def _choose_exit(state: dict, needle: str) -> "dict | None":
    """Make one hub the exit, refusals worded here.

    Args:
        state: The state payload.
        needle: The hub's name, id or binding id.

    Returns:
        The state payload with that hub as the exit, or None after the
        refusal was printed.
    """
    hub = wording.choose_hub(_hub_rows(state), needle)
    if hub is None:
        return None
    if hub.get("is_exit"):
        return state
    answer = wording.request("POST", "/api/exit/set", {"hub_id": hub.get("hub_id")})
    if answer is None:
        return None
    _, reply = answer
    if reply.get("code"):
        print(
            wording.word_code(str(reply.get("code")), reply.get("params")),
            file=sys.stderr,
        )
        return None
    return reply


def _address(entry: dict) -> dict:
    """What names one entry to the resident: its hub and its id.

    Args:
        entry: The entry.

    Returns:
        ``{"hub_id", "id"}``.
    """
    return {"hub_id": entry.get("hub_id", ""), "id": entry.get("id", "")}


def _forward_of(state: dict, entry: dict) -> dict:
    """One entry's forward row, empty when none runs."""
    key = service_key(str(entry.get("hub_id", "")), str(entry.get("id", "")))
    return (state.get("forwards") or {}).get(key) or {}


def _entries(state: dict, kind: str = "", hub_id: "str | None" = None) -> list:
    """The published entries, in the state's own order.

    Args:
        state: The state payload.
        kind: Keep only this type; empty keeps every type.
        hub_id: Keep only the entries this hub published; None keeps every
            hub's, and a hub that has not said its id published none.

    Returns:
        The entries.
    """
    entries = [
        entry for entry in state.get("services") or [] if isinstance(entry, dict)
    ]
    if kind:
        entries = [entry for entry in entries if entry.get("type") == kind]
    if hub_id is not None:
        entries = [entry for entry in entries if entry.get("hub_id", "") == hub_id]
    return entries


def _resolve(state: dict, kind: str, ref: str, hub_id: str) -> "dict | None":
    """One entry by its number under its hub, or by its id.

    Args:
        state: The state payload.
        kind: The service type the command names.
        ref: A 1-based position in the kind's listing order under that hub,
            or an id.
        hub_id: The hub the entry belongs to.

    Returns:
        The entry, or None after the refusal was printed.
    """
    rows = _entries(state, kind, hub_id)
    if ref.isdigit():
        position = int(ref)
        if 1 <= position <= len(rows):
            return rows[position - 1]
    else:
        for entry in rows:
            if entry.get("id") == ref:
                return entry
    print(f"no {kind} entry {ref}; see nclient service list", file=sys.stderr)
    return None


def _act(service_type: str, body: dict) -> "dict | None":
    """One service action, refusals worded here.

    Args:
        service_type: The type the action belongs to.
        body: The action's own fields.

    Returns:
        The fresh state payload, or None after the refusal was printed.
    """
    answer = wording.request("POST", f"/api/services/{service_type}", body)
    if answer is None:
        return None
    _, reply = answer
    if reply.get("code"):
        print(
            wording.word_code(str(reply.get("code")), reply.get("params")),
            file=sys.stderr,
        )
        return None
    return reply


def _entry_line(state: dict, kind: str, entry: dict, title_width: int) -> str:
    """One entry's listing line: title, payload essence, standing.

    Args:
        state: The state payload.
        kind: The entry's type.
        entry: The entry.
        title_width: The kind's title column width.

    Returns:
        The line after the number.
    """
    payload = entry.get("payload") or {}
    if kind == "web":
        essence = str(payload.get("url", ""))
    elif kind == "port":
        essence = f"{payload.get('host', '')}:{payload.get('port', '')}"
        forward = _forward_of(state, entry)
        if forward.get("is_active"):
            essence += f" -> {FORWARD_HOST}:{forward.get('local_port')}"
    elif kind == "ai":
        essence = str(payload.get("endpoint", ""))
    elif kind == "rdp":
        essence = f"{payload.get('host', '')}:{payload.get('port', '')}"
    else:
        essence = f"//{payload.get('host', '')}/{payload.get('share', '')}"
    notes = []
    if not entry.get("is_healthy"):
        notes.append(SERVICE_UNHEALTHY)
    if entry.get("description"):
        notes.append(str(entry.get("description")))
    tail = f"  ({'; '.join(notes)})" if notes else ""
    return f"{str(entry.get('title', '')):<{title_width}}  {essence}{tail}"


def _records(state: dict, entry: dict) -> list:
    """One entry's mount records, in the state's own order."""
    return [
        record
        for record in state.get("mounts") or []
        if isinstance(record, dict)
        and record.get("hub_id") == entry.get("hub_id")
        and record.get("entry_id") == entry.get("id")
    ]


def _record_at(state: dict, entry: dict, path: str) -> "dict | None":
    """The entry's record at one path, or None."""
    for record in _records(state, entry):
        if record.get("path") == path:
            return record
    return None


def _record_line(record: dict) -> str:
    """One mount record's line: path and standing.

    Args:
        record: The state payload's mount row.

    Returns:
        The line to print.
    """
    failure = wording.word_code(str(record.get("code", "")), record.get("params"))
    if failure:
        standing = failure
    else:
        standing = wording.CLIENT_MOUNT_STATE_WORDS.get(
            str(record.get("state", "")), ""
        )
        if not standing:
            standing = (
                wording.CLIENT_MOUNT_STATE_WORDS["mounted"]
                if record.get("is_attached")
                else wording.CLIENT_MOUNT_STATE_WORDS["detached"]
            )
    return f"{record.get('path', '')}: {standing}"


def _merged_tool_configs(state: dict, chosen: dict) -> dict:
    """The kept tool choices with the given flags settled in.

    Args:
        state: The state payload.
        chosen: Tool to knob to value; None keeps the kept choice.

    Returns:
        The tool configs to send.
    """
    merged = {}
    kept = state.get("ai_tool_configs") or {}
    for tool, knobs in chosen.items():
        tool_config = dict(kept.get(tool) or {})
        for knob, value in knobs.items():
            if value is not None:
                tool_config[knob] = value
        merged[tool] = tool_config
    return merged
