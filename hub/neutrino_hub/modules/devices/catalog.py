"""Composing the catalog a heartbeat answers with, behind a cache.

The catalog has two halves under one hash: the modules, and the typed service
list. Both are resolved for the machine that asked — a payload host that is
the hub's own becomes the address that device reaches, and each module's
manifest becomes the one entry that device's platform matches. **The agent is
handed conclusions, never a table to search**, which is what lets it carry no
manifest logic at all.

The composed copy is kept per resolved host and platform, and dropped whole
whenever the manifests or the list move: an agent beats every few seconds,
and recomposing on each beat would be waste.
"""

import hashlib
import json

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_SWITCHER_MANIFEST,
    CLIPROXYAPI_SWITCHER_NAME,
)
from neutrino_hub.modules.devices.agent_module_cache import (
    AgentModuleCache,
    resolve_platform_entry,
)
from neutrino_hub.modules.devices.manifests import (
    load_module_manifests,
    manifests_stamp,
)
from neutrino_hub.modules.services.collector import catalog_entries
from neutrino_hub.modules.services.constants import SERVICES_TYPE_AI


def resolve_module(manifest: dict, platform: dict) -> dict:
    """One manifest, reduced to what one machine needs of it.

    Args:
        manifest: The module's manifest.
        platform: The tuple the agent reported.

    Returns:
        The module's title and kind, plus the entry, verify command and
        package name for this platform. ``entry`` is None where the manifest
        offers this platform nothing, which is the machine's whole basis for
        reporting the module unsupported.
    """
    platform_key, entry = resolve_platform_entry(manifest, platform)
    os_name = str(platform.get("os", "")) if platform else ""
    resolved = entry if entry is not None else {}
    return {
        "title": manifest.get("title", manifest.get("name", "")),
        "description": manifest.get("description", ""),
        "kind": manifest.get("kind", ""),
        "is_builtin": bool(manifest.get("is_builtin")),
        "has_activation": bool(manifest.get("has_activation")),
        "platform_key": platform_key,
        "entry": entry,
        "verify": str(manifest.get("verify", {}).get(os_name, "") or ""),
        "package": str(resolved.get("package", "") or manifest.get("name", "")),
    }


def resolved_modules(platform: dict) -> dict:
    """Every module, each resolved for one machine's platform.

    Args:
        platform: The tuple the agent reported.

    Returns:
        Module name to its resolved form.
    """
    return {
        name: resolve_module(manifest, platform)
        for name, manifest in sorted(load_module_manifests().items())
    }


def artifact_sources() -> dict:
    """Every artifact this hub can fetch for a machine, by name.

    The modules a device can be told to install, plus the cc-switch command
    line the AI service needs. One list, because a managed machine receives
    software one way and this is it.

    Returns:
        Name to manifest.
    """
    sources = dict(load_module_manifests())
    sources[CLIPROXYAPI_SWITCHER_NAME] = CLIPROXYAPI_SWITCHER_MANIFEST
    return sources


def with_switcher_artifact(entries: list, platform: dict) -> list:
    """Name the cc-switch artifact in the ai entry, for one platform.

    The machine still decides which accounts it points at the hub and what
    their tools are configured with; only the getting of the binary is the
    hub's, which is what leaves the agent with nothing to download.

    Args:
        entries: The composed service entries.
        platform: The tuple the device reported.

    Returns:
        The entries, the ai one carrying the key its machine asks for the
        binary by. A platform with no cc-switch build gets no block, which
        is how the machine knows there is none.
    """
    _, entry = resolve_platform_entry(CLIPROXYAPI_SWITCHER_MANIFEST, platform)
    if entry is None:
        return entries
    key = AgentModuleCache().artifact_key(
        name=CLIPROXYAPI_SWITCHER_NAME,
        manifest=CLIPROXYAPI_SWITCHER_MANIFEST,
        platform=platform,
    )
    resolved = []
    for service in entries:
        if service.get("type") != SERVICES_TYPE_AI:
            resolved.append(service)
            continue
        payload = dict(service.get("payload", {}))
        payload["switcher"] = {
            "artifact_key": key,
            "binary": entry.get("binary", ""),
            "package_kind": entry.get("package_kind", ""),
        }
        resolved.append({**service, "payload": payload})
    return resolved


class DeviceCatalogCache:
    """Composes and hashes the catalog, per device-reachable host and platform."""

    def __init__(self, *, services):
        """
        Args:
            services: The shared
                :class:`neutrino_hub.modules.services.published.PublishedServiceCache`.
        """
        self._services = services
        self._stamp: tuple | None = None
        self._by_key: dict[tuple, tuple[dict, str]] = {}

    def catalog(self, *, device_host: str, platform: dict | None = None) -> tuple:
        """The catalog and its hash for one device, recomposed when stale.

        Args:
            device_host: The address the device reaches the hub on.
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
            device_host,
            str(platform.get("os", "")),
            str(platform.get("family", "")),
            str(platform.get("arch", "")),
        )
        held = self._by_key.get(key)
        if held is None:
            composed = {
                "modules": resolved_modules(platform),
                "services": with_switcher_artifact(
                    catalog_entries(self._services.entries_for(device_host)), platform
                ),
            }
            serialized = json.dumps(composed, sort_keys=True).encode("utf-8")
            held = (composed, hashlib.sha256(serialized).hexdigest()[:16])
            self._by_key[key] = held
        return held
