"""The Claude Code module's configuration: the accounts it makes Claude Code ready for.

Each account is one the person enabled on the machine page. On Windows an
account also carries its password, from the login the hub holds for it,
since a command run as an account there needs its password.

Pure: parsing and validation.
"""

from neutrino_agent.modules.shared.programs import ProgramConfig


class ClaudeCodeConfig(ProgramConfig):
    """Everything the Claude Code module's desired configuration holds."""
