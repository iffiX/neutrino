"""What kind of machine this is, and which platform class answers for it."""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import platform
import sys

from neutrino_client.platforms.base import ClientPlatform, PlatformUnsupportedError
from neutrino_client.platforms.linux import LinuxPlatform
from neutrino_client.platforms.windows import WindowsPlatform

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
        ``{"os", "family", "arch"}``: the operating system (``linux`` /
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


def detect_platform() -> ClientPlatform:
    """The platform class that answers for this machine.

    Returns:
        A platform instance; an operating system the client does not know
        gets the base contract, which refuses every capability.

    Raises:
        PlatformUnsupportedError: On macOS, which the client does not run
            on yet.
    """
    os_name = platform_tuple()["os"]
    if os_name == "linux":
        return LinuxPlatform()
    if os_name == "windows":
        return WindowsPlatform()
    if os_name == "darwin":
        raise PlatformUnsupportedError("the client does not run on macOS yet")
    return ClientPlatform()


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
