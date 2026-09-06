"""Gathering and caching the published service list.

The collector is pure; this is the half that reads — the configs, the unit
states, the podman survey, the gateway's served models, the declared-service
probes — and keeps the composed list for a short while, because the Services
page polls it and every heartbeat reads it. One list feeds both, under one
fingerprint.
"""

import hashlib
import json
import time

import httpx

from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_AUTH_RELATIVE,
    CLIPROXYAPI_BINARY_PATH,
)
from neutrino_hub.modules.cliproxyapi.ops import load_config as load_cliproxyapi_config
from neutrino_hub.modules.credentials.vault import VaultError
from neutrino_hub.modules.gitea.config import GiteaConfig
from neutrino_hub.modules.podman.ops import PodmanStatusReader
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

    def __init__(self, *, declared_probe, served_models, units, device_shares=None):
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
        """
        self._declared_probe = declared_probe
        self._served_models = served_models
        self._units = units
        self._device_shares = device_shares
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

    def refresh(self) -> None:
        """Compose the list now, replacing the cache whole."""
        declared = DeclaredServiceRegistry().list_records()
        healths = {
            health.service_id: health
            for health in self._declared_probe.results(declared)
        }
        lan_addresses = self._lan_addresses()
        hub_host = lan_addresses[0] if lan_addresses else "127.0.0.1"
        self._hub_addresses = hub_self_addresses(lan_addresses)

        gitea = self._unit("gitea")
        samba = self._unit("samba")
        cliproxyapi = self._unit("cliproxyapi")
        podman = self._unit("podman")

        gitea_url = self._gitea_url(hub_host)
        is_ai_served = self._is_ai_served()
        ai_port, ai_models, is_ai_healthy = self._ai_state(cliproxyapi.is_active)

        entries = ServiceListCollector(
            hub_host=hub_host,
            is_gitea_served=_is_served(gitea),
            gitea_url=gitea_url,
            is_gitea_healthy=gitea.is_active and self._is_answering(gitea_url),
            is_samba_served=_is_served(samba),
            samba_share_names=self._samba_share_names(),
            is_samba_healthy=samba.is_active,
            is_ai_served=is_ai_served,
            ai_port=ai_port,
            ai_models=ai_models,
            is_ai_healthy=is_ai_healthy,
            is_podman_served=_is_served(podman),
            podman_containers=(
                PodmanStatusReader().survey(declared_names=[])
                if _is_served(podman)
                else []
            ),
            declared_services=declared,
            declared_healths=healths,
            device_shares=(
                self._device_shares.live() if self._device_shares is not None else []
            ),
        ).render()

        self._entries = entries
        serialized = json.dumps(entries, sort_keys=True).encode("utf-8")
        self._fingerprint = hashlib.sha256(serialized).hexdigest()[:16]
        self._refreshed_at = time.monotonic()

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

    def _samba_share_names(self) -> list[str]:
        try:
            data = json_file.read_config("samba/samba.json")
        except (FileNotFoundError, ValueError):
            return []
        return [
            str(share.get("name", ""))
            for share in data.get("shares", [])
            if share.get("name")
        ]

    def _gitea_url(self, hub_host: str) -> str:
        try:
            config = GiteaConfig.from_dict(json_file.read_config("gitea/gitea.json"))
        except (FileNotFoundError, ValueError):
            config = GiteaConfig()
        if config.root_url:
            return config.root_url
        return f"http://{hub_host}:{config.listen_port}/"

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


def _is_served(status) -> bool:
    """Whether a module counts as installed and enabled."""
    return status.is_installed and (status.is_enabled or status.is_active)


__all__ = ["PublishedServiceCache"]
