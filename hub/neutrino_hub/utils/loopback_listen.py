"""The IPv6 loopback a listener a browser opens binds beside its IPv4 address.

A browser reaches ``localhost`` on ``::1`` before ``127.0.0.1``. A listener
holding ``[::1]`` at its own port leaves no program of another account a
place to answer there first.

Not pure: binds sockets.
"""

import ipaddress
import os
import socket

from neutrino_hub.utils.constants import UTILS_LOOPBACK_IPV6


def has_ipv6_loopback() -> bool:
    """Whether the machine has the IPv6 loopback address.

    Returns:
        True when a TCP socket binds ``[::1]``.
    """
    try:
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        probe.bind((UTILS_LOOPBACK_IPV6, 0))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def is_ipv4_host(host: str) -> bool:
    """Whether a listen address is an IPv4 address.

    Args:
        host: The address, such as ``0.0.0.0`` or ``::``.

    Returns:
        True for an IPv4 address.
    """
    try:
        return ipaddress.ip_address(host).version == 4
    except ValueError:
        return False


def with_ipv6_loopback(host: str, is_ipv6=has_ipv6_loopback) -> list:
    """The addresses a listener a browser opens binds.

    Args:
        host: The address the listener binds first.
        is_ipv6: Says whether the machine has the IPv6 loopback.

    Returns:
        ``[host]``, and ``::1`` after it when ``host`` is an IPv4 address
        and the machine has the IPv6 loopback.
    """
    if is_ipv4_host(host) and is_ipv6():
        return [host, UTILS_LOOPBACK_IPV6]
    return [host]


def bind_ipv6_loopback(port: int) -> socket.socket:
    """A TCP socket bound to ``[::1]`` at a port, for a server to listen on.

    Args:
        port: The port.

    Returns:
        The bound socket, IPv6 alone, inheritable, with address reuse off
        Windows as uvicorn binds its own.

    Raises:
        OSError: When another program holds ``[::1]`` at the port.
    """
    held = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        held.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        if os.name != "nt":
            held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind((UTILS_LOOPBACK_IPV6, port))
        held.set_inheritable(True)
    except OSError:
        held.close()
        raise
    return held
