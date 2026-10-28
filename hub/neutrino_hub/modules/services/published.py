"""Gathering and caching the published apps and the service list.

The collector is pure; this is the half that reads: the configs, the
agents' last reports, the gateway's served models, the declared apps'
probes. It keeps the composed list for a short while, because the Services
page polls it and every device catalog reads it. One list feeds both,
under one fingerprint.
"""

import concurrent.futures
import hashlib
import json
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_AUTH_RELATIVE,
    CLIPROXYAPI_BINARY_PATH,
)
from neutrino_hub.modules.cliproxyapi.ops import load_config as load_cliproxyapi_config
from neutrino_hub.modules.channel.constants import (
    CHANNEL_MODULE_CONFIGURED_WANTS,
    CHANNEL_MODULE_STATE_RUNNING,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_AYAKALEAF_MODULE,
    DEVICE_HERMES_WEBUI_MODULE,
    DEVICE_MODULE_NAMES,
    DEVICE_SAMBA_MODULE,
    DEVICE_SSH_SERVER_MODULE,
)
from neutrino_hub.modules.devices.desired_state import DesiredStateStore, smb_user
from neutrino_hub.modules.devices.folder_shares import folder_shares
from neutrino_hub.modules.devices.module_table import account_program_names
from neutrino_hub.modules.router import link_status
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.services.apps import machine_slugs, slug
from neutrino_hub.modules.services.collector import (
    ServiceListCollector,
    hub_self_addresses,
    resolve_entries,
)
from neutrino_hub.modules.services.config import DeclaredAppRegistry
from neutrino_hub.modules.services.constants import (
    SERVICES_CONTAINER_AUTO,
    SERVICES_CONTAINER_WEB,
    SERVICES_HTTP_SCHEMES,
    SERVICES_LIST_TTL_S,
    SERVICES_MACHINE_SLUG_FALLBACK,
    SERVICES_PORT_PROTOCOLS,
    SERVICES_PROTOCOL_TCP,
    SERVICES_SOURCE_DECLARED,
    SERVICES_SOURCE_MANUAL,
)
from neutrino_hub.modules.services.host_scope import HostScope, device_host_for
from neutrino_hub.utils import constants as utils_constants
from neutrino_hub.utils import json_file

# The owner a reported container carries when a container module runs it.
CONTAINER_SOURCE_HUB = "hub"


def gitea_url(details: dict) -> str:
    """Gitea's URL as a device reports it, at the port its server listens on.

    Args:
        details: The Gitea row's ``details``: ``url`` from ``ROOT_URL`` and
            ``port``, the server's ``HTTP_PORT``.

    Returns:
        The URL with the listen port in place of any port it named, which is
        the port the agent's end of a ``connect`` stream dials; the URL as
        reported when either part is missing.
    """
    url = str(details.get("url", "") or "")
    port = details.get("port")
    parts = urlsplit(url)
    if not parts.hostname or not isinstance(port, int) or isinstance(port, bool):
        return url
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return urlunsplit(
        (parts.scheme, f"{host}:{port}", parts.path, parts.query, parts.fragment)
    )


class PublishedServiceCache:
    """Composes the published apps and entries and keeps them for a short while."""

    def __init__(
        self,
        *,
        declared_probe,
        served_models,
        units,
        device_shares=None,
        agent_sessions=None,
        device_addresses=None,
        device_interfaces=None,
        desired_states=None,
        device_names=None,
        hub_name=None,
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
            agent_sessions: The shared session registry, whose reports say
                which device hosts what; None publishes no device-hosted
                entries.
            device_addresses: Device id to the address its session comes
                from, the runtime's own mapping.
            device_interfaces: Device id to the interfaces its agent last
                reported, the runtime's own mapping; a device absent here
                is at its session's address in every scope.
            desired_states: The :class:`DesiredStateStore` the enabled
                accounts are read from; None builds one.
            device_names: Returns device id to what the hub calls the
                machine, for every stored device; None names none.
            hub_name: Returns the hub's own name; None is the fallback slug.
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
        self._device_interfaces = (
            device_interfaces if device_interfaces is not None else {}
        )
        self._desired_states = (
            desired_states if desired_states is not None else DesiredStateStore()
        )
        self._device_names = device_names
        self._hub_name = hub_name
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
        self._entries: list = []
        self._apps: list = []
        self._fingerprint = ""
        self._hub_addresses: set = set()
        # None, not zero: `time.monotonic()` counts from boot on Linux, and a
        # panel started early in one would read the cache as fresh.
        self._refreshed_at: float | None = None

    def entries(self) -> tuple:
        """The published entries and their fingerprint, refreshed when stale.

        Returns:
            ``(entries, fingerprint)``; the fingerprint moves whenever the
            composed list changes.
        """
        self._refresh_if_stale()
        return list(self._entries), self._fingerprint

    def apps(self) -> list:
        """The apps the published entries belong to, refreshed when stale.

        Returns:
            One ``{id, title, source, device_id, device_name, local_name,
            description}`` per app.
        """
        self._refresh_if_stale()
        return [dict(app) for app in self._apps]

    def entries_for(self, scope: HostScope) -> list:
        """The entries resolved for one caller's scope.

        Every device's entry names the address that device has in the
        scope, and the hub's own entries name the hub's address there.

        Args:
            scope: The caller's scope.

        Returns:
            The resolved entries.
        """
        entries, _ = self.entries()
        device_hosts = {}
        for entry in entries:
            device_id = str(entry.get("device_id") or "")
            if device_id and device_id not in device_hosts:
                device_hosts[device_id] = device_host_for(
                    scope,
                    self._device_interfaces.get(device_id, []),
                    str(self._device_addresses.get(device_id, "") or ""),
                )
        return resolve_entries(
            entries,
            device_hosts=device_hosts,
            hub_addresses=self._hub_addresses,
            hub_host=scope.hub_address,
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
        declared = DeclaredAppRegistry().list_apps()
        healths = self._declared_probe.results(declared)
        lan_addresses = self._lan_addresses()
        own_addresses = self._own_addresses()
        # Composed with the address most devices are on, then rewritten per
        # caller by :meth:`entries_for`. The composed value only shows
        # through where a caller's scope names no hub address.
        hub_host = (lan_addresses or own_addresses or ["127.0.0.1"])[0]
        self._hub_addresses = hub_self_addresses(own_addresses)

        cliproxyapi = self._unit("cliproxyapi")
        is_ai_served = self._is_ai_served()
        ai_port, ai_models, is_ai_healthy = self._ai_state(cliproxyapi.is_active)
        names = self._device_names() if self._device_names is not None else {}
        collector = ServiceListCollector(
            hub_host=hub_host,
            is_ai_served=is_ai_served,
            ai_port=ai_port,
            ai_models=ai_models,
            is_ai_healthy=is_ai_healthy,
            device_modules=self._device_modules(),
            declared_apps=declared,
            declared_healths=healths,
            device_shares=(
                self._device_shares.live() if self._device_shares is not None else []
            ),
            machine_slugs=machine_slugs(names),
            hub_slug=self._hub_slug(),
            device_ids_by_address={
                address: device_id
                for device_id, address in self._device_addresses.items()
                if address and device_id in names
            },
            device_names=names,
        )
        entries = collector.render()
        apps = collector.apps()

        previous = self._fingerprint
        self._entries = entries
        self._apps = apps
        serialized = json.dumps([entries, apps], sort_keys=True).encode("utf-8")
        self._fingerprint = hashlib.sha256(serialized).hexdigest()[:16]
        self._refreshed_at = time.monotonic()
        if self._fingerprint != previous and self._on_fingerprint_change is not None:
            self._on_fingerprint_change()

    def _refresh_if_stale(self) -> None:
        if (
            self._refreshed_at is None
            or time.monotonic() - self._refreshed_at > SERVICES_LIST_TTL_S
        ):
            self.refresh()

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

    def _hub_slug(self) -> str:
        """The slug of the hub's own name, the fallback when it does not read."""
        if self._hub_name is None:
            return SERVICES_MACHINE_SLUG_FALLBACK
        try:
            return slug(str(self._hub_name() or ""), SERVICES_MACHINE_SLUG_FALLBACK)
        except (FileNotFoundError, ValueError):
            return SERVICES_MACHINE_SLUG_FALLBACK

    def _lan_addresses(self) -> list:
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

    def _own_addresses(self) -> list:
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
            ``{"device_id", "host"}`` and one key per module of
            :data:`DEVICE_MODULE_NAMES`.
        """
        if self._agent_sessions is None:
            return []
        devices = []
        for key, report in self._agent_sessions.reports().items():
            modules = report.get("modules") if isinstance(report, dict) else {}
            modules = modules if isinstance(modules, dict) else {}
            host = str(self._device_addresses.get(key, "") or "")
            platform = _platform_of(report)
            entry = {"device_id": key, "host": host}
            for name in DEVICE_MODULE_NAMES:
                entry[name] = self._hosted(key, name, modules.get(name), platform)
            if any(entry[name] for name in DEVICE_MODULE_NAMES):
                devices.append(entry)
        return devices

    def _hosted(self, key: str, name: str, status, platform: dict) -> "dict | None":
        """One device's module as the list needs it, None while not served.

        An instance of an account-layer module is listed only while the
        device reports it running, at the port the agent took, Hermes WebUI
        and Ayakaleaf only while the device reports the module running, and an SSH server
        instance while the module enables its account. Gitea listens on the
        device's loopback alone, so its health is the device's word that
        the server runs.
        """
        if not isinstance(status, dict):
            return None
        if status.get("state") not in CHANNEL_MODULE_CONFIGURED_WANTS:
            return None
        if name == DEVICE_SSH_SERVER_MODULE:
            return self._hosted_ssh_server(key, status)
        if (
            self._desired_states.want_of(key, name)
            not in CHANNEL_MODULE_CONFIGURED_WANTS
        ):
            return None
        details = (
            status.get("details") if isinstance(status.get("details"), dict) else {}
        )
        if name in (DEVICE_HERMES_WEBUI_MODULE, DEVICE_AYAKALEAF_MODULE):
            if status.get("state") != CHANNEL_MODULE_STATE_RUNNING:
                return None
            port = details.get("port")
            if not isinstance(port, int) or isinstance(port, bool) or port <= 0:
                return None
            return {"port": port, "is_healthy": True}
        if name == DEVICE_SAMBA_MODULE:
            enabled = self._desired_states.enabled_accounts(key, name)
            return {
                "is_healthy": bool(details.get("is_active")),
                "shares": [
                    {"name": account, "user": smb_user(account, platform)}
                    for account in enabled
                ],
                "folder_shares": [
                    {
                        "name": share["name"],
                        "accounts": [
                            {"account": account, "user": smb_user(account, platform)}
                            for account in share["accounts"]
                            if account in enabled
                        ],
                    }
                    for share in folder_shares(self._desired_states.read(key, name))
                ],
            }
        if name == "gitea":
            return {
                "is_healthy": bool(details.get("is_running")),
                "url": gitea_url(details),
                "ssh_listen_port": _port_of(details.get("ssh_listen_port")),
            }
        if name in account_program_names():
            return {"instances": self._running_instances(key, name, details)}
        if name == "podman":
            declared = {
                str(container.get("name", "")): container.get("services") or []
                for container in self._desired_states.read(key, "podman").get(
                    "containers"
                )
                or []
                if isinstance(container, dict)
            }
            containers = []
            for container in details.get("containers") or []:
                if not isinstance(container, dict) or not container.get("name"):
                    continue
                # A container module's page is its own entry, behind its
                # forwarder; its containers' ports give none.
                if container.get("module"):
                    continue
                container_name = str(container["name"])
                containers.append(
                    {
                        "name": container_name,
                        "image": str(container.get("image", "")),
                        "is_running": bool(container.get("is_running")),
                        "source": (
                            SERVICES_SOURCE_DECLARED
                            if container_name in declared
                            else SERVICES_SOURCE_MANUAL
                        ),
                        "bindings": container_bindings(
                            container, declared.get(container_name, [])
                        ),
                    }
                )
            return {"containers": containers}
        return None

    def _hosted_ssh_server(self, key: str, status: dict) -> "dict | None":
        """The SSH server's instances the module enables, as last reported,
        each with its account key's fingerprint."""
        details = (
            status.get("details") if isinstance(status.get("details"), dict) else {}
        )
        instances = self._running_instances(
            key, DEVICE_SSH_SERVER_MODULE, details, is_running_required=False
        )
        if not instances:
            return None
        for instance in instances:
            instance["account_key_fingerprint"] = (
                self._desired_states.account_key_fingerprint(key, instance["account"])
            )
        return {
            "host_key_fingerprint": str(details.get("host_key_fingerprint", "") or ""),
            "instances": instances,
        }

    def _running_instances(
        self, key: str, name: str, details: dict, *, is_running_required: bool = True
    ) -> list:
        """The enabled accounts' instances with the ports the agent reports.

        Args:
            key: The device.
            name: The module.
            details: The module's ``details`` as last reported.
            is_running_required: Whether an instance that does not run is
                left out.

        Returns:
            ``[{account, port, is_healthy}]`` in the enabled accounts' order,
            instances with no reported port left out.
        """
        reported = {
            str(instance.get("account", "")): instance
            for instance in details.get("instances") or []
            if isinstance(instance, dict)
        }
        instances = []
        for account in self._desired_states.enabled_accounts(key, name):
            seen = reported.get(account)
            if seen is None:
                continue
            port = _port_of(seen.get("port"))
            is_running = bool(seen.get("is_running"))
            if not port or (is_running_required and not is_running):
                continue
            instances.append(
                {"account": account, "port": port, "is_healthy": is_running}
            )
        return instances

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

    def _ai_state(self, is_active: bool) -> tuple:
        """The gateway's port, served models and health.

        With no key to probe with, which is a box that has never applied the
        gateway, the unit's own state is the health and the model list stays
        empty.

        Returns:
            ``(port, models, is_healthy)``.
        """
        config = load_cliproxyapi_config()
        key = config.probe_key()
        if key is None or not is_active:
            return config.listen_port, [], is_active
        is_answered, models = self._served_models.served(
            port=config.listen_port, client_key=key
        )
        return config.listen_port, models, is_answered


__all__ = ["PublishedServiceCache"]


def _platform_of(report) -> dict:
    """The platform tuple one report carries, empty when it carries none."""
    machine = report.get("machine") if isinstance(report, dict) else None
    platform = machine.get("platform") if isinstance(machine, dict) else None
    return dict(platform) if isinstance(platform, dict) else {}


def _port_of(value) -> int:
    """A reported port as an int, 0 for anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value > 0 else 0


def container_bindings(container: dict, services: list) -> list:
    """The entries the ports one container publishes give, once each.

    A TCP port is a ``web`` entry when its service is ``web``, or ``auto``
    with ``http`` or ``https`` detected, and a ``port`` entry otherwise; a
    UDP port is a ``port`` entry unless its service is ``web``.

    Args:
        container: One container of a Podman report's ``details``.
        services: The container's declared services, ``{port, kind,
            scheme, protocols}`` each; empty for a container the hub does
            not declare.

    Returns:
        ``(port, protocol, scheme)`` triples in the report's order, one per
        port and protocol of ``host_bindings``, a missing ``protocol`` read
        as ``tcp``, every ``host_ports`` number as ``tcp`` when the report
        has no ``host_bindings`` at all, as an agent before 0.5.0 sends it;
        ``scheme`` is ``http`` or ``https`` for a ``web`` entry and empty
        for a ``port`` entry.
    """
    kinds = {}
    for service in services:
        if not isinstance(service, dict):
            continue
        try:
            kinds[int(service.get("port") or 0)] = service
        except (TypeError, ValueError):
            continue
    bindings = container.get("host_bindings")
    if not isinstance(bindings, list):
        bindings = [{"port": port} for port in container.get("host_ports") or []]
    seen = set()
    triples = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        try:
            port = int(binding.get("port") or 0)
        except (TypeError, ValueError):
            continue
        protocol = str(binding.get("protocol") or SERVICES_PROTOCOL_TCP)
        if port <= 0 or protocol not in SERVICES_PORT_PROTOCOLS:
            continue
        if (port, protocol) in seen:
            continue
        seen.add((port, protocol))
        service = kinds.get(port, {})
        is_web = str(service.get("kind") or "") == SERVICES_CONTAINER_WEB
        if protocol != SERVICES_PROTOCOL_TCP:
            if not is_web:
                triples.append((port, protocol, ""))
            continue
        triples.append((port, protocol, _web_scheme(service, binding)))
    return triples


def _web_scheme(service: dict, binding: dict) -> str:
    """The scheme a container's TCP port is a ``web`` entry with, empty for a
    ``port`` entry."""
    kind = str(service.get("kind") or SERVICES_CONTAINER_AUTO)
    if kind == SERVICES_CONTAINER_WEB:
        scheme = str(service.get("scheme") or "")
        return scheme if scheme in SERVICES_HTTP_SCHEMES else SERVICES_HTTP_SCHEMES[0]
    if kind == SERVICES_CONTAINER_AUTO:
        detected = str(binding.get("detected") or "")
        return detected if detected in SERVICES_HTTP_SCHEMES else ""
    return ""
