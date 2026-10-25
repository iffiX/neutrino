"""Paths and filesystem locations shared across packages.

Five roots, each answering one question about what is in it. The layout and
the reasoning are in
[design/files.md](../../../skills/core-code-author/design/files.md); this is where it is
written down for the code.
"""

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

from neutrino_hub.platforms.constants import (
    PLATFORM_OS_WINDOWS,
    PLATFORM_ROOT_CONFIG,
    PLATFORM_ROOT_LOG,
    PLATFORM_ROOT_RUNTIME,
    PLATFORM_ROOT_STATE,
    PLATFORM_ROOT_STATIC,
    PLATFORM_ROOTS,
)
from neutrino_hub.platforms.detect import hub_os

# A working copy's own root, which every root below hangs under when it is
# set. It is what `--dev` uses to put a whole appliance's filesystem inside the
# checkout, so deleting one directory undoes the hub. What it does not undo is
# in design/install_and_dev.md.
UTILS_DEV_ROOT_ENV = "NEUTRINO_DEV_ROOT"


def _rooted(question: str) -> Path:
    """One of the five roots, moved under the development root when there is one.

    Args:
        question: Which root, a ``PLATFORM_ROOT_`` key of this system's table.

    Returns:
        The path this system uses, or the same path inside ``NEUTRINO_DEV_ROOT``.
    """
    system = hub_os()
    path = PLATFORM_ROOTS[system][question]
    dev_root = os.environ.get(UTILS_DEV_ROOT_ENV)
    if not dev_root:
        return Path(path)
    if system == PLATFORM_OS_WINDOWS:
        return Path(dev_root, *PureWindowsPath(path).parts[1:])
    return Path(dev_root, *PurePosixPath(path).parts[1:])


# The five roots. Nothing below invents a sixth.
UTILS_STATIC_ROOT = _rooted(PLATFORM_ROOT_STATIC)
UTILS_SYSTEM_CONFIG_DIR = _rooted(PLATFORM_ROOT_CONFIG)
UTILS_CONFIG_ROOT = UTILS_SYSTEM_CONFIG_DIR.parent
UTILS_STATE_ROOT = _rooted(PLATFORM_ROOT_STATE)
UTILS_LOG_ROOT = _rooted(PLATFORM_ROOT_LOG)
UTILS_RUNTIME_ROOT = _rooted(PLATFORM_ROOT_RUNTIME)


# Where the package puts the programs it carries; on Windows each name ends in
# .exe.
UTILS_PROGRAM_DIR = UTILS_STATIC_ROOT / "bin"
UTILS_WINDOWS_PROGRAM_SUFFIX = ".exe"


def carried_program(name: str) -> Path:
    """The path of one program the hub's package carries.

    Args:
        name: The program's name without a suffix, for example ``xray``.

    Returns:
        The program under :data:`UTILS_PROGRAM_DIR`, with ``.exe`` added on
        Windows.

    Raises:
        RuntimeError: The system is none of the three.
    """
    suffix = UTILS_WINDOWS_PROGRAM_SUFFIX if hub_os() == PLATFORM_OS_WINDOWS else ""
    return UTILS_PROGRAM_DIR / f"{name}{suffix}"


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
# How an example names a placeholder record, as a key or as an id in a list.
UTILS_EXAMPLE_RECORD_PREFIX = "_example_"

# Where the real configuration lives. An installed hub keeps it under /etc; a
# checkout keeps it beside the source so development needs no setup. The
# environment variable wins, which is what makes a second instance testable.
UTILS_CONFIG_ENV = "NEUTRINO_CONFIG_DIR"
UTILS_CHECKOUT_CONFIG_DIR = UTILS_PACKAGE_ROOT.parent.parent / "config"

# Rendered from config/ and thrown away whenever it is rendered again, so it is
# state rather than configuration: nothing here is worth backing up.
UTILS_GENERATED_DIR = UTILS_STATE_ROOT / "generated"


UTILS_LOG_DIR = UTILS_LOG_ROOT

# What one `nhub setup` run wrote down. The installer truncates it as it
# starts, so the file is that run and no earlier one, and it needs no cap.
UTILS_SETUP_LOG_PATH = UTILS_LOG_ROOT / "setup.log"


def is_stamped_package() -> bool:
    """Whether this hub is a built package rather than a checkout.

    A build writes ``_version.py`` into the tree, compiled or not; a checkout
    has none.

    Returns:
        True when the build stamp imports.
    """
    try:
        import neutrino_hub._version  # noqa: F401
    except ImportError:
        return False
    return True


def resolve_config_dir() -> Path:
    """Where this instance reads and writes its configuration.

    Returns:
        The environment's override; the system directory under a development
        root, in a built package whether or not it exists yet, or when it
        exists; and the checkout's own ``config/`` otherwise.
    """
    override = os.environ.get(UTILS_CONFIG_ENV)
    if override:
        return Path(override)
    # A development root is a whole appliance, so its configuration is where an
    # appliance keeps it. The checkout's own `config/` is what a working copy
    # with no development root falls back to.
    if is_dev_root_set() or is_stamped_package() or UTILS_SYSTEM_CONFIG_DIR.exists():
        return UTILS_SYSTEM_CONFIG_DIR
    return UTILS_CHECKOUT_CONFIG_DIR


UTILS_CONFIG_DIR = resolve_config_dir()


# How every download chooses among the sources that serve its bytes
# (design/agent/module_install.md, "Choosing a source"): a probe asks each
# source for this much of the file and waits this long for an answer; the
# sources are measured again this often while a download has at least that
# long left; one this many times faster than the current source over the
# window takes over; a source silent this long fails; two speeds within this
# share of each other go to the earlier first byte.
UTILS_FETCH_PROBE_BYTES = 1024 * 1024
UTILS_FETCH_PROBE_TIMEOUT_S = 5.0
UTILS_FETCH_MEASURE_INTERVAL_S = 30.0
UTILS_FETCH_MOVE_FACTOR = 1.5
UTILS_FETCH_SPEED_WINDOW_S = 10.0
UTILS_FETCH_STALL_S = 20.0
UTILS_FETCH_NEAR_TIE = 0.1
UTILS_FETCH_CHUNK_BYTES = 64 * 1024
# How much of a file's start is kept for the check of what kind of file it is.
UTILS_FETCH_HEAD_BYTES = 512
# The largest document a version list or latest.json read takes.
UTILS_FETCH_DOCUMENT_LIMIT_BYTES = 4 * 1024 * 1024
# A download's progress line is written every this many percent, or after
# this many seconds when the percent moves slower or the size is unknown.
UTILS_FETCH_PROGRESS_PERCENT_STEP = 5
UTILS_FETCH_PROGRESS_INTERVAL_S = 2.0
# A program's own User-Agent, which the GitHub API requires, and no browser's:
# a mirror that answers a browser with a page of its own hands a program the
# file itself.
UTILS_FETCH_HEADERS = {"User-Agent": "neutrino-hub"}
# What a source names a release site by, the file and the version.
UTILS_SOURCE_RELEASE = "{release}"
UTILS_SOURCE_FILE = "{file}"
UTILS_SOURCE_VERSION = "{version}"
# The tag a release site keeps a version's files under.
UTILS_RELEASE_TAG_PREFIX = "v"
