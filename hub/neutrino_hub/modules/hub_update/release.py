"""What the hub's own releases publish, read from GitHub.

A release is the one `releases/latest` names, which by GitHub's definition is
neither a draft nor a pre-release; the package this box wants from it is the
one whose name the build stamped into this package with the version left
open, so nothing here knows how any family spells a machine. Pure but for the
one fetch, which a test replaces.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from neutrino_hub import HUB_PACKAGE_ASSET
from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_CHECKSUMS_NAME,
    HUB_UPDATE_FETCH_TIMEOUT_S,
    HUB_UPDATE_HEADERS,
    HUB_UPDATE_LATEST_URL,
    HUB_UPDATE_RELATION_CURRENT,
    HUB_UPDATE_RELATION_MAJOR,
    HUB_UPDATE_RELATION_NEWER,
    HUB_UPDATE_REPOSITORY,
    HUB_UPDATE_TAG_PREFIX,
    HUB_UPDATE_TAG_URL,
)
from neutrino_hub.utils.version_number import parse_version

VERSION_FIELD = "{version}"
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
# What a version looks like inside a file name: digits, dots, and the
# characters a pre-release or a build suffix may add.
VERSION_IN_NAME = r"([0-9][0-9A-Za-z.+~-]*?)"


@dataclass(frozen=True)
class HubRelease:
    """One published release and the package in it for this box.

    Attributes:
        version: The version, the tag without its prefix.
        tag: The tag as GitHub names it.
        published_at: When it was published, as GitHub stamps it.
        notes: The release's body.
        page_url: The release's page.
        asset_name: The package file's name.
        asset_url: Where the package downloads from.
        asset_size: The package's size in bytes.
        checksums_url: Where the release's digest list downloads from.
    """

    version: str
    tag: str
    published_at: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    asset_size: int
    checksums_url: str


def asset_name(version: str, *, asset: str = HUB_PACKAGE_ASSET) -> str:
    """The package file a release carries for this box, at one version.

    Args:
        version: The version wanted.
        asset: The name the build stamped, with ``{version}`` open.

    Returns:
        The file name.

    Raises:
        ValueError: If this hub carries no stamp, which a checkout does not.
    """
    if VERSION_FIELD not in asset:
        raise ValueError("this hub was not built as a package")
    return asset.replace(VERSION_FIELD, version)


def version_of_asset(name: str, *, asset: str = HUB_PACKAGE_ASSET) -> str:
    """The version a package file's name carries, for a file handed over.

    Args:
        name: The file's name.
        asset: The name the build stamped, with ``{version}`` open.

    Returns:
        The version.

    Raises:
        ValueError: If the name is not this box's package at any version, or
            this hub carries no stamp.
    """
    if VERSION_FIELD not in asset:
        raise ValueError("this hub was not built as a package")
    head, tail = asset.split(VERSION_FIELD, 1)
    match = re.fullmatch(re.escape(head) + VERSION_IN_NAME + re.escape(tail), name)
    if match is None:
        raise ValueError(f"{name} is not {asset}")
    return match.group(1)


def relation(current: str, latest: str) -> str:
    """How the newest release stands to the version running.

    Args:
        current: The version running, a ``+suffix`` ignored.
        latest: The newest release's version.

    Returns:
        ``newer`` when the release is ahead within the same major, ``major``
        when its major is ahead, ``current`` otherwise; a version that does
        not parse reads as current, since nothing can be said of it.
    """
    running = parse_version(current)
    newest = parse_version(latest)
    if running is None or newest is None or newest <= running:
        return HUB_UPDATE_RELATION_CURRENT
    if newest[0] > running[0]:
        return HUB_UPDATE_RELATION_MAJOR
    return HUB_UPDATE_RELATION_NEWER


class HubReleaseChecker:
    """Reads what the repository publishes for this box's kind of package."""

    def __init__(
        self,
        *,
        asset: str = HUB_PACKAGE_ASSET,
        repository: str = HUB_UPDATE_REPOSITORY,
        fetch_bytes: Callable[[str], bytes] | None = None,
    ):
        """Set up a checker.

        Args:
            asset: The name the build stamped, with ``{version}`` open.
            repository: The GitHub repository the releases are under.
            fetch_bytes: How one address is read; None reads it over the
                network, and a test answers from its own table instead.
        """
        self._asset = asset
        self._repository = repository
        self._read = _read if fetch_bytes is None else fetch_bytes

    def latest(self) -> HubRelease | None:
        """The newest release, neither a draft nor a pre-release.

        Returns:
            The release with this box's package in it, or None when nothing
            has been published yet.

        Raises:
            OSError: If GitHub cannot be reached.
            ValueError: If the reply is not a release, or the release carries
                no package for this box.
        """
        return self._release_at(
            HUB_UPDATE_LATEST_URL.format(repository=self._repository)
        )

    def for_version(self, version: str) -> HubRelease | None:
        """The release of one version, for the package the box runs now.

        Args:
            version: The version wanted.

        Returns:
            The release with this box's package in it, or None when no
            release carries that tag, which a CI build's version does not.

        Raises:
            OSError: If GitHub cannot be reached.
            ValueError: If the reply is not a release, or the release carries
                no package for this box.
        """
        tag = HUB_UPDATE_TAG_PREFIX + version
        return self._release_at(
            HUB_UPDATE_TAG_URL.format(repository=self._repository, tag=tag)
        )

    def digest_of(self, release: HubRelease) -> str:
        """The sha256 the release publishes for this box's package.

        Args:
            release: The release.

        Returns:
            The digest, sixty-four hex characters.

        Raises:
            OSError: If the digest list cannot be reached.
            ValueError: If the list has no line for the package, or that line
                is not a digest.
        """
        listing = self._read(release.checksums_url).decode("utf-8", "replace")
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == release.asset_name:
                if not DIGEST_PATTERN.match(parts[0]):
                    raise ValueError(f"{release.asset_name} has no digest")
                return parts[0]
        raise ValueError(f"{HUB_UPDATE_CHECKSUMS_NAME} names no {release.asset_name}")

    def _release_at(self, url: str) -> HubRelease | None:
        """One release as GitHub describes it.

        Args:
            url: The API address of the release.

        Returns:
            The release, or None when GitHub has nothing at that address.

        Raises:
            OSError: If GitHub cannot be reached.
            ValueError: If the reply is not a release with this box's package.
        """
        try:
            raw = self._read(url)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        try:
            described = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError(f"{url} did not answer with a release") from error
        if not isinstance(described, dict):
            raise ValueError(f"{url} did not answer with a release")
        tag = described.get("tag_name")
        if not isinstance(tag, str) or not tag.startswith(HUB_UPDATE_TAG_PREFIX):
            raise ValueError(f"{url} named no release tag")
        version = tag[len(HUB_UPDATE_TAG_PREFIX) :]
        wanted = asset_name(version, asset=self._asset)
        assets = {
            entry.get("name"): entry
            for entry in described.get("assets") or []
            if isinstance(entry, dict)
        }
        package = assets.get(wanted)
        checksums = assets.get(HUB_UPDATE_CHECKSUMS_NAME)
        if package is None or checksums is None:
            raise ValueError(f"{tag} carries no {wanted}")
        return HubRelease(
            version=version,
            tag=tag,
            published_at=str(described.get("published_at") or ""),
            notes=str(described.get("body") or ""),
            page_url=str(described.get("html_url") or ""),
            asset_name=wanted,
            asset_url=str(package.get("browser_download_url") or ""),
            asset_size=int(package.get("size") or 0),
            checksums_url=str(checksums.get("browser_download_url") or ""),
        )


def _read(url: str) -> bytes:
    """Read one address.

    Args:
        url: What to read.

    Returns:
        Everything it answered with.

    Raises:
        OSError: If it cannot be reached; an HTTP refusal is the
            ``urllib.error.HTTPError`` kind of it.
    """
    request = urllib.request.Request(url, headers=HUB_UPDATE_HEADERS)
    with urllib.request.urlopen(request, timeout=HUB_UPDATE_FETCH_TIMEOUT_S) as reply:
        return reply.read()
