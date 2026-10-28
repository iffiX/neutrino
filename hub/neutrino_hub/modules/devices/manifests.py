"""Reading the device module manifests, and resolving one machine's entry.

The manifests under ``manifests/`` are the one record of where a module's
software comes from and how a machine checks for it: the module's identity
at the top, and one entry per platform, ``{runner, min_version, install:
{method, params}}``, the ``params`` shaped by the method. A manifest that
says ``is_module: false`` names a program the agent runs itself, cc-switch,
with its version at the top and ``artifacts`` alone in each entry. The
loader refuses a manifest whose keys or ``params`` fall outside those shapes,
so a wrong file fails the suite instead of shipping. Comment keys are
stripped the same way the rest of ``config/`` is.

:func:`resolve_platform_entry` is the one function that picks a machine's
entry; the catalog's row, the Modules page's list, the cache and the state's
recipe all read it.

**The modules come back in the order both surfaces draw them**: what the
agent's own package carries, what the system holds or its package manager
installs, what the module's installer fetches, then container images, and by
title inside each.
"""

import json
import re

from neutrino_hub import HUB_VERSION
from neutrino_hub.modules.devices.source_sets import load_source_sets
from neutrino_hub.modules.devices.constants import (
    DEVICE_ARTIFACT_DIRECTORY_KINDS,
    DEVICE_ARTIFACT_FILE_KINDS,
    DEVICE_ARTIFACT_KIND_DMG,
    DEVICE_ARTIFACT_KIND_IMAGE,
    DEVICE_ARTIFACT_KIND_NPM,
    DEVICE_FEED_KEYS,
    DEVICE_METHOD_AGENT,
    DEVICE_METHOD_BUILTIN,
    DEVICE_METHOD_CONTAINER,
    DEVICE_METHOD_HUB,
    DEVICE_METHOD_RANKS,
    DEVICE_METHOD_SYSTEM,
    DEVICE_METHODS_WITH_LICENSE,
    DEVICE_PLATFORM_OS,
    DEVICE_SYSTEM_VERSION,
)
from neutrino_hub.utils.constants import (
    UTILS_DATA_DIR,
    UTILS_SOURCE_FILE,
    UTILS_SOURCE_RELEASE,
    UTILS_SOURCE_VERSION,
)
from neutrino_hub.utils.json_file import strip_comments
from neutrino_hub.utils.release_sites import release_addresses

MANIFESTS_DIR = UTILS_DATA_DIR / "manifests"
# What a platform entry's ``min_version`` looks like: 2.28, 26100, 12.3.
MANIFEST_VERSION_PATTERN = r"\d+(\.\d+)*"
# A platform key: the system, then a family or an architecture, or both.
MANIFEST_PLATFORM_PATTERN = r"[a-z]+(-[a-z0-9]+){0,2}"
MANIFEST_SHA256_PATTERN = r"sha256:[0-9a-f]{64}"
MANIFEST_INTEGRITY_PATTERN = r"sha512-[A-Za-z0-9+/]+={0,2}"
MODULE_KEYS = {
    "name",
    "title",
    "description",
    "publisher",
    "license",
    "corresponding_source",
    "is_data_forward_only",
    "uninstall_data",
    "platforms",
}
TOOL_KEYS = (MODULE_KEYS - {"is_data_forward_only", "uninstall_data"}) | {
    "is_module",
    "version",
}
# What ``uninstall_data`` holds, and the languages its line is in.
UNINSTALL_DATA_KEYS = {"is_deleted", "text"}
UNINSTALL_DATA_LANGUAGES = {"en", "zh-CN"}
ENTRY_KEYS = {"runner", "min_version", "install"}
# What each method's params hold: the keys it must name, and those it may.
PARAMS_REQUIRED = {
    DEVICE_METHOD_AGENT: set(),
    DEVICE_METHOD_BUILTIN: set(),
    DEVICE_METHOD_SYSTEM: {"version", "packages", "verify", "uninstall"},
    DEVICE_METHOD_HUB: {"version", "releases", "artifacts", "verify", "uninstall"},
    DEVICE_METHOD_CONTAINER: {"version", "artifacts"},
}
PARAMS_OPTIONAL = {
    DEVICE_METHOD_SYSTEM: {"pre_install"},
    DEVICE_METHOD_HUB: {"packages"},
    DEVICE_METHOD_CONTAINER: {"releases", "source_sets"},
}
UNINSTALL_KEYS = {
    DEVICE_METHOD_SYSTEM: {"packages", "post_uninstall"},
    DEVICE_METHOD_HUB: {"post_uninstall", "is_data_kept"},
}
# The artifact keys each kind names, beside ``name``, ``kind`` and ``digest``.
FILE_ARTIFACT_KEYS = {
    "name",
    "kind",
    "digest",
    "file",
    "sources",
    "directory",
    "member",
}
NPM_ARTIFACT_KEYS = {"name", "kind", "digest", "package", "source_set", "hosts"}
IMAGE_ARTIFACT_KEYS = {"name", "kind", "digest", "sources"}
# What the recipe keeps of a hub artifact the agent takes from the package
# stream: the bytes come down the stream, so no source is sent.
RECIPE_FILE_ARTIFACT_KEYS = ("name", "kind", "digest", "directory", "member")


def load_module_manifests() -> dict:
    """Read every module manifest, keyed by module name, in display order.

    Returns:
        Module name to its parsed manifest, comment keys removed, ordered by
        method and then by title.

    Raises:
        ValueError: For a manifest whose keys or ``params`` fall outside the
            shapes module_install.md fixes, naming the file and what is wrong.
    """
    loaded = []
    for path, manifest in _read_manifests():
        if manifest.get("is_module") is False:
            continue
        _check_module(path.name, manifest)
        loaded.append((manifest["name"], manifest))
    loaded.sort(key=_display_order)
    return dict(loaded)


def load_tool_manifests() -> dict:
    """Read every manifest that names a program the agent runs rather than a module.

    Returns:
        Name to its parsed manifest, comment keys removed, for each manifest
        that says ``is_module: false``.

    Raises:
        ValueError: For one whose keys or artifacts fall outside the shape
            module_install.md fixes for it.
    """
    loaded = {}
    for path, manifest in _read_manifests():
        if manifest.get("is_module") is not False:
            continue
        _check_tool(path.name, manifest)
        loaded[manifest["name"]] = manifest
    return loaded


def platform_keys(platform: dict) -> list:
    """The manifest keys a platform tuple matches, in the order they are tried.

    Args:
        platform: The tuple the agent reported: ``os``, ``family``, ``arch``.

    Returns:
        ``<os>-<family>-<arch>``, ``<os>-<family>``, ``<os>-<arch>`` and
        ``<os>``; the first a manifest names wins. Empty when the machine
        has not reported a platform yet.
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
    """The manifest's entry for one machine's platform, and the key it matched.

    Args:
        manifest: The module's manifest.
        platform: The tuple the agent reported.

    Returns:
        ``(platform_key, entry)``, or ``("", None)`` when the manifest names
        no entry for the platform. An entry whose ``min_version`` is above
        the tuple's ``version`` is no entry; a tuple with no ``version`` is
        not ruled out.
    """
    platforms = manifest.get("platforms", {})
    for key in platform_keys(platform):
        if key in platforms:
            entry = platforms[key]
            floor = str(entry.get("min_version", "") or "")
            if is_version_below(str(platform.get("version", "") or ""), floor):
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


def entry_method(entry: "dict | None") -> str:
    """The install method one platform entry names, empty for no entry."""
    if not isinstance(entry, dict):
        return ""
    return str((entry.get("install") or {}).get("method", "") or "")


def entry_params(entry: "dict | None") -> dict:
    """The install params one platform entry names, empty for no entry."""
    if not isinstance(entry, dict):
        return {}
    return dict((entry.get("install") or {}).get("params") or {})


def entry_version(manifest: dict, entry: "dict | None") -> str:
    """The tested version one entry installs.

    Args:
        manifest: The module's or the tool's manifest.
        entry: Its entry for one platform.

    Returns:
        A tool's top-level version, the params' ``version`` of a module
        entry (``system`` for a system entry), empty for an ``agent`` or a
        ``builtin`` entry or for no entry.
    """
    if manifest.get("is_module") is False:
        return str(manifest.get("version", "") or "")
    return str(entry_params(entry).get("version", "") or "")


def entry_artifacts(manifest: dict, entry: "dict | None") -> list:
    """The artifacts one platform entry installs.

    Args:
        manifest: The module's or the tool's manifest.
        entry: Its entry for one platform.

    Returns:
        The artifacts as the manifest names them; empty for an entry of a
        method that names none, or for no entry.
    """
    if not isinstance(entry, dict):
        return []
    if manifest.get("is_module") is False:
        return [dict(item) for item in entry.get("artifacts") or []]
    return [dict(item) for item in entry_params(entry).get("artifacts") or []]


def artifact_file(artifact: dict, version: str) -> str:
    """The file one artifact names, its version filled in.

    Args:
        artifact: The artifact.
        version: The version installed.

    Returns:
        The file's name; the artifact's name for an artifact that names no
        file.
    """
    file = str(artifact.get("file", "") or artifact.get("name", "") or "")
    return file.replace(UTILS_SOURCE_VERSION, version)


def artifact_sources(
    artifact: dict, version: str, *, hub_version: str = HUB_VERSION, sites=None
) -> list:
    """Every address that serves one artifact, filled in.

    ``{file}`` is the artifact's file and ``{version}`` the version
    installed; a source naming ``{release}`` becomes one address per release
    site the hub's build stamped, at the release the hub came from, and none
    in a checkout.

    Args:
        artifact: The artifact.
        version: The version installed.
        hub_version: The hub's own version, the release ``{release}`` names.
        sites: The stamped sites; None reads this hub's stamp.

    Returns:
        The addresses, in the manifest's order.
    """
    file = artifact_file(artifact, version)
    filled = []
    for source in artifact.get("sources") or []:
        text = str(source).replace(UTILS_SOURCE_FILE, file)
        text = text.replace(UTILS_SOURCE_VERSION, version)
        if UTILS_SOURCE_RELEASE in text:
            filled += [
                text.replace(UTILS_SOURCE_RELEASE, address)
                for address in release_addresses(hub_version, sites=sites)
            ]
        else:
            filled.append(text)
    return filled


def module_recipe(entry: "dict | None") -> dict:
    """The recipe the state carries for one module on one machine.

    Args:
        entry: The module's entry for the machine's platform.

    Returns:
        ``{runner, method, params}``: the params without ``releases``, each
        artifact the agent takes from the package stream without its file
        and sources, and an ``npm`` or ``image`` artifact with its sources;
        empty for no entry.
    """
    if not isinstance(entry, dict):
        return {}
    method = entry_method(entry)
    params = {
        key: value for key, value in entry_params(entry).items() if key != "releases"
    }
    if "artifacts" in params:
        params["artifacts"] = [_recipe_artifact(item) for item in params["artifacts"]]
    return {
        "runner": str(entry.get("runner", "") or ""),
        "method": method,
        "params": params,
    }


def manifest_methods(manifest: dict) -> list:
    """Every method a manifest's entries name, in entry order.

    Args:
        manifest: The module's manifest.

    Returns:
        The methods, each once.
    """
    methods = []
    for entry in (manifest.get("platforms") or {}).values():
        method = entry_method(entry)
        if method and method not in methods:
            methods.append(method)
    return methods


def manifests_stamp() -> tuple:
    """A cheap fingerprint of the manifest files, for cache keys.

    Returns:
        A tuple that changes whenever a manifest is added, removed or edited.
    """
    if not MANIFESTS_DIR.is_dir():
        return ()
    entries = []
    for path in sorted(MANIFESTS_DIR.glob("*.json")):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((path.name, stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def _recipe_artifact(artifact: dict) -> dict:
    """One artifact as the recipe carries it."""
    kind = artifact.get("kind")
    if kind in (DEVICE_ARTIFACT_KIND_NPM, DEVICE_ARTIFACT_KIND_IMAGE):
        return dict(artifact)
    return {key: artifact[key] for key in RECIPE_FILE_ARTIFACT_KEYS if key in artifact}


def _read_manifests() -> list:
    """Every manifest file, parsed, as ``(path, manifest)``.

    Raises:
        ValueError: For a file that is not a JSON object.
    """
    if not MANIFESTS_DIR.is_dir():
        return []
    read = []
    for path in sorted(MANIFESTS_DIR.glob("*.json")):
        try:
            manifest = strip_comments(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            raise ValueError(f"manifest {path.name}: {error}") from error
        if not isinstance(manifest, dict):
            raise ValueError(f"manifest {path.name}: must be an object")
        read.append((path, manifest))
    return read


def _display_order(pair: tuple) -> tuple:
    """Where one ``(name, manifest)`` sorts: by its first method's rank, then title."""
    name, manifest = pair
    rank = min(DEVICE_METHOD_RANKS[method] for method in manifest_methods(manifest))
    return rank, str(manifest.get("title", name)).lower()


def _refuse(file_name: str, where: str, what: str) -> None:
    """Raise the loader's refusal for one part of one manifest.

    Raises:
        ValueError: Always.
    """
    named = f"{file_name}: {where}" if where else file_name
    raise ValueError(f"manifest {named} {what}")


def _check_keys(file_name: str, where: str, held: dict, allowed: set, required: set):
    """Refuse a mapping holding a key outside ``allowed`` or lacking one of ``required``.

    Raises:
        ValueError: Naming the first stray or missing key.
    """
    if not isinstance(held, dict):
        _refuse(file_name, where, "must be an object")
    stray = sorted(set(held) - allowed)
    if stray:
        _refuse(file_name, where, f"names {', '.join(stray)}, which it may not")
    missing = sorted(required - set(held))
    if missing:
        _refuse(file_name, where, f"must name {', '.join(missing)}")


def _check_text(file_name: str, where: str, value, *, pattern: str = "") -> None:
    """Refuse a value that is not a string that is not empty, or not of a pattern.

    Raises:
        ValueError: Naming the value.
    """
    if not isinstance(value, str) or not value:
        _refuse(file_name, where, "must be a string that is not empty")
    if pattern and not re.fullmatch(pattern, value):
        _refuse(file_name, where, f"is not of the form {pattern}, not {value!r}")


def _check_texts(file_name: str, where: str, value, *, is_empty_allowed=True) -> None:
    """Refuse a value that is not a list of strings that are not empty.

    Raises:
        ValueError: Naming the list.
    """
    if not isinstance(value, list) or (not value and not is_empty_allowed):
        _refuse(file_name, where, "must be a list of strings")
    for item in value:
        _check_text(file_name, where, item)


def _check_identity(file_name: str, manifest: dict, *, is_licensed: bool) -> None:
    """Refuse a manifest whose identity is missing or not shaped.

    Raises:
        ValueError: Naming the field.
    """
    for field in ("name", "title", "description", "publisher"):
        _check_text(file_name, field, manifest.get(field))
    if manifest["name"] != file_name.removesuffix(".json"):
        _refuse(file_name, "name", "must be the file's own name")
    for field in ("license", "corresponding_source"):
        if is_licensed or field in manifest:
            _check_text(file_name, field, manifest.get(field))
    if "is_data_forward_only" in manifest and not isinstance(
        manifest["is_data_forward_only"], bool
    ):
        _refuse(file_name, "is_data_forward_only", "must be true or false")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        _refuse(file_name, "platforms", "must name at least one platform")
    for key in platforms:
        system = key.split("-", 1)[0]
        if not re.fullmatch(MANIFEST_PLATFORM_PATTERN, key) or (
            system not in DEVICE_PLATFORM_OS
        ):
            _refuse(file_name, f"platform {key}", "is no platform key")


def _check_module(file_name: str, manifest: dict) -> None:
    """Refuse a module manifest outside the shapes of module_install.md.

    Raises:
        ValueError: Naming the file, the place and what is wrong.
    """
    _check_keys(file_name, "", manifest, MODULE_KEYS, {"platforms"})
    platforms = manifest.get("platforms")
    is_licensed = isinstance(platforms, dict) and any(
        entry_method(entry) in DEVICE_METHODS_WITH_LICENSE
        for entry in platforms.values()
        if isinstance(entry, dict)
    )
    _check_identity(file_name, manifest, is_licensed=is_licensed)
    if "uninstall_data" in manifest:
        _check_uninstall_data(file_name, manifest)
    for key, entry in platforms.items():
        where = f"platform {key}"
        _check_keys(file_name, where, entry, ENTRY_KEYS, {"runner", "install"})
        _check_text(file_name, f"{where} runner", entry["runner"])
        if "min_version" in entry:
            _check_text(
                file_name,
                f"{where} min_version",
                entry["min_version"],
                pattern=MANIFEST_VERSION_PATTERN,
            )
        install = entry["install"]
        _check_keys(
            file_name,
            f"{where} install",
            install,
            {"method", "params"},
            {"method", "params"},
        )
        method = install["method"]
        if method not in PARAMS_REQUIRED:
            _refuse(
                file_name, f"{where} method", f"is no install method, not {method!r}"
            )
        _check_params(file_name, where, method, install["params"])


def _check_uninstall_data(file_name: str, manifest: dict) -> None:
    """Refuse an ``uninstall_data`` of another shape, or one that disagrees with the entries.

    Raises:
        ValueError: For keys outside ``{is_deleted, text}``, a line missing in
            a language of the panel, or ``is_deleted`` against what an entry's
            method or ``is_data_kept`` says.
    """
    held = manifest["uninstall_data"]
    _check_keys(
        file_name, "uninstall_data", held, UNINSTALL_DATA_KEYS, UNINSTALL_DATA_KEYS
    )
    if not isinstance(held["is_deleted"], bool):
        _refuse(file_name, "uninstall_data is_deleted", "must be true or false")
    _check_keys(
        file_name,
        "uninstall_data text",
        held["text"],
        UNINSTALL_DATA_LANGUAGES,
        UNINSTALL_DATA_LANGUAGES,
    )
    for language in UNINSTALL_DATA_LANGUAGES:
        _check_text(
            file_name, f"uninstall_data text {language}", held["text"][language]
        )
    for key, entry in manifest["platforms"].items():
        install = entry.get("install") if isinstance(entry, dict) else None
        method = install.get("method") if isinstance(install, dict) else None
        params = install.get("params") if isinstance(install, dict) else None
        removal = params.get("uninstall") if isinstance(params, dict) else None
        is_deleted = method == DEVICE_METHOD_CONTAINER or (
            method == DEVICE_METHOD_HUB
            and isinstance(removal, dict)
            and removal.get("is_data_kept") is False
        )
        if method != DEVICE_METHOD_AGENT and held["is_deleted"] != is_deleted:
            _refuse(
                file_name,
                "uninstall_data is_deleted",
                f"disagrees with platform {key}",
            )


def _check_params(file_name: str, where: str, method: str, params) -> None:
    """Refuse ``params`` outside the shape their method fixes.

    Raises:
        ValueError: Naming the place and what is wrong.
    """
    required = PARAMS_REQUIRED[method]
    allowed = required | PARAMS_OPTIONAL.get(method, set())
    _check_keys(file_name, f"{where} params", params, allowed, required)
    if method in (DEVICE_METHOD_AGENT, DEVICE_METHOD_BUILTIN):
        return
    if method == DEVICE_METHOD_SYSTEM and params["version"] != DEVICE_SYSTEM_VERSION:
        _refuse(file_name, f"{where} version", "of a system entry must be system")
    _check_text(file_name, f"{where} version", params["version"])
    for field in ("packages", "pre_install"):
        if field in params:
            _check_texts(file_name, f"{where} {field}", params[field])
    if "verify" in required:
        _check_text(file_name, f"{where} verify", params["verify"])
    if method in UNINSTALL_KEYS:
        keys = UNINSTALL_KEYS[method]
        removal = params["uninstall"]
        _check_keys(file_name, f"{where} uninstall", removal, keys, keys)
        for field in ("packages", "post_uninstall"):
            if field in keys:
                _check_texts(file_name, f"{where} uninstall {field}", removal[field])
        if "is_data_kept" in keys and not isinstance(removal["is_data_kept"], bool):
            _refuse(file_name, f"{where} is_data_kept", "must be true or false")
    if "releases" in params:
        feeds = params["releases"]
        if not isinstance(feeds, list) or not feeds:
            _refuse(file_name, f"{where} releases", "must list at least one feed")
        for feed in feeds:
            _check_feed(file_name, f"{where} releases", feed)
    if "source_sets" in params:
        sets = params["source_sets"]
        _check_texts(file_name, f"{where} source_sets", sets)
        defined = load_source_sets()
        for name in sets:
            if name not in defined:
                _refuse(file_name, f"{where} source_sets", f"names no set, {name!r}")
    if "artifacts" in required:
        kinds = (
            (DEVICE_ARTIFACT_KIND_IMAGE,)
            if method == DEVICE_METHOD_CONTAINER
            else DEVICE_ARTIFACT_FILE_KINDS + (DEVICE_ARTIFACT_KIND_NPM,)
        )
        _check_artifacts(file_name, where, params["artifacts"], kinds)


def _check_feed(file_name: str, where: str, feed) -> None:
    """Refuse a feed whose kind is unknown or whose keys are not its kind's.

    Raises:
        ValueError: Naming the feed.
    """
    kind = feed.get("kind") if isinstance(feed, dict) else None
    if kind not in DEVICE_FEED_KEYS:
        _refuse(file_name, where, f"names a feed of no known kind, {kind!r}")
    keys = {"kind", "sources"} | set(DEVICE_FEED_KEYS[kind])
    _check_keys(file_name, f"{where} {kind}", feed, keys, keys)
    _check_texts(
        file_name, f"{where} {kind} sources", feed["sources"], is_empty_allowed=False
    )
    for key in DEVICE_FEED_KEYS[kind]:
        _check_text(file_name, f"{where} {kind} {key}", feed[key])


def _check_artifacts(file_name: str, where: str, artifacts, kinds: tuple) -> None:
    """Refuse an artifact list the cache, Podman or npm could not act on.

    Raises:
        ValueError: For an empty list, an artifact of a kind the method does
            not take, a key outside its kind's, a digest not of its kind's
            form, a source that does not name the file, or two artifacts
            sharing a name or a directory.
    """
    if not isinstance(artifacts, list) or not artifacts:
        _refuse(file_name, f"{where} artifacts", "must list at least one artifact")
    names: set = set()
    directories: set = set()
    for artifact in artifacts:
        kind = artifact.get("kind") if isinstance(artifact, dict) else None
        if kind not in kinds:
            _refuse(
                file_name, f"{where} artifacts", f"names an artifact of kind {kind!r}"
            )
        _check_text(file_name, f"{where} artifact name", artifact.get("name"))
        named = f"{where} artifact {artifact['name']}"
        if artifact["name"] in names:
            _refuse(file_name, named, "is named twice")
        names.add(artifact["name"])
        if kind == DEVICE_ARTIFACT_KIND_NPM:
            _check_keys(
                file_name,
                named,
                artifact,
                NPM_ARTIFACT_KEYS,
                NPM_ARTIFACT_KEYS - {"hosts"},
            )
            _check_text(file_name, f"{named} package", artifact["package"])
            _check_text(
                file_name,
                f"{named} digest",
                artifact["digest"],
                pattern=MANIFEST_INTEGRITY_PATTERN,
            )
            if artifact["source_set"] != DEVICE_ARTIFACT_KIND_NPM:
                _refuse(file_name, f"{named} source_set", "must be the npm set")
            if artifact["source_set"] not in load_source_sets():
                _refuse(file_name, f"{named} source_set", "names no set")
            for setting, hosts in (artifact.get("hosts") or {}).items():
                _check_texts(
                    file_name, f"{named} hosts {setting}", hosts, is_empty_allowed=False
                )
            continue
        if kind == DEVICE_ARTIFACT_KIND_IMAGE:
            _check_keys(
                file_name, named, artifact, IMAGE_ARTIFACT_KEYS, IMAGE_ARTIFACT_KEYS
            )
        else:
            required = FILE_ARTIFACT_KEYS - {"directory", "member"}
            if kind in DEVICE_ARTIFACT_DIRECTORY_KINDS:
                required = FILE_ARTIFACT_KEYS - {"member"}
            allowed = FILE_ARTIFACT_KEYS - {"member"}
            if kind == "binary":
                allowed = FILE_ARTIFACT_KEYS - {"directory", "member"}
            if kind == DEVICE_ARTIFACT_KIND_DMG:
                required = required | {"member"}
                allowed = FILE_ARTIFACT_KEYS
            _check_keys(file_name, named, artifact, allowed, required)
            _check_text(file_name, f"{named} file", artifact["file"])
            if "member" in artifact:
                _check_text(
                    file_name,
                    f"{named} member",
                    artifact["member"],
                    pattern=r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*",
                )
                if ".." in artifact["member"].split("/"):
                    _refuse(file_name, f"{named} member", "must stay inside the image")
            if "directory" in artifact:
                directory = artifact["directory"]
                _check_text(
                    file_name, f"{named} directory", directory, pattern=r"[a-z0-9_]+"
                )
                if directory in directories:
                    _refuse(
                        file_name, named, f"unpacks into {directory!r} beside another"
                    )
                directories.add(directory)
        _check_text(
            file_name,
            f"{named} digest",
            artifact["digest"],
            pattern=MANIFEST_SHA256_PATTERN,
        )
        _check_texts(
            file_name, f"{named} sources", artifact["sources"], is_empty_allowed=False
        )
        if kind != DEVICE_ARTIFACT_KIND_IMAGE:
            for source in artifact["sources"]:
                if UTILS_SOURCE_FILE not in source:
                    _refuse(
                        file_name,
                        f"{named} source",
                        f"must name {{file}}, not {source!r}",
                    )


def _check_tool(file_name: str, manifest: dict) -> None:
    """Refuse a tool manifest outside the shape module_install.md fixes for it.

    Raises:
        ValueError: Naming the file, the place and what is wrong.
    """
    _check_keys(
        file_name,
        "",
        manifest,
        TOOL_KEYS,
        {"platforms", "version", "is_module", "license", "corresponding_source"},
    )
    _check_identity(file_name, manifest, is_licensed=True)
    _check_text(file_name, "version", manifest["version"])
    for key, entry in manifest["platforms"].items():
        where = f"platform {key}"
        _check_keys(file_name, where, entry, {"artifacts"}, {"artifacts"})
        _check_artifacts(
            file_name, where, entry["artifacts"], DEVICE_ARTIFACT_FILE_KINDS
        )
