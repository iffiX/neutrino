"""Which system the hub runs on, and the platform class that answers for it.

The classes are imported when asked for, so this module stays importable
from ``utils/constants.py`` before anything else of the hub is.
"""

import sys

from neutrino_hub.platforms.constants import (
    PLATFORM_OS_DARWIN,
    PLATFORM_OS_LINUX,
    PLATFORM_OS_WINDOWS,
)

# The one controller this process hands out.
_CONTROLLER = None


def hub_os() -> str:
    """Name the system the hub runs on.

    Returns:
        ``linux``, ``darwin`` or ``windows``, the words the panel's API uses.

    Raises:
        RuntimeError: The system is none of the three.
    """
    if sys.platform.startswith("linux"):
        return PLATFORM_OS_LINUX
    if sys.platform == "darwin":
        return PLATFORM_OS_DARWIN
    if sys.platform == "win32":
        return PLATFORM_OS_WINDOWS
    raise RuntimeError(f"unsupported system: {sys.platform}")


def is_linux() -> bool:
    """Whether the hub runs on Linux, where each daemon is a unit of its own.

    Returns:
        True on Linux.

    Raises:
        RuntimeError: The system is none of the three.
    """
    return hub_os() == PLATFORM_OS_LINUX


def hub_platform():
    """The platform class that answers for this system.

    Returns:
        A :class:`neutrino_hub.platforms.base.HubPlatform`.

    Raises:
        RuntimeError: The system is none of the three.
    """
    system = hub_os()
    if system == PLATFORM_OS_LINUX:
        from neutrino_hub.platforms.linux import LinuxHubPlatform

        return LinuxHubPlatform()
    if system == PLATFORM_OS_DARWIN:
        from neutrino_hub.platforms.darwin import DarwinHubPlatform

        return DarwinHubPlatform()
    from neutrino_hub.platforms.windows import WindowsHubPlatform

    return WindowsHubPlatform()


def process_controller():
    """The one controller of the daemons the hub runs, for this process.

    The panel's runtime, the supervisor and every ``nhub`` command take it
    from here, so inside the service they share the children it runs.

    Returns:
        A :class:`neutrino_hub.system.process_control.ProcessController`.

    Raises:
        RuntimeError: The system is none of the three.
    """
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = hub_platform().process_controller()
    return _CONTROLLER
