"""``nagent service``: the Services section, from a terminal.

One panel per type — Web, Ports, AI, Files — nested the way the page
nests them: a kind heading, then numbered entries in the state's own
order. Actions address an entry by that number or by its id. Every choice
here is machine state in the agent's own store, decided on the machine as
the design says; the hub only publishes the list.

The agent reports refusals as ``{"code", "params"}``; the wording lives in
``wording.py``. A share password is read from the terminal and travels
only in the one request that sends it — never on argv.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import getpass
import sys
import webbrowser

from neutrino_agent.cli import wording

SERVICE_KIND_TITLES = (
    ("web", "Web"),
    ("port", "Ports"),
    ("ai", "AI"),
    ("file", "Files"),
    ("rdp", "Remote desktops"),
)

SERVICES_EMPTY = "nothing is published for this machine yet"
SERVICE_UNHEALTHY = "not reachable now"
SERVICE_NO_AI = "no AI service is published for this machine"
SERVICE_NO_RECORD = "no saved login for this share; set one: nagent service file config"
SERVICE_CONVERGES = "the tools follow on the machine's next report"
SERVICE_RDP_NOT_SHARED = "this machine's desktop is not shared"
SERVICE_RDP_ID = "RustDesk ID"
SERVICE_RDP_MODULE = "rustdesk"

FORWARD_HOST = "127.0.0.1"


def main_list() -> int:
    """Print every published entry, nested by kind, numbered per kind.

    Returns:
        Process exit status: 0 with the list (empty included), 1 while the
        machine has joined no gateway.
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
            missing = _missing_modules(state, entry)
            if missing:
                print(f"     {_needs_line(missing)}")
            if kind == "file":
                for record in _records(state, entry):
                    print(f"     {_record_line(record)}")
    return 0


def main_web_open(ref: str) -> int:
    """Open the default browser on one published link.

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
        print(f"{entry.get('title', '')} — {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    url = str((entry.get("payload") or {}).get("url", ""))
    webbrowser.open(url)
    print(f"opening {url}")
    return 0


def main_port(ref: str, *, is_enabled: bool) -> int:
    """Start or stop one published port's loopback forward.

    Args:
        ref: The entry's per-kind number or id.
        is_enabled: True to forward, False to unforward.

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
        print(f"{entry.get('title', '')} — {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    if not is_enabled and not forward.get("is_active"):
        print(f"no forward is running for {entry.get('title', '')}")
        return 0
    reply = _act("port", {"id": entry.get("id"), "is_enabled": is_enabled})
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
    missing = _missing_modules(state, entry)
    if missing:
        print(_needs_line(missing), file=sys.stderr)
        return 1
    if not entry.get("is_healthy"):
        print(f"{entry.get('title', '')} — {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    password = getpass.getpass("Share password: ")
    reply = _act(
        "file",
        {
            "action": "mount",
            "id": entry.get("id"),
            "username": username,
            "password": password,
            "path": path,
        },
    )
    if reply is None:
        return 1
    record = _record_at(reply, entry, path)
    print(_record_line(record) if record else f"{path} — asked")
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
    missing = _missing_modules(state, entry)
    if missing:
        print(_needs_line(missing), file=sys.stderr)
        return 1
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
    print(_record_line(fresh) if fresh else f"{record.get('path', '')} — asked")
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
        print(f"{record.get('path', '')} — {wording.CLI_MOUNT_STATE_WORDS['detached']}")
        return 0
    reply = _act("file", {"action": "unmount", "record_id": record.get("record_id")})
    if reply is None:
        return 1
    fresh = _record_at(reply, entry, str(record.get("path", "")))
    print(_record_line(fresh) if fresh else f"{record.get('path', '')} — unmounted")
    return 0


def main_rdp_share() -> int:
    """Share this machine's desktop behind an access password.

    The password is asked on the terminal, the way the page's form asks,
    and appears on no command line. It stays on this machine: RustDesk
    keeps it salted and the agent keeps a copy only root can read, and the
    hub is never told it.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    missing = _missing_rdp_module(state)
    if missing:
        print(_needs_line(missing), file=sys.stderr)
        return 1
    password = getpass.getpass("Access password: ")
    if not password:
        print(wording.word_code("rdp_password_missing", {}), file=sys.stderr)
        return 2
    reply = _act("rdp", {"action": "share", "password": password})
    if reply is None:
        return 1
    print(_rdp_share_line(reply))
    return 0


def main_rdp_unshare() -> int:
    """Stop sharing this machine's desktop.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    if not (state.get("rdp") or {}).get("is_shared"):
        print(SERVICE_RDP_NOT_SHARED)
        return 0
    reply = _act("rdp", {"action": "unshare"})
    if reply is None:
        return 1
    print(SERVICE_RDP_NOT_SHARED)
    return 0


def main_rdp_connect(ref: str) -> int:
    """Open the local RustDesk client at one shared desktop.

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
    missing = _missing_rdp_module(state)
    if missing:
        print(_needs_line(missing), file=sys.stderr)
        return 1
    reply = _act("rdp", {"action": "connect", "id": entry.get("id")})
    if reply is None:
        return 1
    payload = entry.get("payload") or {}
    print(f"opening {payload.get('host', '')}:{payload.get('port', '')}")
    return 0


def main_rdp_show() -> int:
    """Print where this machine's own share stands.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    print(_rdp_share_line(state))
    missing = _missing_rdp_module(state)
    if missing:
        print(_needs_line(missing))
    return 0


def _missing_rdp_module(state: dict) -> list:
    """The rustdesk module when this machine does not have it.

    Args:
        state: The state payload.

    Returns:
        ``(name, title)`` pairs, empty when the module is installed.
    """
    return _missing_modules(state, {"modules": [SERVICE_RDP_MODULE]})


def _rdp_share_line(state: dict) -> str:
    """This machine's own share, as one line.

    Args:
        state: The state payload.

    Returns:
        The line to print.
    """
    share = state.get("rdp") or {}
    standing = wording.word_state(str(share.get("state", "unknown")))
    if not share.get("is_shared"):
        return standing
    where = f"{state.get('hostname', '')}:{share.get('port', '')}"
    identifier = str(share.get("rustdesk_id", ""))
    tail = f"  {SERVICE_RDP_ID} {identifier}" if identifier else ""
    return f"{where} — {standing}{tail}"


def main_ai_show() -> int:
    """Print the AI entry and each account's standing — the page's chips.

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
    missing = _missing_modules(state, entry)
    if missing:
        print(_needs_line(missing))
    accounts = [str(account) for account in state.get("accounts", [])]
    targets = state.get("ai_targets") or {}
    states = state.get("ai_states") or {}
    width = max((len(account) for account in accounts), default=0)
    for account in accounts:
        row = states.get(account) or {}
        standing = wording.word_state(str(row.get("state", "unknown")))
        failure = wording.word_code(str(row.get("code", "")), row.get("params"))
        if failure:
            standing = f"{standing} — {failure}"
        switch = "on" if targets.get(account) else "off"
        print(f"  {account:<{width}}  {switch:<3}  {standing}")
    return 0


def main_ai_apply(
    accounts: list,
    *,
    claude_default: "str | None",
    claude_opus: "str | None",
    claude_sonnet: "str | None",
    claude_haiku: "str | None",
    codex_model: "str | None",
    codex_effort: "str | None",
    gemini_model: "str | None",
) -> int:
    """Commit one whole target set, exactly the page's Apply.

    The named accounts become the entire enabled set: every other account
    is put back the way activation found it. A knob flag left out keeps the
    machine's kept choice; an empty value returns it to the gateway
    default.

    Args:
        accounts: The accounts to switch at the gateway.
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
    missing = _missing_modules(state, entry)
    if missing:
        print(_needs_line(missing), file=sys.stderr)
        return 1
    if not entry.get("is_healthy"):
        print(f"{entry.get('title', '')} — {SERVICE_UNHEALTHY}", file=sys.stderr)
        return 1
    known = [str(account) for account in state.get("accounts", [])]
    for account in accounts:
        if account not in known:
            print(f"no account {account} on this machine", file=sys.stderr)
            return 2
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
    tool_configs = _merged_tool_configs(state, chosen)
    targets = {account: account in set(accounts) for account in known}
    reply = _act("ai", {"targets": targets, "tool_configs": tool_configs})
    if reply is None:
        return 1
    enabled = sorted(account for account, wish in targets.items() if wish)
    restored = sorted(account for account, wish in targets.items() if not wish)
    print(f"switched at the gateway: {', '.join(enabled) or 'nobody'}")
    if restored:
        print(f"put back: {', '.join(restored)}")
    print(SERVICE_CONVERGES)
    return 0


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
    print(f"no {kind} entry {ref}; see nagent service list", file=sys.stderr)
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
    tail = f" — {'; '.join(notes)}" if notes else ""
    return f"{str(entry.get('title', '')):<{title_width}}  {essence}{tail}"


def _missing_modules(state: dict, entry: dict) -> list:
    """The modules one entry depends on that this machine does not have.

    Args:
        state: The state payload.
        entry: The entry.

    Returns:
        ``(name, title)`` pairs, in the entry's own order.
    """
    by_name = {
        row.get("name"): row
        for row in state.get("modules", [])
        if isinstance(row, dict)
    }
    missing = []
    for name in entry.get("modules") or []:
        row = by_name.get(name)
        if row is None or row.get("state") != "installed":
            missing.append((name, str(row.get("title", name)) if row else str(name)))
    return missing


def _needs_line(missing: list) -> str:
    """The notice a gated entry stands behind, with the way past it.

    Args:
        missing: ``(name, title)`` pairs from :func:`_missing_modules`.

    Returns:
        The line to print.
    """
    titles = ", ".join(title for _, title in missing)
    commands = "; ".join(f"nagent module install {name}" for name, _ in missing)
    return f"these modules are missing: {titles} — {commands}"


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
    """One mount record's line: path, account, standing.

    Args:
        record: The state payload's mount row.

    Returns:
        The line to print.
    """
    failure = wording.word_code(str(record.get("code", "")), record.get("params"))
    if failure:
        standing = failure
    else:
        standing = wording.CLI_MOUNT_STATE_WORDS.get(str(record.get("state", "")), "")
        if not standing:
            standing = (
                wording.CLI_MOUNT_STATE_WORDS["mounted"]
                if record.get("is_attached")
                else wording.CLI_MOUNT_STATE_WORDS["detached"]
            )
    return f"{record.get('path', '')} ({record.get('account', '')}) — {standing}"


def _merged_tool_configs(state: dict, chosen: dict) -> dict:
    """The machine's kept tool choices with the given flags settled in.

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
