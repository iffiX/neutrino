"""What Codex adds to the shared runner of the command line programs.

The module's copy is OpenAI's npm build for the machine's platform,
unpacked into ``package`` in the module's directory. Its program is
``vendor/<target>/bin/codex`` there, beside the helpers Codex finds through
``codex-package.json``. The launcher starts it and sets nothing, and its
``verify`` runs with ``CODEX_HOME`` in the module's directory.

Not pure: reads the machine's platform.
"""

from neutrino_agent.modules.codex.config import CodexConfig
from neutrino_agent.modules.codex.constants import (
    CODEX_BIN_DIR_NAME,
    CODEX_HOME_VARIABLE,
    CODEX_KNOWN_PLACES,
    CODEX_NAME,
    CODEX_PROGRAM,
    CODEX_RUNNER,
    CODEX_TARGETS,
    CODEX_TITLE,
    CODEX_VENDOR_DIR_NAME,
)
from neutrino_agent.modules.shared.programs import ProgramHooks
from neutrino_agent.platforms.detect import platform_tuple


class CodexHooks(ProgramHooks):
    """Codex's part of the shared runner."""

    name = CODEX_NAME
    title = CODEX_TITLE
    runner = CODEX_RUNNER
    program = CODEX_PROGRAM
    known_places = CODEX_KNOWN_PLACES
    home_variable = CODEX_HOME_VARIABLE
    config_class = CodexConfig

    def program_parts(self) -> tuple:
        """The program under the module's copy for this machine's system and architecture.

        Returns:
            ``vendor/<target>/bin/codex``, ``codex.exe`` on Windows.
        """
        os_name = self._platform.os_name
        target = CODEX_TARGETS.get((os_name, platform_tuple()["arch"]), "")
        program = CODEX_PROGRAM + (".exe" if os_name == "windows" else "")
        return (CODEX_VENDOR_DIR_NAME, target, CODEX_BIN_DIR_NAME, program)
