"""Ayakaleaf on the hub: its file, the configuration the state sends, and its three containers.

The file is ``config/devices/<id>/ayakaleaf.json``: the token secret, the
administrator's password and the app's session and invitation secrets,
generated the first time the module is installed and sealed under the
vault's data key, the module's gateway key, and ``model``, the tab's AI
model, empty for the gateway's first. The state carries ``{secret,
password, cookie_name, local_name, guests}`` opened: the name of the app's
session cookie on the device, the app's local name, which its forwarder
checks the ``Host`` against, and the guest account of each live Web share
of the app. The forwarder's port is the agent's. The module runs three hub
containers on Containers: MongoDB and Redis first, then the app, which
starts after both and whose 80 the module's forwarder serves.

Pure apart from the module's file, read and written through the store.
"""

import secrets

from neutrino_hub.modules.clients.ai_keys import module_key
from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.modules.devices.constants import (
    DEVICE_AYAKALEAF_AI_PATH,
    DEVICE_AYAKALEAF_APP_CONTAINER,
    DEVICE_AYAKALEAF_APP_ENVIRONMENT,
    DEVICE_AYAKALEAF_APP_IMAGE,
    DEVICE_AYAKALEAF_APP_STOP_TIMEOUT_S,
    DEVICE_AYAKALEAF_APP_SUCCESS_EXIT_CODES,
    DEVICE_AYAKALEAF_APP_VOLUMES,
    DEVICE_AYAKALEAF_COOKIE_ID_CHARS,
    DEVICE_AYAKALEAF_COOKIE_PREFIX,
    DEVICE_AYAKALEAF_INVITE_SECRET_KEY,
    DEVICE_AYAKALEAF_MODEL_KEY,
    DEVICE_AYAKALEAF_MODULE,
    DEVICE_AYAKALEAF_MONGO_COMMAND,
    DEVICE_AYAKALEAF_MONGO_CONTAINER,
    DEVICE_AYAKALEAF_MONGO_IMAGE,
    DEVICE_AYAKALEAF_MONGO_VOLUMES,
    DEVICE_AYAKALEAF_PAGE_PORT,
    DEVICE_AYAKALEAF_PASSWORD_KEY,
    DEVICE_AYAKALEAF_REDIS_COMMAND,
    DEVICE_AYAKALEAF_REDIS_CONTAINER,
    DEVICE_AYAKALEAF_REDIS_IMAGE,
    DEVICE_AYAKALEAF_REDIS_VOLUMES,
    DEVICE_AYAKALEAF_SECRET_KEY,
    DEVICE_AYAKALEAF_SESSION_SECRET_KEY,
)
from neutrino_hub.modules.devices.hermes_webui import gateway_url
from neutrino_hub.modules.devices.hub_containers import (
    HUB_CONTAINER_COMPOSERS,
    HubContainer,
    HubContainerRequest,
)
from neutrino_hub.modules.devices.module_table import module_row
from neutrino_hub.modules.services.constants import SERVICES_AYAKALEAF_ID
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK

# The sealed fields the state carries opened; the session and invitation
# secrets go into the app's environment alone.
STATE_FIELDS = (DEVICE_AYAKALEAF_SECRET_KEY, DEVICE_AYAKALEAF_PASSWORD_KEY)


def ensure_config(store, key: str) -> dict:
    """Write the module's file with its four secrets, generating a secret it lacks.

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
    row = module_row(DEVICE_AYAKALEAF_MODULE)
    with CONFIG_WRITE_LOCK:
        held = store.read(key, DEVICE_AYAKALEAF_MODULE)
        written = dict(held)
        for sealed in row.sealed_fields:
            current = held.get(sealed.key)
            if isinstance(current, dict) and current:
                continue
            written[sealed.key] = seal_bytes(
                secrets.token_urlsafe(sealed.secret_bytes).encode(), sealed.aad
            )
        if written != held:
            store.write(key, DEVICE_AYAKALEAF_MODULE, written)
    return written


def cookie_name(key: str) -> str:
    """The name of the app's session cookie on one device.

    Args:
        key: The device.

    Returns:
        ``ayakaleaf_sid_`` and the first 12 characters of the device id.
    """
    return DEVICE_AYAKALEAF_COOKIE_PREFIX + key[:DEVICE_AYAKALEAF_COOKIE_ID_CHARS]


def app_id(key: str) -> str:
    """The id of the app the module's page is on one device, ``ayakaleaf_<device id>``."""
    return f"{SERVICES_AYAKALEAF_ID}_{key}"


def share_guests(key: str) -> list:
    """The guest accounts of the live Web shares of the app on one device.

    Args:
        key: The device.

    Returns:
        ``[{account, email, password, secret}]`` opened, in the shares'
        order; none while the hub has no Web share module or the vault is
        locked.
    """
    try:
        from neutrino_hub.modules.clients import web_shares
    except ImportError:
        return []
    return [
        {
            "account": str(guest.get("account", "") or ""),
            "email": str(guest.get("email", "") or ""),
            "password": str(guest.get("password", "") or ""),
            "secret": str(guest.get("secret", "") or ""),
        }
        for guest in web_shares.guest_accounts(key, app_id(key))
        if isinstance(guest, dict)
    ]


def agent_config(
    stored: dict, key: str, *, local_name: str = "", guests: "list | None" = None
) -> dict:
    """What the agent is sent for Ayakaleaf.

    Args:
        stored: The module's file.
        key: The device.
        local_name: The app's local name, which the forwarder checks the
            ``Host`` against.
        guests: The guest accounts of the app's live Web shares; None
            reads them from the Web share module.

    Returns:
        ``{secret, password, cookie_name, local_name, guests}``, each
        secret opened, empty when the file holds none or the vault cannot
        open it.
    """
    row = module_row(DEVICE_AYAKALEAF_MODULE)
    config = {}
    for name in STATE_FIELDS:
        sealed = row.sealed_field(name)
        config[sealed.opened_key] = _opened(stored.get(sealed.key), sealed.aad)
    config["cookie_name"] = cookie_name(key)
    config["local_name"] = local_name
    config["guests"] = list(guests) if guests is not None else share_guests(key)
    return config


def chosen_model(stored: dict, models) -> str:
    """The model the app's AI assistant uses.

    Args:
        stored: The module's file.
        models: The names the gateway serves now.

    Returns:
        The tab's model, or the first model the gateway serves while the
        tab names none; empty while the gateway serves none.
    """
    served = [str(model) for model in models or () if model]
    if not served:
        return ""
    return str(stored.get(DEVICE_AYAKALEAF_MODEL_KEY, "") or "") or served[0]


def compose_containers(request: HubContainerRequest) -> tuple:
    """The module's three hub containers on one machine.

    Args:
        request: The store, the device, whether it is the hub's machine,
            and the models the gateway serves.

    Returns:
        MongoDB, Redis, then the app; none while a secret of the app does
        not open, so no app runs without its own login and sessions.
    """
    stored = request.store.read(request.key, DEVICE_AYAKALEAF_MODULE)
    row = module_row(DEVICE_AYAKALEAF_MODULE)
    opened = {
        sealed.key: _opened(stored.get(sealed.key), sealed.aad)
        for sealed in row.sealed_fields
    }
    if not all(opened.values()):
        return ()
    url = gateway_url(is_hub_machine=request.is_hub_machine)
    key = module_key(request.store, request.key, DEVICE_AYAKALEAF_MODULE)
    environment = [
        *DEVICE_AYAKALEAF_APP_ENVIRONMENT,
        f"OVERLEAF_SESSION_SECRET={opened[DEVICE_AYAKALEAF_SESSION_SECRET_KEY]}",
        f"OVERLEAF_INVITE_TOKEN_SECRET={opened[DEVICE_AYAKALEAF_INVITE_SECRET_KEY]}",
        f"COOKIE_NAME={cookie_name(request.key)}",
        f"NEUTRINO_GATEWAY_URL={url}",
        f"NEUTRINO_GATEWAY_KEY={key}",
    ]
    model = chosen_model(stored, request.models)
    if model and key:
        environment += [
            "AI_ENABLED=true",
            f"AI_BASE_URL={url}{DEVICE_AYAKALEAF_AI_PATH}",
            f"AI_API_KEY={key}",
            f"AI_MODEL={model}",
        ]
    mongo = HubContainer(
        name=DEVICE_AYAKALEAF_MONGO_CONTAINER,
        image=DEVICE_AYAKALEAF_MONGO_IMAGE,
        volumes=DEVICE_AYAKALEAF_MONGO_VOLUMES,
        command=DEVICE_AYAKALEAF_MONGO_COMMAND,
    )
    redis = HubContainer(
        name=DEVICE_AYAKALEAF_REDIS_CONTAINER,
        image=DEVICE_AYAKALEAF_REDIS_IMAGE,
        volumes=DEVICE_AYAKALEAF_REDIS_VOLUMES,
        command=DEVICE_AYAKALEAF_REDIS_COMMAND,
    )
    app = HubContainer(
        name=DEVICE_AYAKALEAF_APP_CONTAINER,
        image=DEVICE_AYAKALEAF_APP_IMAGE,
        volumes=DEVICE_AYAKALEAF_APP_VOLUMES,
        environment=tuple(environment),
        after=(DEVICE_AYAKALEAF_MONGO_CONTAINER, DEVICE_AYAKALEAF_REDIS_CONTAINER),
        page_port=DEVICE_AYAKALEAF_PAGE_PORT,
        stop_timeout_s=DEVICE_AYAKALEAF_APP_STOP_TIMEOUT_S,
        success_exit_codes=DEVICE_AYAKALEAF_APP_SUCCESS_EXIT_CODES,
    )
    return (mongo, redis, app)


def _opened(sealed, aad: bytes) -> str:
    """A sealed string opened, empty when there is none or it does not open."""
    if not isinstance(sealed, dict) or not sealed:
        return ""
    try:
        return unseal_bytes(sealed, aad).decode()
    except ValueError:
        return ""


HUB_CONTAINER_COMPOSERS[DEVICE_AYAKALEAF_MODULE] = compose_containers
