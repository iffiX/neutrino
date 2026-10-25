"""What the hub's own releases publish, read from the release sites.

A release site holds every file of every release under the names the release
gives them, ``latest.json`` naming the newest release as ``{tag, version}``
and each release's ``SHA256SUMS`` covering all of its files. The newest
release is the one ``latest.json`` names, read from every site at once; its
digest list is read the same way, and the package this box wants from it is
the one whose name the build stamped into this package with the version left
open, so nothing here knows how any family spells a machine, or which
edition's package is whose. Every read goes through the fetcher. A checker
remembers each release it read, so an install can reuse what a check read
moments before.
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Callable

from neutrino_hub import HUB_PACKAGE_ASSET
from neutrino_hub.exceptions import DownloadFailedError
from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_CHECKSUMS_NAME,
    HUB_UPDATE_LATEST_NAME,
    HUB_UPDATE_RELATION_CURRENT,
    HUB_UPDATE_RELATION_MAJOR,
    HUB_UPDATE_RELATION_NEWER,
    HUB_UPDATE_SIZE_PROBE_BYTES,
    HUB_UPDATE_TAG_PREFIX,
)
from neutrino_hub.utils.release_sites import latest_addresses, release_addresses
from neutrino_hub.utils.source_fetch import SourceFetcher, http_reason
from neutrino_hub.utils.version_number import parse_version

VERSION_FIELD = "{version}"
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
# What a version looks like inside a file name: digits, dots, and the
# characters a pre-release or a build suffix may add.
VERSION_IN_NAME = r"([0-9][0-9A-Za-z.+~-]*?)"
# The key a remembered read of the newest release is kept under.
LATEST_KEY = ""


@dataclass(frozen=True)
class HubRelease:
    """One published release and the package in it for this box.

    Attributes:
        version: The version, the tag without its prefix.
        tag: The tag the release sites file it under.
        asset_name: The package file's name.
        sources: Each release site's address of the package; empty without
            a package.
        digest: The package's ``sha256:<hex>`` as the release's
            ``SHA256SUMS`` lists it; empty without a package.
        asset_size: The package's size in bytes, 0 when no site named it.
        has_package: Whether the release's digest list names this box's
            package.
    """

    version: str
    tag: str
    asset_name: str
    sources: tuple = ()
    digest: str = ""
    asset_size: int = 0
    has_package: bool = True


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


def latest_version(body: bytes) -> str:
    """The version a ``latest.json`` names.

    Args:
        body: The file as a site served it.

    Returns:
        The version, the tag without its prefix.

    Raises:
        ValueError: If the file names no tag of the release's form, or a
            version other than its tag's.
    """
    try:
        named = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("latest.json is not JSON") from error
    tag = named.get("tag") if isinstance(named, dict) else None
    if not isinstance(tag, str) or not tag.startswith(HUB_UPDATE_TAG_PREFIX):
        raise ValueError("latest.json names no release tag")
    version = tag[len(HUB_UPDATE_TAG_PREFIX) :]
    if str(named.get("version", version)) != version:
        raise ValueError("latest.json names a version other than its tag's")
    return version


def digest_listing(body: bytes) -> dict:
    """The digests a ``SHA256SUMS`` lists, by file name.

    Args:
        body: The file as a site served it.

    Returns:
        File name to its sha256 in hex.

    Raises:
        ValueError: If a line is not ``<sha256>  <file>``.
    """
    listing = {}
    for line in body.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2 or not DIGEST_PATTERN.match(parts[0]):
            raise ValueError(
                f"{HUB_UPDATE_CHECKSUMS_NAME} has a line that is no digest"
            )
        listing[parts[1].lstrip("*")] = parts[0]
    return listing


def is_nowhere(error: DownloadFailedError) -> bool:
    """Whether every source answered that it holds no such file.

    Args:
        error: The failed read.

    Returns:
        True when there were sources and each answered 404.
    """
    sources = error.params.get("sources") or []
    return bool(sources) and all(item["reason"] == http_reason(404) for item in sources)


class HubReleaseChecker:
    """Reads what the release sites publish for this box's kind of package."""

    def __init__(
        self,
        *,
        asset: str = HUB_PACKAGE_ASSET,
        sites=None,
        fetcher=None,
        clock: Callable[[], float] = time.monotonic,
    ):
        """Set up a checker.

        Args:
            asset: The name the build stamped, with ``{version}`` open.
            sites: The release sites; None reads this hub's stamp.
            fetcher: What reads the sites; None is a
                :class:`~neutrino_hub.utils.source_fetch.SourceFetcher`
                whose probe asks for one byte, enough for a size.
            clock: Monotonic seconds, which age what the checker remembers.
        """
        self._asset = asset
        self._sites = sites
        self._fetcher = (
            fetcher
            if fetcher is not None
            else SourceFetcher(probe_bytes=HUB_UPDATE_SIZE_PROBE_BYTES)
        )
        self._clock = clock
        self._remembered: dict[str, tuple[float, HubRelease | None]] = {}

    def latest(self, *, max_age_s: float = 0) -> HubRelease | None:
        """The newest release, as ``latest.json`` names it.

        Args:
            max_age_s: How old a release this checker read before may be
                and still be answered without asking again; 0 always asks.

        Returns:
            The release, ``has_package`` False when it carries no package for
            this box, or None when no site names one yet.

        Raises:
            DownloadFailedError: When no site answered.
        """
        remembered = self._remembered.get(LATEST_KEY)
        if remembered is not None and self._clock() - remembered[0] < max_age_s:
            return remembered[1]
        try:
            version, _ = self._fetcher.fetch_document(
                file=HUB_UPDATE_LATEST_NAME,
                sources=latest_addresses(sites=self._sites),
                parse=latest_version,
            )
        except DownloadFailedError as error:
            if not is_nowhere(error):
                raise
            found = None
        else:
            found = self.for_version(version, max_age_s=max_age_s)
        self._remembered[LATEST_KEY] = (self._clock(), found)
        return found

    def for_version(self, version: str, *, max_age_s: float = 0) -> HubRelease | None:
        """The release of one version, for the package the box runs now.

        Args:
            version: The version wanted.
            max_age_s: How old a release this checker read before may be
                and still be answered without asking again; 0 always asks.

        Returns:
            The release, ``has_package`` False when it carries no package for
            this box, or None when no site holds that release, which a CI
            build's version does not.

        Raises:
            DownloadFailedError: When no site answered.
            ValueError: If this hub carries no stamp.
        """
        remembered = self._remembered.get(version)
        if remembered is not None and self._clock() - remembered[0] < max_age_s:
            return remembered[1]
        found = self._read_release(version)
        self._remembered[version] = (self._clock(), found)
        return found

    def _read_release(self, version: str) -> HubRelease | None:
        """One release as its digest list describes it, read now.

        Args:
            version: The version wanted.

        Returns:
            The release, or None when no site holds it.

        Raises:
            DownloadFailedError: When no site answered.
            ValueError: If this hub carries no stamp.
        """
        wanted = asset_name(version, asset=self._asset)
        tag = HUB_UPDATE_TAG_PREFIX + version
        addresses = release_addresses(version, sites=self._sites)
        try:
            listing, _ = self._fetcher.fetch_document(
                file=HUB_UPDATE_CHECKSUMS_NAME,
                sources=[
                    f"{address}/{HUB_UPDATE_CHECKSUMS_NAME}" for address in addresses
                ],
                parse=digest_listing,
            )
        except DownloadFailedError as error:
            if is_nowhere(error):
                return None
            raise
        if wanted not in listing:
            return HubRelease(
                version=version, tag=tag, asset_name=wanted, has_package=False
            )
        sources = tuple(f"{address}/{wanted}" for address in addresses)
        return HubRelease(
            version=version,
            tag=tag,
            asset_name=wanted,
            sources=sources,
            digest="sha256:" + listing[wanted],
            asset_size=self._size_of(sources),
        )

    def _size_of(self, sources: tuple) -> int:
        """The package's size, as the first site that names it says.

        Args:
            sources: Each site's address of the package.

        Returns:
            The size in bytes, 0 when no site names one.
        """
        for source in sources:
            size = self._fetcher.probe(source).size
            if size:
                return size
        return 0
