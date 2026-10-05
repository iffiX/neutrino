"""A socket peer's address, as every judge of one reads it.

A dual-stack socket reports an IPv4 peer as an IPv4-mapped IPv6 address,
``::ffff:a.b.c.d``. Every place that judges or records where a peer comes
from reads it through :func:`unmapped`, so the same peer is the same address
whichever socket took it.
"""

import ipaddress


def unmapped(address: str) -> str:
    """The address a peer's socket names, an IPv4-mapped one as its IPv4 address.

    Args:
        address: The peer's address as the socket reports it.

    Returns:
        ``a.b.c.d`` for ``::ffff:a.b.c.d``; anything else unchanged.
    """
    text = str(address or "")
    if ":" not in text:
        return text
    try:
        mapped = ipaddress.IPv6Address(text.split("%", 1)[0]).ipv4_mapped
    except ValueError:
        return text
    return str(mapped) if mapped is not None else text
