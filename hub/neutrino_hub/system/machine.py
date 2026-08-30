"""What machine this is, for modules that care.

Every module declares ``<PREFIX>_SUPPORTED_ARCHITECTURES`` in its
``constants.py`` — ``("*",)`` when its installer handles architecture itself
(the package manager and the vendors' own scripts do), or the explicit list
when the module downloads a binary and must pick the right one.

A module that installs system packages declares ``<PREFIX>_PACKAGES`` the same
way, keyed by distribution family, and a family it has no entry for is a family
it does not run on. This is where both declarations meet the actual machine.
"""

import platform
from pathlib import Path

# Kernel names for one architecture vary by distribution and bitness; the
# normalized name is what release downloads are keyed by.
ARCHITECTURE_NORMALIZATION = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    # 32-bit Raspberry Pi OS reports armv6l or armv7l; vendors ship one
    # ARM-32 build and key it to the v6 baseline.
    "armv6l": "arm-6",
    "armv7l": "arm-6",
}

ANY_ARCHITECTURE = "*"

OS_RELEASE_PATH = Path("/etc/os-release")

# Which family a distribution belongs to decides its package manager, its
# package names and some of its service names. Matched against the ID field of
# /etc/os-release first, then against ID_LIKE, so a derivative nobody listed
# here still lands in the right family.
DISTRIBUTION_FAMILIES = {
    "debian": ("debian", "ubuntu", "raspbian", "linuxmint", "pop"),
    "rhel": ("rhel", "fedora", "centos", "rocky", "almalinux"),
    "arch": ("arch", "manjaro", "endeavouros"),
    "suse": ("opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"),
}

UNKNOWN_FAMILY = ""


def machine_architecture() -> str:
    """The normalized name of this machine's architecture.

    Returns:
        ``amd64``, ``arm64``, ``arm-6``, or the kernel's own name for
        anything unrecognized — honest input for a support check, rather
        than a guess.
    """
    raw = platform.machine().lower()
    return ARCHITECTURE_NORMALIZATION.get(raw, raw)


def require_architecture(supported: tuple, what: str) -> None:
    """Refuse to continue on a machine a module does not support.

    Args:
        supported: The module's declared list, possibly ``("*",)``.
        what: What was about to be installed, for the error.

    Raises:
        RuntimeError: When this machine is not covered — before a wrong
            binary lands, not after it fails to start.
    """
    if ANY_ARCHITECTURE in supported:
        return
    architecture = machine_architecture()
    if architecture not in supported:
        raise RuntimeError(
            f"{what} does not support this machine ({architecture}); "
            f"it runs on: {', '.join(supported)}"
        )


def distribution_family() -> str:
    """Which family of distributions this machine belongs to.

    Returns:
        ``debian``, ``rhel``, ``arch``, ``suse``, or empty when
        ``/etc/os-release`` names something unrecognized. Empty is honest
        input for a support check rather than a guess at a package manager.
    """
    fields = _os_release()
    names = [fields.get("ID", "")] + fields.get("ID_LIKE", "").split()
    for name in names:
        for family, members in DISTRIBUTION_FAMILIES.items():
            if name in members:
                return family
    return UNKNOWN_FAMILY


def distribution_name() -> str:
    """What the distribution calls itself, for error messages.

    Returns:
        Something like ``Debian GNU/Linux 12 (bookworm)``, or ``unknown``.
    """
    return _os_release().get("PRETTY_NAME", "") or "unknown"


def require_distribution(packages: dict, what: str) -> tuple:
    """Refuse to install on a distribution a module has no packages for.

    Args:
        packages: The module's ``<PREFIX>_PACKAGES``, keyed by family.
        what: What was about to be installed, for the error.

    Returns:
        The package names for this machine's family.

    Raises:
        RuntimeError: When the family is not covered, or is covered by an
            entry saying the distribution has no such packages.
    """
    family = distribution_family()
    if family not in packages or packages[family] is None:
        raise RuntimeError(
            f"{what} does not support {distribution_name()}; "
            f"it installs on: {', '.join(sorted(packages))}"
        )
    return packages[family]


def _os_release() -> dict:
    """Parse ``/etc/os-release`` into its fields.

    Returns:
        The file's key-value pairs with quotes stripped, empty when the file
        is missing or unreadable.
    """
    try:
        text = OS_RELEASE_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    fields = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields
