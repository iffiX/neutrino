"""What machine this is, for modules that care.

Every module declares ``<PREFIX>_SUPPORTED_ARCHITECTURES`` in its
``constants.py`` — ``("*",)`` when its installer handles architecture itself
(apt and the vendors' own scripts do), or the explicit list when the module
downloads a binary and must pick the right one. This is where the declaration
meets the actual machine.
"""

import platform

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
