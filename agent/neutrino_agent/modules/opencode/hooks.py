"""What OpenCode adds to the shared runner of the command line programs.

The module's copy is the publisher's npm package for the machine's
platform, unpacked into ``package`` in the module's directory, the program
``bin/opencode`` there. The launcher starts it and sets nothing, and its
``verify`` runs with the home folder in the module's directory.

Pure: names the program and the home folder's variable.
"""

from neutrino_agent.modules.opencode.config import OpencodeConfig
from neutrino_agent.modules.opencode.constants import (
    OPENCODE_BIN_DIR_NAME,
    OPENCODE_HOME_VARIABLE,
    OPENCODE_HOME_VARIABLES,
    OPENCODE_KNOWN_PLACES,
    OPENCODE_NAME,
    OPENCODE_PROGRAM,
    OPENCODE_RUNNER,
    OPENCODE_TITLE,
)
from neutrino_agent.modules.shared.programs import ProgramHooks


class OpencodeHooks(ProgramHooks):
    """OpenCode's part of the shared runner."""

    name = OPENCODE_NAME
    title = OPENCODE_TITLE
    runner = OPENCODE_RUNNER
    program = OPENCODE_PROGRAM
    known_places = OPENCODE_KNOWN_PLACES
    config_class = OpencodeConfig

    @property
    def home_variable(self) -> str:
        """The variable naming the home folder on this machine's system.

        Returns:
            ``USERPROFILE`` on Windows, ``HOME`` elsewhere.
        """
        return OPENCODE_HOME_VARIABLES.get(
            self._platform.os_name, OPENCODE_HOME_VARIABLE
        )

    def program_parts(self) -> tuple:
        """The program in the module's copy.

        Returns:
            ``bin/opencode``, ``bin/opencode.exe`` on Windows.
        """
        suffix = ".exe" if self._platform.os_name == "windows" else ""
        return (OPENCODE_BIN_DIR_NAME, OPENCODE_PROGRAM + suffix)
