"""Paths and filesystem locations shared across packages."""

import os
from pathlib import Path

# The installed package, and the data that ships inside it: unit templates,
# feature manifests, the built panel, the example configs and the icons.
UTILS_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
UTILS_DATA_DIR = UTILS_PACKAGE_ROOT / "data"

# Where the real configuration lives. An installed hub keeps it under /etc; a
# checkout keeps it beside the source so development needs no setup. The
# environment variable wins, which is what makes a second instance testable.
UTILS_CONFIG_ENV = "NEUTRINO_CONFIG_DIR"
UTILS_SYSTEM_CONFIG_DIR = Path("/etc/neutrino/config")
UTILS_CHECKOUT_CONFIG_DIR = UTILS_PACKAGE_ROOT.parent.parent / "config"

UTILS_GENERATED_DIR = Path("/etc/neutrino/generated")
UTILS_LOG_DIR = Path("/var/log/neutrino")


def resolve_config_dir() -> Path:
    """Where this instance reads and writes its configuration.

    Returns:
        The environment's override, the system directory when it exists, and
        the checkout's own ``config/`` otherwise.
    """
    override = os.environ.get(UTILS_CONFIG_ENV)
    if override:
        return Path(override)
    if UTILS_SYSTEM_CONFIG_DIR.exists():
        return UTILS_SYSTEM_CONFIG_DIR
    return UTILS_CHECKOUT_CONFIG_DIR


UTILS_CONFIG_DIR = resolve_config_dir()
