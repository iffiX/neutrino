"""What kind of machine this is, and which platform class answers for it.

A manifest lists the platforms a package exists for; this module produces
the keys that listing is matched against, from most to least specific, so a
manifest can say ``linux-debian-amd64`` when the artifact is that
particular, or just ``linux`` when anything with the right kernel works.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import platform
import sys

from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.linux import LinuxPlatform

OS_RELEASE_PATH = "/etc/os-release"

MACHINE_TO_ARCH = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "armhf",
    "armv6l": "armhf",
}

DEBIAN_LIKE = ("debian", "ubuntu", "raspbian", "linuxmint", "pop")
RHEL_LIKE = ("rhel", "fedora", "centos", "rocky", "almalinux")


def platform_tuple() -> dict:
    """Describe this machine.

    Returns:
        ``{"os", "family", "arch"}`` — the operating system, the
        distribution family (``debian`` / ``rhel`` / empty), and the
        normalized architecture.
    """
    os_name = "linux" if sys.platform.startswith("linux") else sys.platform
    return {
        "os": os_name,
        "family": _distro_family() if os_name == "linux" else "",
        "arch": MACHINE_TO_ARCH.get(platform.machine().lower(), platform.machine()),
    }


def detect_platform() -> LinuxPlatform:
    """The platform class that answers for this machine.

    Returns:
        The Linux platform.

    Raises:
        PlatformUnsupportedError: On anything that is not Linux.
    """
    os_name = platform_tuple()["os"]
    if os_name != "linux":
        raise PlatformUnsupportedError(f"the agent runs on Linux, not {os_name}")
    return LinuxPlatform()


def _distro_family() -> str:
    try:
        with open(OS_RELEASE_PATH, "r", encoding="utf-8") as stream:
            fields = {}
            for line in stream:
                key, _, value = line.partition("=")
                fields[key.strip()] = value.strip().strip('"')
    except OSError:
        return ""
    names = [fields.get("ID", "")] + fields.get("ID_LIKE", "").split()
    for name in names:
        if name in DEBIAN_LIKE:
            return "debian"
        if name in RHEL_LIKE:
            return "rhel"
    return ""
