"""The release sites the hub's build stamped, as the addresses a download names.

A release site holds every file of every release under the names the release
gives them. The build stamps the sites into ``_version.py`` as
``HUB_RELEASE_SITES``, each ``{files, latest}``: ``files`` the address of one
tag's files with ``{tag}`` where the tag goes, ``latest`` the address of the
site's ``latest.json``. A checkout has no stamp and names no site.

Pure.
"""

from neutrino_hub import HUB_RELEASE_SITES
from neutrino_hub.utils.constants import UTILS_RELEASE_TAG_PREFIX

TAG_FIELD = "{tag}"


def release_addresses(version: str, *, sites=None) -> list:
    """Each site's address of one release's files.

    Args:
        version: The release's version, without the tag's prefix.
        sites: The stamped sites; None reads this hub's stamp.

    Returns:
        One address per site that names one, in the stamp's order, with no
        trailing ``/``; empty for a checkout.
    """
    tag = UTILS_RELEASE_TAG_PREFIX + version
    addresses = []
    for site in HUB_RELEASE_SITES if sites is None else sites:
        files = str(site.get("files", "") or "") if isinstance(site, dict) else ""
        if TAG_FIELD in files:
            addresses.append(files.replace(TAG_FIELD, tag).rstrip("/"))
    return addresses


def latest_addresses(*, sites=None) -> list:
    """Each site's address of its ``latest.json``.

    Args:
        sites: The stamped sites; None reads this hub's stamp.

    Returns:
        One address per site that names one, in the stamp's order; empty
        for a checkout.
    """
    addresses = []
    for site in HUB_RELEASE_SITES if sites is None else sites:
        latest = str(site.get("latest", "") or "") if isinstance(site, dict) else ""
        if latest:
            addresses.append(latest)
    return addresses
