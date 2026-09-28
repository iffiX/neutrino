"""The Windows platform."""

from neutrino_agent.platforms.base import AgentPlatform


class WindowsPlatform(AgentPlatform):
    """Windows behind the platform contract."""

    os_name = "windows"
