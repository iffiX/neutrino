"""Whether a build stamps the release sites into what it builds.

A release build is asked with ``--release-sites``; it names that in
``NEUTRINO_HAS_RELEASE_SITES``, which a build in a container is handed and
which the step writing the hub's ``_version.py`` reads. Any other build
stamps no site, so a hub it makes holds the one agent package it seeded and
refuses the rest by name.

Not pure: reads and sets the process's environment.
"""

import os

from shared.constants import PACKAGING_RELEASE_SITES, PACKAGING_RELEASE_SITES_ENV


def add_release_sites_argument(parser) -> None:
    """Give a build script's parser the ``--release-sites`` option.

    Args:
        parser: The script's ``argparse.ArgumentParser``.
    """
    parser.add_argument(
        "--release-sites",
        dest="has_release_sites",
        action="store_true",
        help="stamp the release sites, as a tag's build does",
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
        ``PACKAGING_RELEASE_SITES`` when the build was asked for them, else
        an empty tuple.
    """
    if os.environ.get(PACKAGING_RELEASE_SITES_ENV, "").strip() == "1":
        return PACKAGING_RELEASE_SITES
    return ()
