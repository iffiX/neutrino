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

The hub's package seeds this directory with the builds it was made from, which
is what keeps a Linux install and a Linux self-update offline. A platform it
seeded none for is fetched once from the release the manifest names, checked
against the hash the manifest pins, and kept. A platform with neither is
refused by name rather than served the wrong machine's build.

A build dropped under ``config/devices/packages`` wins over both.

Not pure: fetches over the network and writes under the state root.
"""

import hashlib
import json
import urllib.request
from pathlib import Path

from neutrino_hub.modules.devices.constants import (
    AGENT_PACKAGE_CACHE_DIR,
    AGENT_PACKAGE_FETCH_LIMIT_BYTES,
    AGENT_PACKAGE_FETCH_TIMEOUT_S,
    AGENT_PACKAGE_MANIFEST_PATH,
)
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR

# What each format spells the same machine, mapped to the name the agent's
# platform tuple reports.
AGENT_PACKAGE_ARCHITECTURES = {
    "amd64": "amd64",
    "x86_64": "amd64",
    "arm64": "arm64",
    "aarch64": "arm64",
}

# The suffix each family's files carry.
AGENT_PACKAGE_FAMILIES = {".deb": "deb", ".rpm": "rpm"}


class AgentPackageFetchError(RuntimeError):
    """Raised when an agent package cannot be produced.

    Attributes:
        code: The typed reason, for every surface to word.
        params: What the wording names.
    """

    def __init__(self, code: str, **params):
        """
        Args:
            code: The typed reason.
            **params: Values the wording names.
        """
        super().__init__(code)
        self.code = code
        self.params = params


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
        ``deb`` or ``rpm``, or empty for anything else.
    """
    return AGENT_PACKAGE_FAMILIES.get(Path(name).suffix, "")


class AgentPackageCache:
    """Resolves a family and a machine to the agent package for it."""

    def __init__(
        self,
        *,
        root: "Path | None" = None,
        manifest_path: "Path | None" = None,
        pinned_dir: "Path | None" = None,
    ):
        """
        Args:
            root: Where packages are kept; the state root's own directory by
                default.
            manifest_path: The manifest the build stamped; the package's own
                by default.
            pinned_dir: Where a hand-pinned build is looked for; the
                configuration directory's own by default.
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
            else UTILS_CONFIG_DIR / "devices" / "packages"
        )

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
            True when the package is pinned, on disk, or fetchable.
        """
        if self._pinned(family=family, architecture=architecture) is not None:
            return True
        key = platform_key(family, architecture)
        entry = self.manifest().get(key)
        if not isinstance(entry, dict):
            return False
        return self._file(entry) is not None or bool(entry.get("url"))

    def package(self, *, family: str, architecture: str) -> Path:
        """The agent package for one family and machine.

        Args:
            family: ``deb`` or ``rpm``.
            architecture: The machine the device reported.

        Returns:
            Where the file is.

        Raises:
            AgentPackageFetchError: ``agent_package_missing`` when this hub
                has nothing for that platform and nothing to fetch,
                ``agent_package_fetch_failed`` when the release cannot be
                read, and ``agent_package_sha256_mismatch`` when what arrived
                is not what the manifest pinned.
        """
        pinned = self._pinned(family=family, architecture=architecture)
        if pinned is not None:
            return pinned

        key = platform_key(family, architecture)
        entry = self.manifest().get(key)
        if not isinstance(entry, dict):
            raise AgentPackageFetchError("agent_package_missing", platform=key)
        held = self._held(entry)
        if held is not None:
            return held

        url = str(entry.get("url", "") or "")
        name = package_name(entry)
        if not url or not name:
            raise AgentPackageFetchError("agent_package_missing", platform=key)
        content = self._fetch(url)
        pinned_digest = str(entry.get("sha256", "") or "").lower()
        received = hashlib.sha256(content).hexdigest()
        if pinned_digest and pinned_digest != received:
            raise AgentPackageFetchError(
                "agent_package_sha256_mismatch",
                platform=key,
                expected=pinned_digest,
                received=received,
            )
        path = self._root / name
        self._write(path, content)
        return path

    def manifest(self) -> dict:
        """What the build stamped: the platforms this hub knows a package for.

        Returns:
            Platform key to ``{url, sha256, size}``, empty for a checkout,
            which has no build behind it and therefore no manifest.
        """
        try:
            loaded = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

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
            held = hashlib.sha256(path.read_bytes()).hexdigest()
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

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        """Put a package in place whole, never half-written.

        Args:
            path: Where it belongs.
            content: The bytes.

        Raises:
            AgentPackageFetchError: ``agent_package_cache_unwritable``.
        """
        temporary = path.with_name(path.name + ".partial")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(content)
            temporary.replace(path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise AgentPackageFetchError(
                "agent_package_cache_unwritable", detail=str(error)[:200]
            ) from error

    @staticmethod
    def _fetch(url: str) -> bytes:
        """Download one package from where the manifest publishes it.

        Args:
            url: What the manifest names.

        Returns:
            The file's bytes.

        Raises:
            AgentPackageFetchError: ``agent_package_fetch_failed``.
        """
        try:
            with urllib.request.urlopen(
                url, timeout=AGENT_PACKAGE_FETCH_TIMEOUT_S
            ) as response:
                content = response.read(AGENT_PACKAGE_FETCH_LIMIT_BYTES + 1)
        except OSError as error:
            raise AgentPackageFetchError(
                "agent_package_fetch_failed", detail=str(error)[:200]
            ) from error
        if len(content) > AGENT_PACKAGE_FETCH_LIMIT_BYTES:
            raise AgentPackageFetchError(
                "agent_package_fetch_failed",
                detail=f"the download is past {AGENT_PACKAGE_FETCH_LIMIT_BYTES} bytes",
            )
        return content
