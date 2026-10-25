"""Hermes WebUI on the hub: its file, the configuration the state sends, and its two containers.

The file is ``config/devices/<id>/hermes_webui.json``: ``port``, the
forwarder's, 8787 unless the person sets another; the token secret and the
webui's password, generated the first time the module is installed or its
port is set and sealed under the vault's data key; and the module's gateway
key. The state carries ``{port, secret, password}`` opened, and the name
of the webui's login cookie on the device. The module runs two hub
containers on Containers: the agent's gateway first, then the webui, which
starts after it and whose 8787 the module's forwarder serves.

Pure apart from the module's file, read and written through the store.
"""

import secrets

from neutrino_hub.modules.clients.ai_keys import gateway_port, module_key
from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.modules.devices.constants import (
    DEVICE_CONTAINER_GATEWAY_FORWARD_PORT,
    DEVICE_CONTAINER_GATEWAY_URL,
    DEVICE_HERMES_WEBUI_AGENT_COMMAND,
    DEVICE_HERMES_WEBUI_COOKIE_ID_CHARS,
    DEVICE_HERMES_WEBUI_COOKIE_PREFIX,
    DEVICE_HERMES_WEBUI_AGENT_CONTAINER,
    DEVICE_HERMES_WEBUI_AGENT_IMAGE,
    DEVICE_HERMES_WEBUI_AGENT_VOLUMES,
    DEVICE_HERMES_WEBUI_DEFAULT_PORT,
    DEVICE_HERMES_WEBUI_MODULE,
    DEVICE_HERMES_WEBUI_PAGE_PORT,
    DEVICE_HERMES_WEBUI_PORT_MAX,
    DEVICE_HERMES_WEBUI_PORT_MIN,
    DEVICE_HERMES_WEBUI_STATE_DIR,
    DEVICE_HERMES_WEBUI_UID,
    DEVICE_HERMES_WEBUI_WEBUI_CONTAINER,
    DEVICE_HERMES_WEBUI_WEBUI_IMAGE,
    DEVICE_HERMES_WEBUI_WEBUI_VOLUMES,
)
from neutrino_hub.modules.devices.hub_containers import (
    HUB_CONTAINER_COMPOSERS,
    HubContainer,
    HubContainerRequest,
)
from neutrino_hub.modules.devices.module_table import module_row
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK


def is_port_valid(port) -> bool:
    """Whether a port is one the forwarder may listen on.

    Args:
        port: What was asked for.

    Returns:
        True for an integer from 1024 to 65535.
    """
    return (
        isinstance(port, int)
        and not isinstance(port, bool)
        and DEVICE_HERMES_WEBUI_PORT_MIN <= port <= DEVICE_HERMES_WEBUI_PORT_MAX
    )


def stored_port(stored: dict) -> int:
    """The forwarder's port the module's file holds, 8787 when it holds none.

    Args:
        stored: The module's file.

    Returns:
        The port.
    """
    port = stored.get("port")
    return port if is_port_valid(port) else DEVICE_HERMES_WEBUI_DEFAULT_PORT


def ensure_config(store, key: str, *, port: "int | None" = None) -> dict:
    """Write the module's file with its port and both secrets, generating a secret it lacks.

    Args:
        store: The desired state store.
        key: The device.
        port: The forwarder's port; None keeps the stored one, 8787 when
            the file holds none.

    Returns:
        The file as it stands afterwards.

    Raises:
        ValueError: For a port outside 1024 to 65535.
        VaultLockedError: When a secret is missing and there is no data key
            to seal one under.
        OSError: When the file cannot be written.
    """
    if port is not None and not is_port_valid(port):
        raise ValueError(f"port {port!r} is outside 1024 to 65535")
    row = module_row(DEVICE_HERMES_WEBUI_MODULE)
    with CONFIG_WRITE_LOCK:
        held = store.read(key, DEVICE_HERMES_WEBUI_MODULE)
        written = dict(held)
        written["port"] = port if port is not None else stored_port(held)
        for sealed in row.sealed_fields:
            current = held.get(sealed.key)
            if isinstance(current, dict) and current:
                continue
            written[sealed.key] = seal_bytes(
                secrets.token_urlsafe(sealed.secret_bytes).encode(), sealed.aad
            )
        if written != held:
            store.write(key, DEVICE_HERMES_WEBUI_MODULE, written)
    return written


def cookie_name(key: str) -> str:
    """The name of the webui's login cookie on one device.

    Args:
        key: The device.

    Returns:
        ``hermes_session_`` and the first 12 characters of the device id.
    """
    return DEVICE_HERMES_WEBUI_COOKIE_PREFIX + key[:DEVICE_HERMES_WEBUI_COOKIE_ID_CHARS]


def agent_config(stored: dict, key: str) -> dict:
    """What the agent is sent for Hermes WebUI.

    Args:
        stored: The module's file.
        key: The device.

    Returns:
        ``{port, secret, password, cookie_name}``, each secret opened, empty
        when the file holds none or the vault cannot open it.
    """
    config = {"port": stored_port(stored)}
    for sealed in module_row(DEVICE_HERMES_WEBUI_MODULE).sealed_fields:
        config[sealed.opened_key] = _opened(stored.get(sealed.key), sealed.aad)
    config["cookie_name"] = cookie_name(key)
    return config


def gateway_url(*, is_hub_machine: bool) -> str:
    """Where the module's containers reach the AI gateway.

    Args:
        is_hub_machine: Whether the device is the hub's own machine.

    Returns:
        ``http://host.containers.internal:8317``, the agent's forward, on a
        managed machine; the gateway's own ``listen_port`` in place of 8317
        on the hub's machine.
    """
    port = gateway_port() if is_hub_machine else DEVICE_CONTAINER_GATEWAY_FORWARD_PORT
    return DEVICE_CONTAINER_GATEWAY_URL.format(port=port)


def compose_containers(request: HubContainerRequest) -> tuple:
    """The module's two hub containers on one machine.

    Args:
        request: The store, the device, and whether it is the hub's machine.

    Returns:
        The agent container, then the webui; none while the webui's password
        does not open, so no webui runs without its own login.
    """
    config = agent_config(
        request.store.read(request.key, DEVICE_HERMES_WEBUI_MODULE), request.key
    )
    if not config["password"]:
        return ()
    gateway = (
        f"NEUTRINO_GATEWAY_URL={gateway_url(is_hub_machine=request.is_hub_machine)}",
        "NEUTRINO_GATEWAY_KEY="
        + module_key(request.store, request.key, DEVICE_HERMES_WEBUI_MODULE),
    )
    agent = HubContainer(
        name=DEVICE_HERMES_WEBUI_AGENT_CONTAINER,
        image=DEVICE_HERMES_WEBUI_AGENT_IMAGE,
        volumes=DEVICE_HERMES_WEBUI_AGENT_VOLUMES,
        environment=(
            f"HERMES_UID={DEVICE_HERMES_WEBUI_UID}",
            f"HERMES_GID={DEVICE_HERMES_WEBUI_UID}",
            *gateway,
        ),
        command=DEVICE_HERMES_WEBUI_AGENT_COMMAND,
    )
    webui = HubContainer(
        name=DEVICE_HERMES_WEBUI_WEBUI_CONTAINER,
        image=DEVICE_HERMES_WEBUI_WEBUI_IMAGE,
        volumes=DEVICE_HERMES_WEBUI_WEBUI_VOLUMES,
        environment=(
            f"WANTED_UID={DEVICE_HERMES_WEBUI_UID}",
            f"WANTED_GID={DEVICE_HERMES_WEBUI_UID}",
            f"HERMES_WEBUI_STATE_DIR={DEVICE_HERMES_WEBUI_STATE_DIR}",
            f"HERMES_WEBUI_PASSWORD={config['password']}",
            f"HERMES_WEBUI_COOKIE_NAME={config['cookie_name']}",
            *gateway,
        ),
        after=(DEVICE_HERMES_WEBUI_AGENT_CONTAINER,),
        page_port=DEVICE_HERMES_WEBUI_PAGE_PORT,
    )
    return (agent, webui)


def _opened(sealed, aad: bytes) -> str:
    """A sealed string opened, empty when there is none or it does not open."""
    if not isinstance(sealed, dict) or not sealed:
        return ""
    try:
        return unseal_bytes(sealed, aad).decode()
    except ValueError:
        return ""


HUB_CONTAINER_COMPOSERS[DEVICE_HERMES_WEBUI_MODULE] = compose_containers
