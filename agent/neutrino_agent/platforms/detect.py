"""What kind of machine this is, and which platform class answers for it.

A manifest lists the platforms a package exists for; this module produces
the keys that listing is matched against, from most to least specific, so a
manifest can say ``linux-debian-amd64`` when the artifact is that
particular, or just ``linux`` when anything with the right kernel works.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import platform
import sys

from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform

OS_RELEASE_PATH = "/etc/os-release"

# What ``sys.platform`` reports, mapped to the name the tuple carries: the
# same names the client reports, so the hub reads one table for both.
OS_NAMES = {"linux": "linux", "win32": "windows", "darwin": "darwin"}

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
        ``{"os", "family", "arch", "version"}``: the operating system
        (``linux`` / ``windows`` / ``darwin``, else what Python names it),
        the distribution family (``debian`` / ``rhel`` / empty), the
        normalized architecture, and the system's version: the glibc
        version on Linux, the build number on Windows, the product version
        on macOS, empty where it cannot be read.
    """
    reported = "linux" if sys.platform.startswith("linux") else sys.platform
    os_name = OS_NAMES.get(reported, reported)
    return {
        "os": os_name,
        "family": _distro_family() if os_name == "linux" else "",
        "arch": MACHINE_TO_ARCH.get(platform.machine().lower(), platform.machine()),
        "version": _system_version(os_name),
    }


def detect_platform() -> AgentPlatform:
    """The platform class that answers for this machine.

    Returns:
        The platform of this operating system; one the agent does not know
        gets the base contract, which advertises nothing and refuses every
        capability.
    """
    os_name = platform_tuple()["os"]
    if os_name == "linux":
        return LinuxPlatform()
    if os_name == "windows":
        return WindowsPlatform()
    if os_name == "darwin":
        return DarwinPlatform()
    return AgentPlatform()


def _system_version(os_name: str) -> str:
    """The version a manifest's floor is compared with, empty when unknown."""
    if os_name == "linux":
        return _glibc_version()
    if os_name == "windows":
        getter = getattr(sys, "getwindowsversion", None)
        return str(getter().build) if getter is not None else ""
    if os_name == "darwin":
        return platform.mac_ver()[0]
    return ""


def _glibc_version() -> str:
    """The C library's version, as glibc names itself; empty on another libc."""
    try:
        named = os.confstr("CS_GNU_LIBC_VERSION") or ""
    except (AttributeError, ValueError, OSError):
        named = ""
    library, _, version = named.partition(" ")
    if library == "glibc" and version:
        return version
    library, version = platform.libc_ver()
    return version if library == "glibc" else ""


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
