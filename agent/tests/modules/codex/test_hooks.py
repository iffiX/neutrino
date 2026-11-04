"""Codex's part of the shared runner: its program under the build target of each platform, its known places, a launcher that sets nothing."""

import pytest

from neutrino_agent.modules.codex import hooks as codex_hooks
from neutrino_agent.modules.codex.hooks import CodexHooks
from neutrino_agent.platforms.base import AgentPlatform


class Platform(AgentPlatform):
    def __init__(self, os_name):
        self.os_name = os_name


@pytest.mark.parametrize(
    "os_name, arch, parts",
    [
        ("linux", "amd64", ("x86_64-unknown-linux-musl", "codex")),
        ("linux", "arm64", ("aarch64-unknown-linux-musl", "codex")),
        ("darwin", "amd64", ("x86_64-apple-darwin", "codex")),
        ("darwin", "arm64", ("aarch64-apple-darwin", "codex")),
        ("windows", "amd64", ("x86_64-pc-windows-msvc", "codex.exe")),
        ("windows", "arm64", ("aarch64-pc-windows-msvc", "codex.exe")),
    ],
)
def test_the_program_is_vendor_target_bin_codex(monkeypatch, os_name, arch, parts):
    monkeypatch.setattr(codex_hooks, "platform_tuple", lambda: {"arch": arch})
    target, program = parts

    assert CodexHooks(platform=Platform(os_name)).program_parts() == (
        "vendor",
        target,
        "bin",
        program,
    )


def test_the_known_places_and_the_launcher():
    assert CodexHooks.program == "codex"
    assert CodexHooks.launcher_variables == ()
    assert CodexHooks.known_places["linux"] == (
        "~/.local/bin/codex",
        "/usr/local/bin/codex",
    )
    assert CodexHooks.known_places["darwin"] == (
        "~/.local/bin/codex",
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
    )
    assert CodexHooks.known_places["windows"] == (
        "%LOCALAPPDATA%\\Programs\\OpenAI\\Codex\\bin\\codex.exe",
        "%APPDATA%\\npm\\codex.cmd",
    )
