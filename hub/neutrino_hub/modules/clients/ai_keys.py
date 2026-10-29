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

One more per container module that uses the gateway on each device,
labelled ``device/<name>/<module>`` and kept sealed in that module's file
under the device's directory: minted when the module is installed, voided
at its uninstall and when the device is removed, and handed to the module's
containers in their environment whatever the AI tools setting says.

One more per enabled account of a program run as an account that uses the
gateway, SiYuan, labelled ``device/<name>/<module>/<account>`` and kept
sealed in the account's record of that module's file: minted when the
account is enabled, voided when it is disabled or removed, at the module's
uninstall and when the device is removed, and handed to the instance in the
module's section of the state.
"""

from neutrino_hub.modules.clients.constants import (
    CLIENT_AI_DEVICE_FORWARD_URL,
    CLIENT_AI_DEVICE_KEY_LABEL_PREFIX,
    CLIENT_AI_KEY_LABEL_PREFIX,
)
from neutrino_hub.modules.clients.registry import Client, ClientRegistry
from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_LISTEN_HOST
from neutrino_hub.modules.devices.constants import (
    DEVICE_DISABLED_ACCOUNTS_KEY,
    DEVICE_ENABLED_ACCOUNTS_KEY,
    DEVICE_INSTANCE_GATEWAY_KEY,
    DEVICE_INSTANCE_GATEWAY_LABEL,
    DEVICE_MODULE_GATEWAY_KEY,
    DEVICE_MODULE_GATEWAY_LABEL,
)
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


def ensure_module_key(store, device_id: str, module: str, name: str) -> "str | None":
    """One container module's key material on one device, minting a key when it holds none.

    Args:
        store: The desired state store, whose file of the module holds the key.
        device_id: The device.
        module: The container module.
        name: What the device is called, for the key's label.

    Returns:
        The key material, or None while the vault is locked or the held key
        does not open.

    Raises:
        OSError: When the module's file cannot be written.
    """
    with CONFIG_WRITE_LOCK:
        held = store.read(device_id, module)
        key = CliproxyApiClientKey.from_stored(held.get(DEVICE_MODULE_GATEWAY_KEY))
        if key is not None:
            try:
                return key.open_key()
            except ValueError:
                return None
        label = DEVICE_MODULE_GATEWAY_LABEL.format(
            device=name or device_id, module=module
        )
        try:
            key = CliproxyApiClientKey.generated(label)
        except ValueError:
            return None
        store.write(
            device_id, module, {**held, DEVICE_MODULE_GATEWAY_KEY: key.to_dict()}
        )
    material = key.open_key()
    _apply(new_key=material)
    return material


def module_key(store, device_id: str, module: str) -> str:
    """One container module's key material on one device, minting none.

    Args:
        store: The desired state store.
        device_id: The device.
        module: The container module.

    Returns:
        The material; empty when the module's file holds no key or it does
        not open.
    """
    held = store.read(device_id, module)
    key = CliproxyApiClientKey.from_stored(held.get(DEVICE_MODULE_GATEWAY_KEY))
    if key is None:
        return ""
    try:
        return key.open_key()
    except ValueError:
        return ""


def revoke_module_key(store, device_id: str, module: str) -> None:
    """Void one container module's key on one device, and hand the gateway the change.

    Args:
        store: The desired state store.
        device_id: The device.
        module: The container module.

    Raises:
        OSError: When the module's file cannot be written.
    """
    with CONFIG_WRITE_LOCK:
        held = store.read(device_id, module)
        if DEVICE_MODULE_GATEWAY_KEY not in held:
            return
        held.pop(DEVICE_MODULE_GATEWAY_KEY)
        store.write(device_id, module, held)
    _apply()


def settle_instance_keys(store, device_id: str, module: str, name: str) -> None:
    """Give each enabled account of one module its own key, and void a disabled account's.

    Args:
        store: The desired state store, whose file of the module holds the
            accounts' records.
        device_id: The device.
        module: A program run as an account that uses the gateway.
        name: What the device is called, for each key's label.

    Raises:
        OSError: When the module's file cannot be written.
    """
    minted = []
    with CONFIG_WRITE_LOCK:
        held = store.read(device_id, module)
        written = dict(held)
        enabled = []
        for record in held.get(DEVICE_ENABLED_ACCOUNTS_KEY) or []:
            if not isinstance(record, dict) or not record.get("account"):
                continue
            record = dict(record)
            if CliproxyApiClientKey.from_stored(
                record.get(DEVICE_INSTANCE_GATEWAY_KEY)
            ):
                enabled.append(record)
                continue
            label = DEVICE_INSTANCE_GATEWAY_LABEL.format(
                device=name or device_id, module=module, account=record["account"]
            )
            try:
                key = CliproxyApiClientKey.generated(label)
            except ValueError:
                enabled.append(record)
                continue
            record[DEVICE_INSTANCE_GATEWAY_KEY] = key.to_dict()
            minted.append(key)
            enabled.append(record)
        written[DEVICE_ENABLED_ACCOUNTS_KEY] = enabled
        disabled = [
            {
                field: value
                for field, value in record.items()
                if field != DEVICE_INSTANCE_GATEWAY_KEY
            }
            for record in held.get(DEVICE_DISABLED_ACCOUNTS_KEY) or []
            if isinstance(record, dict)
        ]
        if disabled:
            written[DEVICE_DISABLED_ACCOUNTS_KEY] = disabled
        if written == held:
            return
        store.write(device_id, module, written)
    _apply(new_key=minted[-1].open_key() if minted else None)


def revoke_instance_keys(store, device_id: str, module: str) -> None:
    """Void every account's key of one module on one device, and hand the gateway the change.

    Args:
        store: The desired state store.
        device_id: The device.
        module: A program run as an account that uses the gateway.

    Raises:
        OSError: When the module's file cannot be written.
    """
    with CONFIG_WRITE_LOCK:
        held = store.read(device_id, module)
        written = dict(held)
        is_changed = False
        for group in (DEVICE_ENABLED_ACCOUNTS_KEY, DEVICE_DISABLED_ACCOUNTS_KEY):
            records = []
            for record in held.get(group) or []:
                if isinstance(record, dict) and DEVICE_INSTANCE_GATEWAY_KEY in record:
                    record = {
                        field: value
                        for field, value in record.items()
                        if field != DEVICE_INSTANCE_GATEWAY_KEY
                    }
                    is_changed = True
                records.append(record)
            if group in held:
                written[group] = records
        if not is_changed:
            return
        store.write(device_id, module, written)
    _apply()


def instance_key(record: dict) -> str:
    """One enabled account's key material, minting none.

    Args:
        record: The account's record in the module's file.

    Returns:
        The material; empty when the record holds no key or it does not
        open.
    """
    key = CliproxyApiClientKey.from_stored(record.get(DEVICE_INSTANCE_GATEWAY_KEY))
    if key is None:
        return ""
    try:
        return key.open_key()
    except ValueError:
        return ""


def apply_keys() -> None:
    """Hand the gateway the keys as they stand, after a file that held some went away."""
    _apply()


def device_gateway(device_id: str, *, is_hub_machine: bool = False) -> dict:
    """Where one device's AI tools reach the gateway, and with which key.

    Args:
        device_id: The device.
        is_hub_machine: Whether the device is the hub's own machine, whose
            tools reach the gateway itself on its loopback port.

    Returns:
        ``{gateway_url, gateway_key}``: ``http://127.0.0.1:8317``, the
        agent's AI gateway forward, or ``http://127.0.0.1:<listen-port>``
        on the hub's own machine, and the device's key; both empty while
        the device holds no key or its key does not open.
    """
    held = load_config()
    key = held.device_keys.get(device_id)
    if key is None:
        return {"gateway_url": "", "gateway_key": ""}
    try:
        material = key.open_key()
    except ValueError:
        return {"gateway_url": "", "gateway_key": ""}
    url = CLIENT_AI_DEVICE_FORWARD_URL
    if is_hub_machine:
        url = f"http://{CLIPROXYAPI_LISTEN_HOST}:{held.listen_port}"
    return {"gateway_url": url, "gateway_key": material}


def gateway_port() -> int:
    """The port the gateway listens on, on the hub's loopback.

    Returns:
        The gateway's ``listen_port``.
    """
    return load_config().listen_port


def gateway_models(served_models) -> list:
    """The names the gateway serves now, probed with the hub's own key.

    Args:
        served_models: The shared
            :class:`neutrino_hub.modules.cliproxyapi.ops.CliproxyApiServedModelCache`.

    Returns:
        The served names, the last list that held a name while the probe
        fails or finds no name; empty while the gateway has no hub key or
        the key does not open.
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
