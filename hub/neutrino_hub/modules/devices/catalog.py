"""Composing the catalog a heartbeat answers with, behind a cache.

The catalog has two halves under one hash: the module manifests, and the
typed service list. A payload host that is the hub's own resolves to the
address the asking device reaches, so the composed copy is kept per resolved
host and dropped whole whenever the manifests or the list move — an agent
beats every few seconds, and recomposing on each beat would be waste.
"""

import hashlib
import json

from neutrino_hub.modules.devices.manifests import (
    load_module_manifests,
    manifests_stamp,
)
from neutrino_hub.modules.services.collector import catalog_entries


class DeviceCatalogCache:
    """Composes and hashes the catalog, per device-reachable host."""

    def __init__(self, *, services):
        """
        Args:
            services: The shared
                :class:`neutrino_hub.modules.services.published.PublishedServiceCache`.
        """
        self._services = services
        self._stamp: tuple | None = None
        self._by_host: dict[str, tuple[dict, str]] = {}

    def catalog(self, *, device_host: str) -> tuple[dict, str]:
        """The catalog and its hash for one device, recomposed when stale.

        Args:
            device_host: The address the device reaches the hub on.

        Returns:
            ``({"modules", "services"}, hash)``.
        """
        _, fingerprint = self._services.entries()
        stamp = (manifests_stamp(), fingerprint)
        if stamp != self._stamp:
            self._by_host = {}
            self._stamp = stamp
        held = self._by_host.get(device_host)
        if held is None:
            composed = {
                "modules": load_module_manifests(),
                "services": catalog_entries(self._services.entries_for(device_host)),
            }
            serialized = json.dumps(composed, sort_keys=True).encode("utf-8")
            held = (composed, hashlib.sha256(serialized).hexdigest()[:16])
            self._by_host[device_host] = held
        return held
