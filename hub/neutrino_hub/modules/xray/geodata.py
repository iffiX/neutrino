"""The address and domain databases the split runs on, and replacing them.

The package carries one release of each, so a box splits traffic the moment it
is installed. The lists behind them move every few days, which is why a running
machine can take a newer release: the file is fetched from the repository that
publishes it, held against the digest published beside it, and written over the
copy xray loads only once both files are in hand.

Which release a machine holds is state, not configuration. It describes the
bytes on the disk, so it lives beside them under ``/var/lib`` rather than in
``config/``, and a restored backup brings back neither.
"""

import hashlib
import json
import os
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.modules.xray.constants import (
    XRAY_GEODATA,
    XRAY_GEODATA_DOWNLOAD_URL,
    XRAY_GEODATA_LATEST_URL,
    XRAY_GEODATA_SOURCE_PACKAGE,
    XRAY_GEODATA_SOURCE_RELEASE,
    XRAY_GEODATA_SUM_SUFFIX,
    XRAY_GEODATA_TIMEOUT_S,
    XRAY_GEODATA_VERSION_PATH,
)
from neutrino_hub.utils.constants import UTILS_GEODATA_DIR


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


def latest(*, fetch_bytes: Callable[[str], bytes] | None = None) -> dict[str, str]:
    """The newest release each database's repository publishes.

    Args:
        fetch_bytes: How one address is read; None reads it over the
            network, and a test answers from its own table instead.

    Returns:
        File name to the release tag.

    Raises:
        OSError: If a repository cannot be reached.
        ValueError: If a reply is not a release naming a tag.
    """
    read = _read if fetch_bytes is None else fetch_bytes
    found = {}
    for source in sources():
        url = XRAY_GEODATA_LATEST_URL.format(repository=source.repository)
        try:
            release = json.loads(read(url).decode("utf-8"))["tag_name"]
        except (KeyError, UnicodeDecodeError, ValueError) as error:
            raise ValueError(f"{url} named no release") from error
        if not isinstance(release, str) or not release:
            raise ValueError(f"{url} named no release")
        found[source.file_name] = release
    return found


def fetch(
    releases: dict[str, str],
    *,
    directory: Path = UTILS_GEODATA_DIR,
    version_path: Path = XRAY_GEODATA_VERSION_PATH,
    fetch_bytes: Callable[[str], bytes] | None = None,
) -> XrayGeodataState:
    """Put the named release of every database where xray reads it.

    Both files are fetched and checked before either is written, and each is
    written through a temporary file in the same directory and moved into
    place, so a database xray is loading is never half a file and a digest
    that does not match leaves the machine on what it already had.

    Args:
        releases: File name to the release to take it from.
        directory: Where xray reads its databases.
        version_path: The file recording what was taken.
        fetch_bytes: How one address is read; None reads it over the
            network.

    Returns:
        What the machine holds afterwards.

    Raises:
        KeyError: If a database has no release named for it.
        OSError: If an address cannot be read or a file cannot be written.
        ValueError: If a file does not match the digest published beside it,
            or a digest file is not one.
    """
    read = _read if fetch_bytes is None else fetch_bytes
    taken = {
        source.file_name: _downloaded(source, releases[source.file_name], read)
        for source in sources()
    }
    directory.mkdir(parents=True, exist_ok=True)
    for file_name, payload in taken.items():
        _replace(directory / file_name, payload)
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


def _downloaded(
    source: XrayGeodataSource, release: str, fetch_bytes: Callable[[str], bytes]
) -> bytes:
    """One database's bytes, checked against the digest published with them.

    Args:
        source: Which database.
        release: The release to take it from.
        fetch_bytes: How one address is read.

    Returns:
        The file's bytes.

    Raises:
        OSError: If an address cannot be read.
        ValueError: If the digest file is not one, or the bytes do not match
            it.
    """
    address = XRAY_GEODATA_DOWNLOAD_URL.format(
        repository=source.repository, release=release, asset=source.asset
    )
    published = fetch_bytes(address + XRAY_GEODATA_SUM_SUFFIX).decode(
        "utf-8", "replace"
    )
    wanted = published.split()[0] if published.split() else ""
    if len(wanted) != 64 or not all(letter in "0123456789abcdef" for letter in wanted):
        raise ValueError(f"{address}{XRAY_GEODATA_SUM_SUFFIX} published no digest")
    payload = fetch_bytes(address)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != wanted:
        raise ValueError(f"{address} came back as {digest}, not {wanted}")
    return payload


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


def _read(url: str) -> bytes:
    """Read one address.

    Args:
        url: What to read.

    Returns:
        Everything it answered with.

    Raises:
        OSError: If it cannot be reached.
    """
    with urllib.request.urlopen(url, timeout=XRAY_GEODATA_TIMEOUT_S) as reply:
        return reply.read()
