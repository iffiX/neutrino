"""Turning "this machine, on this platform, wants this module" into bytes.

The hub is the only thing that fetches a module, so everything a fetch needs
— the manifest's platform table and GitHub's release API — lives here rather
than on a machine that carries no dependencies.

**The cache key is the module name, the platform key it resolved, and a
digest of the resolved entry itself.** A manifest carries no version number,
so the entry is the only honest identity of what will be installed: change
its url, its package kind or its install arguments and the digest changes
with it, which is what stops a manifest edit from being served yesterday's
file. Nothing but the key names a file, so losing the directory costs a
download and nothing else.

Not pure: fetches over the network and writes under the state root.
"""

import hashlib
import json
import shutil
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.modules.devices.constants import (
    AGENT_MODULE_PACKAGE_MAGIC,
    AGENT_MODULE_BROWSER_HEADERS,
    AGENT_MODULE_CACHE_DIR,
    AGENT_MODULE_FETCH_LIMIT_BYTES,
    AGENT_MODULE_FETCH_TIMEOUT_S,
    AGENT_MODULE_GITHUB_API,
    AGENT_MODULE_KEY_DIGEST_CHARS,
)


class AgentModuleFetchError(RuntimeError):
    """Raised when a module's bytes cannot be obtained.

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


@dataclass
class AgentModuleArtifact:
    """One module's bytes on the hub's own disk.

    Attributes:
        key: What addresses it in the cache, and what an agent asks for.
        path: Where the file is.
        digest: Its SHA-256, which the agent checks what it received against.
        package_kind: The kind the manifest names.
    """

    key: str
    path: Path
    digest: str
    package_kind: str


def platform_keys(platform: dict) -> list:
    """The manifest keys a platform tuple matches, most specific first.

    Args:
        platform: The tuple the agent reported — ``os``, ``family``, ``arch``.

    Returns:
        Candidate keys; the first present in a manifest's platform table
        wins. Empty when the machine has not reported a platform yet.
    """
    if not platform:
        return []
    os_name = str(platform.get("os", ""))
    family = str(platform.get("family", ""))
    arch = str(platform.get("arch", ""))
    keys = []
    if family:
        keys.append(f"{os_name}-{family}-{arch}")
        keys.append(f"{os_name}-{family}")
    keys.append(f"{os_name}-{arch}")
    keys.append(os_name)
    return keys


def resolve_platform_entry(manifest: dict, platform: dict) -> tuple:
    """The manifest's entry for one platform, and the key it matched.

    Args:
        manifest: The module's manifest.
        platform: The tuple the agent reported.

    Returns:
        ``(platform_key, entry)``, or ``("", None)`` when the manifest
        offers this platform nothing.
    """
    platforms = manifest.get("platforms", {})
    for key in platform_keys(platform):
        if key in platforms:
            return key, platforms[key]
    return "", None


def looks_like_package(content: bytes, package_kind: str) -> bool:
    """Whether a payload opens like its claimed package kind.

    Args:
        content: The downloaded bytes.
        package_kind: The kind the manifest names.

    Returns:
        True when the payload starts with one of the kind's magic prefixes,
        or when the kind names no magic to check.
    """
    magic = AGENT_MODULE_PACKAGE_MAGIC.get(package_kind)
    if not magic:
        return True
    return any(content.startswith(prefix) for prefix in magic)


class AgentModuleCache:
    """Resolves a module to bytes, fetching each artifact exactly once."""

    def __init__(self, *, root: "Path | None" = None):
        """
        Args:
            root: Where artifacts are kept; the state root's own directory
                by default.
        """
        self._root = Path(root) if root is not None else AGENT_MODULE_CACHE_DIR
        self._guard = threading.Lock()
        self._fetch_locks: dict = {}

    def artifact_key(self, *, name: str, manifest: dict, platform: dict) -> str:
        """What addresses this module's artifact for this platform.

        Args:
            name: The module name.
            manifest: Its manifest.
            platform: The tuple the agent reported.

        Returns:
            The cache key, empty when the manifest offers this platform
            nothing.
        """
        platform_key, entry = resolve_platform_entry(manifest, platform)
        if entry is None:
            return ""
        return self._key(name=name, platform_key=platform_key, entry=entry)

    def artifact(
        self, *, name: str, manifest: dict, platform: dict
    ) -> AgentModuleArtifact:
        """The module's bytes for this platform, fetched if they are not held.

        Two devices of one platform asking at once share the single fetch:
        the second waits on the first rather than starting its own, and
        finds the file already there when it is let through.

        Args:
            name: The module name.
            manifest: Its manifest.
            platform: The tuple the agent reported.

        Returns:
            The artifact.

        Raises:
            AgentModuleFetchError: ``no_platform_build`` when the manifest
                offers this platform nothing, ``no_download_named`` when its
                entry names neither a url nor a release to resolve, and the
                fetch's own typed reasons otherwise.
        """
        platform_key, entry = resolve_platform_entry(manifest, platform)
        if entry is None:
            raise AgentModuleFetchError("no_platform_build")
        package_kind = str(entry.get("package_kind", "") or "")
        key = self._key(name=name, platform_key=platform_key, entry=entry)
        path = self._root / key

        with self._lock_for(key):
            held = self._read_held(path)
            if held is not None:
                return AgentModuleArtifact(
                    key=key, path=path, digest=held, package_kind=package_kind
                )
            content = self._fetch(entry)
            self._write(path, content)
            return AgentModuleArtifact(
                key=key,
                path=path,
                digest=hashlib.sha256(content).hexdigest(),
                package_kind=package_kind,
            )

    def artifact_for_key(
        self, key: str, *, sources: dict, platform: dict
    ) -> AgentModuleArtifact:
        """The artifact a key names, fetching it again if it is not held.

        The key is a pure function of the name, the platform and the entry,
        so it can be resolved back without anything having been remembered.
        That is what makes losing the directory cost a download and nothing
        else: an order made before a restart still finds its bytes.

        Args:
            key: The cache key an order carried.
            sources: Name to manifest — every artifact this hub can serve.
            platform: The tuple the asking device reported.

        Returns:
            The artifact.

        Raises:
            AgentModuleFetchError: ``module_artifact_unknown`` when no
                manifest this hub holds resolves to that key, and the
                fetch's own typed reasons otherwise.
        """
        if not self._is_safe_key(key):
            raise AgentModuleFetchError("module_artifact_unknown")
        for name, manifest in sources.items():
            if (
                self.artifact_key(name=name, manifest=manifest, platform=platform)
                == key
            ):
                return self.artifact(name=name, manifest=manifest, platform=platform)
        raise AgentModuleFetchError("module_artifact_unknown", artifact_key=key)

    def held(self, key: str) -> "Path | None":
        """The artifact a key names, when the cache still holds it.

        Args:
            key: The cache key.

        Returns:
            Its path, or None — a directory cleared since the order reads as
            nothing held, and the caller resolves the key again instead.
        """
        if not self._is_safe_key(key):
            return None
        path = self._root / key
        return path if path.is_file() else None

    @staticmethod
    def _is_safe_key(key: str) -> bool:
        """Whether a key names a file in the cache and nowhere else."""
        return (
            bool(key) and "/" not in key and "\\" not in key and not key.startswith(".")
        )

    def _key(self, *, name: str, platform_key: str, entry: dict) -> str:
        """Address one artifact by what would actually be installed."""
        serialized = json.dumps(entry, sort_keys=True, default=str).encode("utf-8")
        digest = hashlib.sha256(serialized).hexdigest()[:AGENT_MODULE_KEY_DIGEST_CHARS]
        safe = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in f"{name}-{platform_key}"
        )
        return f"{safe}-{digest}"

    def _lock_for(self, key: str) -> threading.Lock:
        """The one lock every asker for this artifact waits on."""
        with self._guard:
            lock = self._fetch_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._fetch_locks[key] = lock
            return lock

    @staticmethod
    def _read_held(path: Path) -> "str | None":
        """The digest of an artifact already on disk, or None."""
        try:
            with open(path, "rb") as stream:
                return hashlib.sha256(stream.read()).hexdigest()
        except OSError:
            return None

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        """Put an artifact in place whole, never half-written.

        Args:
            path: Where it belongs.
            content: The bytes.

        Raises:
            AgentModuleFetchError: If the cache cannot be written.
        """
        temporary = path.with_name(path.name + ".partial")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(content)
            temporary.replace(path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise AgentModuleFetchError(
                "module_cache_unwritable", detail=str(error)[:200]
            ) from error

    def _fetch(self, entry: dict) -> bytes:
        """Get one module's bytes.

        Args:
            entry: The manifest's entry for this platform.

        Returns:
            The package.

        Raises:
            AgentModuleFetchError: With the typed reason; a payload that does
                not open like the entry's package kind is
                ``module_fetch_failed``, so an error page never gets cached
                as a package.
        """
        url = str(entry.get("url", "") or "")
        if not url and entry.get("github_repo"):
            url = self._resolve_github_asset(
                str(entry["github_repo"]), str(entry.get("asset_pattern", "") or "")
            )
        if not url:
            raise AgentModuleFetchError("no_download_named")
        content = self._fetch_plain(url)
        if len(content) > AGENT_MODULE_FETCH_LIMIT_BYTES:
            raise AgentModuleFetchError(
                "module_fetch_too_large",
                limit_mb=AGENT_MODULE_FETCH_LIMIT_BYTES // (1024 * 1024),
            )
        package_kind = str(entry.get("package_kind", "") or "")
        if not looks_like_package(content, package_kind):
            raise AgentModuleFetchError(
                "module_fetch_failed",
                detail=f"the download does not open like a {package_kind} package",
            )
        return content

    @staticmethod
    def _fetch_plain(url: str) -> bytes:
        """Fetch directly, with ordinary browser headers.

        Args:
            url: What the manifest names.

        Returns:
            The body.

        Raises:
            AgentModuleFetchError: ``module_fetch_failed``.
        """
        request = urllib.request.Request(url, headers=AGENT_MODULE_BROWSER_HEADERS)
        try:
            with urllib.request.urlopen(
                request, timeout=AGENT_MODULE_FETCH_TIMEOUT_S
            ) as response:
                return response.read(AGENT_MODULE_FETCH_LIMIT_BYTES + 1)
        except OSError as error:
            raise AgentModuleFetchError(
                "module_fetch_failed", detail=str(error)[:200]
            ) from error

    @staticmethod
    def _resolve_github_asset(repo: str, asset_pattern: str) -> str:
        """The newest release asset whose name ends with a pattern.

        Args:
            repo: ``owner/name`` on GitHub.
            asset_pattern: Suffix the wanted asset's file name ends with.

        Returns:
            The asset's download URL.

        Raises:
            AgentModuleFetchError: ``module_release_unreadable`` when the
                release cannot be read, ``no_download_named`` when nothing
                in it matches.
        """
        request = urllib.request.Request(
            AGENT_MODULE_GITHUB_API.format(repo=repo),
            headers=AGENT_MODULE_BROWSER_HEADERS,
        )
        try:
            with urllib.request.urlopen(
                request, timeout=AGENT_MODULE_FETCH_TIMEOUT_S
            ) as response:
                release = json.load(response)
        except (OSError, ValueError) as error:
            raise AgentModuleFetchError(
                "module_release_unreadable", repo=repo, detail=str(error)[:200]
            ) from error
        for asset in release.get("assets", []):
            if str(asset.get("name", "")).endswith(asset_pattern):
                return str(asset.get("browser_download_url", ""))
        raise AgentModuleFetchError("no_download_named", repo=repo)


def clear_module_cache(root: "Path | None" = None) -> None:
    """Drop every fetched artifact.

    A reset hands the machine back with nothing of the hub's on it, and this
    directory is a cache: what it costs to lose is one download.

    Args:
        root: Where artifacts are kept; the state root's own by default.
    """
    directory = Path(root) if root is not None else AGENT_MODULE_CACHE_DIR
    shutil.rmtree(directory, ignore_errors=True)
