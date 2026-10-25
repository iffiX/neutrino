"""The agent packages the hub can deliver.

Two callers hand these out: the SSH install pushes one to a device, and the
agent channel serves one to an agent updating itself. Both resolve the same
file for a family and a machine.

**A file here is named the way the release publishes it**, so one name
addresses a package in this directory, in the manifest, and in the release a
device may be sent to. The agent carries an interpreter and compiled bindings,
so one family is not one file: a package is for one platform and one machine,
and the manifest pins the hash of each. Because the name says nothing about
what is inside it, a held file is believed only while it still hashes to what
the manifest pins; one that does not is a stale fetch and is fetched again.

The hub's package seeds this directory with one agent package, the one of its
own system, machine and package family, which keeps the hub's own agent and
every device of the same platform offline. Every other platform the release
publishes is named in the manifest with its file name and its hash, fetched
once the first time a device needs it from the release sites the hub's build
stamped, at the release the hub came from, through the method every download
uses, and kept. A platform the manifest does not name, an entry that pins no
hash, and a build with no release sites are refused by name rather than
served the wrong machine's build or an unchecked one.

A build dropped under ``config/devices/packages`` wins over both.

Not pure: fetches over the network and writes under the state root.
"""

import json
from pathlib import Path

from neutrino_hub import HUB_VERSION
from neutrino_hub.exceptions import (
    AgentArtifactFetchError,
    DownloadFailedError,
    DownloadTooLargeError,
)
from neutrino_hub.modules.devices.constants import (
    AGENT_PACKAGE_CACHE_DIR,
    AGENT_PACKAGE_FETCH_LIMIT_BYTES,
    AGENT_PACKAGE_MANIFEST_PATH,
    DEVICE_PACKAGES_DIR_NAME,
)
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR
from neutrino_hub.utils.release_sites import release_addresses
from neutrino_hub.utils.source_fetch import (
    DIGEST_PREFIX,
    SourceFetcher,
    failure_entry,
    file_sha256,
)

# What each format spells the same machine, mapped to the name the agent's
# platform tuple reports.
AGENT_PACKAGE_ARCHITECTURES = {
    "amd64": "amd64",
    "x86_64": "amd64",
    "arm64": "arm64",
    "aarch64": "arm64",
}

# The suffix each family's files carry.
AGENT_PACKAGE_FAMILIES = {".deb": "deb", ".rpm": "rpm", ".msi": "msi", ".pkg": "pkg"}
# Which package family a machine's platform family installs.
AGENT_PACKAGE_FAMILY_OF_PLATFORM = {"debian": "deb", "rhel": "rpm", "suse": "rpm"}
# Which package family a machine installs by its operating system alone,
# where the platform tuple names no distribution family.
AGENT_PACKAGE_FAMILY_OF_OS = {"windows": "msi", "darwin": "pkg"}


def platform_key(family: str, architecture: str) -> str:
    """What addresses one platform in the manifest.

    Args:
        family: ``deb`` or ``rpm``.
        architecture: The machine, named the way the agent's platform tuple
            names it.

    Returns:
        The key, empty when either half is missing.
    """
    if not family or not architecture:
        return ""
    return f"{family}-{architecture}"


def package_name(entry: dict) -> str:
    """What one manifest entry calls its file.

    Args:
        entry: The manifest's entry for a platform.

    Returns:
        The file name, empty when the entry names none or names one that
        would land outside the cache directory.
    """
    name = str(entry.get("name", "") or "")
    if not name or name in (".", "..") or Path(name).name != name:
        return ""
    return name


def package_architecture(name: str) -> str:
    """Which machine a package file is for, read from its name.

    Args:
        name: The file name, as either format writes it.

    Returns:
        ``amd64`` or ``arm64``, or empty when the name says neither.
    """
    # Longest first: the two families punctuate the same machine differently,
    # and `aarch64` would otherwise be read by a shorter name inside it.
    for token in sorted(AGENT_PACKAGE_ARCHITECTURES, key=len, reverse=True):
        if token in name:
            return AGENT_PACKAGE_ARCHITECTURES[token]
    return ""


def package_family(name: str) -> str:
    """Which family a package file belongs to, read from its suffix.

    Args:
        name: The file name.

    Returns:
        ``deb``, ``rpm``, ``msi`` or ``pkg``, or empty for anything else.
    """
    return AGENT_PACKAGE_FAMILIES.get(Path(name).suffix, "")


def platform_family(platform: dict) -> str:
    """Which package family a machine installs, from its platform tuple.

    Args:
        platform: ``{os, family, arch}`` as the agent reported it.

    Returns:
        ``msi`` on Windows, ``pkg`` on macOS, else ``deb`` or ``rpm`` by the
        distribution family, or empty when no agent package is built for
        the machine.
    """
    by_os = AGENT_PACKAGE_FAMILY_OF_OS.get(str(platform.get("os", "")), "")
    if by_os:
        return by_os
    return AGENT_PACKAGE_FAMILY_OF_PLATFORM.get(str(platform.get("family", "")), "")


class AgentPackageCache:
    """Resolves a family and a machine to the agent package for it."""

    def __init__(
        self,
        *,
        root: "Path | None" = None,
        manifest_path: "Path | None" = None,
        pinned_dir: "Path | None" = None,
        fetcher: "SourceFetcher | None" = None,
        sites=None,
        hub_version: str = HUB_VERSION,
    ):
        """
        Args:
            root: Where packages are kept; the state root's own directory by
                default.
            manifest_path: The manifest the build stamped; the package's own
                by default.
            pinned_dir: Where a hand-pinned build is looked for; the
                configuration directory's own by default.
            fetcher: The fetcher every download goes through; a new one by
                default.
            sites: The release sites; None reads the hub's stamp.
            hub_version: The release the hub came from, whose files are
                fetched.
        """
        self._root = Path(root) if root is not None else AGENT_PACKAGE_CACHE_DIR
        self._manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else AGENT_PACKAGE_MANIFEST_PATH
        )
        self._pinned_dir = (
            Path(pinned_dir)
            if pinned_dir is not None
            else UTILS_CONFIG_DIR / "devices" / DEVICE_PACKAGES_DIR_NAME
        )
        self._fetcher = fetcher if fetcher is not None else SourceFetcher()
        self._sites = sites
        self._hub_version = hub_version

    def has_packages(self) -> bool:
        """Whether this hub can deliver an agent package at all.

        Returns:
            True when a build is pinned by hand, held in the cache, or named
            by the manifest. False is a hub that has nothing for any machine,
            which is a refusal before a device is even reached.
        """
        if self._pinned_paths():
            return True
        return bool(self.manifest())

    def serves(self, *, family: str, architecture: str) -> bool:
        """Whether one platform can be produced without being asked twice.

        Args:
            family: ``deb`` or ``rpm``.
            architecture: The machine the device reported.

        Returns:
            True when the package is pinned, held, or fetchable.
        """
        if self._pinned(family=family, architecture=architecture) is not None:
            return True
        key = platform_key(family, architecture)
        entry = self.manifest().get(key)
        if not isinstance(entry, dict):
            return False
        return self._held(entry) is not None or self._is_fetchable(entry)

    def package(self, *, family: str, architecture: str) -> Path:
        """The agent package for one family and machine.

        Args:
            family: ``deb`` or ``rpm``.
            architecture: The machine the device reported.

        Returns:
            Where the file is.

        Raises:
            AgentArtifactFetchError: ``agent_package_missing`` when this hub
                has nothing for that platform and nothing to fetch,
                ``download_failed {file, sources}`` when no release site
                serves the pinned bytes, and
                ``agent_package_cache_unwritable`` when the cache cannot be
                written.
        """
        pinned = self._pinned(family=family, architecture=architecture)
        if pinned is not None:
            return pinned

        key = platform_key(family, architecture)
        entry = self.manifest().get(key)
        if not isinstance(entry, dict):
            raise AgentArtifactFetchError("agent_package_missing", platform=key)
        held = self._held(entry)
        if held is not None:
            return held

        if not self._is_fetchable(entry):
            raise AgentArtifactFetchError("agent_package_missing", platform=key)
        return self._fetch(entry)

    def manifest(self) -> dict:
        """What the build stamped: the platforms this hub knows a package for.

        Returns:
            Platform key to ``{name, sha256, ...}``, empty for a checkout,
            which has no build behind it and therefore no manifest.
        """
        try:
            loaded = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _is_fetchable(self, entry: dict) -> bool:
        """Whether one entry names a file and its hash, and a release site serves it.

        Args:
            entry: The manifest's entry for a platform.

        Returns:
            True when all three are there; a fetch is never kept unchecked.
        """
        return bool(
            package_name(entry)
            and entry.get("sha256")
            and release_addresses(self._hub_version, sites=self._sites)
        )

    def _file(self, entry: dict) -> "Path | None":
        """Where one entry's package would be, when a file is there.

        Args:
            entry: The manifest's entry for a platform.

        Returns:
            Its path, or None when the entry names no file or none is there.
        """
        name = package_name(entry)
        if not name:
            return None
        path = self._root / name
        return path if path.is_file() else None

    def _held(self, entry: dict) -> "Path | None":
        """The file the entry names, while it still holds what the entry pins.

        Args:
            entry: The manifest's entry for a platform.

        Returns:
            Its path, or None when nothing is there or what is there is
            another build under the release's name.
        """
        path = self._file(entry)
        if path is None:
            return None
        digest = str(entry.get("sha256", "") or "").lower()
        if not digest:
            return None
        try:
            held = file_sha256(path)
        except OSError:
            return None
        return path if held == digest else None

    def _pinned(self, *, family: str, architecture: str) -> "Path | None":
        """A build dropped under ``config/devices/packages`` for one platform.

        Args:
            family: ``deb`` or ``rpm``.
            architecture: The machine the device reported.

        Returns:
            Its path, newest name last, or None when none is pinned.
        """
        found = [
            path
            for path in self._pinned_paths()
            if package_family(path.name) == family
            and package_architecture(path.name) == architecture
        ]
        return found[-1] if found else None

    def _pinned_paths(self) -> list:
        """Every hand-pinned build, in name order."""
        if not self._pinned_dir.is_dir():
            return []
        return [
            path
            for path in sorted(self._pinned_dir.iterdir())
            if path.is_file() and package_family(path.name)
        ]

    def _fetch(self, entry: dict) -> Path:
        """Fetch one entry's package from the release sites into the cache.

        Args:
            entry: The manifest's entry for a platform, naming a file and
                its hash.

        Returns:
            Where the package is kept.

        Raises:
            AgentArtifactFetchError: ``download_failed {file, sources}`` when
                no site serves the pinned bytes, or one names a size past
                the limit; ``agent_package_cache_unwritable`` when the cache
                cannot be written. Nothing is left on disk.
        """
        name = package_name(entry)
        sources = [
            f"{address}/{name}"
            for address in release_addresses(self._hub_version, sites=self._sites)
        ]
        try:
            download = self._fetcher.fetch_file(
                file=name,
                sources=sources,
                digest=DIGEST_PREFIX + str(entry["sha256"]).lower(),
                directory=self._root,
                limit=AGENT_PACKAGE_FETCH_LIMIT_BYTES,
            )
        except DownloadFailedError as error:
            raise AgentArtifactFetchError(error.code, **error.params) from error
        except DownloadTooLargeError as error:
            raise AgentArtifactFetchError(
                DownloadFailedError.code,
                file=name,
                sources=[
                    failure_entry(source, "digest_mismatch", str(error))
                    for source in sources
                ],
            ) from error
        except (OSError, ValueError) as error:
            raise AgentArtifactFetchError(
                "agent_package_cache_unwritable", detail=str(error)[:200]
            ) from error
        path = self._root / name
        try:
            download.place(path)
        except OSError as error:
            raise AgentArtifactFetchError(
                "agent_package_cache_unwritable", detail=str(error)[:200]
            ) from error
        return path
