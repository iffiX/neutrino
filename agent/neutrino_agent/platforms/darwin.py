"""The macOS platform."""

from neutrino_agent.platforms.base import AgentPlatform


class DarwinPlatform(AgentPlatform):
    """macOS behind the platform contract."""

    os_name = "darwin"
