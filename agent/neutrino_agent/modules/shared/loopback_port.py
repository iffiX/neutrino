"""A port on loopback the agent takes for one of its listeners or instances.

The agent picks the ports a person never sees: each instance of a program
run as an account, Gitea's own SSH server, Hermes WebUI's forwarder. A port
is free when a listener can bind it on ``127.0.0.1`` now, and the pick is
the first free one from a module's base port up, past the ports the module
already keeps for another of its instances. The page behind a forwarder takes
its port from ``AGENT_PAGE_PORT_BASE`` up, past the ports any module keeps for
a page.

Not pure: binds and connects sockets to test them, and reads the modules' files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import socket
import threading

from neutrino_agent.constants import (
    AGENT_FORWARD_LISTEN_HOST,
    AGENT_PAGE_PORT_BASE,
    AGENT_PAGE_PORT_FIELDS,
    AGENT_PAGE_PORTS_NAME,
)
from neutrino_agent.modules.shared.record_store import RECORD_FILES_LOCK

# The highest port a pick reaches.
LOOPBACK_PORT_MAX = 65535
# How long a connection to a loopback listener may take to open.
LOOPBACK_CONNECT_TIMEOUT_S = 1.0
# The end of the name of every file a module keeps a page's port in.
KEPT_FILE_SUFFIX = ".json"

# The page ports picked since the agent started, by state root. A task picks a
# port before its service starts and keeps it in the record after, and another
# module's task picks meanwhile.
_PICKED_PAGE_PORTS: dict = {}
_PICK_LOCK = threading.Lock()


def is_port_free(port: int, host: str = AGENT_FORWARD_LISTEN_HOST) -> bool:
    """Whether a listener can bind one port on loopback now.

    The test binds as the forwarders bind: with ``SO_REUSEADDR`` off
    Windows, so a port whose last connections linger in ``TIME_WAIT`` reads
    free, and a port another program listens on does not.

    Args:
        port: The port.
        host: The address to bind.

    Returns:
        True when the bind succeeds.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name != "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, int(port)))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def is_port_refused(port: int, host: str = AGENT_FORWARD_LISTEN_HOST) -> bool:
    """Whether the system refuses every listener on one loopback port now.

    A bind on a port Windows reserved fails with a permission error. A bind on a
    port another program listens on fails with a port in use.

    Args:
        port: The port.
        host: The address to bind.

    Returns:
        True when the bind fails with a permission error.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, int(port)))
    except PermissionError:
        return True
    except OSError:
        return False
    finally:
        probe.close()
    return False


def is_listening(port: int, host: str = AGENT_FORWARD_LISTEN_HOST) -> bool:
    """Whether a listener on loopback accepts a connection on one port now.

    Args:
        port: The port.
        host: The address to connect to.

    Returns:
        True when the connection opens; it is closed at once.
    """
    try:
        with socket.create_connection(
            (host, int(port)), timeout=LOOPBACK_CONNECT_TIMEOUT_S
        ):
            return True
    except OSError:
        return False


def pick_port(base: int, *, taken=(), is_free=is_port_free) -> int:
    """The first free port from a base up, past the ports already taken.

    Args:
        base: The module's base port.
        taken: Ports kept for something else, never picked.
        is_free: Answers whether a port can be bound now.

    Returns:
        The port.

    Raises:
        ValueError: For a base outside 1 to 65535.
        OSError: When no port from the base up is free.
    """
    if not 1 <= int(base) <= LOOPBACK_PORT_MAX:
        raise ValueError(f"base port {base!r}")
    held = {int(port) for port in taken}
    for port in range(int(base), LOOPBACK_PORT_MAX + 1):
        if port not in held and is_free(port):
            return port
    raise OSError(f"no free port from {base} up")


def kept_page_ports(state_root: str) -> set:
    """Every port a module keeps for the page behind its forwarder.

    Args:
        state_root: The directory holding each module's directory.

    Returns:
        The ports of each module's ``page_ports.json`` and the page port
        fields of its other files; a file that does not read holds none.
    """
    kept: set = set()
    try:
        modules = os.listdir(state_root)
    except OSError:
        return kept
    for module in modules:
        directory = os.path.join(state_root, module)
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if name.endswith(KEPT_FILE_SUFFIX) and not name.startswith("."):
                kept.update(_ports_of_file(os.path.join(directory, name), name))
    return kept


def pick_page_port(state_root: str, *, is_free=is_port_free) -> int:
    """The first free port from ``AGENT_PAGE_PORT_BASE`` up for the page behind a forwarder.

    Args:
        state_root: The directory holding each module's directory.
        is_free: Answers whether a port can be bound now.

    Returns:
        The port, past the ports any module keeps and the ports picked before.

    Raises:
        OSError: When no port from the base up is free.
    """
    with _PICK_LOCK:
        picked = _PICKED_PAGE_PORTS.setdefault(state_root, set())
        port = pick_port(
            AGENT_PAGE_PORT_BASE,
            taken=kept_page_ports(state_root) | picked,
            is_free=is_free,
        )
        picked.add(port)
    return port


def _ports_of_file(path: str, name: str) -> list:
    """The page ports one file of a module keeps, none for a file that does not read."""
    try:
        with RECORD_FILES_LOCK, open(path, "r", encoding="utf-8") as stream:
            held = json.load(stream)
    except (OSError, ValueError):
        return []
    if not isinstance(held, dict):
        return []
    values = (
        held.values()
        if name == AGENT_PAGE_PORTS_NAME
        else [held.get(field) for field in AGENT_PAGE_PORT_FIELDS]
    )
    return [
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
