"""Where the binaries the client carries are installed.

The packages put cc-switch and the RustDesk viewer beside the client: under
``/opt/neutrino_client`` on Linux, next to the package on Windows, under
the app bundle's ``Contents/Resources`` on macOS. A checkout carries
neither, and asking for one there is a typed refusal.
"""

import os
import pathlib
import sys

from neutrino_client.constants import (
    CLIENT_BUNDLED_PATHS_DARWIN,
    CLIENT_BUNDLED_PATHS_LINUX,
    CLIENT_BUNDLED_PATHS_WINDOWS,
    CLIENT_INSTALL_PREFIX_LINUX,
)

_PACKAGE_DIR = pathlib.Path(__file__).resolve().parent


def bundle_missing(binary: str) -> dict:
    """The typed refusal for a carried binary that is not on the machine.

    Args:
        binary: The binary's name.

    Returns:
        ``{"code": "bundle_missing", "params": {"binary"}}``.
    """
    return {"code": "bundle_missing", "params": {"binary": binary}}


def bundled_path(binary: str) -> str:
    """One carried binary's absolute path.

    Args:
        binary: ``cc-switch`` or ``rustdesk``.

    Returns:
        The path when the binary is on the machine, empty otherwise.
    """
    if os.name == "nt":
        relative = CLIENT_BUNDLED_PATHS_WINDOWS.get(binary, "")
        root = _PACKAGE_DIR.parent
    elif sys.platform == "darwin":
        relative = CLIENT_BUNDLED_PATHS_DARWIN.get(binary, "")
        root = _PACKAGE_DIR.parent.parent
    else:
        relative = CLIENT_BUNDLED_PATHS_LINUX.get(binary, "")
        root = pathlib.Path(CLIENT_INSTALL_PREFIX_LINUX)
    if not relative:
        return ""
    candidate = root / relative
    if candidate.is_file() and os.access(str(candidate), os.X_OK):
        return str(candidate)
    return ""


def cc_switch_path() -> str:
    """The carried cc-switch CLI, empty when the bundle is absent."""
    return bundled_path("cc-switch")


def rustdesk_path() -> str:
    """The carried RustDesk viewer, empty when the bundle is absent."""
    return bundled_path("rustdesk")
