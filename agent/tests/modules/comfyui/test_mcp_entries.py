"""Each tool's ``comfyui`` entry in its file's shape with nothing else of the file changed, an entry that is right left as it is, only the module's own entry taken out, and the variables comfy-mcp runs with."""

import json

import pytest

from neutrino_agent.modules.comfyui.mcp_entries import (
    codex_table,
    command_programs,
    entry_in,
    entry_of,
    with_entry,
    without_entry,
)
from neutrino_agent.modules.comfyui.mcp_wiring import mcp_environment, mcp_program

ENVIRONMENT = mcp_environment(
    mcp_dir="/s/comfyui/mcp",
    port=15000,
    workspace="/home/anna/.local/share/neutrino/agent/comfyui/workspace",
    os_name="linux",
    is_git_missing=False,
)


def test_comfy_mcp_runs_with_its_environment():
    assert ENVIRONMENT == {
        "COMFY_BIN": "/s/comfyui/mcp/bin/comfy",
        "COMFY_LOCAL_URL": "http://127.0.0.1:15000",
        "COMFY_PROJECT": "/home/anna/.local/share/neutrino/agent/comfyui/workspace",
        "DO_NOT_TRACK": "1",
    }
    mac = mcp_environment(
        mcp_dir="/m", port=1, workspace="/w", os_name="darwin", is_git_missing=True
    )
    assert mac["GIT_PYTHON_REFRESH"] == "quiet"
    assert mac["GIT_PYTHON_GIT_EXECUTABLE"].startswith("/nonexistent")
    assert (
        mcp_program("C:\\s\\mcp", "comfy-mcp", "windows")
        == "C:\\s\\mcp\\Scripts\\comfy-mcp.exe"
    )


def test_claude_codes_entry_goes_into_its_file_with_the_rest_kept():
    program = mcp_program("/s/comfyui/mcp", "comfy-mcp", "linux")
    entry = entry_of("claude_code", program=program, environment=ENVIRONMENT)
    assert entry == {
        "type": "stdio",
        "command": program,
        "args": [],
        "env": ENVIRONMENT,
    }
    text = json.dumps({"numStartups": 3, "mcpServers": {"mine": {"command": "x"}}})
    written = with_entry("claude_code", text, entry)
    document = json.loads(written)
    assert document["numStartups"] == 3
    assert document["mcpServers"]["mine"] == {"command": "x"}
    assert document["mcpServers"]["comfyui"] == entry
    assert with_entry("claude_code", written, entry) is None
    assert json.loads(with_entry("claude_code", "", entry)) == {
        "mcpServers": {"comfyui": entry}
    }
    removed = json.loads(without_entry("claude_code", written, program=program))
    assert removed == {"numStartups": 3, "mcpServers": {"mine": {"command": "x"}}}
    assert without_entry("claude_code", written, program="/other") is None


def test_opencodes_entry_is_a_local_command_list():
    program = "/s/comfyui/mcp/bin/comfy-mcp"
    entry = entry_of("opencode", program=program, environment=ENVIRONMENT)
    assert entry == {
        "type": "local",
        "command": [program],
        "environment": ENVIRONMENT,
        "enabled": True,
    }
    written = json.loads(with_entry("opencode", '{"model": "neutrino/x"}', entry))
    assert written == {"model": "neutrino/x", "mcp": {"comfyui": entry}}
    assert command_programs(entry_in("opencode", json.dumps(written))) == [program]
    with pytest.raises(ValueError):
        with_entry("opencode", "[]", entry)


def test_codexs_entry_is_its_own_table_with_the_rest_kept():
    program = "C:\\s\\mcp\\Scripts\\comfy-mcp.exe"
    entry = entry_of("codex", program=program, environment={"COMFY_BIN": "C:\\b"})
    table = codex_table(entry)
    assert table == (
        "[mcp_servers.comfyui]\n"
        'command = "C:\\\\s\\\\mcp\\\\Scripts\\\\comfy-mcp.exe"\n'
        "args = []\n"
        'env = { "COMFY_BIN" = "C:\\\\b" }\n'
    )
    text = 'model = "gpt"\n\n[mcp_servers.mine]\ncommand = "m"\n'
    written = with_entry("codex", text, entry)
    assert written.startswith(text.rstrip("\n") + "\n\n[mcp_servers.comfyui]")
    assert with_entry("codex", written, entry) is None
    old = written.replace("comfy-mcp.exe", "old.exe")
    again = with_entry("codex", old + '[mcp_servers.comfyui.env]\nX = "1"\n', entry)
    assert again.count("[mcp_servers.comfyui") == 1 and "old.exe" not in again
    assert without_entry("codex", written, program=program) == text.rstrip("\n") + "\n"
    assert command_programs(entry_in("codex", written)) == [program]
