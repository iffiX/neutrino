"""comfy-mcp's ``comfyui`` entry in each tool's list of MCP servers.

Claude Code keeps it in ``~/.claude.json`` as ``mcpServers.comfyui``,
``{type: stdio, command, args: [], env}``; Codex in ``~/.codex/config.toml``
as the table ``[mcp_servers.comfyui]`` with ``command``, ``args`` and
``env``; OpenCode in ``~/.config/opencode/opencode.json`` as
``mcp.comfyui``, ``{type: local, command: [<program>], environment,
enabled: true}``. Each edit changes the one entry and nothing else of the
file. A file that is not the format its tool writes is refused.

Pure: text in, text out.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import re

from neutrino_agent.modules.comfyui.constants import COMFYUI_MCP_SERVER

# Codex's table of the entry, and a table header.
CODEX_TABLE = f"mcp_servers.{COMFYUI_MCP_SERVER}"
TOML_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
# How a JSON file the module writes is indented.
JSON_INDENT = 2


def entry_of(tool: str, *, program: str, environment: dict) -> dict:
    """The entry one tool names comfy-mcp with. Pure.

    Args:
        tool: ``claude_code``, ``codex`` or ``opencode``.
        program: comfy-mcp's program.
        environment: The variables it runs with.

    Returns:
        The entry as the tool's file holds it.
    """
    if tool == "opencode":
        return {
            "type": "local",
            "command": [program],
            "environment": dict(environment),
            "enabled": True,
        }
    if tool == "codex":
        return {"command": program, "args": [], "env": dict(environment)}
    return {"type": "stdio", "command": program, "args": [], "env": dict(environment)}


def _json_document(text: str) -> dict:
    """A tool's JSON file as an object; empty for an empty file. Pure.

    Raises:
        ValueError: For a file that is not a JSON object.
    """
    if not text.strip():
        return {}
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError("the file is not a JSON object")
    return document


def _json_key(tool: str) -> str:
    """The key of the object that holds a JSON tool's MCP servers."""
    return "mcp" if tool == "opencode" else "mcpServers"


def _json_text(document: dict) -> str:
    """A JSON file's text as the module writes it."""
    return json.dumps(document, indent=JSON_INDENT, ensure_ascii=False) + "\n"


def codex_value(value) -> str:
    """One value as TOML writes it: a basic string, an array or an inline table. Pure."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(codex_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(
            f"{json.dumps(name)} = {codex_value(held)}" for name, held in value.items()
        )
        return "{ " + pairs + " }" if pairs else "{}"
    return json.dumps(value)


def codex_table(entry: dict) -> str:
    """Codex's table of the entry. Pure.

    Args:
        entry: The entry, as :func:`entry_of` makes it for Codex.

    Returns:
        ``[mcp_servers.comfyui]`` and one line per key.
    """
    lines = [f"[{CODEX_TABLE}]"]
    lines += [f"{name} = {codex_value(value)}" for name, value in entry.items()]
    return "\n".join(lines) + "\n"


def _codex_split(text: str) -> tuple:
    """A ``config.toml`` with the entry's tables taken out, and those tables' text. Pure."""
    kept = []
    taken = []
    is_ours = False
    for line in text.splitlines(keepends=True):
        header = TOML_HEADER.match(line)
        if header:
            name = header.group(1).replace('"', "").replace(" ", "")
            is_ours = name == CODEX_TABLE or name.startswith(CODEX_TABLE + ".")
        (taken if is_ours else kept).append(line)
    return "".join(kept), "".join(taken)


def entry_in(tool: str, text: str):
    """The ``comfyui`` entry a tool's file holds. Pure.

    Args:
        tool: ``claude_code``, ``codex`` or ``opencode``.
        text: The file's text, empty for none.

    Returns:
        The entry; Codex's as its tables' text; None when the file holds
        none.

    Raises:
        ValueError: For a JSON file that is not a JSON object.
    """
    if tool == "codex":
        _kept, taken = _codex_split(text)
        return taken or None
    servers = _json_document(text).get(_json_key(tool))
    if not isinstance(servers, dict):
        return None
    return servers.get(COMFYUI_MCP_SERVER)


def with_entry(tool: str, text: str, entry: dict) -> "str | None":
    """A tool's file with the entry in it. Pure.

    Args:
        tool: ``claude_code``, ``codex`` or ``opencode``.
        text: The file's text, empty for none.
        entry: The entry, as :func:`entry_of` makes it.

    Returns:
        The new text; None when the file already holds the entry as it is.

    Raises:
        ValueError: For a JSON file that is not a JSON object, or whose
            list of servers is no object.
    """
    if tool == "codex":
        kept, taken = _codex_split(text)
        table = codex_table(entry)
        if taken.strip() == table.strip():
            return None
        body = kept.rstrip("\n")
        return (body + "\n\n" if body.strip() else "") + table
    document = _json_document(text)
    key = _json_key(tool)
    servers = document.setdefault(key, {})
    if not isinstance(servers, dict):
        raise ValueError(f"{key} is not a JSON object")
    if servers.get(COMFYUI_MCP_SERVER) == entry:
        return None
    servers[COMFYUI_MCP_SERVER] = entry
    return _json_text(document)


def without_entry(tool: str, text: str, *, program: str = "") -> "str | None":
    """A tool's file with the entry taken out. Pure.

    Args:
        tool: ``claude_code``, ``codex`` or ``opencode``.
        text: The file's text.
        program: When set, the entry goes only while its command names
            this program.

    Returns:
        The new text; None when the file holds no such entry.

    Raises:
        ValueError: For a JSON file that is not a JSON object.
    """
    if tool == "codex":
        kept, taken = _codex_split(text)
        if not taken or (program and codex_value(program) not in taken):
            return None
        return kept.rstrip("\n") + "\n" if kept.strip() else ""
    document = _json_document(text)
    servers = document.get(_json_key(tool))
    if not isinstance(servers, dict) or COMFYUI_MCP_SERVER not in servers:
        return None
    if program and program not in command_programs(servers[COMFYUI_MCP_SERVER]):
        return None
    del servers[COMFYUI_MCP_SERVER]
    return _json_text(document)


def command_programs(entry) -> list:
    """The programs an entry's command names. Pure.

    Args:
        entry: A JSON entry, or Codex's tables' text.

    Returns:
        The command, or the first item of OpenCode's command list; empty
        when it names none.
    """
    if isinstance(entry, str):
        for line in entry.splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "command":
                try:
                    held = json.loads(value.strip())
                except ValueError:
                    return []
                return [held] if isinstance(held, str) else []
        return []
    if not isinstance(entry, dict):
        return []
    command = entry.get("command")
    if isinstance(command, list):
        command = command[0] if command else ""
    return [command] if isinstance(command, str) and command else []
