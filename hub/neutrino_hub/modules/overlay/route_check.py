"""Whether the overlays' networks and routes collide with each other or with
the box's own networks.

Pure: networks and routes in, collisions out. Reading the kernel's routes and
taking a route away is :mod:`neutrino_hub.modules.overlay.ops`.
"""

import ipaddress
from dataclasses import dataclass

from neutrino_hub.modules.overlay.constants import OVERLAY_DEFAULT_ROUTE


@dataclass(frozen=True)
class OverlaySubnetOverlap:
    """An overlay's own network overlapping another network.

    Attributes:
        provider: The overlay whose network it is.
        subnet: Its network.
        conflict: The network it overlaps: a network of this box, or
            another overlay's.
    """

    provider: str
    subnet: str
    conflict: str


@dataclass(frozen=True)
class OverlayRouteConflict:
    """A route an overlay installed that the hub does not accept.

    Attributes:
        provider: The overlay whose device the route names.
        route: The route's destination.
        conflict: The network it overlaps; empty for a default route.
        is_withdrawn: Whether the hub took it away.
    """

    provider: str
    route: str
    conflict: str
    is_withdrawn: bool = False

    @property
    def is_default(self) -> bool:
        """Whether the route is for every address."""
        return self.route == OVERLAY_DEFAULT_ROUTE


def find_subnet_overlap(
    overlay_subnets: dict, local_networks: list
) -> "OverlaySubnetOverlap | None":
    """The first overlap between an overlay's network and any other.

    Args:
        overlay_subnets: Provider to the networks its addresses come from.
        local_networks: This box's own networks: the served ones and every
            other network it holds an address on.

    Returns:
        The first overlap, the overlays compared in the order given; None
        when every pair is apart.
    """
    providers = list(overlay_subnets)
    for index, provider in enumerate(providers):
        others = list(local_networks)
        for other in providers[index + 1 :]:
            others += list(overlay_subnets[other])
        for subnet in overlay_subnets[provider]:
            conflict = _first_overlap(subnet, others)
            if conflict:
                return OverlaySubnetOverlap(
                    provider=provider, subnet=subnet, conflict=conflict
                )
    return None


def find_route_conflicts(
    routes: dict, overlay_subnets: dict, local_networks: list
) -> list[OverlayRouteConflict]:
    """The routes the overlays installed that the hub does not accept.

    A default route is refused wherever it appears. Any other route is
    refused when it overlaps one of this box's own networks or another
    overlay's network; a route inside the overlay's own network is its own.

    Args:
        routes: Provider to the destinations of the routes naming its
            devices, in CIDR form.
        overlay_subnets: Provider to the networks its addresses come from.
        local_networks: This box's own networks.

    Returns:
        One conflict per refused route, in the order given.
    """
    conflicts = []
    for provider, destinations in routes.items():
        others = list(local_networks)
        for other, subnets in overlay_subnets.items():
            if other != provider:
                others += list(subnets)
        for destination in destinations:
            if _network_of(destination) == OVERLAY_DEFAULT_ROUTE:
                conflicts.append(
                    OverlayRouteConflict(
                        provider=provider, route=OVERLAY_DEFAULT_ROUTE, conflict=""
                    )
                )
                continue
            if _first_overlap(destination, overlay_subnets.get(provider, [])):
                continue
            conflict = _first_overlap(destination, others)
            if conflict:
                conflicts.append(
                    OverlayRouteConflict(
                        provider=provider,
                        route=_network_of(destination),
                        conflict=conflict,
                    )
                )
    return conflicts


def _first_overlap(cidr: str, networks: list) -> str:
    """The first of the networks that overlaps one CIDR.

    Args:
        cidr: A network, host bits allowed.
        networks: Networks to compare with, host bits allowed.

    Returns:
        The overlapping network in its normal form, empty when none does or
        the CIDR is not one.
    """
    try:
        subject = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return ""
    for network in networks:
        try:
            other = ipaddress.ip_network(network, strict=False)
        except ValueError:
            continue
        if subject.version == other.version and subject.overlaps(other):
            return str(other)
    return ""


def _network_of(cidr: str) -> str:
    """A CIDR in its normal form, or the text as given when it is not one."""
    try:
        return str(ipaddress.ip_network(cidr, strict=False))
    except ValueError:
        return cidr
