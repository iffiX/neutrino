"""The hub's own identity: the id peers group it by and the name they show.

``config/web/identity.json`` is ``{id, name}``. The id is generated once and
never changes; the name defaults to the hostname and the Settings page
changes it.
"""

import socket
import uuid

from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK, read_config, write_config
from neutrino_hub.web.constants import WEB_IDENTITY_FILE


def ensure_hub_identity() -> bool:
    """Write the identity file once; an existing file is left alone.

    Returns:
        True when the file was written.

    Raises:
        ValueError: If an existing file is not valid JSON.
        OSError: If the file cannot be written.
    """
    with CONFIG_WRITE_LOCK:
        try:
            read_config(WEB_IDENTITY_FILE)
        except FileNotFoundError:
            write_config(
                WEB_IDENTITY_FILE,
                {"id": uuid.uuid4().hex, "name": socket.gethostname()},
            )
            return True
    return False


def hub_id() -> str:
    """The id this hub is grouped by.

    Returns:
        The uuid4 hex string the identity file holds.

    Raises:
        FileNotFoundError: If the identity file is missing.
        ValueError: If it is not valid JSON.
    """
    return str(read_config(WEB_IDENTITY_FILE).get("id", ""))


def hub_name() -> str:
    """The name this hub is shown as.

    Returns:
        The name the identity file holds.

    Raises:
        FileNotFoundError: If the identity file is missing.
        ValueError: If it is not valid JSON.
    """
    return str(read_config(WEB_IDENTITY_FILE).get("name", ""))


def set_hub_name(name: str) -> None:
    """Change the name and nothing else.

    Args:
        name: The name to show; surrounding whitespace is dropped.

    Raises:
        ValueError: If the name is blank, or the file is not valid JSON.
        FileNotFoundError: If the identity file is missing.
        OSError: If the file cannot be written.
    """
    stripped = name.strip()
    if not stripped:
        raise ValueError("a hub name cannot be blank")
    with CONFIG_WRITE_LOCK:
        identity = read_config(WEB_IDENTITY_FILE)
        identity["name"] = stripped
        write_config(WEB_IDENTITY_FILE, identity)
