"""Composing the catalog a device's page reads, behind a cache.

The catalog has two halves under one hash: the modules, and the typed service
list. Both are resolved for the machine that asked: every payload host
becomes the address that device reaches in the scope its socket arrived
from, and each module's manifest becomes the one entry that device's
platform matches, which :func:`resolve_platform_entry` picks.

The composed copy is kept per scope and platform, and dropped whole
whenever the manifests or the list move.
"""

import hashlib
import json

from neutrino_hub.modules.channel.constants import (
    CHANNEL_MODULE_PRESENT_STATES,
    CHANNEL_MODULE_STATE_FAILED,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_KIND_PROGRAM,
    DEVICE_KIND_SERVICE,
    DEVICE_METHOD_AGENT,
    DEVICE_METHOD_BUILTIN,
    DEVICE_METHOD_CONTAINER,
    DEVICE_METHOD_HUB,
    DEVICE_METHOD_SYSTEM,
    DEVICE_METHODS_WITH_LICENSE,
    DEVICE_PROGRAM_MODULE_COPY_KEY,
    DEVICE_SOURCE_AGENT,
    DEVICE_SOURCE_CONTAINER,
    DEVICE_SOURCE_SYSTEM,
    DEVICE_SOURCE_UPSTREAM,
    DEVICE_SOURCE_USER,
)
from neutrino_hub.modules.devices.module_table import command_line_program_names
from neutrino_hub.modules.devices.manifests import (
    entry_method,
    entry_version,
    load_module_manifests,
    manifests_stamp,
    module_recipe,
    resolve_platform_entry,
)
from neutrino_hub.modules.services.collector import catalog_entries
from neutrino_hub.modules.services.host_scope import HostScope
from neutrino_hub.utils.constants import UTILS_SOURCE_VERSION


def resolve_module(manifest: dict, platform: dict) -> dict:
    """One manifest, reduced to what one machine needs of it.

    Args:
        manifest: The module's manifest.
        platform: The tuple the agent reported.

    Returns:
        ``{title, description, publisher, runner, method, version, license,
        corresponding_source, platform_key, recipe}`` for the entry the
        platform resolves to; the licence and the source address, its
        version filled in, only for a ``hub`` or ``container`` entry; empty
        runner, method and recipe where the manifest names no entry for the
        platform.
    """
    platform_key, entry = resolve_platform_entry(manifest, platform)
    method = entry_method(entry)
    version = entry_version(manifest, entry)
    is_licensed = method in DEVICE_METHODS_WITH_LICENSE
    source = str(manifest.get("corresponding_source", "") or "")
    return {
        "title": str(manifest.get("title", "") or manifest.get("name", "")),
        "description": str(manifest.get("description", "") or ""),
        "publisher": str(manifest.get("publisher", "") or ""),
        "runner": str((entry or {}).get("runner", "") or ""),
        "method": method,
        "version": version,
        "license": str(manifest.get("license", "") or "") if is_licensed else "",
        "corresponding_source": (
            source.replace(UTILS_SOURCE_VERSION, version) if is_licensed else ""
        ),
        "platform_key": platform_key,
        "recipe": module_recipe(entry),
    }


# The source chip's word each install method reads as.
SOURCE_OF_METHOD = {
    DEVICE_METHOD_AGENT: DEVICE_SOURCE_AGENT,
    DEVICE_METHOD_BUILTIN: DEVICE_SOURCE_SYSTEM,
    DEVICE_METHOD_SYSTEM: DEVICE_SOURCE_SYSTEM,
    DEVICE_METHOD_HUB: DEVICE_SOURCE_UPSTREAM,
    DEVICE_METHOD_CONTAINER: DEVICE_SOURCE_CONTAINER,
}
# The states in which a command line program's copies are on the machine,
# whichever copy each account runs.
PROGRAM_COPY_STATES = CHANNEL_MODULE_PRESENT_STATES + (CHANNEL_MODULE_STATE_FAILED,)


def module_source(module: str, method: str, state: str, details: dict) -> str:
    """The source chip's word of one module on one machine.

    Args:
        module: The module.
        method: The install method of its entry for the machine's platform;
            empty where the platform has no entry.
        state: The module's state as last reported.
        details: The ``details`` the machine last reported for it.

    Returns:
        ``agent``, ``system``, ``upstream`` or ``container`` by the method;
        ``user`` for a command line program the machine has while its report
        holds no copy of the module's own; empty for no entry.
    """
    source = SOURCE_OF_METHOD.get(method, "")
    if (
        module in command_line_program_names()
        and state in PROGRAM_COPY_STATES
        and details.get(DEVICE_PROGRAM_MODULE_COPY_KEY) is False
    ):
        return DEVICE_SOURCE_USER
    return source


def module_kind(module: str) -> str:
    """The kind chip's word of one module.

    Args:
        module: The module.

    Returns:
        ``program`` for a command line program, which has no Start or Stop;
        ``service`` for every other module.
    """
    if module in command_line_program_names():
        return DEVICE_KIND_PROGRAM
    return DEVICE_KIND_SERVICE


def resolved_modules(platform: dict) -> dict:
    """Every module, each resolved for one machine's platform.

    Args:
        platform: The tuple the agent reported.

    Returns:
        Module name to its resolved form, in the loader's order.
    """
    return {
        name: resolve_module(manifest, platform)
        for name, manifest in load_module_manifests().items()
    }


class DeviceCatalogCache:
    """Composes and hashes the catalog, per scope and platform."""

    def __init__(self, *, services):
        """
        Args:
            services: The shared
                :class:`neutrino_hub.modules.services.published.PublishedServiceCache`.
        """
        self._services = services
        self._stamp: tuple | None = None
        self._by_key: dict[tuple, tuple[dict, str]] = {}

    def catalog(self, *, scope: HostScope, platform: dict | None = None) -> tuple:
        """The catalog and its hash for one device, recomposed when stale.

        Args:
            scope: The scope the device's socket arrived from.
            platform: The tuple the device reported, which decides which
                entry each module resolves to.

        Returns:
            ``({"modules", "services"}, hash)``.
        """
        _, fingerprint = self._services.entries()
        stamp = (manifests_stamp(), fingerprint)
        if stamp != self._stamp:
            self._by_key = {}
            self._stamp = stamp
        platform = platform or {}
        key = (
            scope,
            str(platform.get("os", "")),
            str(platform.get("family", "")),
            str(platform.get("arch", "")),
            str(platform.get("version", "")),
        )
        held = self._by_key.get(key)
        if held is None:
            composed = {
                "modules": resolved_modules(platform),
                "services": catalog_entries(self._services.entries_for(scope)),
            }
            serialized = json.dumps(composed, sort_keys=True).encode("utf-8")
            held = (composed, hashlib.sha256(serialized).hexdigest()[:16])
            self._by_key[key] = held
        return held
