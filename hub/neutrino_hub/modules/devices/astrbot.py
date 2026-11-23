"""AstrBot on the hub: its file, the configuration the state sends, and its container.

The file is ``config/devices/<id>/astrbot.json``: the token secret and the
password of AstrBot's dashboard user, generated the first time the module is
installed and sealed under the vault's data key, and the module's gateway
key. The state carries ``{secret, password, cookie_name, local_name,
model}``, the secrets opened: the name of the forwarder's login cookie, the
app's local name, which its forwarder checks the ``Host`` against, and the
default model, which the agent writes into AstrBot's settings. The
forwarder's port is the agent's. The module runs one hub container on
Containers, whose 6185 the module's forwarder serves.

Pure apart from the module's file, read and written through the store, and
the gateway's file, which names the default model.
"""

import secrets

from neutrino_hub.modules.ai.context_lengths import one_numbers
from neutrino_hub.modules.clients.ai_keys import gateway_default_model, module_key
from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.modules.devices.constants import (
    DEVICE_ASTRBOT_CONTAINER,
    DEVICE_ASTRBOT_ENVIRONMENT,
    DEVICE_ASTRBOT_IMAGE,
    DEVICE_ASTRBOT_LOCAL_PORTS,
    DEVICE_ASTRBOT_MODULE,
    DEVICE_ASTRBOT_PAGE_PORT,
    DEVICE_ASTRBOT_PASSWORD_KEY,
    DEVICE_ASTRBOT_PASSWORD_MIN_CHARS,
    DEVICE_ASTRBOT_STOP_SIGNAL,
    DEVICE_ASTRBOT_VOLUMES,
)
from neutrino_hub.modules.devices.hermes_webui import gateway_url
from neutrino_hub.modules.devices.hub_containers import (
    HUB_CONTAINER_COMPOSERS,
    HubContainer,
    HubContainerRequest,
)
from neutrino_hub.modules.devices.module_table import module_row
from neutrino_hub.modules.services.apps import cookie_name, entry_id
from neutrino_hub.modules.services.constants import (
    SERVICES_ASTRBOT_ID,
    SERVICES_ENTRY_WEB,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK


def is_password_allowed(password: str) -> bool:
    """Whether AstrBot takes a dashboard password.

    Args:
        password: The password.

    Returns:
        True for at least 8 characters with an upper-case letter, a
        lower-case letter and a digit.
    """
    return (
        len(password) >= DEVICE_ASTRBOT_PASSWORD_MIN_CHARS
        and any(character.isupper() for character in password)
        and any(character.islower() for character in password)
        and any(character.isdigit() for character in password)
    )


def new_password(secret_bytes: int) -> str:
    """A fresh dashboard password AstrBot takes.

    Args:
        secret_bytes: How many random bytes it is made of.

    Returns:
        Random bytes in base64url, drawn again until AstrBot's rule holds.
    """
    while True:
        password = secrets.token_urlsafe(secret_bytes)
        if is_password_allowed(password):
            return password


def ensure_config(store, key: str) -> dict:
    """Write the module's file with both secrets, generating a secret it lacks.

    Args:
        store: The desired state store.
        key: The device.

    Returns:
        The file as it stands afterwards.

    Raises:
        VaultLockedError: When a secret is missing and there is no data key
            to seal one under.
        OSError: When the file cannot be written.
    """
    row = module_row(DEVICE_ASTRBOT_MODULE)
    with CONFIG_WRITE_LOCK:
        held = store.read(key, DEVICE_ASTRBOT_MODULE)
        written = dict(held)
        for sealed in row.sealed_fields:
            current = held.get(sealed.key)
            if isinstance(current, dict) and current:
                continue
            if sealed.key == DEVICE_ASTRBOT_PASSWORD_KEY:
                value = new_password(sealed.secret_bytes)
            else:
                value = secrets.token_urlsafe(sealed.secret_bytes)
            written[sealed.key] = seal_bytes(value.encode(), sealed.aad)
        if written != held:
            store.write(key, DEVICE_ASTRBOT_MODULE, written)
    return written


def agent_config(
    stored: dict,
    key: str,
    *,
    local_name: str = "",
    models: "list | tuple" = (),
    context_lengths: "dict | None" = None,
) -> dict:
    """What the agent is sent for AstrBot.

    Args:
        stored: The module's file.
        key: The device.
        local_name: The app's local name, which the forwarder checks the
            ``Host`` against.
        models: The names the gateway serves now.
        context_lengths: Each served name's ``{context_length, input_limit,
            output_limit}``; None names none.

    Returns:
        ``{secret, password, cookie_name, local_name, model,
        context_length}``, each secret opened, empty when the file holds
        none or the vault cannot open it; ``cookie_name`` the entry's,
        ``model`` the default model, empty while no name is served, and
        ``context_length`` the default model's one number, 0 while there is
        no model.
    """
    config = {}
    for sealed in module_row(DEVICE_ASTRBOT_MODULE).sealed_fields:
        config[sealed.opened_key] = _opened(stored.get(sealed.key), sealed.aad)
    config["cookie_name"] = cookie_name(
        entry_id(f"{SERVICES_ASTRBOT_ID}_{key}", SERVICES_ENTRY_WEB)
    )
    config["local_name"] = local_name
    config["model"] = gateway_default_model(models)
    config["context_length"] = one_numbers([config["model"]], context_lengths).get(
        config["model"], 0
    )
    return config


def compose_containers(request: HubContainerRequest) -> tuple:
    """The module's one hub container on one machine.

    Args:
        request: The store, the device, and whether it is the hub's machine.

    Returns:
        The container; none while the dashboard's password does not open,
        so no AstrBot runs without its own login.
    """
    config = agent_config(
        request.store.read(request.key, DEVICE_ASTRBOT_MODULE), request.key
    )
    if not config["password"]:
        return ()
    astrbot = HubContainer(
        name=DEVICE_ASTRBOT_CONTAINER,
        image=DEVICE_ASTRBOT_IMAGE,
        volumes=DEVICE_ASTRBOT_VOLUMES,
        environment=(
            *DEVICE_ASTRBOT_ENVIRONMENT,
            f"NEUTRINO_GATEWAY_URL={gateway_url(is_hub_machine=request.is_hub_machine)}",
            "NEUTRINO_GATEWAY_KEY="
            + module_key(request.store, request.key, DEVICE_ASTRBOT_MODULE),
        ),
        page_port=DEVICE_ASTRBOT_PAGE_PORT,
        local_ports=DEVICE_ASTRBOT_LOCAL_PORTS,
        stop_signal=DEVICE_ASTRBOT_STOP_SIGNAL,
    )
    return (astrbot,)


def _opened(sealed, aad: bytes) -> str:
    """A sealed string opened, empty when there is none or it does not open."""
    if not isinstance(sealed, dict) or not sealed:
        return ""
    try:
        return unseal_bytes(sealed, aad).decode()
    except ValueError:
        return ""


HUB_CONTAINER_COMPOSERS[DEVICE_ASTRBOT_MODULE] = compose_containers
