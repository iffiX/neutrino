"""What kind of machine this is, and which platform class answers for it.

A function manifest lists the platforms a package exists for; this module
produces the keys that listing is matched against, from most to least
specific, so a manifest can say ``linux-debian-amd64`` when the artifact is
that particular, or just ``linux`` when anything with the right kernel works.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import platform
import sys

from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform

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
        ``{"os", "family", "arch"}`` — the operating system (``linux`` /
        ``windows`` / ``darwin``), the distribution family (``debian`` /
        ``rhel`` / empty), and the normalized architecture.
    """
    if sys.platform.startswith("linux"):
        os_name = "linux"
    elif sys.platform == "win32":
        os_name = "windows"
    elif sys.platform == "darwin":
        os_name = "darwin"
    else:
        os_name = sys.platform
    return {
        "os": os_name,
        "family": _distro_family() if os_name == "linux" else "",
        "arch": MACHINE_TO_ARCH.get(platform.machine().lower(), platform.machine()),
    }


def platform_keys(info: dict) -> "list[str]":
    """The manifest keys this machine matches, most specific first.

    Args:
        info: The tuple from :func:`platform_tuple`.

    Returns:
        Candidate keys; the first one present in a manifest's platform table
        wins.
    """
    os_name = info.get("os", "")
    family = info.get("family", "")
    arch = info.get("arch", "")
    keys = []
    if family:
        keys.append(f"{os_name}-{family}-{arch}")
        keys.append(f"{os_name}-{family}")
    keys.append(f"{os_name}-{arch}")
    keys.append(os_name)
    return keys


def detect_platform() -> AgentPlatform:
    """The platform class that answers for this machine.

    Returns:
        A platform instance; an operating system the agent does not know
        gets the base contract, which advertises nothing and refuses every
        capability.
    """
    os_name = platform_tuple()["os"]
    if os_name == "linux":
        return LinuxPlatform()
    if os_name == "darwin":
        return DarwinPlatform()
    if os_name == "windows":
        return WindowsPlatform()
    return AgentPlatform()


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
