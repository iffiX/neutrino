"""Which system the hub runs on."""

import sys

from neutrino_hub.platforms.constants import (
    PLATFORM_OS_DARWIN,
    PLATFORM_OS_LINUX,
    PLATFORM_OS_WINDOWS,
)


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
