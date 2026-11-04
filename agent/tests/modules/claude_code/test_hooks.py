"""Claude Code's part of the shared runner: ``claude`` at the top of its copy, its known places, a launcher that turns the updater off."""

from neutrino_agent.modules.claude_code.hooks import ClaudeCodeHooks
from neutrino_agent.platforms.base import AgentPlatform


class Platform(AgentPlatform):
    def __init__(self, os_name):
        self.os_name = os_name


def test_the_program_is_claude_at_the_top_of_the_copy():
    assert ClaudeCodeHooks(platform=Platform("linux")).program_parts() == ("claude",)
    assert ClaudeCodeHooks(platform=Platform("windows")).program_parts() == (
        "claude.exe",
    )


def test_the_launcher_sets_disable_updates_and_the_known_places():
    assert ClaudeCodeHooks.program == "claude"
    assert ClaudeCodeHooks.launcher_variables == (("DISABLE_UPDATES", "1"),)
    assert ClaudeCodeHooks.known_places["linux"] == (
        "~/.local/bin/claude",
        "/usr/local/bin/claude",
        "/usr/bin/claude",
    )
    assert ClaudeCodeHooks.known_places["darwin"] == (
        "~/.local/bin/claude",
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    )
    assert ClaudeCodeHooks.known_places["windows"] == (
        "%USERPROFILE%\\.local\\bin\\claude.exe",
        "%LOCALAPPDATA%\\Microsoft\\WinGet\\Links\\claude.exe",
        "%APPDATA%\\npm\\claude.cmd",
    )
