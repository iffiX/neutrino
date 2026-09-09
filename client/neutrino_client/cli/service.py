"""``nclient service``: the Services section, from a terminal.

One panel per type, Web, Ports, AI, Files, Remote desktops, nested the way
the page nests them: a kind heading, then numbered entries in the state's
own order. Actions address an entry by that number or by its id.

The resident reports refusals as ``{"code", "params"}``; the wording lives
in ``wording.py``. A share password is read from the terminal and travels
only in the one request that sends it, never on argv.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import sys

from neutrino_client.cli import wording

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


def main_list() -> int:
    """Print every published entry, nested by kind, numbered per kind.

    Returns:
        Process exit status: 0 with the list (empty included), 1 while the
        person has joined no hub.
    """
    state = wording.read_state()
    if state is None:
        return 1
    if not state.get("is_connected"):
        print(wording.NOT_JOINED)
        return 1
    if not _entries(state):
        print(SERVICES_EMPTY)
        return 0
    for kind, heading in SERVICE_KIND_TITLES:
        rows = _entries(state, kind)
        if not rows:
            continue
        print(heading)
        title_width = max(len(str(entry.get("title", ""))) for entry in rows)
        for position, entry in enumerate(rows, start=1):
            print(f"  {position}  {_entry_line(state, kind, entry, title_width)}")
            if kind == "file":
                for record in _records(state, entry):
                    print(f"     {_record_line(record)}")
    return 0


def main_web_open(ref: str) -> int:
    """Open the browser on one published link.

    Args:
        ref: The entry's per-kind number or id.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    entry = _resolve(state, "web", ref)
    if entry is None:
        return 2
    if not entry.get("is_healthy"):
        print(f"{entry.get('title', '')}: {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    if _act("web", {"id": entry.get("id")}) is None:
        return 1
    print(f"opening {(entry.get('payload') or {}).get('url', '')}")
    return 0


def main_port(ref: str, *, is_enabled: bool, local_port: int = 0) -> int:
    """Start or stop one published port's loopback forward.

    Args:
        ref: The entry's per-kind number or id.
        is_enabled: True to forward, False to unforward.
        local_port: The loopback port to prefer; 0 means the published one.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    entry = _resolve(state, "port", ref)
    if entry is None:
        return 2
    forward = (state.get("forwards") or {}).get(entry.get("id")) or {}
    if is_enabled and forward.get("is_active"):
        print(f"{FORWARD_HOST}:{forward.get('local_port')}")
        return 0
    if is_enabled and not entry.get("is_healthy"):
        print(f"{entry.get('title', '')}: {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    if not is_enabled and not forward.get("is_active"):
        print(f"no forward is running for {entry.get('title', '')}")
        return 0
    body = {"id": entry.get("id"), "is_enabled": is_enabled}
    if is_enabled and local_port:
        body["local_port"] = local_port
    reply = _act("port", body)
    if reply is None:
        return 1
    if is_enabled:
        fresh = (reply.get("forwards") or {}).get(entry.get("id")) or {}
        print(f"{FORWARD_HOST}:{fresh.get('local_port')}")
    else:
        print(f"closed {FORWARD_HOST}:{forward.get('local_port')}")
    return 0


def main_file_config(ref: str, *, path: str, username: str) -> int:
    """Save one share's login and path, and mount it there.

    The password is asked on the terminal, the way the page's form asks,
    and appears on no command line.

    Args:
        ref: The entry's per-kind number or id.
        path: Where to mount the share.
        username: The share's own username.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    entry = _resolve(state, "file", ref)
    if entry is None:
        return 2
    if not entry.get("is_healthy"):
        print(f"{entry.get('title', '')}: {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    password = wording.ask_secret("Share password: ")
    body = {
        "action": "mount",
        "id": entry.get("id"),
        "username": username,
        "password": password,
        "path": path,
    }
    reply = _act("file", body)
    if reply is None:
        return 1
    record = _record_at(reply, entry, path)
    print(_record_line(record) if record else f"{path}: asked")
    return 0


def main_file_mount(ref: str) -> int:
    """Mount one share again with the login its record keeps.

    Args:
        ref: The entry's per-kind number or id.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    entry = _resolve(state, "file", ref)
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
    reply = _act("file", {"action": "mount", "record_id": record.get("record_id")})
    if reply is None:
        return 1
    fresh = _record_at(reply, entry, str(record.get("path", "")))
    print(_record_line(fresh) if fresh else f"{record.get('path', '')}: asked")
    return 0


def main_file_unmount(ref: str) -> int:
    """Unmount one share; its record and login stay for the next mount.

    Args:
        ref: The entry's per-kind number or id.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    entry = _resolve(state, "file", ref)
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
    reply = _act("file", {"action": "unmount", "record_id": record.get("record_id")})
    if reply is None:
        return 1
    fresh = _record_at(reply, entry, str(record.get("path", "")))
    print(_record_line(fresh) if fresh else f"{record.get('path', '')}: unmounted")
    return 0


def main_ai_show() -> int:
    """Print the AI entry and where this person's tools point.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    rows = _entries(state, "ai")
    if not rows:
        print(SERVICE_NO_AI, file=sys.stderr)
        return 1
    entry = rows[0]
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

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    rows = _entries(state, "ai")
    if not rows:
        print(SERVICE_NO_AI, file=sys.stderr)
        return 1
    entry = rows[0]
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


def main_desktop_connect(ref: str) -> int:
    """Open the viewer at one shared desktop.

    Args:
        ref: The entry's per-kind number or id.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    entry = _resolve(state, "rdp", ref)
    if entry is None:
        return 2
    if not entry.get("is_healthy"):
        print(f"{entry.get('title', '')}: {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    reply = _act("rdp", {"action": "connect", "id": entry.get("id")})
    if reply is None:
        return 1
    print(f"opening {entry.get('title', '')}")
    return 0


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
    where = SERVICE_AI_ON if row.get("is_active") else SERVICE_AI_OFF
    switch = "on" if row.get("is_enabled") else "off"
    return f"{switch}  {where}  ({standing})"


def _entries(state: dict, kind: str = "") -> list:
    """The published entries, in the state's own order.

    Args:
        state: The state payload.
        kind: Keep only this type; empty keeps every entry.

    Returns:
        The entries.
    """
    entries = [
        entry for entry in state.get("services") or [] if isinstance(entry, dict)
    ]
    if kind:
        entries = [entry for entry in entries if entry.get("type") == kind]
    return entries


def _resolve(state: dict, kind: str, ref: str) -> "dict | None":
    """One entry by its per-kind number or its id.

    Args:
        state: The state payload.
        kind: The service type the command names.
        ref: A 1-based position in the kind's listing order, or an id.

    Returns:
        The entry, or None after the refusal was printed.
    """
    rows = _entries(state, kind)
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
        forward = (state.get("forwards") or {}).get(entry.get("id")) or {}
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
        if isinstance(record, dict) and record.get("entry_id") == entry.get("id")
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
