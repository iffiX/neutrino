"""Composing the typed service list the hub publishes.

Every entry is ``{id, type, title, payload, is_healthy, source, description,
modules, record_id, detail_code}`` with four types — web, port, ai, file.
Module-declared entries exist only while their module serves and carry the
module's own health; manual declarations carry their probe results.
``modules`` names the device modules the entry cannot work without.
``record_id`` names the declared record an entry came from, for the panel's
delete and probe, and ``detail_code`` is what that record's last probe
measured; the catalog copy drops both.

Pure: everything composed comes in through the constructor. Reading the
configs, the unit states and the probe caches is the caller's.
"""

from urllib.parse import urlsplit, urlunsplit

from neutrino_hub.modules.services.config import DeclaredService
from neutrino_hub.modules.services.constants import (
    SERVICES_AI_DESCRIPTION,
    SERVICES_AI_ID,
    SERVICES_AI_MODULES,
    SERVICES_AI_PROTOCOL,
    SERVICES_AI_TITLE,
    SERVICES_FILE_MODULES,
    SERVICES_FILE_PROTOCOL,
    SERVICES_GITEA_DESCRIPTION,
    SERVICES_GITEA_ID,
    SERVICES_GITEA_TITLE,
    SERVICES_HUB_SELF_HOSTS,
    SERVICES_KIND_GENERIC_TCP,
    SERVICES_KIND_HTTP,
    SERVICES_KIND_SAMBA,
    SERVICES_PODMAN_DESCRIPTION,
    SERVICES_SAMBA_DESCRIPTION,
    SERVICES_SOURCE_DECLARED,
    SERVICES_SOURCE_MODULE,
    SERVICES_TYPE_AI,
    SERVICES_TYPE_FILE,
    SERVICES_TYPE_PORT,
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
    "modules",
)


class ServiceListCollector:
    """Renders every entry the hub currently publishes."""

    def __init__(
        self,
        *,
        hub_host: str,
        is_gitea_served: bool,
        gitea_url: str,
        is_gitea_healthy: bool,
        is_samba_served: bool,
        samba_share_names: list[str],
        is_samba_healthy: bool,
        is_ai_served: bool,
        ai_port: int,
        ai_models: list[str],
        is_ai_healthy: bool,
        is_podman_served: bool,
        podman_containers: list,
        declared_services: list[DeclaredService],
        declared_healths: dict,
    ):
        """
        Args:
            hub_host: The address the hub's own entries name; resolved per
                caller by :func:`resolve_entries`.
            is_gitea_served: Whether the gitea module is installed and enabled.
            gitea_url: The URL that opens it.
            is_gitea_healthy: Whether its unit runs and it answers.
            is_samba_served: Whether the samba module is installed and enabled.
            samba_share_names: The hub's own share names.
            is_samba_healthy: Whether its unit runs.
            is_ai_served: Whether the AI gateway is installed and enabled.
            ai_port: The port the gateway listens on.
            ai_models: The model names the gateway really serves.
            is_ai_healthy: Whether the gateway answers.
            is_podman_served: Whether the podman module is installed and
                enabled.
            podman_containers: The surveyed containers, each with ``name``,
                ``image``, ``is_running`` and ``host_ports``.
            declared_services: Every declared service.
            declared_healths: Declared record id to its
                :class:`neutrino_hub.modules.services.probe.DeclaredServiceHealth`;
                a record never probed is absent.
        """
        self._hub_host = hub_host
        self._is_gitea_served = is_gitea_served
        self._gitea_url = gitea_url
        self._is_gitea_healthy = is_gitea_healthy
        self._is_samba_served = is_samba_served
        self._samba_share_names = samba_share_names
        self._is_samba_healthy = is_samba_healthy
        self._is_ai_served = is_ai_served
        self._ai_port = ai_port
        self._ai_models = ai_models
        self._is_ai_healthy = is_ai_healthy
        self._is_podman_served = is_podman_served
        self._podman_containers = podman_containers
        self._declared_services = declared_services
        self._declared_healths = declared_healths

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
        return entries

    def _web_entries(self) -> list[dict]:
        entries = []
        if self._is_gitea_served and self._gitea_url:
            entries.append(
                _entry(
                    id=SERVICES_GITEA_ID,
                    type=SERVICES_TYPE_WEB,
                    title=SERVICES_GITEA_TITLE,
                    payload={"url": self._gitea_url},
                    is_healthy=self._is_gitea_healthy,
                    description=SERVICES_GITEA_DESCRIPTION,
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
        if self._is_podman_served and self._hub_host:
            for container in self._podman_containers:
                for port in container.host_ports:
                    entries.append(
                        _entry(
                            id=f"podman_{container.name}_{port}",
                            type=SERVICES_TYPE_PORT,
                            title=container.name,
                            payload={"host": self._hub_host, "port": port},
                            is_healthy=container.is_running,
                            description=SERVICES_PODMAN_DESCRIPTION.format(
                                name=container.name, image=container.image
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
        if self._is_samba_served and self._hub_host:
            for name in self._samba_share_names:
                entries.append(
                    _entry(
                        id=f"samba_{name}",
                        type=SERVICES_TYPE_FILE,
                        title=name,
                        payload={
                            "protocol": SERVICES_FILE_PROTOCOL,
                            "host": self._hub_host,
                            "share": name,
                        },
                        is_healthy=self._is_samba_healthy,
                        description=SERVICES_SAMBA_DESCRIPTION,
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

    Args:
        entries: The composed entries.
        hub_addresses: Every host that means the hub itself.
        target_host: The address the caller reaches the hub on.

    A module-declared entry is the hub's own by construction, so its host is
    resolved even when the composed address is not one the caller would
    recognize; a declared entry names any host and keeps the address-set
    guard, so a NAS a person declared is never rewritten. A ``web`` entry
    keeps the guard either way, so a Gitea reached through a custom URL is
    left as the administrator set it.

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
        is_hub_own = entry.get("source") == SERVICES_SOURCE_MODULE
        if entry["type"] == SERVICES_TYPE_WEB:
            payload["url"] = _resolve_url(payload["url"], hub_addresses, target_host)
        elif entry["type"] == SERVICES_TYPE_AI:
            payload["endpoint"] = _resolve_url(
                payload["endpoint"], hub_addresses, target_host, force=is_hub_own
            )
        elif is_hub_own or payload.get("host") in hub_addresses:
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
) -> dict:
    return {
        "id": id,
        "type": type,
        "title": title,
        "payload": payload,
        "is_healthy": is_healthy,
        "source": (SERVICES_SOURCE_DECLARED if record_id else SERVICES_SOURCE_MODULE),
        "description": description,
        "modules": list(_type_modules(type)),
        "record_id": record_id,
        "detail_code": detail_code,
    }


def _type_modules(type: str) -> tuple:
    """The device modules an entry of this type depends on."""
    if type == SERVICES_TYPE_AI:
        return SERVICES_AI_MODULES
    if type == SERVICES_TYPE_FILE:
        return SERVICES_FILE_MODULES
    return ()


def _resolve_url(
    url: str, hub_addresses: set[str], target_host: str, force: bool = False
) -> str:
    parts = urlsplit(url)
    hostname = parts.hostname
    if hostname is None:
        return url
    if not force and hostname not in hub_addresses:
        return url
    netloc = target_host if parts.port is None else f"{target_host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
