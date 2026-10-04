"""What a client is handed when it opens a ``service`` stream.

The stream's close is the material: ``{host, port, password}`` for a
desktop, ``{base_url, api_key, model}`` for the AI gateway, ``{token}`` for
a VS Code instance, and for a CloudCLI or code-server instance a
``{token}`` minted for that one answer. Every host in
it is resolved for the scope the client's socket arrived from, at that
moment. The published list carries no secret; this is where the one
secret a service takes from the hub is opened, for one close.
"""

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.clients.ai_keys import client_credential
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_DISABLED,
    CLIENT_CODE_PERMISSION_DENIED,
    CLIENT_CODE_RDP_NOT_SHARED,
    CLIENT_CODE_SERVICE_UNKNOWN,
    CLIENT_RDP_SERVICE_PREFIX,
)
from neutrino_hub.modules.clients.permissions import (
    entry_device_id,
    is_device_permitted,
    permitted_devices,
    permitted_kinds,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.channel.constants import CHANNEL_CODE_BINDING_UNKNOWN
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.system.machine import machine_id
from neutrino_hub.modules.services.collector import catalog_entries
from neutrino_hub.modules.services.constants import (
    SERVICES_DESCRIPTION_CLOUDCLI_MODULE,
    SERVICES_DESCRIPTION_CODE_SERVER_MODULE,
    SERVICES_DESCRIPTION_VSCODE_MODULE,
    SERVICES_TYPE_AI,
    SERVICES_TYPE_RDP,
)
from neutrino_hub.modules.services.host_scope import (
    HostScope,
    link_scope,
)


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
    if client is None:
        return CHANNEL_CODE_BINDING_UNKNOWN, {}
    if client.is_disabled:
        return CLIENT_CODE_DISABLED, {}
    scope = runtime.client_scope.get(client_id) or link_scope("")
    entry = _entry(runtime, scope, entry_id)
    if entry is None:
        return CLIENT_CODE_SERVICE_UNKNOWN, {"service_id": entry_id}
    if entry["type"] not in permitted_kinds(registry, client):
        return CLIENT_CODE_PERMISSION_DENIED, {"kind": entry["type"]}
    devices = permitted_devices(registry, client)
    if devices.get(entry["type"]):
        hub_device_id, device_ids_by_address = device_owners(runtime)
        provider = entry_device_id(
            _raw_entry(runtime, scope, entry_id),
            hub_device_id=hub_device_id,
            device_ids_by_address=device_ids_by_address,
        )
        if not is_device_permitted(devices, entry["type"], provider):
            return CLIENT_CODE_PERMISSION_DENIED, {"kind": entry["type"]}
    if entry["type"] == SERVICES_TYPE_RDP:
        return _rdp_material(runtime, entry)
    if entry["type"] == SERVICES_TYPE_AI:
        credential = client_credential(
            registry,
            client,
            hub_host=scope.hub_address,
            served_models=runtime.served_models,
        )
        if credential is None:
            return VaultLockedError.code, {}
        return "", credential
    if entry["description_code"] == SERVICES_DESCRIPTION_VSCODE_MODULE:
        device_id = str(_raw_entry(runtime, scope, entry_id).get("device_id") or "")
        account = str(entry["description_params"].get("account", "") or "")
        token = runtime.desired_states.vscode_token(device_id, account)
        if not token:
            return VaultLockedError.code, {}
        return "", {"token": token}
    if entry["description_code"] == SERVICES_DESCRIPTION_CLOUDCLI_MODULE:
        device_id = str(_raw_entry(runtime, scope, entry_id).get("device_id") or "")
        account = str(entry["description_params"].get("account", "") or "")
        token = runtime.desired_states.cloudcli_token(device_id, account)
        if not token:
            return VaultLockedError.code, {}
        return "", {"token": token}
    if entry["description_code"] == SERVICES_DESCRIPTION_CODE_SERVER_MODULE:
        device_id = str(_raw_entry(runtime, scope, entry_id).get("device_id") or "")
        account = str(entry["description_params"].get("account", "") or "")
        token = runtime.desired_states.code_server_token(device_id, account)
        if not token:
            return VaultLockedError.code, {}
        return "", {"token": token}
    return "", {}


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


def _rdp_material(runtime, entry: dict) -> tuple:
    """A shared desktop's host and port as its entry names them for the client, and its seat password."""
    share_id = entry["id"][len(CLIENT_RDP_SERVICE_PREFIX) :]
    for share in runtime.device_shares.live():
        if share.share_id == share_id:
            return "", {
                "host": entry["payload"]["host"],
                "port": entry["payload"]["port"],
                "password": runtime.desired_states.seat_password(share.device_id),
            }
    return CLIENT_CODE_RDP_NOT_SHARED, {"service_id": entry["id"]}
