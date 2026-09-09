"""The networks a device's shares answer, beside the firewall's own fence.

A file share the hub composes for a device names the subnets it may admit,
and the answer has two halves: which networks this hub serves, which is
configuration, and which addresses it holds, which is the kernel.

Pure: configuration and addresses in, network addresses out.
"""

import ipaddress

from neutrino_hub.modules.router.constants import ROUTER_MODE_SERVER
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig


def allowed_subnets(lan_cidrs: list, exposed_addresses: list) -> list:
    """The networks the shares answer.

    Args:
        lan_cidrs: The LAN-role interfaces' cidrs, host form allowed.
        exposed_addresses: The exposed interfaces' live addresses with
            prefix (``a.b.c.d/nn``).

    Returns:
        Deduplicated network addresses, order kept.
    """
    subnets = []
    for value in list(lan_cidrs) + list(exposed_addresses):
        if not value:
            continue
        try:
            network = str(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
        if network not in subnets:
            subnets.append(network)
    return subnets


def share_subnets(
    *,
    network: RouterNetworkConfig,
    link_addresses: dict,
    device_addresses: dict,
) -> list:
    """The networks the shares answer on, for this hub as it is now.

    Args:
        network: The parsed router configuration.
        link_addresses: Interface name to live address with prefix, for the
            interfaces the hub assigns roles to.
        device_addresses: The same for every device on the box, which is
            where an overlay's address is found.

    Returns:
        Deduplicated network addresses, served networks first.
    """
    if network.mode == ROUTER_MODE_SERVER:
        # Nothing here has a role, so every wire the box holds an address
        # on is a wire its shares are meant to answer.
        reachable = [address for address in link_addresses.values() if address]
    else:
        reachable = [
            link_addresses.get(name, "") for name in network.exposed_device_names
        ]
    reachable += [
        device_addresses.get(name, "") for name in network.exposed_overlay_device_names
    ]
    return allowed_subnets(
        [interface.lan.cidr for interface in network.lan_interfaces], reachable
    )
