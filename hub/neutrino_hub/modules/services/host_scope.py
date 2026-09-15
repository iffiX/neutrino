"""Which network a caller arrived from, and where a device is on it.

A scope is one network the hub answers on: a served LAN, named by its
network CIDR, the overlay, or ``link`` for everything else. A caller's
scope is settled from its socket's peer address, and a device's address
in that scope is the first of its reported interface addresses inside it,
else the address its own socket comes from. Only IPv4 is considered.

Pure: the configuration and the addresses the box holds come in as
arguments.
"""

import ipaddress
from dataclasses import dataclass

from neutrino_hub.modules.services.constants import (
    SERVICES_SCOPE_LINK,
    SERVICES_SCOPE_OVERLAY,
)


@dataclass(frozen=True)
class HostScope:
    """One network a caller can arrive from.

    Attributes:
        id: A served LAN's network CIDR, ``overlay``, or ``link``.
        cidr: The IPv4 network the scope covers; empty for ``link``.
        hub_address: The hub's own address in the scope; for ``link``, the
            address the caller reached.
    """

    id: str
    cidr: str
    hub_address: str


def served_scopes(network, addresses: dict) -> list[HostScope]:
    """Every scope the hub serves: each served LAN, then each overlay it holds an address on.

    Args:
        network: The router configuration, a
            :class:`neutrino_hub.modules.router.interfaces.RouterNetworkConfig`.
        addresses: Device name to the address with its prefix the box holds,
            as :func:`neutrino_hub.modules.router.link_status.device_addresses`
            reads them.

    Returns:
        The served LANs in configuration order, then the overlays.
    """
    scopes = []
    for interface in network.lan_interfaces:
        lan = interface.lan
        cidr = _network_of(lan.cidr)
        if lan.address and cidr:
            scopes.append(HostScope(id=cidr, cidr=cidr, hub_address=lan.address))
    for name in network.overlay_device_names:
        held = str(addresses.get(name, "") or "")
        cidr = _network_of(held)
        if cidr:
            scopes.append(
                HostScope(
                    id=SERVICES_SCOPE_OVERLAY,
                    cidr=cidr,
                    hub_address=held.split("/")[0],
                )
            )
    return scopes


def scope_of(
    peer_address: str, reached_address: str, served: list[HostScope]
) -> HostScope:
    """The scope a caller arrived from.

    Args:
        peer_address: Where the caller's socket comes from.
        reached_address: The hub address the caller connected to; the hub's
            address in the ``link`` scope.
        served: The scopes from :func:`served_scopes`.

    Returns:
        The first served scope whose network holds the peer, else ``link``.
    """
    address = _ipv4_of(peer_address)
    if address is not None:
        for scope in served:
            if address in ipaddress.ip_network(scope.cidr):
                return scope
    return link_scope(reached_address)


def link_scope(reached_address: str) -> HostScope:
    """The scope of a caller on no served network.

    Args:
        reached_address: The hub address the caller connected to.

    Returns:
        The ``link`` scope with that address as the hub's own.
    """
    return HostScope(id=SERVICES_SCOPE_LINK, cidr="", hub_address=reached_address)


def device_host_for(scope: HostScope, interfaces: list, link_address: str) -> str:
    """Where a device is for a caller in one scope.

    Args:
        scope: The caller's scope.
        interfaces: The device's reported ``network.interfaces``, each
            ``{"name", "mac", "addresses"}``.
        link_address: The device's ``network.link.address``, or the peer
            address standing in for it.

    Returns:
        The link address when it is inside the scope, else the first
        reported IPv4 address inside it, else the link address.
    """
    if not scope.cidr:
        return link_address
    network = ipaddress.ip_network(scope.cidr)
    link = _ipv4_of(link_address)
    if link is not None and link in network:
        return link_address
    for interface in interfaces:
        if not isinstance(interface, dict):
            continue
        for text in interface.get("addresses") or []:
            address = _ipv4_of(str(text))
            if address is not None and address in network:
                return str(address)
    return link_address


def _ipv4_of(text: str) -> "ipaddress.IPv4Address | None":
    """The IPv4 address a bare or prefixed address names, None for anything else."""
    try:
        address = ipaddress.ip_interface(text).ip
    except ValueError:
        return None
    return address if address.version == 4 else None


def _network_of(cidr: str) -> str:
    """The IPv4 network an address with a prefix belongs to, empty when it names none."""
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return ""
    return str(network) if network.version == 4 else ""
