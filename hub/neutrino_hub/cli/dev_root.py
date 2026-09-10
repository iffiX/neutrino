"""The development root a working copy runs an appliance inside.

``--dev`` moves the five roots under ``hub_dev_root/`` in the working copy, so
deleting one directory undoes the hub. What it does not undo — the interface
roles, the firewall, the service account — is in
[design/install_and_dev.md](../../../skills/core-code-author/design/install_and_dev.md).

This runs before anything imports ``utils.constants``, which resolves those
roots against the environment as it is imported. That is why the variable's
name is spelled here rather than read from there, and why a test holds the two
spellings together.
"""

import os
from pathlib import Path

# --- config ---
DEV_ROOT_ENV = "NEUTRINO_DEV_ROOT"
DEV_ROOT_NAME = "hub_dev_root"
# The project a working copy installs the hub from. Its absence is what says
# this hub came from a package, where there is no tree to keep a root beside.
DEV_PROJECT_FILE = "pyproject.toml"


class NoWorkingCopy(RuntimeError):
    """``--dev`` was asked for by a hub that came from a package."""


def enter() -> Path:
    """Point this process at the working copy's development root.

    Creates the directory if it is not there, so the first run needs no setup
    of its own. Running twice is harmless: an environment that already names a
    root is left alone, which is what lets a panel started under ``--dev``
    keep its own root across a reload.

    Returns:
        The root now in force.

    Raises:
        NoWorkingCopy: When there is no checkout to keep a root beside.
    """
    named = os.environ.get(DEV_ROOT_ENV)
    if named:
        return Path(named)
    root = checkout_root() / DEV_ROOT_NAME
    root.mkdir(parents=True, exist_ok=True)
    os.environ[DEV_ROOT_ENV] = str(root)
    return root


def checkout_root() -> Path:
    """The working copy this package was imported from.

    Returns:
        The directory holding ``hub/``.

    Raises:
        NoWorkingCopy: When there is no project beside the package.
    """
    package_root = Path(__file__).resolve().parent.parent
    if not (package_root.parent / DEV_PROJECT_FILE).is_file():
        raise NoWorkingCopy(
            "--dev runs from a working copy, and this hub came from a package"
        )
    return package_root.parent.parent
