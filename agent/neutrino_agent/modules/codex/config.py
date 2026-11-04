"""The Codex module's configuration: the accounts it makes Codex ready for.

Each account is one the person enabled on the machine page. On Windows an
account also carries its password, from the login the hub holds for it,
since a command run as an account there needs its password.

Pure: parsing and validation.
"""

from neutrino_agent.modules.shared.programs import ProgramConfig


class CodexConfig(ProgramConfig):
    """Everything the Codex module's desired configuration holds."""
