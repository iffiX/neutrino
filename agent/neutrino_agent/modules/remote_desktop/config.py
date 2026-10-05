"""The Remote desktop module's configuration: one switch.

Pure: parsing only.
"""

from dataclasses import dataclass


@dataclass
class RemoteDesktopConfig:
    """What the hub says about this machine's desktop.

    Attributes:
        is_enabled: Whether the desktop is shared.
    """

    is_enabled: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteDesktopConfig":
        """Read the configuration the state carries.

        Args:
            data: ``{is_enabled}``; anything else reads as off.

        Returns:
            The configuration.
        """
        if not isinstance(data, dict):
            return cls()
        return cls(is_enabled=data.get("is_enabled") is True)
