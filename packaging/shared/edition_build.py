"""Which edition a build makes, and the check that its tree holds that edition.

Every script under ``packaging/build`` takes ``--edition intl`` or
``--edition cn``. Before it builds anything it checks the tree it runs in:
a ``cn`` build stops when a path of ``PACKAGING_CN_LEFT_OUT_PATHS`` exists
there, and an ``intl`` build stops when one is missing. It then names the
edition in ``NEUTRINO_EDITION``, which a build in a container is handed and
which the step writing each package's ``_version.py`` reads.

Not pure: reads the tree and sets the process's environment.
"""

import os
from pathlib import Path

from shared.constants import (
    PACKAGING_CN_LEFT_OUT_PATHS,
    PACKAGING_EDITION_ENV,
    PACKAGING_EDITIONS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def add_edition_argument(parser) -> None:
    """Give a build script's parser the ``--edition`` option.

    Args:
        parser: The script's ``argparse.ArgumentParser``.
    """
    parser.add_argument(
        "--edition",
        choices=PACKAGING_EDITIONS,
        default=PACKAGING_EDITIONS[0],
        help="the edition to build; cn builds only from the mainland source tree",
    )


def require_edition_tree(edition: str, root: Path = REPO_ROOT) -> None:
    """Check that a tree holds what an edition is built from, and name it.

    Args:
        edition: ``intl`` or ``cn``.
        root: The repository tree the build runs in.

    Raises:
        SystemExit: When a ``cn`` build finds a left-out path in the tree,
            an ``intl`` build finds one missing, or the edition is not one
            of :data:`PACKAGING_EDITIONS`.
    """
    if edition not in PACKAGING_EDITIONS:
        raise SystemExit(
            f"there is no edition {edition}; there is: {', '.join(PACKAGING_EDITIONS)}"
        )
    for path in PACKAGING_CN_LEFT_OUT_PATHS:
        is_present = (root / path).exists()
        if edition == "cn" and is_present:
            raise SystemExit(
                f"a cn build cannot hold {path}; build it from the mainland "
                "source tree"
            )
        if edition != "cn" and not is_present:
            raise SystemExit(
                f"an {edition} build needs {path}, which this tree does not hold"
            )
    os.environ[PACKAGING_EDITION_ENV] = edition


def build_edition() -> str:
    """The edition the running build was asked for.

    Returns:
        ``NEUTRINO_EDITION``, or the first edition when it is unset.

    Raises:
        SystemExit: When it names no edition this project builds.
    """
    edition = os.environ.get(PACKAGING_EDITION_ENV, "").strip()
    if not edition:
        return PACKAGING_EDITIONS[0]
    if edition not in PACKAGING_EDITIONS:
        raise SystemExit(
            f"{PACKAGING_EDITION_ENV} is {edition}, which is no edition; "
            f"there is: {', '.join(PACKAGING_EDITIONS)}"
        )
    return edition
