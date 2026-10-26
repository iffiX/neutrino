"""A port on loopback the agent takes for one of its listeners or instances.

The agent picks the ports a person never sees: each instance of a program
run as an account, Gitea's own SSH server, Hermes WebUI's forwarder. A port
is free when a listener can bind it on ``127.0.0.1`` now, and the pick is
the first free one from a module's base port up, past the ports the module
already keeps for another of its instances.

Not pure: binds sockets to test them.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import socket

from neutrino_agent.constants import AGENT_FORWARD_LISTEN_HOST

# The highest port a pick reaches.
LOOPBACK_PORT_MAX = 65535


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
