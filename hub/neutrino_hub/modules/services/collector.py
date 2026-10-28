"""Composing the apps and the typed service list the hub publishes.

Every entry is ``{id, type, title, payload, is_healthy, source, description,
description_code, description_params, detail_code, device_id, app_id, name,
local_port}`` with six types: web, port, ssh, ai, file, rdp. Every ``web``,
``port`` and ``ssh`` entry belongs to one app, ``{id, title, source,
device_id, device_name, local_name, description}``, and its id is ``<app
id>_<name>``; the ``ai`` and ``rdp`` entries and a machine's ``file`` entries
belong to none (protocol.md, "Apps"). ``description`` is the English
provenance line and ``description_code`` names the same provenance for a
page that words it itself, empty on a declared entry whose person wrote their
own. An entry a device's module declares exists only while that device's
agent reports the module serving and carries the module's own health; a
declared app's entries carry their probe results; an rdp entry is a managed
machine's own word that it is sharing its desktop, and lives only while that
machine keeps saying so. ``detail_code`` is what a declared entry's last
probe measured; the catalog copy drops it.

Pure: everything composed comes in through the constructor. Reading the
configs, the reports and the probe caches is the caller's.
"""

from urllib.parse import urlsplit, urlunsplit

from neutrino_hub.modules.devices.module_table import account_program_rows
from neutrino_hub.modules.services.apps import (
    app_slugs,
    entry_id,
    local_name,
    local_port,
)
from neutrino_hub.modules.services.config import DeclaredApp
from neutrino_hub.modules.services.constants import (
    SERVICES_AI_DESCRIPTION,
    SERVICES_AI_ID,
    SERVICES_AI_PROTOCOL,
    SERVICES_AI_TITLE,
    SERVICES_APP_ENTRY_TYPES,
    SERVICES_DESCRIPTION_AI_GATEWAY,
    SERVICES_DESCRIPTION_CONTAINER,
    SERVICES_DESCRIPTION_DECLARED,
    SERVICES_DESCRIPTION_DEVICE_SHARE,
    SERVICES_DESCRIPTION_GITEA_MODULE,
    SERVICES_DESCRIPTION_HERMES_WEBUI_MODULE,
    SERVICES_DESCRIPTION_SAMBA_MODULE,
    SERVICES_DESCRIPTION_SSH_SERVER_MODULE,
    SERVICES_ENTRY_SSH,
    SERVICES_ENTRY_WEB,
    SERVICES_FILE_PROTOCOL,
    SERVICES_GITEA_DESCRIPTION,
    SERVICES_GITEA_ID,
    SERVICES_GITEA_TITLE,
    SERVICES_HERMES_WEBUI_DESCRIPTION,
    SERVICES_HERMES_WEBUI_ID,
    SERVICES_HERMES_WEBUI_TITLE,
    SERVICES_HUB_SELF_HOSTS,
    SERVICES_INSTANCE_DESCRIPTION,
    SERVICES_MACHINE_SLUG_FALLBACK,
    SERVICES_PODMAN_DESCRIPTION,
    SERVICES_PROTOCOL_TCP,
    SERVICES_PROTOCOL_UDP,
    SERVICES_RDP_DESCRIPTION,
    SERVICES_RDP_PROTOCOL,
    SERVICES_SAMBA_DESCRIPTION,
    SERVICES_SOURCE_DECLARED,
    SERVICES_SOURCE_DEVICE,
    SERVICES_SOURCE_MANUAL,
    SERVICES_SOURCE_MODULE,
    SERVICES_SSH_SERVER_DESCRIPTION,
    SERVICES_SSH_SERVER_ID,
    SERVICES_SSH_SERVER_TITLE,
    SERVICES_TYPE_AI,
    SERVICES_TYPE_FILE,
    SERVICES_TYPE_PORT,
    SERVICES_TYPE_RDP,
    SERVICES_TYPE_SSH,
    SERVICES_TYPE_WEB,
    SERVICES_UDP_ID_SUFFIX,
)

# The entry fields the device catalog and a client's list carry; the rest is
# the panel's.
CATALOG_ENTRY_FIELDS = (
    "id",
    "type",
    "title",
    "payload",
    "is_healthy",
    "source",
    "description",
    "description_code",
    "description_params",
    "app_id",
    "name",
    "local_port",
)
# What a catalog field reads when an entry composed elsewhere leaves it out.
CATALOG_ENTRY_DEFAULTS = {
    "description": "",
    "description_code": "",
    "description_params": {},
    "app_id": "",
    "name": "",
    "local_port": 0,
}
# The module name the Containers module's apps and entries carry in their ids.
PODMAN_MODULE = "podman"


class ServiceListCollector:
    """Renders every app and every entry the hub currently publishes."""

    def __init__(
        self,
        *,
        hub_host: str,
        is_ai_served: bool,
        ai_port: int,
        ai_models: list,
        is_ai_healthy: bool,
        device_modules: list,
        declared_apps: list,
        declared_healths: dict,
        device_shares: "list | None" = None,
        machine_slugs: "dict | None" = None,
        hub_slug: str = SERVICES_MACHINE_SLUG_FALLBACK,
        device_ids_by_address: "dict | None" = None,
        device_names: "dict | None" = None,
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
                ``{"device_id", "host"}`` and one key per module, None when
                the device does not serve it, else ``samba: {"is_healthy",
                "shares": [{"name", "user"}]}``, ``gitea: {"is_healthy",
                "url", "ssh_listen_port"}``, each program run as an account
                under its name as ``{"instances": [{"account", "port",
                "is_healthy"}]}``, ``ssh_server: {"host_key_fingerprint",
                "instances": [{"account", "port", "is_healthy"}]}``,
                ``hermes_webui: {"port", "is_healthy"}`` and ``podman:
                {"containers": [{"name", "image", "is_running", "bindings",
                "source"}]}``, ``bindings`` being ``(port, protocol,
                scheme)`` triples, ``scheme`` naming a ``web`` entry's and
                empty for a ``port`` entry, and ``source`` ``declared`` or
                ``manual``.
            declared_apps: Every declared app.
            declared_healths: Entry id to its
                :class:`neutrino_hub.modules.services.probe.DeclaredEntryHealth`;
                an entry never probed is absent.
            device_shares: The live
                :class:`neutrino_hub.modules.services.device_shares.DeviceShare`
                declarations.
            machine_slugs: Device id to the slug of the machine's name, told
                apart as :func:`neutrino_hub.modules.services.apps.machine_slugs`
                tells them; a device absent here takes the fallback.
            hub_slug: The hub's own machine's slug, which an app no machine
                the hub knows provides takes.
            device_ids_by_address: Address to the device reached there, which
                a declared app at that address belongs to.
            device_names: Device id to what the hub calls the machine.
        """
        self._hub_host = hub_host
        self._is_ai_served = is_ai_served
        self._ai_port = ai_port
        self._ai_models = ai_models
        self._is_ai_healthy = is_ai_healthy
        self._device_modules = list(device_modules)
        self._declared_apps = declared_apps
        self._declared_healths = declared_healths
        self._device_shares = device_shares or []
        self._machine_slugs = dict(machine_slugs or {})
        self._hub_slug = hub_slug
        self._device_ids_by_address = dict(device_ids_by_address or {})
        self._device_names = dict(device_names or {})
        self._composed: "tuple | None" = None

    def render(self) -> list:
        """Every published entry, module entries first, in type order.

        Returns:
            The composed list; every entry carries the same fields.
        """
        return list(self._compose()[1])

    def apps(self) -> list:
        """Every app the ``web``, ``port`` and ``ssh`` entries belong to.

        Returns:
            The apps in the order their first entry is published.
        """
        return list(self._compose()[0])

    def _compose(self) -> tuple:
        if self._composed is not None:
            return self._composed
        apps: dict = {}
        entries = []
        for device in self._device_modules:
            entries += self._device_entries(device, apps)
        entries += self._declared_entries(apps)
        entries += self._ai_entries()
        entries += self._file_entries()
        entries += self._rdp_entries()
        self._name_apps(apps)
        for entry in entries:
            if entry["type"] in SERVICES_APP_ENTRY_TYPES:
                entry["local_port"] = local_port(entry["id"])
        ordered = sorted(entries, key=lambda entry: _TYPE_ORDER.index(entry["type"]))
        self._composed = (list(apps.values()), ordered)
        return self._composed

    def _device_entries(self, device: dict, apps: dict) -> list:
        """Every app entry one device's modules give."""
        device_id = _device_id(device)
        host = device.get("host", "")
        if not host:
            return []
        entries = []
        gitea = device.get("gitea")
        if gitea and gitea.get("url"):
            app_id = f"{SERVICES_GITEA_ID}_{device_id}"
            apps.setdefault(
                app_id,
                self._app(app_id, SERVICES_GITEA_TITLE, SERVICES_SOURCE_MODULE, device),
            )
            entries.append(
                self._app_entry(
                    app_id,
                    SERVICES_ENTRY_WEB,
                    type=SERVICES_TYPE_WEB,
                    title=SERVICES_GITEA_TITLE,
                    payload={"url": gitea["url"]},
                    is_healthy=bool(gitea.get("is_healthy")),
                    description=SERVICES_GITEA_DESCRIPTION.format(host=host),
                    description_code=SERVICES_DESCRIPTION_GITEA_MODULE,
                    description_params={"host": host},
                    device_id=device_id,
                )
            )
            if gitea.get("ssh_listen_port"):
                entries.append(
                    self._app_entry(
                        app_id,
                        SERVICES_ENTRY_SSH,
                        type=SERVICES_TYPE_PORT,
                        title=SERVICES_GITEA_TITLE,
                        payload={
                            "host": host,
                            "port": int(gitea["ssh_listen_port"]),
                            "protocol": SERVICES_PROTOCOL_TCP,
                        },
                        is_healthy=bool(gitea.get("is_healthy")),
                        description=SERVICES_GITEA_DESCRIPTION.format(host=host),
                        description_code=SERVICES_DESCRIPTION_GITEA_MODULE,
                        description_params={"host": host},
                        device_id=device_id,
                    )
                )
        for row in account_program_rows():
            hosted = device.get(row.name)
            if not hosted:
                continue
            for instance in hosted.get("instances") or []:
                account = instance["account"]
                app_id = f"{row.name}_{device_id}_{account}"
                title = row.entry_title.format(account=account)
                apps.setdefault(
                    app_id, self._app(app_id, title, SERVICES_SOURCE_MODULE, device)
                )
                entries.append(
                    self._app_entry(
                        app_id,
                        SERVICES_ENTRY_WEB,
                        type=SERVICES_TYPE_WEB,
                        title=title,
                        payload={
                            "url": f"http://{_url_host(host)}:{instance['port']}/",
                            "is_token_required": True,
                        },
                        is_healthy=bool(instance.get("is_healthy")),
                        description=SERVICES_INSTANCE_DESCRIPTION.format(
                            module=row.name, host=host, account=account
                        ),
                        description_code=row.description_code,
                        description_params={"host": host, "account": account},
                        device_id=device_id,
                    )
                )
        ssh_server = device.get("ssh_server")
        if ssh_server:
            app_id = f"{SERVICES_SSH_SERVER_ID}_{device_id}"
            fingerprint = str(ssh_server.get("host_key_fingerprint", "") or "")
            for instance in ssh_server.get("instances") or []:
                account = str(instance["account"])
                apps.setdefault(
                    app_id,
                    self._app(
                        app_id,
                        SERVICES_SSH_SERVER_TITLE,
                        SERVICES_SOURCE_MODULE,
                        device,
                    ),
                )
                entries.append(
                    self._app_entry(
                        app_id,
                        account,
                        type=SERVICES_TYPE_SSH,
                        title=f"{SERVICES_SSH_SERVER_TITLE} ({account})",
                        payload={
                            "host": host,
                            "port": int(instance["port"]),
                            "account": account,
                            "host_key_fingerprint": fingerprint,
                        },
                        is_healthy=bool(instance.get("is_healthy")),
                        description=SERVICES_SSH_SERVER_DESCRIPTION.format(
                            host=host, account=account
                        ),
                        description_code=SERVICES_DESCRIPTION_SSH_SERVER_MODULE,
                        description_params={"host": host, "account": account},
                        device_id=device_id,
                    )
                )
        hermes = device.get("hermes_webui")
        if hermes and hermes.get("port"):
            app_id = f"{SERVICES_HERMES_WEBUI_ID}_{device_id}"
            apps.setdefault(
                app_id,
                self._app(
                    app_id, SERVICES_HERMES_WEBUI_TITLE, SERVICES_SOURCE_MODULE, device
                ),
            )
            entries.append(
                self._app_entry(
                    app_id,
                    SERVICES_ENTRY_WEB,
                    type=SERVICES_TYPE_WEB,
                    title=SERVICES_HERMES_WEBUI_TITLE,
                    payload={
                        "url": f"http://{_url_host(host)}:{hermes['port']}/",
                        "is_token_required": True,
                    },
                    is_healthy=bool(hermes.get("is_healthy")),
                    description=SERVICES_HERMES_WEBUI_DESCRIPTION.format(host=host),
                    description_code=SERVICES_DESCRIPTION_HERMES_WEBUI_MODULE,
                    description_params={"host": host},
                    device_id=device_id,
                )
            )
        podman = device.get("podman")
        for container in (podman or {}).get("containers") or []:
            name = str(container["name"])
            app_id = f"{PODMAN_MODULE}_{device_id}_{name}"
            source = (
                SERVICES_SOURCE_MANUAL
                if container.get("source") == SERVICES_SOURCE_MANUAL
                else SERVICES_SOURCE_DECLARED
            )
            for port, protocol, scheme in container.get("bindings") or []:
                apps.setdefault(app_id, self._app(app_id, name, source, device))
                entry_name = str(port)
                if protocol == SERVICES_PROTOCOL_UDP:
                    entry_name += SERVICES_UDP_ID_SUFFIX
                if scheme:
                    entry_type = SERVICES_TYPE_WEB
                    payload = {"url": f"{scheme}://{_url_host(host)}:{port}/"}
                else:
                    entry_type = SERVICES_TYPE_PORT
                    payload = {"host": host, "port": port, "protocol": protocol}
                entries.append(
                    self._app_entry(
                        app_id,
                        entry_name,
                        type=entry_type,
                        title=name,
                        payload=payload,
                        is_healthy=bool(container.get("is_running")),
                        description=SERVICES_PODMAN_DESCRIPTION.format(
                            name=name, image=container.get("image", ""), host=host
                        ),
                        description_code=SERVICES_DESCRIPTION_CONTAINER,
                        description_params={"image": container.get("image", "")},
                        device_id=device_id,
                        source=source,
                    )
                )
        return entries

    def _declared_entries(self, apps: dict) -> list:
        """Every entry of every declared app, with its probe's health."""
        entries = []
        for app in self._declared_apps:
            device_id = self._device_ids_by_address.get(app.host, "")
            device = {"device_id": device_id, "host": app.host}
            apps.setdefault(
                app.id,
                self._app(
                    app.id,
                    app.name,
                    SERVICES_SOURCE_DECLARED,
                    device,
                    description=app.description,
                ),
            )
            for entry in app.entries:
                held = self._declared_healths.get(entry_id(app.id, entry.name))
                is_healthy = held.is_healthy if held is not None else None
                detail_code = held.detail_code if held is not None else None
                if entry.type == SERVICES_TYPE_WEB:
                    payload = {
                        "url": f"{entry.scheme}://{_url_host(app.host)}:{entry.port}"
                        f"{entry.path or '/'}"
                    }
                elif entry.type == SERVICES_TYPE_PORT:
                    payload = {
                        "host": app.host,
                        "port": entry.port,
                        "protocol": entry.protocol or SERVICES_PROTOCOL_TCP,
                    }
                else:
                    payload = {
                        "protocol": SERVICES_FILE_PROTOCOL,
                        "host": app.host,
                        "port": entry.port,
                        "share": entry.share,
                        "users": [],
                    }
                entries.append(
                    self._app_entry(
                        app.id,
                        entry.name,
                        type=entry.type,
                        title=(
                            entry.share
                            if entry.type == SERVICES_TYPE_FILE
                            else app.name
                        ),
                        payload=payload,
                        is_healthy=is_healthy,
                        description=app.description,
                        description_code=_declared_code(app),
                        detail_code=detail_code,
                        device_id="",
                        source=SERVICES_SOURCE_DECLARED,
                    )
                )
        return entries

    def _rdp_entries(self) -> list:
        """One entry per machine that says it is sharing its desktop."""
        return [
            _entry(
                id=f"rdp_{share.device_id}",
                type=SERVICES_TYPE_RDP,
                title=share.hostname or share.host,
                payload={
                    "protocol": SERVICES_RDP_PROTOCOL,
                    "host": share.host,
                    "port": share.port,
                    "attention": share.attention,
                    "platform_os": share.platform_os,
                },
                is_healthy=True,
                description=SERVICES_RDP_DESCRIPTION.format(
                    hostname=share.hostname or share.host
                ),
                description_code=SERVICES_DESCRIPTION_DEVICE_SHARE,
                description_params={"device": share.hostname or share.host},
                source=SERVICES_SOURCE_DEVICE,
                device_id=share.device_id,
            )
            for share in self._device_shares
        ]

    def _ai_entries(self) -> list:
        if not self._is_ai_served or not self._hub_host:
            return []
        return [
            _entry(
                id=SERVICES_AI_ID,
                type=SERVICES_TYPE_AI,
                title=SERVICES_AI_TITLE,
                payload={
                    "endpoint": f"http://{_url_host(self._hub_host)}:{self._ai_port}",
                    "protocol": SERVICES_AI_PROTOCOL,
                    "models": list(self._ai_models),
                },
                is_healthy=self._is_ai_healthy,
                description=SERVICES_AI_DESCRIPTION,
                description_code=SERVICES_DESCRIPTION_AI_GATEWAY,
                source=SERVICES_SOURCE_MODULE,
            )
        ]

    def _file_entries(self) -> list:
        """One entry per share of each device's file share."""
        entries = []
        for device in self._device_modules:
            samba = device.get("samba")
            host = device.get("host", "")
            if not samba or not host:
                continue
            for share in samba.get("shares") or []:
                name = str(share.get("name", "") or "")
                if not name:
                    continue
                entries.append(
                    _entry(
                        id=f"samba_{_device_id(device)}_{name}",
                        type=SERVICES_TYPE_FILE,
                        title=name,
                        payload={
                            "protocol": SERVICES_FILE_PROTOCOL,
                            "host": host,
                            "share": name,
                            "users": [str(share.get("user", "") or "")],
                        },
                        is_healthy=bool(samba.get("is_healthy")),
                        description=SERVICES_SAMBA_DESCRIPTION.format(host=host),
                        description_code=SERVICES_DESCRIPTION_SAMBA_MODULE,
                        description_params={"host": host},
                        source=SERVICES_SOURCE_MODULE,
                        device_id=_device_id(device),
                    )
                )
        return entries

    def _app(
        self, app_id: str, title: str, source: str, device: dict, *, description=""
    ) -> dict:
        device_id = _device_id(device)
        return {
            "id": app_id,
            "title": title,
            "source": source,
            "device_id": device_id,
            "device_name": self._device_names.get(device_id, ""),
            "local_name": "",
            "description": description,
        }

    def _app_entry(self, app_id: str, name: str, **fields) -> dict:
        fields.setdefault("source", SERVICES_SOURCE_MODULE)
        return _entry(id=entry_id(app_id, name), app_id=app_id, name=name, **fields)

    def _name_apps(self, apps: dict) -> None:
        """Give every app its local name, told apart per machine."""
        by_device: dict = {}
        for app in apps.values():
            by_device.setdefault(app["device_id"], {})[app["id"]] = app["title"]
        for device_id, titles in by_device.items():
            machine_slug = (
                self._machine_slugs.get(device_id, SERVICES_MACHINE_SLUG_FALLBACK)
                if device_id
                else self._hub_slug
            )
            for app_id, made in app_slugs(titles).items():
                apps[app_id]["local_name"] = local_name(made, machine_slug)


_TYPE_ORDER = (
    SERVICES_TYPE_WEB,
    SERVICES_TYPE_PORT,
    SERVICES_TYPE_SSH,
    SERVICES_TYPE_AI,
    SERVICES_TYPE_FILE,
    SERVICES_TYPE_RDP,
)


def hub_self_addresses(hub_addresses: list) -> set:
    """The hosts that mean the hub itself for one composition.

    Args:
        hub_addresses: Every address the hub holds.

    Returns:
        Those plus the loopback spellings.
    """
    return set(SERVICES_HUB_SELF_HOSTS) | {a for a in hub_addresses if a}


def resolve_entries(
    entries: list,
    *,
    device_hosts: dict,
    hub_addresses: set,
    hub_host: str,
) -> list:
    """Rewrite every payload host for one caller's scope.

    A device's entry names the address that device has in the scope; an
    entry at one of the hub's own addresses, a module hosted on the hub
    box's own agent included, names the hub's address there. A host outside
    both is somebody else's machine and stands.

    Args:
        entries: The composed entries.
        device_hosts: Device id to its address in the scope; a device absent
            here keeps its composed host.
        hub_addresses: Every host that means the hub itself.
        hub_host: The hub's own address in the scope; empty leaves the
            hub's own hosts as composed.

    Returns:
        A new list; the entries themselves are untouched.
    """
    resolved = []
    for entry in entries:
        payload = dict(entry["payload"])
        device_host = device_hosts.get(entry.get("device_id") or "", "")
        if device_host:
            payload = _with_host(entry["type"], payload, device_host)
        if hub_host and _host_of(entry["type"], payload) in hub_addresses:
            payload = _with_host(entry["type"], payload, hub_host)
        resolved.append({**entry, "payload": payload})
    return resolved


def catalog_entries(entries: list) -> list:
    """The entries as a client's list and the device catalog carry them.

    Args:
        entries: The composed entries.

    Returns:
        The same list without the panel-only fields.
    """
    return [
        {
            key: entry.get(key, CATALOG_ENTRY_DEFAULTS.get(key))
            for key in CATALOG_ENTRY_FIELDS
        }
        for entry in entries
    ]


def _declared_code(app: DeclaredApp) -> str:
    """The provenance code a declared app's entries carry.

    Args:
        app: The declaration.

    Returns:
        The declared code, or nothing where the person wrote their own line.
    """
    return "" if app.description else SERVICES_DESCRIPTION_DECLARED


def _device_id(device: dict) -> str:
    """The id of the device one module entry is hosted on."""
    return str(device.get("device_id", "") or "")


def _entry(
    *,
    id: str,
    type: str,
    title: str,
    payload: dict,
    is_healthy,
    description: str,
    description_code: str = "",
    description_params: "dict | None" = None,
    detail_code: "str | None" = None,
    source: str = SERVICES_SOURCE_MODULE,
    device_id: str = "",
    app_id: str = "",
    name: str = "",
) -> dict:
    return {
        "id": id,
        "type": type,
        "title": title,
        "payload": payload,
        "is_healthy": is_healthy,
        "source": source,
        "description": description,
        "description_code": description_code,
        "description_params": description_params or {},
        "detail_code": detail_code,
        "device_id": device_id,
        "app_id": app_id,
        "name": name,
        "local_port": 0,
    }


def _url_host(host: str) -> str:
    """A host as a url writes it, an IPv6 address in brackets."""
    return f"[{host}]" if ":" in host else host


def _host_of(entry_type: str, payload: dict) -> "str | None":
    """The host a payload names, wherever its type keeps it."""
    if entry_type == SERVICES_TYPE_WEB:
        return urlsplit(payload["url"]).hostname
    if entry_type == SERVICES_TYPE_AI:
        return urlsplit(payload["endpoint"]).hostname
    return payload.get("host")


def _with_host(entry_type: str, payload: dict, host: str) -> dict:
    """The payload with its host replaced, wherever its type keeps it."""
    if entry_type == SERVICES_TYPE_WEB:
        return {**payload, "url": _url_at(payload["url"], host)}
    if entry_type == SERVICES_TYPE_AI:
        return {**payload, "endpoint": _url_at(payload["endpoint"], host)}
    return {**payload, "host": host}


def _url_at(url: str, host: str) -> str:
    parts = urlsplit(url)
    if parts.hostname is None:
        return url
    netloc = f"[{host}]" if ":" in host else host
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
