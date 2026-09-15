"""The report's ``network`` section: the link, and every interface.

Pure functions over what the platform read. The link is the interface
holding the socket's own local address, which the hub connection leaves by.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations


def link_of(address: str, interfaces: list) -> "dict | None":
    """The interface holding an address.

    Args:
        address: The socket's own local address.
        interfaces: ``[{"name", "mac", "addresses"}]`` as the platform read
            them.

    Returns:
        The entry whose ``addresses`` holds ``address``, or None when none
        does or the address is empty.
    """
    if not address:
        return None
    for interface in interfaces:
        if address in interface.get("addresses", ()):
            return interface
    return None


def describe(address: str, interfaces: list) -> dict:
    """The ``network`` section a report carries.

    Args:
        address: The socket's own local address; the link is the interface
            holding it.
        interfaces: ``[{"name", "mac", "addresses"}]`` as the platform read
            them.

    Returns:
        ``{"link": {"interface", "mac", "address"}, "interfaces": [...]}``.
        When no interface holds the address, ``link`` still carries it with
        an empty ``interface`` and ``mac``.
    """
    holder = link_of(address, interfaces) or {}
    return {
        "link": {
            "interface": str(holder.get("name", "") or ""),
            "mac": str(holder.get("mac", "") or ""),
            "address": address,
        },
        "interfaces": list(interfaces),
    }
