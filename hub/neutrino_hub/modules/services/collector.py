"""Composing the typed service list the hub publishes.

Every entry is ``{id, type, title, payload, is_healthy, source, description,
record_id, detail_code}`` with five types: web, port, ai, file, rdp. An
entry a device's module declares exists only while that device's agent
reports the module serving and carries the module's own health; manual
declarations carry their probe results; an rdp entry is a managed machine's
own word that it is sharing its desktop, and lives only while that machine
keeps saying so. ``record_id`` names the declared record an entry came
from, for the panel's delete and probe, and ``detail_code`` is what that
record's last probe measured; the catalog copy drops both.

Pure: everything composed comes in through the constructor. Reading the
configs, the reports and the probe caches is the caller's.
"""

from urllib.parse import urlsplit, urlunsplit

from neutrino_hub.modules.services.config import DeclaredService
from neutrino_hub.modules.services.constants import (
    SERVICES_AI_DESCRIPTION,
    SERVICES_AI_ID,
    SERVICES_AI_PROTOCOL,
    SERVICES_AI_TITLE,
    SERVICES_FILE_PROTOCOL,
    SERVICES_GITEA_DESCRIPTION,
    SERVICES_GITEA_ID,
    SERVICES_GITEA_TITLE,
    SERVICES_HUB_SELF_HOSTS,
    SERVICES_KIND_GENERIC_TCP,
    SERVICES_KIND_HTTP,
    SERVICES_KIND_SAMBA,
    SERVICES_PODMAN_DESCRIPTION,
    SERVICES_RDP_DESCRIPTION,
    SERVICES_RDP_PROTOCOL,
    SERVICES_SAMBA_DESCRIPTION,
    SERVICES_SOURCE_DECLARED,
    SERVICES_SOURCE_DEVICE,
    SERVICES_SOURCE_MODULE,
    SERVICES_TYPE_AI,
    SERVICES_TYPE_FILE,
    SERVICES_TYPE_PORT,
    SERVICES_TYPE_RDP,
    SERVICES_TYPE_WEB,
)

# The entry fields the device catalog carries; the rest is the panel's.
CATALOG_ENTRY_FIELDS = (
    "id",
    "type",
    "title",
    "payload",
    "is_healthy",
    "source",
    "description",
)


class ServiceListCollector:
    """Renders every entry the hub currently publishes."""

    def __init__(
        self,
        *,
        hub_host: str,
        is_ai_served: bool,
        ai_port: int,
        ai_models: list[str],
        is_ai_healthy: bool,
        device_modules: list,
        declared_services: list[DeclaredService],
        declared_healths: dict,
        device_shares: list | None = None,
    ):
        """
        Args:
            hub_host: The address the hub's own entries name; resolved per
                caller by :func:`resolve_entries`.
            is_ai_served: Whether the AI gateway is installed and enabled.
            ai_port: The port the gateway listens on.
            ai_models: The model names the gateway really serves.
            is_ai_healthy: Whether the gateway answers.
            device_modules: One entry per device hosting modules:
                ``{"device_id", "host", "samba", "gitea", "podman"}`` where
                each module is None when the device does not serve it,
                else ``samba: {"is_healthy", "share_names"}``,
                ``gitea: {"is_healthy", "url"}`` and
                ``podman: {"containers": [{"name", "image", "is_running",
                "host_ports"}]}``.
            declared_services: Every declared service.
            declared_healths: Declared record id to its
                :class:`neutrino_hub.modules.services.probe.DeclaredServiceHealth`;
                a record never probed is absent.
            device_shares: The live
                :class:`neutrino_hub.modules.services.device_shares.DeviceShare`
                declarations.
        """
        self._hub_host = hub_host
        self._is_ai_served = is_ai_served
        self._ai_port = ai_port
        self._ai_models = ai_models
        self._is_ai_healthy = is_ai_healthy
        self._device_modules = list(device_modules)
        self._declared_services = declared_services
        self._declared_healths = declared_healths
        self._device_shares = device_shares or []

    def render(self) -> list[dict]:
        """Every published entry, module entries first, in type order.

        Returns:
            The composed list; every entry carries the same fields.
        """
        entries = []
        entries += self._web_entries()
        entries += self._port_entries()
        entries += self._ai_entries()
        entries += self._file_entries()
        entries += self._rdp_entries()
        return entries

    def _rdp_entries(self) -> list[dict]:
        """One entry per machine that says it is sharing its desktop."""
        return [
            _entry(
                id=f"rdp_{share.share_id}",
                type=SERVICES_TYPE_RDP,
                title=share.hostname or share.host,
                payload={
                    "protocol": SERVICES_RDP_PROTOCOL,
                    "host": share.host,
                    "port": share.port,
                    "attention": share.attention,
                },
                is_healthy=True,
                description=SERVICES_RDP_DESCRIPTION.format(
                    hostname=share.hostname or share.host
                ),
                source=SERVICES_SOURCE_DEVICE,
            )
            for share in self._device_shares
        ]

    def _web_entries(self) -> list[dict]:
        entries = []
        for device in self._device_modules:
            gitea = device.get("gitea")
            if not gitea or not gitea.get("url"):
                continue
            entries.append(
                _entry(
                    id=f"{SERVICES_GITEA_ID}_{_device_id(device)}",
                    type=SERVICES_TYPE_WEB,
                    title=SERVICES_GITEA_TITLE,
                    payload={"url": gitea["url"]},
                    is_healthy=bool(gitea.get("is_healthy")),
                    description=SERVICES_GITEA_DESCRIPTION.format(
                        host=device.get("host", "")
                    ),
                )
            )
        for record in self._declared_of(SERVICES_KIND_HTTP):
            url = f"{record.scheme}://{record.host}:{record.port}{record.path or '/'}"
            is_healthy, detail_code = self._declared_health(record.id)
            entries.append(
                _entry(
                    id=record.id,
                    type=SERVICES_TYPE_WEB,
                    title=record.name,
                    payload={"url": url},
                    is_healthy=is_healthy,
                    description=record.description,
                    record_id=record.id,
                    detail_code=detail_code,
                )
            )
        return entries

    def _port_entries(self) -> list[dict]:
        entries = []
        for device in self._device_modules:
            podman = device.get("podman")
            host = device.get("host", "")
            if not podman or not host:
                continue
            for container in podman.get("containers") or []:
                for port in container.get("host_ports") or []:
                    entries.append(
                        _entry(
                            id=f"podman_{_device_id(device)}_{container['name']}_{port}",
                            type=SERVICES_TYPE_PORT,
                            title=container["name"],
                            payload={"host": host, "port": port},
                            is_healthy=bool(container.get("is_running")),
                            description=SERVICES_PODMAN_DESCRIPTION.format(
                                name=container["name"],
                                image=container.get("image", ""),
                                host=host,
                            ),
                        )
                    )
        for record in self._declared_of(SERVICES_KIND_GENERIC_TCP):
            is_healthy, detail_code = self._declared_health(record.id)
            entries.append(
                _entry(
                    id=record.id,
                    type=SERVICES_TYPE_PORT,
                    title=record.name,
                    payload={"host": record.host, "port": record.port},
                    is_healthy=is_healthy,
                    description=record.description,
                    record_id=record.id,
                    detail_code=detail_code,
                )
            )
        return entries

    def _ai_entries(self) -> list[dict]:
        if not self._is_ai_served or not self._hub_host:
            return []
        return [
            _entry(
                id=SERVICES_AI_ID,
                type=SERVICES_TYPE_AI,
                title=SERVICES_AI_TITLE,
                payload={
                    "endpoint": f"http://{self._hub_host}:{self._ai_port}",
                    "protocol": SERVICES_AI_PROTOCOL,
                    "models": list(self._ai_models),
                },
                is_healthy=self._is_ai_healthy,
                description=SERVICES_AI_DESCRIPTION,
            )
        ]

    def _file_entries(self) -> list[dict]:
        entries = []
        for device in self._device_modules:
            samba = device.get("samba")
            host = device.get("host", "")
            if not samba or not host:
                continue
            for name in samba.get("share_names") or []:
                entries.append(
                    _entry(
                        id=f"samba_{_device_id(device)}_{name}",
                        type=SERVICES_TYPE_FILE,
                        title=name,
                        payload={
                            "protocol": SERVICES_FILE_PROTOCOL,
                            "host": host,
                            "share": name,
                        },
                        is_healthy=bool(samba.get("is_healthy")),
                        description=SERVICES_SAMBA_DESCRIPTION.format(host=host),
                    )
                )
        for record in self._declared_of(SERVICES_KIND_SAMBA):
            is_healthy, detail_code = self._declared_health(record.id)
            for share in record.shares:
                entries.append(
                    _entry(
                        id=f"{record.id}_{share.name}",
                        type=SERVICES_TYPE_FILE,
                        title=share.name,
                        payload={
                            "protocol": SERVICES_FILE_PROTOCOL,
                            "host": record.host,
                            "share": share.name,
                        },
                        is_healthy=is_healthy,
                        description=record.description,
                        record_id=record.id,
                        detail_code=detail_code,
                    )
                )
        return entries

    def _declared_of(self, kind: str) -> list[DeclaredService]:
        return [r for r in self._declared_services if r.kind == kind]

    def _declared_health(self, record_id: str) -> tuple[bool | None, str | None]:
        health = self._declared_healths.get(record_id)
        if health is None:
            return None, None
        return health.is_healthy, health.detail_code


def hub_self_addresses(hub_addresses: list[str]) -> set[str]:
    """The hosts that mean the hub itself for one composition.

    Args:
        hub_addresses: Every address the hub holds.

    Returns:
        Those plus the loopback spellings.
    """
    return set(SERVICES_HUB_SELF_HOSTS) | {a for a in hub_addresses if a}


def resolve_entries(
    entries: list[dict], *, hub_addresses: set[str], target_host: str
) -> list[dict]:
    """Substitute the hub's own payload hosts with the address one caller reaches.

    A host outside the hub's own set is somebody else's machine, a NAS a
    person declared or a device hosting a module, and is never rewritten;
    a module hosted on the hub box's own agent sits at a hub address and
    resolves like the hub's own entries.

    Args:
        entries: The composed entries.
        hub_addresses: Every host that means the hub itself.
        target_host: The address the caller reaches the hub on.

    Returns:
        A new list; a payload host outside the hub's own set is untouched.
    """
    resolved = []
    for entry in entries:
        payload = dict(entry["payload"])
        if entry["type"] == SERVICES_TYPE_WEB:
            payload["url"] = _resolve_url(payload["url"], hub_addresses, target_host)
        elif entry["type"] == SERVICES_TYPE_AI:
            payload["endpoint"] = _resolve_url(
                payload["endpoint"], hub_addresses, target_host
            )
        elif payload.get("host") in hub_addresses:
            payload["host"] = target_host
        resolved.append({**entry, "payload": payload})
    return resolved


def catalog_entries(entries: list[dict]) -> list[dict]:
    """The entries as the device catalog carries them.

    Args:
        entries: The composed entries.

    Returns:
        The same list without the panel-only fields.
    """
    return [{key: entry[key] for key in CATALOG_ENTRY_FIELDS} for entry in entries]


def _device_id(device: dict) -> str:
    """One device's key as it appears inside an entry id."""
    return str(device.get("device_id", "")).lower().replace(":", "-")


def _entry(
    *,
    id: str,
    type: str,
    title: str,
    payload: dict,
    is_healthy: bool | None,
    description: str,
    record_id: str | None = None,
    detail_code: str | None = None,
    source: str = "",
) -> dict:
    return {
        "id": id,
        "type": type,
        "title": title,
        "payload": payload,
        "is_healthy": is_healthy,
        "source": source
        or (SERVICES_SOURCE_DECLARED if record_id else SERVICES_SOURCE_MODULE),
        "description": description,
        "record_id": record_id,
        "detail_code": detail_code,
    }


def _resolve_url(url: str, hub_addresses: set[str], target_host: str) -> str:
    parts = urlsplit(url)
    hostname = parts.hostname
    if hostname is None or hostname not in hub_addresses:
        return url
    netloc = target_host if parts.port is None else f"{target_host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
