"""What a client is handed when it opens a ``service`` or a ``connect`` stream.

A ``service {is_panel: true}`` stream is answered with a panel sign-in
token for a client that holds the ``panel`` permission.

A ``service`` stream's close is the material: ``{password}`` for a desktop,
``{api_key, model}`` for the AI gateway, ``{token}`` for a VS Code
instance, and for a CloudCLI or code-server instance a ``{token}`` minted for that
one answer. The published list carries no secret; this is where the one secret
a service takes from the hub is opened, for one close.

A ``connect`` stream is judged by the same checks, with the stream limit
among them, and is answered with where its bytes go: a managed machine's
agent at a port, or an address the hub dials itself.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_BINDING_UNKNOWN,
    CHANNEL_CODE_CONNECT_LIMIT,
    CHANNEL_CONNECT_LOOPBACK,
    CHANNEL_CONNECT_STREAMS_MAX,
)
from neutrino_hub.modules.clients.ai_keys import client_credential
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_DISABLED,
    CLIENT_CODE_PERMISSION_DENIED,
    CLIENT_CODE_RDP_NOT_SHARED,
    CLIENT_CODE_SERVICE_UNKNOWN,
    CLIENT_PERMISSION_PANEL,
    CLIENT_RDP_SERVICE_PREFIX,
)
from neutrino_hub.modules.clients.permissions import (
    entry_device_id,
    entry_host,
    is_device_permitted,
    permitted_devices,
    permitted_kinds,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.cliproxyapi.ops import load_config
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.system.machine import machine_id
from neutrino_hub.modules.services.collector import catalog_entries
from neutrino_hub.modules.services.constants import (
    SERVICES_DESCRIPTION_CLOUDCLI_MODULE,
    SERVICES_DESCRIPTION_CODE_SERVER_MODULE,
    SERVICES_DESCRIPTION_VSCODE_MODULE,
    SERVICES_SAMBA_DEFAULT_PORT,
    SERVICES_SOURCE_DECLARED,
    SERVICES_TYPE_AI,
    SERVICES_TYPE_FILE,
    SERVICES_TYPE_PORT,
    SERVICES_TYPE_RDP,
    SERVICES_TYPE_WEB,
)
from neutrino_hub.modules.services.host_scope import (
    HostScope,
    link_scope,
)

# The port a web entry's url stands for when it names none, by its scheme.
SCHEME_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class ConnectTarget:
    """Where the bytes of one ``connect`` stream go.

    Attributes:
        device_id: The managed machine whose agent is opened ``connect
            {port}``; empty when the hub dials ``host`` itself.
        host: The address the hub dials; empty for a machine's agent.
        port: The port, on the machine or at ``host``.
        kind: The permission kind the stream falls under: the entry's type,
            or ``panel``.
        provider: The machine the permission's device lists judge it by,
            empty for none.
    """

    device_id: str
    host: str
    port: int
    kind: str = field(default="", compare=False)
    provider: str = field(default="", compare=False)


def service_material(runtime, client_id: str, entry_id: str) -> tuple:
    """The material one published entry takes, judged for one client now.

    Args:
        runtime: The shared runtime.
        client_id: The client asking.
        entry_id: The published entry's id.

    Returns:
        ``(code, params)``: the close of the stream. An empty code makes the
        params the material; a type that takes no material closes empty.
    """
    registry = ClientRegistry()
    client = registry.get(client_id)
    code, params = _client_refusal(client)
    if code:
        return code, params
    code, params, entry, raw = _judge_entry(runtime, registry, client, entry_id)
    if code:
        return code, params
    if entry["type"] == SERVICES_TYPE_RDP:
        share = _live_share(runtime, entry)
        return "", {"password": runtime.desired_states.seat_password(share.device_id)}
    if entry["type"] == SERVICES_TYPE_AI:
        credential = client_credential(
            registry, client, served_models=runtime.served_models
        )
        if credential is None:
            return VaultLockedError.code, {}
        return "", credential
    if entry["description_code"] == SERVICES_DESCRIPTION_VSCODE_MODULE:
        device_id = str(raw.get("device_id") or "")
        account = str(entry["description_params"].get("account", "") or "")
        token = runtime.desired_states.vscode_token(device_id, account)
        if not token:
            return VaultLockedError.code, {}
        return "", {"token": token}
    if entry["description_code"] == SERVICES_DESCRIPTION_CLOUDCLI_MODULE:
        device_id = str(raw.get("device_id") or "")
        account = str(entry["description_params"].get("account", "") or "")
        token = runtime.desired_states.cloudcli_token(device_id, account)
        if not token:
            return VaultLockedError.code, {}
        return "", {"token": token}
    if entry["description_code"] == SERVICES_DESCRIPTION_CODE_SERVER_MODULE:
        device_id = str(raw.get("device_id") or "")
        account = str(entry["description_params"].get("account", "") or "")
        token = runtime.desired_states.code_server_token(device_id, account)
        if not token:
            return VaultLockedError.code, {}
        return "", {"token": token}
    return "", {}


def panel_material(runtime, client_id: str) -> tuple:
    """A panel sign-in token for one client, judged now.

    Args:
        runtime: The shared runtime, which holds the panel's tokens.
        client_id: The client asking.

    Returns:
        ``(code, params)``: the close of a ``service {is_panel: true}``
        stream; an empty code with ``{token}``, or ``binding_unknown``,
        ``client_disabled`` or ``permission_denied {kind: panel}``.
    """
    registry = ClientRegistry()
    client = registry.get(client_id)
    code, params = _client_refusal(client)
    if code:
        return code, params
    if CLIENT_PERMISSION_PANEL not in permitted_kinds(registry, client):
        return CLIENT_CODE_PERMISSION_DENIED, {"kind": CLIENT_PERMISSION_PANEL}
    return "", {"token": runtime.panel_tokens.mint(client.id)}


def connect_target(
    runtime, client_id: str, args: dict, *, open_count: int, panel_port: int
) -> tuple:
    """Where one ``connect`` stream goes, judged for one client now.

    The checks are the ``service`` stream's, in its order, with the stream
    limit after the client's own two.

    Args:
        runtime: The shared runtime.
        client_id: The client asking.
        args: The open's arguments: ``{id}`` for a published entry, or
            ``{is_panel: true}`` for the hub's own panel.
        open_count: How many ``connect`` streams the client's socket holds
            open besides this one.
        panel_port: The port the panel answers plain HTTP on.

    Returns:
        ``(code, params, target)``: a refusal and None, or an empty code,
        empty params and the :class:`ConnectTarget`.
    """
    registry = ClientRegistry()
    client = registry.get(client_id)
    code, params = _client_refusal(client)
    if code:
        return code, params, None
    if open_count >= CHANNEL_CONNECT_STREAMS_MAX:
        return CHANNEL_CODE_CONNECT_LIMIT, {"limit": CHANNEL_CONNECT_STREAMS_MAX}, None
    if args.get("is_panel") is True:
        if CLIENT_PERMISSION_PANEL not in permitted_kinds(registry, client):
            return (
                CLIENT_CODE_PERMISSION_DENIED,
                {"kind": CLIENT_PERMISSION_PANEL},
                None,
            )
        return (
            "",
            {},
            ConnectTarget(
                "",
                CHANNEL_CONNECT_LOOPBACK,
                int(panel_port),
                kind=CLIENT_PERMISSION_PANEL,
            ),
        )
    entry_id = str(args.get("id", "") or "")
    code, params, entry, raw = _judge_entry(runtime, registry, client, entry_id)
    if code:
        return code, params, None
    kind = entry["type"]
    hub_device_id, device_ids_by_address = device_owners(runtime)
    provider = entry_device_id(
        raw,
        hub_device_id=hub_device_id,
        device_ids_by_address=device_ids_by_address,
    )
    if kind == SERVICES_TYPE_AI:
        port = load_config().listen_port
        target = ConnectTarget("", CHANNEL_CONNECT_LOOPBACK, port)
    elif raw.get("device_id"):
        target = ConnectTarget(str(raw["device_id"]), "", entry_port(raw))
    elif raw.get("source") == SERVICES_SOURCE_DECLARED:
        declared = _unresolved_entry(runtime, entry_id) or raw
        target = ConnectTarget("", entry_host(declared), entry_port(declared))
    else:
        return CLIENT_CODE_SERVICE_UNKNOWN, {"service_id": entry_id}, None
    return (
        "",
        {},
        ConnectTarget(
            target.device_id, target.host, target.port, kind=kind, provider=provider
        ),
    )


def entry_port(entry: dict) -> int:
    """The port one published entry answers on.

    Args:
        entry: The entry.

    Returns:
        A ``web`` entry's url port, 80 or 443 by its scheme when the url
        names none; a ``port`` or ``rdp`` entry's ``port``; 445 for a
        ``file`` entry; 0 for any other.
    """
    payload = entry.get("payload") or {}
    if entry.get("type") == SERVICES_TYPE_WEB:
        parts = urlsplit(str(payload.get("url", "") or ""))
        try:
            port = parts.port
        except ValueError:
            return 0
        return port or SCHEME_PORTS.get(parts.scheme, 0)
    if entry.get("type") in (SERVICES_TYPE_PORT, SERVICES_TYPE_RDP):
        try:
            return int(payload.get("port") or 0)
        except (TypeError, ValueError):
            return 0
    if entry.get("type") == SERVICES_TYPE_FILE:
        return SERVICES_SAMBA_DEFAULT_PORT
    return 0


def device_owners(runtime) -> tuple:
    """What :func:`entry_device_id` needs to tell which device provides an entry.

    Args:
        runtime: The shared runtime, for the addresses devices are reached at.

    Returns:
        ``(hub_device_id, device_ids_by_address)``: the stored device this
        machine is, empty when none is; and every stored device's id by the
        address it is reached at.
    """
    own_machine = machine_id()
    stored = DeviceRegistry().all_stored()
    hub_device_id = next(
        (
            device.id
            for device in stored
            if own_machine and device.machine_id == own_machine
        ),
        "",
    )
    stored_ids = {device.id for device in stored}
    device_ids_by_address = {
        address: device_id
        for device_id, address in runtime.device_address.items()
        if address and device_id in stored_ids
    }
    return hub_device_id, device_ids_by_address


def _client_refusal(client) -> tuple:
    """Whether a client may ask for anything now, as ``(code, params)``."""
    if client is None:
        return CHANNEL_CODE_BINDING_UNKNOWN, {}
    if client.is_disabled:
        return CLIENT_CODE_DISABLED, {}
    return "", {}


def _judge_entry(runtime, registry, client, entry_id: str) -> tuple:
    """Whether one client may use one published entry now.

    Returns:
        ``(code, params, entry, raw)``: a refusal with no entry; or an empty
        code, the entry as the client's list carries it, and the composed
        entry with the fields that say who hosts it.
    """
    scope = runtime.client_scope.get(client.id) or link_scope("")
    entry = _entry(runtime, scope, entry_id)
    if entry is None:
        return CLIENT_CODE_SERVICE_UNKNOWN, {"service_id": entry_id}, None, None
    raw = _raw_entry(runtime, scope, entry_id)
    if entry["type"] not in permitted_kinds(registry, client):
        return CLIENT_CODE_PERMISSION_DENIED, {"kind": entry["type"]}, None, None
    devices = permitted_devices(registry, client)
    if devices.get(entry["type"]):
        hub_device_id, device_ids_by_address = device_owners(runtime)
        provider = entry_device_id(
            raw,
            hub_device_id=hub_device_id,
            device_ids_by_address=device_ids_by_address,
        )
        if not is_device_permitted(devices, entry["type"], provider):
            return CLIENT_CODE_PERMISSION_DENIED, {"kind": entry["type"]}, None, None
    if entry["type"] == SERVICES_TYPE_RDP and _live_share(runtime, entry) is None:
        return CLIENT_CODE_RDP_NOT_SHARED, {"service_id": entry["id"]}, None, None
    return "", {}, entry, raw


def _entry(runtime, scope: HostScope, entry_id: str) -> "dict | None":
    """The published entry one id names, resolved for the client's scope."""
    for entry in catalog_entries(runtime.published_services.entries_for(scope)):
        if entry["id"] == entry_id:
            return entry
    return None


def _raw_entry(runtime, scope: HostScope, entry_id: str) -> dict:
    """The composed entry one id names, with the fields that say who hosts it."""
    for entry in runtime.published_services.entries_for(scope):
        if entry["id"] == entry_id:
            return entry
    return {}


def _unresolved_entry(runtime, entry_id: str) -> dict:
    """The entry one id names as it was composed, before a scope rewrote it."""
    entries, _ = runtime.published_services.entries()
    for entry in entries:
        if entry["id"] == entry_id:
            return entry
    return {}


def _live_share(runtime, entry: dict):
    """The desktop share an ``rdp`` entry names, None once it stopped."""
    share_id = entry["id"][len(CLIENT_RDP_SERVICE_PREFIX) :]
    for share in runtime.device_shares.live():
        if share.share_id == share_id:
            return share
    return None
