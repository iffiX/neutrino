"""Gathering and caching the published service list.

The collector is pure; this is the half that reads: the configs, the
agents' last reports, the gateway's served models, the declared-service
probes. It keeps the composed list for a short while, because the Services
page polls it and every device catalog reads it. One list feeds both,
under one fingerprint.
"""

import concurrent.futures
import hashlib
import json
import threading
import time

import httpx

from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_AUTH_RELATIVE,
    CLIPROXYAPI_BINARY_PATH,
)
from neutrino_hub.modules.cliproxyapi.ops import load_config as load_cliproxyapi_config
from neutrino_hub.modules.credentials.vault import VaultError
from neutrino_hub.modules.devices.constants import DEVICE_MODULE_NAMES
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.router import link_status
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.services.collector import (
    ServiceListCollector,
    hub_self_addresses,
    resolve_entries,
)
from neutrino_hub.modules.services.config import DeclaredServiceRegistry
from neutrino_hub.modules.services.constants import (
    SERVICES_ANSWER_TIMEOUT_S,
    SERVICES_LIST_TTL_S,
)
from neutrino_hub.utils import constants as utils_constants
from neutrino_hub.utils import json_file


class PublishedServiceCache:
    """Composes the published service list and keeps it for a short while."""

    def __init__(
        self,
        *,
        declared_probe,
        served_models,
        units,
        device_shares=None,
        agent_sessions=None,
        device_addresses=None,
        desired_states=None,
        on_fingerprint_change=None,
        executor=None,
    ):
        """
        Args:
            declared_probe: The shared
                :class:`neutrino_hub.modules.services.probe.DeclaredServiceProbe`.
            served_models: The shared
                :class:`neutrino_hub.modules.cliproxyapi.ops.CliproxyApiServedModelCache`.
            units: The shared
                :class:`neutrino_hub.system.systemd_ctl.SystemdServiceController`.
            device_shares: The shared
                :class:`neutrino_hub.modules.services.device_shares.DeviceShareRegistry`;
                None publishes no desktop shares.
            agent_sessions: The shared
                :class:`neutrino_hub.modules.devices.agent_sessions.AgentSessionRegistry`,
                whose reports say which device hosts what; None publishes
                no device-hosted entries.
            device_addresses: Device key to the address its channel comes
                from, the runtime's own mapping.
            desired_states: The :class:`DesiredStateStore` the shares are
                read from; None builds one.
            on_fingerprint_change: Called with nothing when a refresh
                composes a different list; None tells nobody.
            executor: The single-thread executor a scheduled recompose runs
                on; None builds one.
        """
        self._declared_probe = declared_probe
        self._served_models = served_models
        self._units = units
        self._device_shares = device_shares
        self._agent_sessions = agent_sessions
        self._device_addresses = (
            device_addresses if device_addresses is not None else {}
        )
        self._desired_states = (
            desired_states if desired_states is not None else DesiredStateStore()
        )
        self._on_fingerprint_change = on_fingerprint_change
        self._executor = (
            executor
            if executor is not None
            else concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="published_services"
            )
        )
        self._refresh_lock = threading.Lock()
        self._is_refreshing = False
        self._is_refresh_pending = False
        self._entries: list[dict] = []
        self._fingerprint = ""
        self._hub_addresses: set[str] = set()
        # None, not zero: `time.monotonic()` counts from boot on Linux, and a
        # panel started early in one would read the cache as fresh.
        self._refreshed_at: float | None = None

    def entries(self) -> tuple[list[dict], str]:
        """The published entries and their fingerprint, refreshed when stale.

        Returns:
            ``(entries, fingerprint)``; the fingerprint moves whenever the
            composed list changes.
        """
        if (
            self._refreshed_at is None
            or time.monotonic() - self._refreshed_at > SERVICES_LIST_TTL_S
        ):
            self.refresh()
        return list(self._entries), self._fingerprint

    def entries_for(self, target_host: str) -> list[dict]:
        """The entries with the hub's own hosts resolved for one caller.

        Args:
            target_host: The address the caller reaches the hub on.

        Returns:
            The resolved entries.
        """
        entries, _ = self.entries()
        return resolve_entries(
            entries, hub_addresses=self._hub_addresses, target_host=target_host
        )

    def expire(self) -> None:
        """Make the next read recompose, after a declaration or probe."""
        self._refreshed_at = None

    def schedule_refresh(self) -> None:
        """Compose the list again, off the calling thread.

        Safe to call from an event loop. A schedule made while a recompose
        runs is answered by one more run after it, however many arrive.
        """
        with self._refresh_lock:
            if self._is_refreshing:
                self._is_refresh_pending = True
                return
            self._is_refreshing = True
        self._executor.submit(self._refresh_until_settled)

    def refresh(self) -> None:
        """Compose the list now, replacing the cache whole."""
        declared = DeclaredServiceRegistry().list_records()
        healths = {
            health.service_id: health
            for health in self._declared_probe.results(declared)
        }
        lan_addresses = self._lan_addresses()
        own_addresses = self._own_addresses()
        # Composed with the address most devices are on, then rewritten per
        # caller to whatever that one actually reached the hub at. The
        # composed value only shows through where a caller reaches the box on
        # nothing the box knows it holds.
        hub_host = (lan_addresses or own_addresses or ["127.0.0.1"])[0]
        self._hub_addresses = hub_self_addresses(own_addresses)

        cliproxyapi = self._unit("cliproxyapi")
        is_ai_served = self._is_ai_served()
        ai_port, ai_models, is_ai_healthy = self._ai_state(cliproxyapi.is_active)

        entries = ServiceListCollector(
            hub_host=hub_host,
            is_ai_served=is_ai_served,
            ai_port=ai_port,
            ai_models=ai_models,
            is_ai_healthy=is_ai_healthy,
            device_modules=self._device_modules(),
            declared_services=declared,
            declared_healths=healths,
            device_shares=(
                self._device_shares.live() if self._device_shares is not None else []
            ),
        ).render()

        previous = self._fingerprint
        self._entries = entries
        serialized = json.dumps(entries, sort_keys=True).encode("utf-8")
        self._fingerprint = hashlib.sha256(serialized).hexdigest()[:16]
        self._refreshed_at = time.monotonic()
        if self._fingerprint != previous and self._on_fingerprint_change is not None:
            self._on_fingerprint_change()

    def _refresh_until_settled(self) -> None:
        """Refresh, then once more for whatever was asked for meanwhile."""
        while True:
            try:
                self.refresh()
            finally:
                with self._refresh_lock:
                    is_pending = self._is_refresh_pending
                    self._is_refresh_pending = False
                    self._is_refreshing = is_pending
            if not is_pending:
                return

    def _unit(self, name: str):
        return self._units.status(name)

    def _lan_addresses(self) -> list[str]:
        try:
            network = RouterNetworkConfig.from_dict(
                json_file.read_config("router/network.json")
            )
        except (FileNotFoundError, ValueError):
            return []
        return [
            interface.lan.address
            for interface in network.lan_interfaces
            if interface.lan.address
        ]

    def _own_addresses(self) -> list[str]:
        """Every address this box can be reached at, served ones first.

        What makes an entry the hub's own rather than some machine's it was
        told about, so a device that came in over an overlay is handed the
        overlay's address and not the LAN one it cannot route to.

        Returns:
            Addresses without their prefixes, in no particular order beyond
            the served networks coming first.
        """
        served = self._lan_addresses()
        live = [
            address.split("/")[0] for address in link_status.device_addresses().values()
        ]
        return served + [address for address in live if address not in served]

    def _device_modules(self) -> list:
        """What every online device hosts, from its last report.

        Returns:
            One entry per device whose report names a hosted module, each
            ``{"device_id", "host", "samba", "gitea", "podman"}``.
        """
        if self._agent_sessions is None:
            return []
        devices = []
        for key, report in self._agent_sessions.reports().items():
            modules = report.get("modules") if isinstance(report, dict) else {}
            modules = modules if isinstance(modules, dict) else {}
            host = str(self._device_addresses.get(key, "") or "")
            entry = {"device_id": key, "host": host}
            for name in DEVICE_MODULE_NAMES:
                entry[name] = self._hosted(key, name, modules.get(name))
            if any(entry[name] for name in DEVICE_MODULE_NAMES):
                devices.append(entry)
        return devices

    def _hosted(self, key: str, name: str, status) -> "dict | None":
        """One device's module as the list needs it, None while not served."""
        if not isinstance(status, dict) or status.get("state") != "installed":
            return None
        if not self._desired_states.is_enabled(key, name):
            return None
        details = (
            status.get("details") if isinstance(status.get("details"), dict) else {}
        )
        if name == "samba":
            shares = self._desired_states.read(key, "samba").get("shares", [])
            return {
                "is_healthy": bool(details.get("is_active")),
                "share_names": [
                    str(share.get("name", ""))
                    for share in shares
                    if isinstance(share, dict) and share.get("name")
                ],
            }
        if name == "gitea":
            url = str(details.get("url", "") or "")
            return {
                "is_healthy": bool(details.get("is_running"))
                and self._is_answering(url),
                "url": url,
            }
        if name == "podman":
            return {
                "containers": [
                    {
                        "name": str(container.get("name", "")),
                        "image": str(container.get("image", "")),
                        "is_running": bool(container.get("is_running")),
                        "host_ports": [
                            int(port) for port in container.get("host_ports") or []
                        ],
                    }
                    for container in details.get("containers") or []
                    if isinstance(container, dict) and container.get("name")
                ]
            }
        return None

    def _is_answering(self, url: str) -> bool:
        if not url:
            return False
        try:
            response = httpx.get(
                url, timeout=SERVICES_ANSWER_TIMEOUT_S, follow_redirects=True
            )
        except httpx.HTTPError:
            return False
        return response.status_code < 500

    def _is_ai_served(self) -> bool:
        """Whether the gateway has anything to serve a device with.

        Returns:
            True when the binary is on the box and at least one enabled
            keyed provider or one signed-in account feeds it.
        """
        if not CLIPROXYAPI_BINARY_PATH.is_file():
            return False
        for provider in AiProviderRegistry().list_records():
            if provider.is_enabled and provider.secret_id:
                return True
        auth_dir = utils_constants.UTILS_STATE_ROOT / CLIPROXYAPI_AUTH_RELATIVE
        if not auth_dir.is_dir():
            return False
        return any(path.suffix == ".json" for path in auth_dir.iterdir())

    def _ai_state(self, is_active: bool) -> tuple[int, list[str], bool]:
        """The gateway's port, served models and health.

        With no client key to probe with, the unit's own state is the health
        and the model list stays empty.

        Returns:
            ``(port, models, is_healthy)``.
        """
        config = load_cliproxyapi_config()
        key = None
        for stored in config.client_keys:
            try:
                key = stored.open_key()
                break
            except VaultError:
                continue
        if key is None or not is_active:
            return config.listen_port, [], is_active
        is_answered, models = self._served_models.served(
            port=config.listen_port, client_key=key
        )
        return config.listen_port, models, is_answered


__all__ = ["PublishedServiceCache"]
