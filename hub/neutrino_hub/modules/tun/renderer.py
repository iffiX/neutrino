"""What the TUN device on a macOS or Windows hub is and which routes it takes.

Pure: the scopes, the uplink and the addresses that stay out in, the
tun2socks start line and the route plan out. Two scopes divert through the
device, the hub's own and the overlays'; the plan sends both halves of the
address space to it, and keeps a direct route through the uplink for every
address that has to stay out of it. Applying the plan is
:mod:`neutrino_hub.modules.tun.ops`.
"""

import ipaddress
from dataclasses import dataclass

from neutrino_hub.modules.tun.constants import (
    TUN_ADDRESS,
    TUN_DIVERTED_PREFIXES,
    TUN_LOG_LEVEL,
    TUN_MTU,
    TUN_PREFIX_LENGTH,
    TUN_WINDOWS_ON_LINK,
    TUN_WINDOWS_ROUTE_METRIC,
)
from neutrino_hub.modules.xray.constants import (
    XRAY_LOCAL_SOCKS_LISTEN,
    XRAY_SCOPE_HUB,
    XRAY_SCOPE_OVERLAY,
)


@dataclass(frozen=True)
class TunRoute:
    """One route the plan adds.

    Attributes:
        destination: The network, in CIDR form.
        device: The interface the route leaves by.
        gateway: The next hop; empty for a route onto the interface itself.
    """

    destination: str
    device: str
    gateway: str = ""

    def to_dict(self) -> dict:
        """The route as the plan and state files keep it.

        Returns:
            ``destination``, ``device`` and ``gateway``.
        """
        return {
            "destination": self.destination,
            "device": self.device,
            "gateway": self.gateway,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TunRoute":
        """Read a route back.

        Args:
            data: What :meth:`to_dict` wrote.

        Returns:
            The route.

        Raises:
            KeyError: When it names no destination or device.
        """
        return cls(
            destination=str(data["destination"]),
            device=str(data["device"]),
            gateway=str(data.get("gateway") or ""),
        )


@dataclass(frozen=True)
class TunPlan:
    """The device, how tun2socks starts on it, and the routes to add.

    Attributes:
        device: The TUN device's name.
        address: The device's own address.
        prefix_length: The prefix of that address.
        mtu: The device's MTU.
        start_argv: How tun2socks starts, the program first.
        uplink: The interface the direct routes leave by.
        routes: The routes, in the order they are added: the direct ones
            first, the two halves onto the device last.
        forwarding_devices: The interfaces IP forwarding is turned on for,
            when the overlay scope is on.
    """

    device: str
    address: str
    prefix_length: int
    mtu: int
    start_argv: tuple
    uplink: str
    routes: tuple
    forwarding_devices: tuple = ()

    def to_dict(self) -> dict:
        """The plan as the plan file keeps it.

        Returns:
            Every attribute, the routes as dicts.
        """
        return {
            "device": self.device,
            "address": self.address,
            "prefix_length": self.prefix_length,
            "mtu": self.mtu,
            "start_argv": list(self.start_argv),
            "uplink": self.uplink,
            "routes": [route.to_dict() for route in self.routes],
            "forwarding_devices": list(self.forwarding_devices),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TunPlan":
        """Read a plan back.

        Args:
            data: What :meth:`to_dict` wrote.

        Returns:
            The plan.

        Raises:
            KeyError: When a field is missing.
            ValueError: When a number is not one.
        """
        return cls(
            device=str(data["device"]),
            address=str(data["address"]),
            prefix_length=int(data["prefix_length"]),
            mtu=int(data["mtu"]),
            start_argv=tuple(str(word) for word in data["start_argv"]),
            uplink=str(data["uplink"]),
            routes=tuple(TunRoute.from_dict(route) for route in data["routes"]),
            forwarding_devices=tuple(
                str(name) for name in data.get("forwarding_devices") or ()
            ),
        )


def is_tun_wanted(routing: dict, *, has_exit: bool) -> bool:
    """Whether a scope that diverts through the TUN is on.

    Args:
        routing: Parsed ``config/xray/routing.json``.
        has_exit: Whether an enabled exit node can be rendered.

    Returns:
        True when the hub's own scope or the overlay scope is on and there
        is an exit to send it to.
    """
    is_scoped = bool(routing.get(XRAY_SCOPE_HUB, False)) or bool(
        routing.get(XRAY_SCOPE_OVERLAY, False)
    )
    return is_scoped and has_exit


def render_start_line(*, binary: str, device: str, socks_port: int) -> list:
    """How tun2socks starts on the device, pointed at xray's local inbound.

    Args:
        binary: The tun2socks program.
        device: The TUN device's name.
        socks_port: The port of xray's ``socks_local_in``.

    Returns:
        The argument vector.
    """
    return [
        binary,
        "--device",
        f"tun://{device}",
        "--proxy",
        f"socks5://{XRAY_LOCAL_SOCKS_LISTEN}:{socks_port}",
        "--mtu",
        str(TUN_MTU),
        "--loglevel",
        TUN_LOG_LEVEL,
    ]


def render_tun_plan(
    *,
    device: str,
    start_argv: list,
    uplink: str,
    gateway: str,
    local_networks: list,
    kept_out: list,
    forwarding_devices: list,
) -> TunPlan:
    """The plan for the device and the routes around it.

    Args:
        device: The TUN device's name.
        start_argv: How tun2socks starts, from :func:`render_start_line`.
        uplink: The interface the machine's default route leaves by.
        gateway: That route's next hop; empty when it has none.
        local_networks: Every network the box has an address on, in CIDR
            form. An address inside one is on the link and needs no route.
        kept_out: The addresses that stay out of the device: the exit nodes,
            the direct resolver, the reference host, the overlays' servers.
            Anything that is not an IPv4 address is left out.
        forwarding_devices: The interfaces forwarding is turned on for; empty
            when the overlay scope is off.

    Returns:
        The plan. Each address kept out is one host route through the
        gateway, in address order, ahead of the two halves onto the device.
    """
    networks = []
    for cidr in local_networks:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    hosts = set()
    for address in kept_out:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if parsed.version != 4 or parsed.is_loopback or parsed.is_unspecified:
            continue
        if any(parsed in network for network in networks):
            continue
        hosts.add(parsed)
    routes = [
        TunRoute(destination=f"{host}/32", device=uplink, gateway=gateway)
        for host in sorted(hosts)
    ]
    routes += [
        TunRoute(destination=prefix, device=device) for prefix in TUN_DIVERTED_PREFIXES
    ]
    return TunPlan(
        device=device,
        address=TUN_ADDRESS,
        prefix_length=TUN_PREFIX_LENGTH,
        mtu=TUN_MTU,
        start_argv=tuple(start_argv),
        uplink=uplink,
        routes=tuple(routes),
        forwarding_devices=tuple(dict.fromkeys(forwarding_devices)),
    )


def darwin_address_command(plan: TunPlan) -> list:
    """The ``ifconfig`` that gives the utun device its address on macOS.

    Args:
        plan: The plan.

    Returns:
        The argument vector: a point-to-point address to itself, the MTU,
        and up.
    """
    return [
        "ifconfig",
        plan.device,
        plan.address,
        plan.address,
        "mtu",
        str(plan.mtu),
        "up",
    ]


def darwin_route_command(verb: str, route: TunRoute) -> list:
    """The ``route`` command that adds or deletes one route on macOS.

    Args:
        verb: ``add`` or ``delete``.
        route: The route.

    Returns:
        The argument vector: ``-host`` for a single address, ``-net``
        otherwise, through the gateway when the route has one and onto the
        interface when it does not.
    """
    network = ipaddress.ip_network(route.destination, strict=False)
    if network.prefixlen == network.max_prefixlen:
        target = ["-host", str(network.network_address)]
    else:
        target = ["-net", route.destination]
    if route.gateway:
        return ["route", "-n", verb, *target, route.gateway]
    return ["route", "-n", verb, *target, "-interface", route.device]


def windows_route_document(route: TunRoute) -> dict:
    """One route as the Windows scripts read it.

    Args:
        route: The route.

    Returns:
        ``prefix``, ``alias``, ``next_hop`` and ``metric``.
    """
    return {
        "prefix": route.destination,
        "alias": route.device,
        "next_hop": route.gateway or TUN_WINDOWS_ON_LINK,
        "metric": TUN_WINDOWS_ROUTE_METRIC,
    }
