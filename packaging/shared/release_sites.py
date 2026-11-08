"""The release sites of each edition: whether a build stamps them into what
it builds, and which files each site's release holds.

A release build is asked with ``--release-sites``; it names that in
``NEUTRINO_HAS_RELEASE_SITES``, which a build in a container is handed and
which the step writing the hub's ``_version.py`` reads, and it stamps the
sites of its own edition alone. Any other build stamps no site, so a hub it
makes holds the one agent package it seeded and refuses the rest by name.

Not pure: reads and sets the process's environment.
"""

import os

from shared import cc_switch_assets, edition_build
from shared.constants import (
    PACKAGING_CHECKSUMS_FILE,
    PACKAGING_LATEST_FILE,
    PACKAGING_RELEASE_SITES,
    PACKAGING_RELEASE_SITES_ENV,
)


def add_release_sites_argument(parser) -> None:
    """Give a build script's parser the ``--release-sites`` option.

    Args:
        parser: The script's ``argparse.ArgumentParser``.
    """
    parser.add_argument(
        "--release-sites",
        dest="has_release_sites",
        action="store_true",
        help="stamp the edition's release sites, as a tag's build does",
    )


def name_release_sites(has_release_sites: bool) -> None:
    """Name for the steps of this build whether it stamps the release sites.

    Args:
        has_release_sites: What ``--release-sites`` said.
    """
    os.environ[PACKAGING_RELEASE_SITES_ENV] = "1" if has_release_sites else ""


def stamped_sites() -> tuple:
    """The release sites the running build stamps.

    Returns:
        The sites of the edition ``NEUTRINO_EDITION`` names, from
        ``PACKAGING_RELEASE_SITES``, when the build was asked for them, else
        an empty tuple.

    Raises:
        SystemExit: When ``NEUTRINO_EDITION`` names no edition.
    """
    if os.environ.get(PACKAGING_RELEASE_SITES_ENV, "").strip() == "1":
        return PACKAGING_RELEASE_SITES[edition_build.build_edition()]
    return ()


def is_site_file(name: str, edition: str) -> bool:
    """Whether an edition's release site holds a release file.

    Args:
        name: The file name.
        edition: ``intl`` or ``cn``.

    Returns:
        True for a file of the edition, the pinned cc-switch files and their
        licence, ``latest.json`` and ``SHA256SUMS``.
    """
    shared = {
        PACKAGING_LATEST_FILE,
        PACKAGING_CHECKSUMS_FILE,
        cc_switch_assets.license_name(),
        *cc_switch_assets.release_files(),
    }
    return name in shared or edition_build.is_edition_file(name, edition)
