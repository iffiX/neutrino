"""Each module's versions as its publisher's feeds listed them.

A ``hub`` or ``container`` entry names ``releases``, the feeds the hub reads
once a day (module_install.md, "Module versions"): the first lists the
versions, each read as a dotted number, newest first, and each artifact takes
its digest from the feed whose release holds its file. What was read is kept
in ``module_releases.json`` under the state root, ``{read_at, modules:
{<module>: {<platform key>: [{version, artifacts: {<name>: {digest,
sources}}}]}}}``, and a version is listed for a platform only when every
artifact of its entry whose file names ``{version}`` was found in it. A
module whose entry names no ``releases``, and every ``agent``, ``builtin``
and ``system`` entry, has one version, its tested one, locked.

The parsers are pure functions of a feed's answer; the store reads and
writes the file; the reader drives the fetcher over every manifest.
"""

import json
import logging
import re
from datetime import datetime, timezone

from neutrino_hub.exceptions import DownloadFailedError
from neutrino_hub.modules.devices.constants import (
    DEVICE_METHOD_AGENT,
    DEVICE_METHOD_BUILTIN,
    DEVICE_METHOD_SYSTEM,
    DEVICE_MODULE_RELEASES_PATH,
    DEVICE_MODULE_RELEASES_VERSIONS_MAX,
)
from neutrino_hub.modules.devices.manifests import (
    artifact_file,
    artifact_sources,
    entry_artifacts,
    entry_method,
    entry_params,
    entry_version,
    load_module_manifests,
    module_recipe,
    resolve_platform_entry,
    version_parts,
)
from neutrino_hub.utils.constants import UTILS_SOURCE_VERSION
from neutrino_hub.utils.json_file import write_generated

LOGGER = logging.getLogger(__name__)

FEED_GITHUB = "github"
FEED_VSCODE_UPDATE = "vscode_update"
FEED_OCI = "oci"
FEED_NPM = "npm"
# What a version looks like: a dotted number, as module_install.md reads a tag.
VERSION_PATTERN = re.compile(r"^\d+(\.\d+)*$")
# The documents each feed kind reads under its sources.
GITHUB_RELEASES_PATH = "/repos/{repository}/releases?per_page=100"
VSCODE_RELEASES_PATH = "/api/releases/stable"
VSCODE_VERSION_PATH = "/api/versions/{version}/{platform}/stable"
OCI_TAGS_PATH = "/v2/{repository}/tags/list"
NPM_PACKAGE_PATH = "/{package}"
# How many of Microsoft's newest releases are read for their hash, since each
# one is a document of its own.
VSCODE_VERSIONS_READ = 10
# The methods whose version is locked at the tested one.
LOCKED_METHODS = (DEVICE_METHOD_AGENT, DEVICE_METHOD_BUILTIN, DEVICE_METHOD_SYSTEM)


def tag_pattern(template: str) -> re.Pattern:
    """The pattern a feed's tag template matches, the version captured.

    Args:
        template: The feed's ``tag``, such as ``v{version}``.

    Returns:
        A pattern whose first group is the version.
    """
    head, _, tail = template.partition(UTILS_SOURCE_VERSION)
    return re.compile(f"^{re.escape(head)}(.+){re.escape(tail)}$")


def parse_github_releases(document, template: str) -> dict:
    """The versions a GitHub releases listing names, with each asset's digest.

    Args:
        document: The API's answer, a list of releases.
        template: The feed's ``tag``.

    Returns:
        Version to ``{asset name: digest}``, drafts and prereleases left out,
        a tag that is no dotted number left out, an asset with no digest
        left out.

    Raises:
        ValueError: When the document is not a list of releases.
    """
    if not isinstance(document, list):
        raise ValueError("a releases listing is a list")
    pattern = tag_pattern(template)
    versions: dict = {}
    for release in document:
        if not isinstance(release, dict):
            continue
        if release.get("draft") or release.get("prerelease"):
            continue
        match = pattern.match(str(release.get("tag_name", "") or ""))
        if match is None or not VERSION_PATTERN.match(match.group(1)):
            continue
        assets = {}
        for asset in release.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            digest = str(asset.get("digest", "") or "")
            name = str(asset.get("name", "") or "")
            if name and digest:
                assets[name] = {"digest": digest}
        versions[match.group(1)] = assets
    return versions


def parse_vscode_releases(document) -> list:
    """The versions Microsoft's stable list names, newest first.

    Args:
        document: The API's answer, a list of version strings.

    Returns:
        The versions that are dotted numbers, in the list's order.

    Raises:
        ValueError: When the document is not a list.
    """
    if not isinstance(document, list):
        raise ValueError("a release list is a list")
    return [str(item) for item in document if VERSION_PATTERN.match(str(item))]


def parse_vscode_version(document) -> dict:
    """One version's file for one platform, as Microsoft's version document gives it.

    Args:
        document: The API's answer for one version and platform.

    Returns:
        ``{digest, sources}``: ``sha256:`` and the document's ``sha256hash``,
        and its ``url`` as the one source.

    Raises:
        ValueError: When the document names no hash or url.
    """
    if not isinstance(document, dict):
        raise ValueError("a version document is an object")
    digest = str(document.get("sha256hash", "") or "")
    url = str(document.get("url", "") or "")
    if not digest or not url:
        raise ValueError("a version document names sha256hash and url")
    return {"digest": f"sha256:{digest}", "sources": [url]}


def parse_oci_tags(document, template: str) -> list:
    """The versions a registry's tag list names.

    Args:
        document: The registry's answer, ``{name, tags}``.
        template: The feed's ``tag``.

    Returns:
        The versions whose tag matches the template and is a dotted number.

    Raises:
        ValueError: When the document names no tags.
    """
    if not isinstance(document, dict) or not isinstance(document.get("tags"), list):
        raise ValueError("a tag list names tags")
    pattern = tag_pattern(template)
    versions = []
    for tag in document["tags"]:
        match = pattern.match(str(tag))
        if match is not None and VERSION_PATTERN.match(match.group(1)):
            versions.append(match.group(1))
    return versions


def parse_npm_package(document) -> dict:
    """The versions an npm package document names, with each one's integrity.

    Args:
        document: The registry's answer for the package.

    Returns:
        Version to its ``dist.integrity``, versions that are dotted numbers
        alone.

    Raises:
        ValueError: When the document names no versions.
    """
    if not isinstance(document, dict) or not isinstance(document.get("versions"), dict):
        raise ValueError("a package document names versions")
    found = {}
    for version, entry in document["versions"].items():
        if not VERSION_PATTERN.match(str(version)) or not isinstance(entry, dict):
            continue
        integrity = str((entry.get("dist") or {}).get("integrity", "") or "")
        if integrity:
            found[str(version)] = integrity
    return found


def sorted_versions(versions) -> list:
    """Versions newest first.

    Args:
        versions: The versions, dotted numbers.

    Returns:
        The versions sorted by their parts, the highest first.
    """
    return sorted(set(versions), key=version_parts, reverse=True)


def is_locked(manifest: dict, entry: "dict | None") -> bool:
    """Whether a module's version is locked at its tested one on one platform.

    Args:
        manifest: The module's manifest.
        entry: Its entry for the platform.

    Returns:
        True for an ``agent``, ``builtin`` or ``system`` entry, for a
        ``container`` entry that names no ``releases``, and for no entry.
    """
    method = entry_method(entry)
    if not method or method in LOCKED_METHODS:
        return True
    return not entry_params(entry).get("releases")


class ModuleReleaseStore:
    """Reads and writes what the feeds listed, under the state root."""

    def __init__(self, *, path=None):
        """
        Args:
            path: The file; the state root's when None.
        """
        self._path = path or DEVICE_MODULE_RELEASES_PATH

    def read_at(self) -> str:
        """When the feeds were last read, in ISO 8601; empty before the first."""
        return str(self._read().get("read_at", "") or "")

    def listed(self, module: str, platform: dict) -> list:
        """The versions the feeds listed for one module on one platform.

        Args:
            module: The module.
            platform: The tuple the machine reported.

        Returns:
            ``[{version, artifacts}]`` newest first, empty when nothing was
            read for the entry the platform resolves to.
        """
        manifest = load_module_manifests().get(module)
        if manifest is None:
            return []
        platform_key, _ = resolve_platform_entry(manifest, platform)
        held = (self._read().get("modules") or {}).get(module) or {}
        listed = held.get(platform_key)
        return [dict(item) for item in listed] if isinstance(listed, list) else []

    def listed_by_key(self, module: str, platform_key: str) -> list:
        """The versions the feeds listed for one module's one platform entry.

        Args:
            module: The module.
            platform_key: The entry's key in the manifest.

        Returns:
            ``[{version, artifacts}]`` newest first, empty when nothing was
            read for it.
        """
        held = (self._read().get("modules") or {}).get(module) or {}
        listed = held.get(platform_key)
        return [dict(item) for item in listed] if isinstance(listed, list) else []

    def versions(self, module: str, platform: dict) -> list:
        """Every version one machine may choose for one module, newest first.

        Args:
            module: The module.
            platform: The tuple the machine reported.

        Returns:
            ``[{version, is_tested, is_untested}]``: the listed versions with
            the tested one among them, or the tested one alone for a locked
            module or while nothing was read.
        """
        manifest = load_module_manifests().get(module) or {}
        _, entry = resolve_platform_entry(manifest, platform)
        tested = entry_version(manifest, entry)
        if is_locked(manifest, entry):
            return [_version_row(tested, tested)] if tested else []
        found = [str(item.get("version", "")) for item in self.listed(module, platform)]
        if tested and tested not in found:
            found.append(tested)
        return [_version_row(version, tested) for version in sorted_versions(found)]

    def recipe(self, module: str, platform: dict, version: str) -> "dict | None":
        """The recipe of one listed version, for the state.

        Args:
            module: The module.
            platform: The tuple the machine reported.
            version: The version the machine chose.

        Returns:
            The tested recipe with ``version`` and each artifact's digest
            replaced by the version's, or None when the feeds did not list
            the version for the platform.
        """
        manifest = load_module_manifests().get(module) or {}
        _, entry = resolve_platform_entry(manifest, platform)
        if entry is None or version == entry_version(manifest, entry):
            return module_recipe(entry) if entry is not None else None
        found = self._found(module, platform, version)
        if found is None:
            return None
        recipe = module_recipe(entry)
        recipe["params"] = dict(recipe["params"])
        recipe["params"]["version"] = version
        artifacts = []
        for artifact in recipe["params"].get("artifacts") or []:
            held = found.get(artifact["name"])
            artifacts.append(
                {**artifact, "digest": held["digest"]} if held else dict(artifact)
            )
        recipe["params"]["artifacts"] = artifacts
        return recipe

    def artifact_sources(
        self, module: str, platform: dict, name: str, digest: str
    ) -> "list | None":
        """Where one artifact of one listed version comes from.

        Args:
            module: The module.
            platform: The tuple the machine reported.
            name: The artifact's name.
            digest: The digest the recipe named for it.

        Returns:
            The addresses that serve the file of the version whose artifact
            has that digest, or None when no listed version does.
        """
        manifest = load_module_manifests().get(module) or {}
        _, entry = resolve_platform_entry(manifest, platform)
        for item in self.listed(module, platform):
            held = (item.get("artifacts") or {}).get(name)
            if not held or held.get("digest") != digest:
                continue
            if held.get("sources"):
                return list(held["sources"])
            for artifact in entry_artifacts(manifest, entry):
                if artifact["name"] == name:
                    return artifact_sources(artifact, str(item["version"]))
        return None

    def replace(self, modules: dict, *, read_at: "str | None" = None) -> None:
        """Write what a read listed, whole.

        Args:
            modules: Module to platform key to its version list.
            read_at: When the read happened; None is now.

        Raises:
            OSError: When the file cannot be written.
        """
        stamp = read_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_generated(
            self._path,
            json.dumps({"read_at": stamp, "modules": modules}, indent=2),
            mode=0o600,
        )

    def _found(self, module: str, platform: dict, version: str) -> "dict | None":
        for item in self.listed(module, platform):
            if str(item.get("version", "")) == version:
                return dict(item.get("artifacts") or {})
        return None

    def _read(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        return held if isinstance(held, dict) else {}


def _version_row(version: str, tested: str) -> dict:
    return {
        "version": version,
        "is_tested": version == tested,
        "is_untested": bool(tested)
        and version != tested
        and version_parts(version) > version_parts(tested),
    }


class ModuleReleaseReader:
    """Reads every manifest's feeds into the store."""

    def __init__(self, *, fetcher, store: "ModuleReleaseStore | None" = None):
        """
        Args:
            fetcher: The :class:`~neutrino_hub.utils.source_fetch.SourceFetcher`
                the documents are read with.
            store: Where the read lands; None is the state root's.
        """
        self._fetcher = fetcher
        self._store = store if store is not None else ModuleReleaseStore()

    def read(self) -> dict:
        """Read every feed once and write what it listed.

        An entry whose feeds cannot be read keeps nothing new; the store is
        written with every entry that read, the others as they were.

        Returns:
            Module to platform key to its version list, as written.
        """
        previous = self._store._read().get("modules") or {}
        modules: dict = {}
        for name, manifest in load_module_manifests().items():
            for platform_key, entry in (manifest.get("platforms") or {}).items():
                if is_locked(manifest, entry):
                    continue
                try:
                    listed = self.read_entry(manifest, entry)
                except (DownloadFailedError, ValueError, OSError) as error:
                    LOGGER.warning("module versions of %s not read: %s", name, error)
                    kept = (previous.get(name) or {}).get(platform_key)
                    if kept is not None:
                        modules.setdefault(name, {})[platform_key] = kept
                    continue
                modules.setdefault(name, {})[platform_key] = listed
        self._store.replace(modules)
        return modules

    def read_entry(self, manifest: dict, entry: dict) -> list:
        """One entry's version list, from its feeds.

        Args:
            manifest: The module's manifest.
            entry: The platform entry.

        Returns:
            ``[{version, artifacts: {name: {digest, sources?}}}]`` newest
            first, versions every versioned artifact was found in alone.

        Raises:
            DownloadFailedError: When a feed's sources did not answer.
            ValueError: When a feed answered with something else.
        """
        feeds = entry_params(entry).get("releases") or []
        answers = [self._read_feed(feed) for feed in feeds]
        versions = sorted_versions(answers[0].keys())[
            :DEVICE_MODULE_RELEASES_VERSIONS_MAX
        ]
        artifacts = entry_artifacts(manifest, entry)
        listed = []
        for version in versions:
            found = {}
            is_whole = True
            for artifact in artifacts:
                if not _is_versioned(artifact):
                    continue
                file = artifact_file(artifact, version)
                held = next(
                    (
                        answer[version].get(file)
                        or answer[version].get(artifact["name"])
                        for answer in answers
                        if version in answer
                        and (
                            answer[version].get(file)
                            or answer[version].get(artifact["name"])
                        )
                    ),
                    None,
                )
                if held is None:
                    is_whole = False
                    break
                found[artifact["name"]] = dict(held)
            if is_whole:
                listed.append({"version": version, "artifacts": found})
        return listed

    def _read_feed(self, feed: dict) -> dict:
        """One feed's answer as version to ``{file or name: {digest, sources?}}``."""
        kind = feed["kind"]
        sources = [str(source).rstrip("/") for source in feed["sources"]]
        if kind == FEED_GITHUB:
            document, _ = self._fetcher.fetch_document(
                file=f"{feed['repository']} releases",
                sources=[
                    source + GITHUB_RELEASES_PATH.format(repository=feed["repository"])
                    for source in sources
                ],
                parse=json.loads,
            )
            return parse_github_releases(document, feed["tag"])
        if kind == FEED_VSCODE_UPDATE:
            document, _ = self._fetcher.fetch_document(
                file="vscode releases",
                sources=[source + VSCODE_RELEASES_PATH for source in sources],
                parse=json.loads,
            )
            versions = {}
            for version in parse_vscode_releases(document)[:VSCODE_VERSIONS_READ]:
                path = VSCODE_VERSION_PATH.format(
                    version=version, platform=feed["platform"]
                )
                try:
                    found, _ = self._fetcher.fetch_document(
                        file=f"vscode {version}",
                        sources=[source + path for source in sources],
                        parse=json.loads,
                    )
                except DownloadFailedError:
                    continue
                versions[version] = {_VSCODE_ANY_FILE: parse_vscode_version(found)}
            return versions
        if kind == FEED_OCI:
            document, _ = self._fetcher.fetch_document(
                file=f"{feed['repository']} tags",
                sources=[
                    source + OCI_TAGS_PATH.format(repository=feed["repository"])
                    for source in sources
                ],
                parse=json.loads,
            )
            return {version: {} for version in parse_oci_tags(document, feed["tag"])}
        if kind == FEED_NPM:
            document, _ = self._fetcher.fetch_document(
                file=f"{feed['package']} package",
                sources=[
                    source + NPM_PACKAGE_PATH.format(package=feed["package"])
                    for source in sources
                ],
                parse=json.loads,
            )
            return {
                version: {_NPM_ANY_FILE: {"digest": integrity}}
                for version, integrity in parse_npm_package(document).items()
            }
        raise ValueError(f"no feed of kind {kind!r}")


# The one artifact a vscode_update or an npm feed answers for, whatever its
# file is called: the feed names the platform or the package itself.
_VSCODE_ANY_FILE = "*"
_NPM_ANY_FILE = "*"


def _is_versioned(artifact: dict) -> bool:
    """Whether an artifact's file or sources name ``{version}``, or its feed answers for any file."""
    if UTILS_SOURCE_VERSION in str(artifact.get("file", "") or ""):
        return True
    return any(
        UTILS_SOURCE_VERSION in str(source) for source in artifact.get("sources") or []
    )
