"""OpenCode's part of the shared runner: its program in the package's bin folder, its known places, a launcher that sets nothing, its home folder's variable."""

import pytest

from neutrino_agent.modules.opencode.hooks import OpencodeHooks
from neutrino_agent.platforms.base import AgentPlatform


class Platform(AgentPlatform):
    def __init__(self, os_name):
        self.os_name = os_name


@pytest.mark.parametrize(
    "os_name, program, variable",
    [
        ("linux", "opencode", "HOME"),
        ("darwin", "opencode", "HOME"),
        ("windows", "opencode.exe", "USERPROFILE"),
    ],
)
def test_the_program_is_bin_opencode_and_its_home_folder_s_variable(
    os_name, program, variable
):
    hooks = OpencodeHooks(platform=Platform(os_name))

    assert hooks.program_parts() == ("bin", program)
    assert hooks.home_variable == variable


def test_the_known_places_and_the_launcher():
    assert OpencodeHooks.name == OpencodeHooks.runner == "opencode"
    assert OpencodeHooks.program == "opencode"
    assert OpencodeHooks.launcher_variables == ()
    assert OpencodeHooks.known_places["linux"] == (
        "~/.opencode/bin/opencode",
        "/usr/local/bin/opencode",
        "/usr/bin/opencode",
    )
    assert OpencodeHooks.known_places["darwin"] == (
        "~/.opencode/bin/opencode",
        "/opt/homebrew/bin/opencode",
        "/usr/local/bin/opencode",
    )
    assert OpencodeHooks.known_places["windows"] == (
        "%USERPROFILE%\\scoop\\shims\\opencode.exe",
        "%ProgramData%\\chocolatey\\bin\\opencode.exe",
        "%APPDATA%\\npm\\opencode.cmd",
    )
