"""OpenCode's part of the shared runner: its program in the package's bin folder, a launcher that sets nothing, its home folder's variable."""

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


def test_the_launcher_sets_nothing():
    assert OpencodeHooks.name == OpencodeHooks.runner == "opencode"
    assert OpencodeHooks.program == "opencode"
    assert OpencodeHooks.launcher_variables == ()
