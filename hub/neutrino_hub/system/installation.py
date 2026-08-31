"""Where this hub came from, and what follows from that.

A package carries its own environment with the hub already installed into it;
a checkout runs from the tree it sits in. Every path that differs between the
two is decided here, so no caller has to work it out twice.
"""

import sys
from pathlib import Path

from neutrino_hub.system.constants import SYSTEM_VENV_DIR_NAME
from neutrino_hub.utils.constants import UTILS_PACKAGE_ROOT

# --- config ---
# The project a checkout would install the hub from. It sits beside the
# package rather than at the root of the repository, which holds `hub/` and
# `config/` and no project of its own.
SYSTEM_PROJECT_FILE = "pyproject.toml"


def is_packaged() -> bool:
    """Whether this hub came from a package rather than a checkout.

    A package carries its environment with the hub already installed into it,
    so there is no project to build one from: beside the package sits
    site-packages rather than the ``hub/`` directory of a checkout.

    Returns:
        True when there is no project to install from.
    """
    return not project_root().is_file()


def project_root() -> Path:
    """The pyproject a checkout would install the hub from.

    Returns:
        The path, whether or not it exists.
    """
    return UTILS_PACKAGE_ROOT.parent / SYSTEM_PROJECT_FILE


def checkout_root() -> Path:
    """The working copy this package was imported from.

    Only meaningful in a checkout, which is what the editable install and the
    virtual environment both assume.

    Returns:
        The directory holding ``hub/`` and ``config/``.
    """
    return UTILS_PACKAGE_ROOT.parent.parent


def venv_python() -> Path:
    """The interpreter the panel runs under.

    Returns:
        The one inside the environment the package carries when the hub was
        installed from a package, and the checkout's own otherwise.
    """
    if is_packaged():
        return Path(sys.executable)
    return checkout_root() / SYSTEM_VENV_DIR_NAME / "bin" / "python"
