"""Paths and filesystem locations shared across packages.

Five roots, each answering one question about what is in it. The layout and
the reasoning are in
[design/files.md](../../../docs/standard/design/files.md); this is where it is
written down for the code.
"""

import os
from pathlib import Path

# The five roots. Nothing below invents a sixth.
UTILS_STATIC_ROOT = Path("/opt/neutrino")
UTILS_CONFIG_ROOT = Path("/etc/neutrino")
UTILS_STATE_ROOT = Path("/var/lib/neutrino")
UTILS_LOG_ROOT = Path("/var/log/neutrino")
UTILS_RUNTIME_ROOT = Path("/run/neutrino")

# The installed package, and the data that ships inside it: unit templates,
# feature manifests, the built panel, the example configs and the icons.
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
