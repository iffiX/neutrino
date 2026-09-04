"""Paths and filesystem locations shared across packages.

Five roots, each answering one question about what is in it. The layout and
the reasoning are in
[design/files.md](../../../docs/standard/design/files.md); this is where it is
written down for the code.
"""

import os
from pathlib import Path

# A working copy's own root, which every root below hangs under when it is
# set. It is what `--dev` uses to put a whole appliance's filesystem inside the
# checkout, so deleting one directory undoes the hub. What it does not undo is
# in design/install_and_dev.md.
UTILS_DEV_ROOT_ENV = "NEUTRINO_DEV_ROOT"


def _rooted(path: str) -> Path:
    """One of the five roots, moved under the development root when there is one.

    Args:
        path: The absolute path a real machine uses.

    Returns:
        That path, or the same path inside ``NEUTRINO_DEV_ROOT``.
    """
    dev_root = os.environ.get(UTILS_DEV_ROOT_ENV)
    if not dev_root:
        return Path(path)
    return Path(dev_root) / path.lstrip("/")


# The five roots. Nothing below invents a sixth.
UTILS_STATIC_ROOT = _rooted("/opt/neutrino")
UTILS_CONFIG_ROOT = _rooted("/etc/neutrino")
UTILS_STATE_ROOT = _rooted("/var/lib/neutrino")
UTILS_LOG_ROOT = _rooted("/var/log/neutrino")
UTILS_RUNTIME_ROOT = _rooted("/run/neutrino")


def is_dev_root_set() -> bool:
    """Whether this process runs against a development root.

    Returns:
        True when ``NEUTRINO_DEV_ROOT`` names one.
    """
    return bool(os.environ.get(UTILS_DEV_ROOT_ENV))


# The installed package, and the data that ships inside it: unit templates,
# function manifests, the built panel, the example configs and the icons.
UTILS_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
UTILS_DATA_DIR = UTILS_PACKAGE_ROOT / "data"

# The committed *.example.json, laid out the way config/ is, so a fresh
# machine's first config is a copy from here. They ship inside the package
# rather than beside the real files, which are not in git at all.
UTILS_EXAMPLES_DIR = UTILS_DATA_DIR / "examples"

# Where the real configuration lives. An installed hub keeps it under /etc; a
# checkout keeps it beside the source so development needs no setup. The
# environment variable wins, which is what makes a second instance testable.
UTILS_CONFIG_ENV = "NEUTRINO_CONFIG_DIR"
UTILS_SYSTEM_CONFIG_DIR = UTILS_CONFIG_ROOT / "hub"
UTILS_CHECKOUT_CONFIG_DIR = UTILS_PACKAGE_ROOT.parent.parent / "config"

# Rendered from config/ and thrown away whenever it is rendered again, so it is
# state rather than configuration: nothing here is worth backing up.
UTILS_GENERATED_DIR = UTILS_STATE_ROOT / "generated"

# The address and domain databases. They ship with the package and are replaced
# by newer ones while the machine runs, which is what keeps them out of the
# static root.
UTILS_GEODATA_DIR = UTILS_STATE_ROOT / "geodata"

UTILS_LOG_DIR = UTILS_LOG_ROOT


def resolve_config_dir() -> Path:
    """Where this instance reads and writes its configuration.

    Returns:
        The environment's override, the system directory under a development
        root or when one exists, and the checkout's own ``config/`` otherwise.
    """
    override = os.environ.get(UTILS_CONFIG_ENV)
    if override:
        return Path(override)
    # A development root is a whole appliance, so its configuration is where an
    # appliance keeps it. The checkout's own `config/` is what a working copy
    # with no development root falls back to.
    if is_dev_root_set() or UTILS_SYSTEM_CONFIG_DIR.exists():
        return UTILS_SYSTEM_CONFIG_DIR
    return UTILS_CHECKOUT_CONFIG_DIR


UTILS_CONFIG_DIR = resolve_config_dir()
