"""The module cache: the files a module's installer fetches for managed machines.

The hub is the one thing that fetches a module's files. For a ``package
{module, artifact, digest}`` stream the cache resolves the module's entry for
the asking machine's platform, finds the artifact of that name and digest,
and serves the file it keeps under that digest, fetching it first when it is
not held: every source the manifest names, filled in, through the method
every download uses (:mod:`neutrino_hub.utils.source_fetch`), the digest and
the head checked, a file larger than 2 GiB refused. Once a new file is in
place, the files of no module some machine names, and of no version the
manifests pin, are deleted; cc-switch's pinned files stay.

Not pure: fetches over the network and writes under the state root.
"""

import re
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.exceptions import (
    AgentArtifactFetchError,
    DownloadFailedError,
    DownloadTooLargeError,
)
from neutrino_hub.modules.devices.constants import (
    AGENT_MODULE_CACHE_DIR,
    AGENT_MODULE_FETCH_LIMIT_BYTES,
    AGENT_MODULE_PACKAGE_MAGIC,
    AGENT_MODULE_PROGRESS_INTERVAL_S,
    AGENT_MODULE_PROGRESS_PERCENT_STEP,
    DEVICE_ARTIFACT_FILE_KINDS,
)
from neutrino_hub.modules.devices.manifests import (
    artifact_file,
    artifact_sources,
    entry_artifacts,
    entry_version,
    load_module_manifests,
    load_tool_manifests,
    resolve_platform_entry,
)
from neutrino_hub.utils.source_fetch import (
    REASON_DIGEST_MISMATCH,
    SourceFetcher,
    failure_entry,
    file_sha256,
    hex_of,
)

# A file the cache keeps is named by its digest's hex.
CACHE_NAME_PATTERN = re.compile(r"[0-9a-f]{64}")
# A file a 0.5 hub kept, ``<module>-<platform>-<16 hex of its digest>``,
# which no hub serves any more.
CACHE_OLD_NAME_PATTERN = re.compile(r"[a-z0-9_]+(?:-[a-z0-9_]+)+-[0-9a-f]{16}")


@dataclass
class AgentModuleArtifact:
    """One artifact's file on the hub's own disk.

    Attributes:
        path: Where the file is, named by its digest.
        digest: Its ``sha256:<hex>``.
        file: The artifact's file name, as its sources name it.
        title: What progress lines call it, from :func:`artifact_title`.
    """

    path: Path
    digest: str
    file: str
    title: str


def looks_like_kind(head: bytes, kind: str) -> bool:
    """Whether a file's first bytes open like its artifact kind.

    Args:
        head: The file's first bytes.
        kind: The artifact's kind.

    Returns:
        True when the head starts with one of the kind's magic prefixes, or
        when the kind names none.
    """
    magic = AGENT_MODULE_PACKAGE_MAGIC.get(kind)
    if not magic:
        return True
    return any(head.startswith(prefix) for prefix in magic)


def format_megabytes(size: int) -> str:
    """A byte count in megabytes with one decimal, as progress lines show it.

    Args:
        size: The count in bytes.

    Returns:
        Such as ``12.9``.
    """
    return f"{size / (1024 * 1024):.1f}"


def artifact_title(manifest: dict, entry: dict, artifact: dict) -> str:
    """What progress lines call one artifact: its module's title and version.

    Args:
        manifest: The module's or the tool's manifest.
        entry: The entry for the machine's platform.
        artifact: The artifact.

    Returns:
        Such as ``VS Code 1.140.0``, or ``Containers 6.1.4 (image)`` for an
        entry with more than one artifact.
    """
    title = str(manifest.get("title", "") or manifest.get("name", ""))
    version = entry_version(manifest, entry)
    titled = f"{title} {version}" if version else title
    if len(entry_artifacts(manifest, entry)) > 1:
        return f"{titled} ({artifact['name']})"
    return titled


class AgentModuleSendProgress:
    """Turns a running byte count into ``hub: sending`` lines.

    A line is written for the first chunk, then each time the share of the
    bytes sent grows by :data:`AGENT_MODULE_PROGRESS_PERCENT_STEP` percent or
    :data:`AGENT_MODULE_PROGRESS_INTERVAL_S` seconds pass, and for the last.
    """

    def __init__(
        self,
        *,
        title: str,
        recipient: str,
        on_line: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
    ):
        """
        Args:
            title: The artifact's title, from :func:`artifact_title`.
            recipient: The machine the bytes go to.
            on_line: Called with each line.
            clock: Seconds, monotonic; injected by tests.
        """
        self._title = title
        self._recipient = recipient
        self._on_line = on_line
        self._clock = clock
        self._last_at: "float | None" = None
        self._last_percent = 0

    def note(self, sent: int, total: int, *, is_done: bool = False) -> None:
        """Take the byte count after one chunk, writing a line when one is due.

        Args:
            sent: Bytes sent so far.
            total: The file's size; 0 when unknown.
            is_done: Whether the send has ended.
        """
        now = self._clock()
        percent = sent * 100 // total if total > 0 else 0
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
        amount = format_megabytes(sent)
        if total > 0:
            amount = f"{amount} / {format_megabytes(total)}"
        self._on_line(f"hub: sending {self._title}, {amount} MB to {self._recipient}")


class AgentModuleCache:
    """Serves each module artifact by its digest, fetching it exactly once."""

    def __init__(
        self,
        *,
        root: "Path | None" = None,
        fetcher: "SourceFetcher | None" = None,
        named_modules: "Callable[[], set] | None" = None,
    ):
        """
        Args:
            root: Where files are kept; the state root's own directory by
                default.
            fetcher: The fetcher every download goes through; a new one by
                default.
            named_modules: Returns the modules some machine names; their
                files are kept and every other module's go. None keeps every
                module's files.
        """
        self._root = Path(root) if root is not None else AGENT_MODULE_CACHE_DIR
        self._fetcher = fetcher if fetcher is not None else SourceFetcher()
        self._named_modules = named_modules
        self._guard = threading.Lock()
        self._fetch_locks: dict = {}

    def artifact(
        self,
        *,
        module: str,
        artifact: str,
        digest: str,
        platform: dict,
        on_progress: "Callable[[str], None] | None" = None,
    ) -> AgentModuleArtifact:
        """The file of one artifact of a module, fetched if it is not held.

        Two devices asking for one digest at once share the single fetch:
        the second waits on the first, and finds the file there when it is
        let through.

        Args:
            module: The module, or the tool, the stream names.
            artifact: The artifact's name.
            digest: The ``sha256:<hex>`` the stream asks for.
            platform: The tuple the asking agent reported.
            on_progress: Called on this thread with each ``hub:`` line: the
                fetch's ``hub: fetching`` lines, or that the file is in the
                cache. None writes no line.

        Returns:
            The artifact.

        Raises:
            AgentArtifactFetchError: ``module_unknown {name}`` for a name no
                manifest names, ``no_platform_build {module}`` when the
                manifest names no entry for the platform,
                ``module_artifact_unknown {module, artifact, digest}`` when
                the entry names no such artifact with that digest,
                ``download_failed {file, sources}`` when no source serves
                it, ``module_fetch_too_large {limit_mb}`` for a file past 2
                GiB, and ``module_cache_unwritable {detail}`` when the cache
                cannot be written.
        """
        manifest = load_module_manifests().get(module) or load_tool_manifests().get(
            module
        )
        if manifest is None:
            raise AgentArtifactFetchError("module_unknown", name=module)
        _, entry = resolve_platform_entry(manifest, platform)
        if entry is None:
            raise AgentArtifactFetchError("no_platform_build", module=module)
        named = self._named_artifact(manifest, entry, artifact, digest)
        if named is None:
            raise AgentArtifactFetchError(
                "module_artifact_unknown",
                module=module,
                artifact=artifact,
                digest=digest,
            )
        version = entry_version(manifest, entry)
        file = artifact_file(named, version)
        title = artifact_title(manifest, entry, named)
        hexed = hex_of(digest)
        path = self._root / hexed
        with self._lock_for(hexed):
            if self._is_held(path, hexed):
                if on_progress is not None:
                    on_progress(f"hub: {title} is in the cache")
            else:
                self._fetch(named, file, version, digest, path, on_progress)
                self._prune()
        return AgentModuleArtifact(path=path, digest=digest, file=file, title=title)

    def kept_digests(self) -> set:
        """The digests the cache keeps files of.

        Returns:
            The hex digest of every file artifact of every entry of each
            module some machine names, and of every tool's artifacts.
        """
        named = self._named_modules() if self._named_modules is not None else None
        kept = set()
        sources = list(load_module_manifests().items())
        sources += list(load_tool_manifests().items())
        tools = set(load_tool_manifests())
        for name, manifest in sources:
            if named is not None and name not in named and name not in tools:
                continue
            for entry in (manifest.get("platforms") or {}).values():
                for artifact in entry_artifacts(manifest, entry):
                    if artifact.get("kind") in DEVICE_ARTIFACT_FILE_KINDS:
                        kept.add(hex_of(artifact["digest"]))
        return kept

    @staticmethod
    def _named_artifact(manifest: dict, entry: dict, name: str, digest: str):
        """The entry's file artifact of that name and digest, or None."""
        for artifact in entry_artifacts(manifest, entry):
            if (
                artifact.get("name") == name
                and artifact.get("digest") == digest
                and artifact.get("kind") in DEVICE_ARTIFACT_FILE_KINDS
            ):
                return artifact
        return None

    def _fetch(self, artifact, file, version, digest, path, on_progress) -> None:
        """Fetch one artifact from its sources, check it, and put it in place.

        Raises:
            AgentArtifactFetchError: ``download_failed``,
                ``module_fetch_too_large`` or ``module_cache_unwritable``;
                nothing is left on disk.
        """
        try:
            download = self._fetcher.fetch_file(
                file=file,
                sources=artifact_sources(artifact, version),
                digest=digest,
                directory=self._root,
                limit=AGENT_MODULE_FETCH_LIMIT_BYTES,
                on_line=on_progress,
            )
        except DownloadFailedError as error:
            raise AgentArtifactFetchError(error.code, **error.params) from error
        except DownloadTooLargeError as error:
            raise AgentArtifactFetchError(
                "module_fetch_too_large", limit_mb=error.limit // (1024 * 1024)
            ) from error
        except OSError as error:
            raise AgentArtifactFetchError(
                "module_cache_unwritable", detail=str(error)[:200]
            ) from error
        kind = str(artifact.get("kind", ""))
        if not looks_like_kind(download.head, kind):
            download.discard()
            raise AgentArtifactFetchError(
                DownloadFailedError.code,
                file=file,
                sources=[
                    failure_entry(
                        download.source,
                        REASON_DIGEST_MISMATCH,
                        f"the file does not open like a {kind}",
                    )
                ],
            )
        try:
            download.place(path)
        except OSError as error:
            raise AgentArtifactFetchError(
                "module_cache_unwritable", detail=str(error)[:200]
            ) from error

    def _prune(self) -> None:
        """Delete every file the cache no longer keeps, and every file of a 0.5
        hub's naming; one that cannot go stays."""
        kept = self.kept_digests()
        try:
            held = list(self._root.iterdir())
        except OSError:
            return
        for path in held:
            is_dropped = bool(
                (CACHE_NAME_PATTERN.fullmatch(path.name) and path.name not in kept)
                or CACHE_OLD_NAME_PATTERN.fullmatch(path.name)
            )
            if not is_dropped:
                continue
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError:
                continue

    def _lock_for(self, key: str) -> threading.Lock:
        """The one lock every asker for this digest waits on."""
        with self._guard:
            lock = self._fetch_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._fetch_locks[key] = lock
            return lock

    @staticmethod
    def _is_held(path: Path, hexed: str) -> bool:
        """Whether the file is there and still hashes to its name."""
        try:
            return file_sha256(path) == hexed
        except OSError:
            return False


def clear_module_cache(root: "Path | None" = None) -> None:
    """Drop every fetched file.

    A reset hands the machine back with nothing of the hub's on it, and this
    directory is a cache: what it costs to lose is one download.

    Args:
        root: Where files are kept; the state root's own by default.
    """
    directory = Path(root) if root is not None else AGENT_MODULE_CACHE_DIR
    shutil.rmtree(directory, ignore_errors=True)
