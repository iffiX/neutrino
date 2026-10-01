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
import re
import shutil
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.exceptions import AgentArtifactFetchError
from neutrino_hub.modules.devices.constants import (
    AGENT_MODULE_PACKAGE_MAGIC,
    AGENT_MODULE_BROWSER_HEADERS,
    AGENT_MODULE_CACHE_DIR,
    AGENT_MODULE_FETCH_CHUNK_BYTES,
    AGENT_MODULE_FETCH_LIMIT_BYTES,
    AGENT_MODULE_FETCH_TIMEOUT_S,
    AGENT_MODULE_GITHUB_API,
    AGENT_MODULE_KEY_DIGEST_CHARS,
    AGENT_MODULE_PROGRESS_INTERVAL_S,
    AGENT_MODULE_PROGRESS_PERCENT_STEP,
)


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


def read_in_chunks(response, progress: "AgentModuleFetchProgress | None") -> bytes:
    """A response's body, read in 64 KB chunks up to one byte past the limit.

    Args:
        response: What ``urlopen`` answered; its ``Content-Length`` header,
            when present, is the total ``progress`` is told.
        progress: Told the byte count after each chunk and once at the end;
            None tells nobody.

    Returns:
        The bytes read.
    """
    try:
        total = int(response.headers.get("Content-Length", "") or 0)
    except (AttributeError, ValueError):
        total = 0
    chunks = []
    received = 0
    ceiling = AGENT_MODULE_FETCH_LIMIT_BYTES + 1
    while received < ceiling:
        chunk = response.read(min(AGENT_MODULE_FETCH_CHUNK_BYTES, ceiling - received))
        if not chunk:
            break
        chunks.append(chunk)
        received += len(chunk)
        if progress is not None:
            progress.note(received, total)
    if progress is not None:
        progress.note(received, total, is_done=True)
    return b"".join(chunks)


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
        offers this platform nothing. An entry whose ``min_version`` is
        above the tuple's ``version`` is no entry; a tuple with no
        ``version`` is not ruled out.
    """
    platforms = manifest.get("platforms", {})
    for key in platform_keys(platform):
        if key in platforms:
            entry = platforms[key]
            floor = entry.get("min_version", "") if isinstance(entry, dict) else ""
            if is_version_below(str(platform.get("version", "") or ""), str(floor)):
                return "", None
            return key, entry
    return "", None


def is_version_below(version: str, floor: str) -> bool:
    """Whether a reported system version is below a manifest's floor.

    Both are dotted numbers compared part by part: ``2.27`` is below
    ``2.28``, ``15.3.1`` is not below ``12.3``.

    Args:
        version: What the agent reported; empty when it reported none.
        floor: The entry's ``min_version``; empty when it names none.

    Returns:
        True only when both are given and ``version`` is lower.
    """
    if not version or not floor:
        return False
    return version_parts(version) < version_parts(floor)


def version_parts(version: str) -> tuple:
    """A dotted version as the tuple of its leading numbers.

    Args:
        version: A version such as ``2.36``, ``26100`` or ``15.3.1``.

    Returns:
        One int per part, from each part's leading digits; 0 for a part
        with none.
    """
    parts = []
    for part in version.strip().split("."):
        lead = re.match(r"\d*", part).group()
        parts.append(int(lead) if lead else 0)
    return tuple(parts)


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


def format_megabytes(size: int) -> str:
    """A byte count in megabytes with one decimal, as progress lines show it.

    Args:
        size: The count in bytes.

    Returns:
        Such as ``12.9``.
    """
    return f"{size / (1024 * 1024):.1f}"


def artifact_title(name: str, manifest: dict) -> str:
    """What progress lines call a module's artifact: its title and version.

    Args:
        name: The module name, used when the manifest names no title.
        manifest: Its manifest.

    Returns:
        Such as ``VS Code 1.140.0``.
    """
    title = str(manifest.get("title", "") or name)
    version = str(manifest.get("version", "") or "")
    return f"{title} {version}" if version else title


class AgentModuleFetchProgress:
    """Turns a download's running byte count into ``hub: downloading`` lines.

    A line is written for the first chunk, then each time the share received
    moves by :data:`AGENT_MODULE_PROGRESS_PERCENT_STEP` percent or
    :data:`AGENT_MODULE_PROGRESS_INTERVAL_S` seconds pass, and for the last.
    """

    def __init__(
        self,
        *,
        title: str,
        source: str,
        on_line: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
    ):
        """
        Args:
            title: The artifact's title and version, from
                :func:`artifact_title`.
            source: Where it comes from, such as ``Microsoft``; empty leaves
                the ``from`` part out.
            on_line: Called with each line.
            clock: Seconds, monotonic; injected by tests.
        """
        self._title = title
        self._source = source
        self._on_line = on_line
        self._clock = clock
        self._last_at: "float | None" = None
        self._last_percent = 0

    def note(self, received: int, total: int, *, is_done: bool = False) -> None:
        """Take the byte count after one chunk, writing a line when one is due.

        Args:
            received: Bytes received so far.
            total: The size the server announced; 0 when it announced none.
            is_done: Whether the download has ended.
        """
        now = self._clock()
        percent = received * 100 // total if total > 0 else 0
        is_due = (
            is_done
            or self._last_at is None
            or now - self._last_at >= AGENT_MODULE_PROGRESS_INTERVAL_S
            or percent - self._last_percent >= AGENT_MODULE_PROGRESS_PERCENT_STEP
        )
        if not is_due:
            return
        self._last_at = now
        self._last_percent = percent
        self._on_line(self._line(received, total))

    def _line(self, received: int, total: int) -> str:
        """One progress line for this byte count."""
        amount = format_megabytes(received)
        if total > 0:
            amount = f"{amount} / {format_megabytes(total)}"
        origin = f" from {self._source}" if self._source else ""
        return f"hub: downloading {self._title}{origin}, {amount} MB"


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
        self,
        *,
        name: str,
        manifest: dict,
        platform: dict,
        on_progress: "Callable[[str], None] | None" = None,
    ) -> AgentModuleArtifact:
        """The module's bytes for this platform, fetched if they are not held.

        Two devices of one platform asking at once share the single fetch:
        the second waits on the first rather than starting its own, and
        finds the file already there when it is let through.

        Args:
            name: The module name.
            manifest: Its manifest.
            platform: The tuple the agent reported.
            on_progress: Called on this thread with each ``hub:`` line: the
                download's progress, or that the artifact is in the cache.
                None writes no line.

        Returns:
            The artifact.

        Raises:
            AgentArtifactFetchError: ``no_platform_build`` when the manifest
                offers this platform nothing, ``no_download_named`` when its
                entry names neither a url nor a release to resolve, and the
                fetch's own typed reasons otherwise.
        """
        platform_key, entry = resolve_platform_entry(manifest, platform)
        if entry is None:
            raise AgentArtifactFetchError("no_platform_build")
        package_kind = str(entry.get("package_kind", "") or "")
        key = self._key(name=name, platform_key=platform_key, entry=entry)
        path = self._root / key

        title = artifact_title(name, manifest)
        with self._lock_for(key):
            held = self._read_held(path)
            if held is None:
                progress = None
                if on_progress is not None:
                    progress = AgentModuleFetchProgress(
                        title=title,
                        source=str(manifest.get("source", "") or ""),
                        on_line=on_progress,
                    )
                content = self._fetch(entry, progress=progress)
                self._write(path, content)
                held = hashlib.sha256(content).hexdigest()
            elif on_progress is not None:
                on_progress(f"hub: {title} is in the cache")
            return AgentModuleArtifact(
                key=key,
                path=path,
                digest=held,
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
            AgentArtifactFetchError: ``module_artifact_unknown`` when no
                manifest this hub holds resolves to that key, and the
                fetch's own typed reasons otherwise.
        """
        if not self._is_safe_key(key):
            raise AgentArtifactFetchError("module_artifact_unknown")
        for name, manifest in sources.items():
            if (
                self.artifact_key(name=name, manifest=manifest, platform=platform)
                == key
            ):
                return self.artifact(name=name, manifest=manifest, platform=platform)
        raise AgentArtifactFetchError("module_artifact_unknown", artifact_key=key)

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
            AgentArtifactFetchError: If the cache cannot be written.
        """
        temporary = path.with_name(path.name + ".partial")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(content)
            temporary.replace(path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise AgentArtifactFetchError(
                "module_cache_unwritable", detail=str(error)[:200]
            ) from error

    def _fetch(
        self, entry: dict, *, progress: "AgentModuleFetchProgress | None" = None
    ) -> bytes:
        """Get one module's bytes.

        Args:
            entry: The manifest's entry for this platform.
            progress: Told the byte count after each chunk; None tells nobody.

        Returns:
            The package.

        Raises:
            AgentArtifactFetchError: With the typed reason; a payload that does
                not open like the entry's package kind is
                ``module_fetch_failed``, so an error page never gets cached
                as a package, and one whose digest is not the pinned
                ``sha256`` is ``module_sha256_mismatch``.
        """
        url = str(entry.get("url", "") or "")
        if not url and entry.get("github_repo"):
            url = self._resolve_github_asset(
                str(entry["github_repo"]), str(entry.get("asset_pattern", "") or "")
            )
        if not url:
            raise AgentArtifactFetchError("no_download_named")
        content = self._fetch_plain(url, progress=progress)
        if len(content) > AGENT_MODULE_FETCH_LIMIT_BYTES:
            raise AgentArtifactFetchError(
                "module_fetch_too_large",
                limit_mb=AGENT_MODULE_FETCH_LIMIT_BYTES // (1024 * 1024),
            )
        package_kind = str(entry.get("package_kind", "") or "")
        if not looks_like_package(content, package_kind):
            raise AgentArtifactFetchError(
                "module_fetch_failed",
                detail=f"the download does not open like a {package_kind} package",
            )
        pinned = str(entry.get("sha256", "") or "").lower()
        received = hashlib.sha256(content).hexdigest()
        if pinned and pinned != received:
            raise AgentArtifactFetchError(
                "module_sha256_mismatch", expected=pinned, received=received
            )
        return content

    @staticmethod
    def _fetch_plain(
        url: str, *, progress: "AgentModuleFetchProgress | None" = None
    ) -> bytes:
        """Fetch directly, with ordinary browser headers, in 64 KB chunks.

        Args:
            url: What the manifest names.
            progress: Told the byte count after each chunk; None tells nobody.

        Returns:
            The body, at most one byte past the fetch limit.

        Raises:
            AgentArtifactFetchError: ``module_fetch_failed``.
        """
        request = urllib.request.Request(url, headers=AGENT_MODULE_BROWSER_HEADERS)
        try:
            with urllib.request.urlopen(
                request, timeout=AGENT_MODULE_FETCH_TIMEOUT_S
            ) as response:
                return read_in_chunks(response, progress)
        except OSError as error:
            raise AgentArtifactFetchError(
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
            AgentArtifactFetchError: ``module_release_unreadable`` when the
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
            raise AgentArtifactFetchError(
                "module_release_unreadable", repo=repo, detail=str(error)[:200]
            ) from error
        for asset in release.get("assets", []):
            if str(asset.get("name", "")).endswith(asset_pattern):
                return str(asset.get("browser_download_url", ""))
        raise AgentArtifactFetchError("no_download_named", repo=repo)


def clear_module_cache(root: "Path | None" = None) -> None:
    """Drop every fetched artifact.

    A reset hands the machine back with nothing of the hub's on it, and this
    directory is a cache: what it costs to lose is one download.

    Args:
        root: Where artifacts are kept; the state root's own by default.
    """
    directory = Path(root) if root is not None else AGENT_MODULE_CACHE_DIR
    shutil.rmtree(directory, ignore_errors=True)
