"""The gateway key each client is handed, and each managed device's.

One :class:`CliproxyApiClientKey` per client, labelled ``client/<name>``:
minted the first time the client connects with the vault unlocked, revoked
when it is disabled or deleted, minted again when it is enabled. The key's
id lives on the client record; the material lives sealed in the gateway's
own config and is handed to the client as a ``service`` stream's close.

One more per managed device whose AI tools setting is on, labelled
``device/<name>`` and kept under the device's id in the gateway's
``device_keys``: minted when the setting goes on, revoked when it goes off
and when the device is removed, and handed to the device in its desired
state's ``ai_tools`` section. A key no setting holds on, as one minted for
CloudCLI by an earlier build, is revoked when the panel starts.
"""

from neutrino_hub.modules.clients.constants import (
    CLIENT_AI_DEVICE_KEY_LABEL_PREFIX,
    CLIENT_AI_KEY_LABEL_PREFIX,
)
from neutrino_hub.modules.clients.registry import Client, ClientRegistry
from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
from neutrino_hub.modules.cliproxyapi.ops import (
    CliproxyApiConfigApplier,
    load_config,
    save_config,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK


def ensure_client_key(registry: ClientRegistry, client: Client) -> "str | None":
    """The client's key material, minting a key when it holds none.

    Args:
        registry: The client records.
        client: The client.

    Returns:
        The key material, or None while the vault is locked.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        held = _held_key(config, client.ai_key_id)
        if held is not None:
            try:
                return held.open_key()
            except ValueError:
                return None
        try:
            key = CliproxyApiClientKey.generated(_label(client))
        except ValueError:
            return None
        config.client_keys.append(key)
        save_config(config)
        registry.set_ai_key_id(client.id, key.id)
    material = key.open_key()
    _apply(new_key=material)
    return material


def revoke_client_key(registry: ClientRegistry, client: Client) -> None:
    """Remove the client's key from the gateway and forget its id.

    Args:
        registry: The client records.
        client: The client.
    """
    if not client.ai_key_id:
        return
    is_changed = False
    with CONFIG_WRITE_LOCK:
        config = load_config()
        remaining = [key for key in config.client_keys if key.id != client.ai_key_id]
        if len(remaining) != len(config.client_keys):
            config.client_keys = remaining
            save_config(config)
            is_changed = True
        if registry.get(client.id) is not None:
            registry.set_ai_key_id(client.id, None)
    if is_changed:
        _apply()


def ensure_device_key(device_id: str, name: str) -> "str | None":
    """One device's key material, minting a key when it holds none.

    Args:
        device_id: The device.
        name: What the device is called, for the key's label.

    Returns:
        The key material, or None while the vault is locked.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        held = config.device_keys.get(device_id)
        if held is not None:
            try:
                return held.open_key()
            except ValueError:
                return None
        try:
            key = CliproxyApiClientKey.generated(
                f"{CLIENT_AI_DEVICE_KEY_LABEL_PREFIX}{name or device_id}"
            )
        except ValueError:
            return None
        config.device_keys[device_id] = key
        save_config(config)
    material = key.open_key()
    _apply(new_key=material)
    return material


def revoke_device_key(device_id: str) -> None:
    """Remove one device's key from the gateway.

    Args:
        device_id: The device.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        if config.device_keys.pop(device_id, None) is None:
            return
        save_config(config)
    _apply()


def device_gateway(device_id: str, hub_address: str) -> dict:
    """Where one device's AI tools reach the gateway, and with which key.

    Args:
        device_id: The device.
        hub_address: The hub's address on the device's network.

    Returns:
        ``{gateway_url, gateway_key}``; both empty while the device holds no
        key, its key does not open, or its network is not known.
    """
    held = load_config()
    key = held.device_keys.get(device_id)
    if key is None or not hub_address:
        return {"gateway_url": "", "gateway_key": ""}
    try:
        material = key.open_key()
    except ValueError:
        return {"gateway_url": "", "gateway_key": ""}
    return {
        "gateway_url": f"http://{hub_address}:{held.listen_port}",
        "gateway_key": material,
    }


def gateway_models(served_models) -> list:
    """The names the gateway serves now, probed with the hub's own key.

    Args:
        served_models: The shared
            :class:`neutrino_hub.modules.cliproxyapi.ops.CliproxyApiServedModelCache`.

    Returns:
        The served names; empty while the gateway has no hub key, the key
        does not open, the gateway does not answer, or it serves nothing.
    """
    held = load_config()
    if held.hub_key is None:
        return []
    try:
        material = held.hub_key.open_key()
    except ValueError:
        return []
    _, models = served_models.served(port=held.listen_port, client_key=material)
    return list(models)


def settle_device_keys(enabled_ids) -> list:
    """Revoke every device key whose device's AI tools setting is not on.

    Args:
        enabled_ids: The devices whose setting is on.

    Returns:
        The ids whose key was revoked.
    """
    kept = set(enabled_ids)
    with CONFIG_WRITE_LOCK:
        config = load_config()
        dropped = sorted(key for key in config.device_keys if key not in kept)
        if not dropped:
            return []
        for device_id in dropped:
            config.device_keys.pop(device_id, None)
        save_config(config)
    _apply()
    return dropped


def client_credential(
    registry: ClientRegistry, client: Client, *, served_models
) -> "dict | None":
    """What the client's AI tools hand the gateway through the client's forward.

    Args:
        registry: The client records.
        client: The client.
        served_models: The shared
            :class:`neutrino_hub.modules.cliproxyapi.ops.CliproxyApiServedModelCache`.

    Returns:
        ``{api_key, model}``: the client's own key and the first model the
        gateway serves; None while the client is disabled or the vault is
        locked.
    """
    if client.is_disabled:
        return None
    api_key = ensure_client_key(registry, client)
    if api_key is None:
        return None
    port = load_config().listen_port
    return {
        "api_key": api_key,
        "model": served_models.first_model(port=port, client_key=api_key),
    }


def _held_key(config, key_id: "str | None") -> "CliproxyApiClientKey | None":
    if not key_id:
        return None
    for key in config.client_keys:
        if key.id == key_id:
            return key
    return None


def _label(client: Client) -> str:
    return f"{CLIENT_AI_KEY_LABEL_PREFIX}{client.name or client.id}"


def _apply(*, new_key: "str | None" = None) -> None:
    """Hand the gateway the changed keys, waiting for ``new_key`` when given."""
    try:
        CliproxyApiConfigApplier().apply_keys(new_key=new_key)
    except ValueError:
        return
