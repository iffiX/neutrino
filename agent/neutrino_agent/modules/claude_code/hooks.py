"""What Claude Code adds to the shared runner of the command line programs.

The module's copy is Anthropic's npm package for the machine's platform,
unpacked into ``package`` in the module's directory, the program ``claude``
at its top. The launcher sets ``DISABLE_UPDATES=1``, so the copy never
installs another version.

Pure: names the program and what the launcher sets.
"""

from neutrino_agent.modules.claude_code.config import ClaudeCodeConfig
from neutrino_agent.modules.claude_code.constants import (
    CLAUDE_CODE_KNOWN_PLACES,
    CLAUDE_CODE_LAUNCHER_VARIABLES,
    CLAUDE_CODE_NAME,
    CLAUDE_CODE_PROGRAM,
    CLAUDE_CODE_RUNNER,
    CLAUDE_CODE_TITLE,
)
from neutrino_agent.modules.shared.programs import ProgramHooks


class ClaudeCodeHooks(ProgramHooks):
    """Claude Code's part of the shared runner."""

    name = CLAUDE_CODE_NAME
    title = CLAUDE_CODE_TITLE
    runner = CLAUDE_CODE_RUNNER
    program = CLAUDE_CODE_PROGRAM
    known_places = CLAUDE_CODE_KNOWN_PLACES
    launcher_variables = CLAUDE_CODE_LAUNCHER_VARIABLES
    config_class = ClaudeCodeConfig

    def program_parts(self) -> tuple:
        """The program at the top of the module's copy.

        Returns:
            ``claude``, ``claude.exe`` on Windows.
        """
        suffix = ".exe" if self._platform.os_name == "windows" else ""
        return (CLAUDE_CODE_PROGRAM + suffix,)
