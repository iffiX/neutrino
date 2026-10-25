"""Which edition a build makes, the check that its tree holds that edition,
and the names its files take.

Every script under ``packaging/build`` takes ``--edition intl`` or
``--edition cn``. Before it builds anything it checks the tree it runs in
with :func:`shared.edition_tree.check_tree`, then names the edition in
``NEUTRINO_EDITION``, which a build in a container is handed and which the
step writing each package's ``_version.py`` reads. A ``cn`` file's name
holds ``-cn`` before its extension, so one release holds both editions.

Not pure: reads the tree and sets the process's environment.
"""

import os
from pathlib import Path

from shared.constants import (
    PACKAGING_ASSET_PATTERNS,
    PACKAGING_EDITION_ENV,
    PACKAGING_EDITION_SUFFIXES,
    PACKAGING_EDITIONS,
)
from shared.edition_tree import check_tree

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
        SystemExit: When the tree is not that edition's, as
            :func:`shared.edition_tree.check_tree` names it.
        ValueError: When the edition is not one of :data:`PACKAGING_EDITIONS`.
    """
    check_tree(root, edition)
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


def asset_name(kind: str, *, name: str, version: str, architecture: str = "") -> str:
    """The file a build of the running edition writes, as a release holds it.

    Args:
        kind: A key of :data:`PACKAGING_ASSET_PATTERNS`.
        name: The package, such as ``neutrino-agent``.
        version: The version, or ``{version}`` to leave it open.
        architecture: The machine as the format spells it; none for the apk
            and the ipa.

    Returns:
        The file name, ``-cn`` before the extension for ``cn``.

    Raises:
        KeyError: When ``kind`` is no format the project builds.
        SystemExit: When ``NEUTRINO_EDITION`` names no edition.
    """
    return PACKAGING_ASSET_PATTERNS[kind].format(
        name=name,
        version=version,
        architecture=architecture,
        suffix=PACKAGING_EDITION_SUFFIXES[build_edition()],
    )


def built_name(kind: str, *, name: str, version: str, architecture: str) -> str:
    """The file a format's own tool writes, before the edition names it.

    Args:
        kind: ``rpm`` or ``pkg``, whose tools name their output themselves.
        name: The package.
        version: The version.
        architecture: The machine as the format spells it.

    Returns:
        The file name with no edition suffix.

    Raises:
        KeyError: When ``kind`` is no format the project builds.
    """
    return PACKAGING_ASSET_PATTERNS[kind].format(
        name=name, version=version, architecture=architecture, suffix=""
    )


def is_edition_file(name: str, edition: str) -> bool:
    """Whether a release file's name is one of an edition's.

    Args:
        name: The file name.
        edition: ``intl`` or ``cn``.

    Returns:
        True for a name holding ``-cn`` before its extension when the
        edition is ``cn``, and for a name holding none when it is ``intl``.
    """
    is_cn = f"{PACKAGING_EDITION_SUFFIXES['cn']}." in name
    return is_cn == (edition == "cn")
