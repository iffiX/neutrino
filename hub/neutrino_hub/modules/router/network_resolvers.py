"""The network's resolvers: the first of the two layers names resolve in.

In router mode they belong to the uplinks. A DHCP uplink's are the ones its
lease names, a static uplink's are the rows it lists, and with several
uplinks each one's come in the uplinks' order of priority. Where the hub
does not address the machine, they are the system's own. When none names
any, the built-in fallbacks answer.

dnsmasq forwards to these, and the proxy's direct lookups ask them while
``direct_dns`` is empty.

Pure: this module composes what the system was read for. Reading the leases
and the system's resolvers is :func:`neutrino_hub.modules.router.routes.read_network_resolvers`.
"""

import ipaddress
import json

from neutrino_hub.modules.router.constants import (
    ROUTER_FALLBACK_RESOLVERS,
    ROUTER_RESOLVER_PORT,
    ROUTER_WAN_METHOD_STATIC,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig


def compose_network_resolvers(
    *,
    network: RouterNetworkConfig,
    uplink_order: list[str],
    lease_dns: dict[str, list[str]],
    system_resolvers: list[str],
) -> list[dict]:
    """The network's resolvers, in the order they are asked.

    Args:
        network: The parsed router configuration.
        uplink_order: The uplinks' names, best first.
        lease_dns: Each DHCP uplink's device to the resolvers its lease
            names.
        system_resolvers: The system's own resolvers, used where the hub does
            not address the machine.

    Returns:
        Each resolver once as ``{address, port}``; the fallbacks when no
        uplink, or the system, names any.
    """
    rows: list[dict] = []
    if network.is_addressing_owned:
        for name in uplink_order:
            interface = network.interface(name)
            if interface is None or not interface.is_wan:
                continue
            if interface.wan.method == ROUTER_WAN_METHOD_STATIC:
                rows += interface.wan.dns
            else:
                rows += _rows(lease_dns.get(interface.device_name, []))
    else:
        rows = _rows(system_resolvers)
    unique: list[dict] = []
    for row in rows:
        entry = {"address": row["address"], "port": int(row["port"])}
        if entry not in unique:
            unique.append(entry)
    return unique or _rows(ROUTER_FALLBACK_RESOLVERS)


def fallback_resolvers() -> list[dict]:
    """The built-in fallbacks, as ``{address, port}``."""
    return _rows(ROUTER_FALLBACK_RESOLVERS)


def parse_recorded_resolvers(text: str) -> list[dict]:
    """The resolvers a render recorded.

    Args:
        text: The record's text.

    Returns:
        The recorded ``{address, port}`` rows; the fallbacks when the text is
        not a list of them.
    """
    try:
        stored = json.loads(text)
    except ValueError:
        return fallback_resolvers()
    rows = []
    for row in stored if isinstance(stored, list) else []:
        if not isinstance(row, dict) or not row.get("address"):
            continue
        try:
            port = int(row.get("port", ROUTER_RESOLVER_PORT))
        except (TypeError, ValueError):
            continue
        rows.append({"address": str(row["address"]), "port": port})
    return rows or fallback_resolvers()


def resolver_refusal(
    rows: list[dict], *, port_min: int, port_max: int
) -> "tuple[str, dict] | None":
    """What is wrong with a list of resolver rows a person sent, if anything.

    Args:
        rows: The rows, each ``{address, port}``.
        port_min: The lowest port a row may name.
        port_max: The highest.

    Returns:
        ``(code, params)`` for the first row refused:
        ``resolver_address_invalid {address}`` for an address that is not an
        IP address, ``port_out_of_range {minimum, maximum, value}`` for a
        port outside the range; None when every row stands.
    """
    for row in rows:
        address = str(row.get("address", ""))
        try:
            ipaddress.ip_address(address)
        except ValueError:
            return "resolver_address_invalid", {"address": address}
        port = row.get("port")
        if not isinstance(port, int) or not port_min <= port <= port_max:
            return "port_out_of_range", {
                "minimum": port_min,
                "maximum": port_max,
                "value": port,
            }
    return None


def _rows(addresses) -> list[dict]:
    return [{"address": address, "port": ROUTER_RESOLVER_PORT} for address in addresses]
