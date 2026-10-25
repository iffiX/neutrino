"""The address and domain databases the split runs on, and replacing them.

The package carries one release of each, so a box splits traffic the moment it
is installed. The lists behind them move every few days, which is why a running
machine can take a newer release: the file is fetched from the repository that
publishes it, held against the digest published beside it, and written over the
copy xray loads only once both files are in hand. Every read goes through the
hub's fetcher, each with the one source the repository has.

Which release a machine holds is state, not configuration. It describes the
bytes on the disk, so it lives beside them under ``/var/lib`` rather than in
``config/``, and a restored backup brings back neither.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.modules.xray.constants import (
    XRAY_GEODATA_DIR,
    XRAY_GEODATA,
    XRAY_GEODATA_DOWNLOAD_URL,
    XRAY_GEODATA_LATEST_URL,
    XRAY_GEODATA_LIMIT_BYTES,
    XRAY_GEODATA_SOURCE_PACKAGE,
    XRAY_GEODATA_SOURCE_RELEASE,
    XRAY_GEODATA_SUM_SUFFIX,
    XRAY_GEODATA_VERSION_PATH,
)
from neutrino_hub.utils.source_fetch import SourceFetcher

DIGEST_LENGTH = 64


@dataclass(frozen=True)
class XrayGeodataSource:
    """One database: the file xray loads, and where releases of it come from.

    Attributes:
        file_name: What the file is called in the directory xray reads.
        repository: The repository publishing it.
        asset: What that repository calls it in a release.
        release: The release the package's own copy was taken from.
    """

    file_name: str
    repository: str
    asset: str
    release: str


@dataclass(frozen=True)
class XrayGeodataState:
    """Which release of each database a machine holds, and where it came from.

    Attributes:
        releases: File name to the release that file was taken from.
        source: ``package`` for the carried copies, ``release`` for fetched
            ones.
    """

    releases: dict[str, str]
    source: str


def sources() -> tuple[XrayGeodataSource, ...]:
    """Every database the box loads, read off the pins the package carries.

    Returns:
        One source per database, in file-name order.

    Raises:
        ValueError: If a pin is not a release download address, which would
            leave the repository and the asset unknown.
    """
    return tuple(
        _source_of(file_name, pin["url"])
        for file_name, pin in sorted(XRAY_GEODATA.items())
    )


def baseline() -> XrayGeodataState:
    """What the package carries, before any machine has taken a newer one.

    Returns:
        The pinned release of each database.
    """
    return XrayGeodataState(
        releases={source.file_name: source.release for source in sources()},
        source=XRAY_GEODATA_SOURCE_PACKAGE,
    )


def installed(*, version_path: Path = XRAY_GEODATA_VERSION_PATH) -> XrayGeodataState:
    """Which release of each database this machine runs.

    Args:
        version_path: The file a fetch writes.

    Returns:
        What that file records, or the package's baseline where it is absent
        or holds no release for a database.
    """
    fallback = baseline()
    try:
        recorded = json.loads(version_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback
    releases = recorded.get("releases")
    if not isinstance(releases, dict):
        return fallback
    taken = {
        file_name: releases[file_name]
        for file_name in fallback.releases
        if isinstance(releases.get(file_name), str) and releases[file_name]
    }
    if len(taken) != len(fallback.releases):
        return fallback
    return XrayGeodataState(releases=taken, source=XRAY_GEODATA_SOURCE_RELEASE)


def latest(*, fetcher=None) -> dict[str, str]:
    """The newest release each database's repository publishes.

    Args:
        fetcher: What reads the repositories; None is a
            :class:`~neutrino_hub.utils.source_fetch.SourceFetcher`.

    Returns:
        File name to the release tag.

    Raises:
        DownloadFailedError: If a repository did not answer with a release
            naming a tag.
    """
    fetcher = fetcher if fetcher is not None else SourceFetcher()
    found = {}
    for source in sources():
        url = XRAY_GEODATA_LATEST_URL.format(repository=source.repository)
        found[source.file_name], _ = fetcher.fetch_document(
            file=f"{source.repository} latest release", sources=[url], parse=_tag_of
        )
    return found


def fetch(
    releases: dict[str, str],
    *,
    directory: Path = XRAY_GEODATA_DIR,
    version_path: Path = XRAY_GEODATA_VERSION_PATH,
    fetcher=None,
) -> XrayGeodataState:
    """Put the named release of every database where xray reads it.

    Both files are fetched and checked before either is written, and each is
    fetched into a temporary file in the same directory and moved into place,
    so a database xray is loading is never half a file and a digest that does
    not match leaves the machine on what it already had.

    Args:
        releases: File name to the release to take it from.
        directory: Where xray reads its databases.
        version_path: The file recording what was taken.
        fetcher: What reads the repositories; None is a
            :class:`~neutrino_hub.utils.source_fetch.SourceFetcher`.

    Returns:
        What the machine holds afterwards.

    Raises:
        KeyError: If a database has no release named for it.
        DownloadFailedError: If a digest file or a database could not be
            had as published.
        OSError: If a file cannot be written.
    """
    fetcher = fetcher if fetcher is not None else SourceFetcher()
    directory.mkdir(parents=True, exist_ok=True)
    taken = {}
    try:
        for source in sources():
            taken[source.file_name] = _downloaded(
                source, releases[source.file_name], directory, fetcher
            )
        for file_name, download in taken.items():
            os.chmod(download.path, 0o644)
            download.place(directory / file_name)
    finally:
        for download in taken.values():
            download.discard()
    state = XrayGeodataState(
        releases={name: releases[name] for name in taken},
        source=XRAY_GEODATA_SOURCE_RELEASE,
    )
    version_path.parent.mkdir(parents=True, exist_ok=True)
    _replace(
        version_path,
        (json.dumps({"releases": state.releases}, indent=2) + "\n").encode("utf-8"),
    )
    return state


def _source_of(file_name: str, url: str) -> XrayGeodataSource:
    """Read one pin as the repository, release and asset behind it.

    Args:
        file_name: What the file is called in the directory xray reads.
        url: The pinned download address.

    Returns:
        The source that address names.

    Raises:
        ValueError: If the address is not a release download.
    """
    parts = url.split("/")
    if len(parts) != 9 or parts[5:7] != ["releases", "download"]:
        raise ValueError(f"{url} is not a release download address")
    return XrayGeodataSource(
        file_name=file_name,
        repository=f"{parts[3]}/{parts[4]}",
        asset=parts[8],
        release=parts[7],
    )


def _downloaded(source: XrayGeodataSource, release: str, directory: Path, fetcher):
    """One database fetched beside its place, checked against its published digest.

    Args:
        source: Which database.
        release: The release to take it from.
        directory: Where the temporary file is made.
        fetcher: What reads the repository.

    Returns:
        The download, not yet in its place.

    Raises:
        DownloadFailedError: If the digest file is not one, or no source
            served the bytes it names.
        OSError: If the temporary file cannot be written.
    """
    address = XRAY_GEODATA_DOWNLOAD_URL.format(
        repository=source.repository, release=release, asset=source.asset
    )
    published, _ = fetcher.fetch_document(
        file=source.asset + XRAY_GEODATA_SUM_SUFFIX,
        sources=[address + XRAY_GEODATA_SUM_SUFFIX],
        parse=_digest_of,
    )
    return fetcher.fetch_file(
        file=source.asset,
        sources=[address],
        digest="sha256:" + published,
        directory=directory,
        limit=XRAY_GEODATA_LIMIT_BYTES,
    )


def _tag_of(body: bytes) -> str:
    """The tag a repository's latest release names.

    Args:
        body: The release as the repository described it.

    Returns:
        The tag.

    Raises:
        ValueError: If the answer names no tag.
    """
    try:
        tag = json.loads(body.decode("utf-8")).get("tag_name")
    except (AttributeError, UnicodeDecodeError, ValueError) as error:
        raise ValueError("the answer is not a release") from error
    if not isinstance(tag, str) or not tag:
        raise ValueError("the release names no tag")
    return tag


def _digest_of(body: bytes) -> str:
    """The sha256 a ``.sha256sum`` file publishes.

    Args:
        body: The file as the repository served it.

    Returns:
        The digest, in hex.

    Raises:
        ValueError: If the file holds no digest.
    """
    words = body.decode("utf-8", "replace").split()
    wanted = words[0].lower() if words else ""
    if len(wanted) != DIGEST_LENGTH or any(
        letter not in "0123456789abcdef" for letter in wanted
    ):
        raise ValueError("the file publishes no digest")
    return wanted


def _replace(path: Path, payload: bytes) -> None:
    """Write bytes over a file in one step.

    Args:
        path: What to write.
        payload: The bytes to put there.

    Raises:
        OSError: If the file cannot be written.
    """
    handle, staged = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.chmod(staged, 0o644)
        os.replace(staged, path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise
