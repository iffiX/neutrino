"""What a client is handed when it opens a ``service`` stream.

The stream's close is the material: ``{host, port, password}`` for a
desktop, ``{base_url, api_key, model}`` for the AI gateway. The published
list carries no secret; this is where the one secret a service takes from
the hub is opened, for one close.
"""

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.clients.ai_keys import client_credential
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_DISABLED,
    CLIENT_CODE_RDP_NOT_SHARED,
    CLIENT_CODE_SERVICE_UNKNOWN,
    CLIENT_RDP_SERVICE_PREFIX,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.channel.constants import CHANNEL_CODE_BINDING_UNKNOWN
from neutrino_hub.modules.services.collector import catalog_entries
from neutrino_hub.modules.services.constants import (
    SERVICES_TYPE_AI,
    SERVICES_TYPE_RDP,
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
    host = runtime.client_catalog_host.get(client_id, "")
    entry = _entry(runtime, host, entry_id)
    if entry is None:
        return CLIENT_CODE_SERVICE_UNKNOWN, {"service_id": entry_id}
    if entry["type"] == SERVICES_TYPE_RDP:
        return _rdp_material(runtime, entry_id)
    if entry["type"] == SERVICES_TYPE_AI:
        credential = client_credential(
            registry, client, hub_host=host, served_models=runtime.served_models
        )
        if credential is None:
            return VaultLockedError.code, {}
        return "", credential
    return "", {}


def _entry(runtime, host: str, entry_id: str) -> "dict | None":
    """The published entry one id names, resolved for the client's host."""
    for entry in catalog_entries(runtime.published_services.entries_for(host)):
        if entry["id"] == entry_id:
            return entry
    return None


def _rdp_material(runtime, entry_id: str) -> tuple:
    """A shared desktop's address and its seat password."""
    share_id = entry_id[len(CLIENT_RDP_SERVICE_PREFIX) :]
    for share in runtime.device_shares.live():
        if share.share_id == share_id:
            return "", {
                "host": share.host,
                "port": share.port,
                "password": runtime.desired_states.seat_password(share.device_id),
            }
    return CLIENT_CODE_RDP_NOT_SHARED, {"service_id": entry_id}
