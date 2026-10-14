"""What the hub's firewall answers, and that answer in each system's own form.

Pure: the configuration, the addresses the box holds and the ports in;
rules, programs and text out. :func:`render_exposure` works out the one
answer: the hub's own ports answer loopback and the senders inside an
exposed segment, Direct opens the agent port to every sender on the enabled
interfaces, and the overlay engines' peer ports and DHCP open with no
switch. Linux renders it into nftables
(:mod:`neutrino_hub.modules.router.nft_renderer`) and, where firewalld runs,
into firewalld's rich rules; Windows into one rule per purpose; macOS into a
pf anchor and the programs its application firewall allows.
"""

import ipaddress
from dataclasses import dataclass

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_DARWIN_LOOPBACK,
    FIREWALL_DARWIN_PF_TABLE_IPV4,
    FIREWALL_DARWIN_PF_TABLE_IPV6,
    FIREWALL_DHCP_PORT,
    FIREWALL_DNS_PORT,
    FIREWALL_FIREWALLD_PRIORITY,
    FIREWALL_OVERLAY_PROTOCOLS,
    FIREWALL_PROTOCOL_TCP,
    FIREWALL_PROTOCOL_UDP,
    FIREWALL_PURPOSE_AGENT,
    FIREWALL_PURPOSE_DIRECT,
    FIREWALL_PURPOSE_DNS,
    FIREWALL_PURPOSE_LINK_SUFFIX,
    FIREWALL_PURPOSE_OVERLAY,
    FIREWALL_PURPOSE_PANEL_HTTP,
    FIREWALL_PURPOSE_PANEL_HTTPS,
    FIREWALL_PURPOSE_SOCKS,
    FIREWALL_RULE_PREFIX,
)
from neutrino_hub.modules.overlay.constants import OVERLAY_ENGINES
from neutrino_hub.modules.router.constants import (
    ROUTER_FAMILY_IPV4,
    ROUTER_FAMILY_IPV6,
    ROUTER_IPV6_LINK_LOCAL_NETWORK,
    ROUTER_MODE_SERVER,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig


@dataclass(frozen=True)
class FirewallPort:
    """One port the firewall rules name.

    Attributes:
        purpose: What it serves, the end of a Windows rule's name.
        protocol: ``TCP`` or ``UDP``.
        port: The local port.
    """

    purpose: str
    protocol: str
    port: int


@dataclass(frozen=True)
class FirewallExposure:
    """What the hub's firewall answers, on any system.

    Attributes:
        hub_ports: The hub's own ports; each answers loopback and the senders
            inside the segments, and no other sender.
        segments: The exposed segments, each a
            :class:`neutrino_hub.modules.router.interfaces.RouterSegment`.
        peer_ports: The running overlay engines' peer ports, open to every
            sender.
        dhcp_devices: The devices of the served networks whose DHCP the hub
            serves; DHCP opens on each.
        enabled_devices: The enabled interfaces holding an address.
        direct_port: The agent port while Direct is on, which opens it to
            every sender on the enabled interfaces; None while it is off.
    """

    hub_ports: tuple = ()
    segments: tuple = ()
    peer_ports: tuple = ()
    dhcp_devices: tuple = ()
    enabled_devices: tuple = ()
    direct_port: "int | None" = None

    def networks(self, family: str) -> list[str]:
        """Every network of one family the segments hold, link-local aside.

        Args:
            family: ``ipv4`` or ``ipv6``.

        Returns:
            Each network once, in segment order.
        """
        found = []
        for segment in self.segments:
            if segment.family != family:
                continue
            for network in segment.networks:
                if network != ROUTER_IPV6_LINK_LOCAL_NETWORK and network not in found:
                    found.append(network)
        return found

    @property
    def link_local_devices(self) -> list[str]:
        """The devices whose IPv6 segment holds ``fe80::/64``, each once."""
        found = []
        for segment in self.segments:
            if (
                ROUTER_IPV6_LINK_LOCAL_NETWORK in segment.networks
                and segment.device not in found
            ):
                found.append(segment.device)
        return found


@dataclass(frozen=True)
class FirewallPortRule:
    """One inbound rule Windows Firewall holds for the hub.

    Attributes:
        name: ``neutrino_hub_<purpose>``.
        protocol: ``TCP`` or ``UDP``.
        port: The local port.
        remote_addresses: The networks whose senders the rule allows; none
            allows every sender.
        interfaces: The interfaces the rule is scoped to; none scopes it to
            every interface.
    """

    name: str
    protocol: str
    port: int
    remote_addresses: tuple = ()
    interfaces: tuple = ()


def render_exposure(
    network: RouterNetworkConfig,
    *,
    held: dict,
    panel_http_port: int,
    panel_https_port: int,
    agent_port: int,
    socks_ports: list,
    is_direct: bool,
) -> FirewallExposure:
    """Work out what the hub's firewall answers.

    Args:
        network: The parsed router configuration, carrying the overlays'
            devices found at run time.
        held: Device name to every address it holds with its prefix, as
            :func:`neutrino_hub.modules.router.link_status.device_held_addresses`
            reads them.
        panel_http_port: The panel's HTTP port.
        panel_https_port: The panel's HTTPS port.
        agent_port: The agent port.
        socks_ports: Every configured SOCKS port, each a hub port over TCP
            and UDP.
        is_direct: Whether Direct is on.

    Returns:
        The exposure. DNS is a hub port in ``router`` and ``side_gateway``.
    """
    hub_ports = [
        FirewallPort(
            FIREWALL_PURPOSE_PANEL_HTTP, FIREWALL_PROTOCOL_TCP, panel_http_port
        ),
        FirewallPort(
            FIREWALL_PURPOSE_PANEL_HTTPS, FIREWALL_PROTOCOL_TCP, panel_https_port
        ),
        FirewallPort(FIREWALL_PURPOSE_AGENT, FIREWALL_PROTOCOL_TCP, agent_port),
    ]
    if network.mode != ROUTER_MODE_SERVER:
        hub_ports += [
            FirewallPort(
                FIREWALL_PURPOSE_DNS.format(protocol=protocol.lower()),
                protocol,
                FIREWALL_DNS_PORT,
            )
            for protocol in (FIREWALL_PROTOCOL_TCP, FIREWALL_PROTOCOL_UDP)
        ]
    for port in sorted({int(port) for port in socks_ports}):
        hub_ports += [
            FirewallPort(
                FIREWALL_PURPOSE_SOCKS.format(port=port, protocol=protocol.lower()),
                protocol,
                port,
            )
            for protocol in (FIREWALL_PROTOCOL_TCP, FIREWALL_PROTOCOL_UDP)
        ]
    running = {overlay.provider for overlay in network.enabled_overlays}
    peer_ports = [
        FirewallPort(
            FIREWALL_PURPOSE_OVERLAY.format(
                provider=provider, protocol=protocol.lower()
            ),
            protocol,
            OVERLAY_ENGINES[provider].peer_port,
        )
        for provider in OVERLAY_ENGINES
        if provider in running
        for protocol in FIREWALL_OVERLAY_PROTOCOLS.get(provider, ())
    ]
    overlays = set(network.overlay_device_names)
    enabled = [name for name in network.enabled_device_names if name in held]
    enabled += [
        name
        for name in held
        if name not in overlays
        and name not in enabled
        and network.interface(name) is None
        and network.is_interface_enabled(name)
    ]
    dhcp = []
    for interface in network.lan_interfaces:
        if interface.lan.is_dhcp_enabled and interface.device_name not in dhcp:
            dhcp.append(interface.device_name)
    return FirewallExposure(
        hub_ports=tuple(hub_ports),
        segments=tuple(network.exposed_segments(held)),
        peer_ports=tuple(peer_ports),
        dhcp_devices=tuple(dhcp),
        enabled_devices=tuple(enabled),
        direct_port=agent_port if is_direct else None,
    )


def render_port_rules(exposure: FirewallExposure) -> list:
    """Windows Firewall's rules for the hub, one per purpose.

    Args:
        exposure: What the firewall answers.

    Returns:
        :class:`FirewallPortRule` list in a stable order: each hub port's
        rule allowing the segments' networks, while there is one; beside it,
        its ``_link`` rule allowing ``fe80::/64`` on the interfaces whose
        IPv6 segment holds it; Direct's rule on the enabled interfaces; and
        each peer port's rule allowing every sender. A rule that would allow
        nobody is left out.
    """
    networks = tuple(
        exposure.networks(ROUTER_FAMILY_IPV4) + exposure.networks(ROUTER_FAMILY_IPV6)
    )
    linked = tuple(exposure.link_local_devices)
    rules = []
    for port in exposure.hub_ports:
        if networks:
            rules.append(_rule(port.purpose, port, remote_addresses=networks))
        if linked:
            rules.append(
                _rule(
                    port.purpose + FIREWALL_PURPOSE_LINK_SUFFIX,
                    port,
                    remote_addresses=(ROUTER_IPV6_LINK_LOCAL_NETWORK,),
                    interfaces=linked,
                )
            )
    if exposure.direct_port is not None and exposure.enabled_devices:
        rules.append(
            _rule(
                FIREWALL_PURPOSE_DIRECT,
                FirewallPort(
                    FIREWALL_PURPOSE_DIRECT,
                    FIREWALL_PROTOCOL_TCP,
                    exposure.direct_port,
                ),
                interfaces=tuple(exposure.enabled_devices),
            )
        )
    for port in exposure.peer_ports:
        rules.append(_rule(port.purpose, port))
    return rules


def render_pf_anchor(exposure: FirewallExposure) -> str:
    """The pf anchor that keeps the hub's ports to loopback and the segments.

    Args:
        exposure: What the firewall answers.

    Returns:
        The anchor's text: an address table per family of the segments'
        networks, then per protocol a pass from loopback, from each table,
        from ``fe80::/64`` on each interface whose IPv6 segment holds it,
        Direct's pass on the enabled interfaces, and a block from every
        other sender. Empty when the hub has no port.
    """
    tables = {
        family: exposure.networks(family)
        for family in (ROUTER_FAMILY_IPV4, ROUTER_FAMILY_IPV6)
    }
    names = {
        ROUTER_FAMILY_IPV4: (FIREWALL_DARWIN_PF_TABLE_IPV4, "inet"),
        ROUTER_FAMILY_IPV6: (FIREWALL_DARWIN_PF_TABLE_IPV6, "inet6"),
    }
    lines = [
        f"table <{names[family][0]}> const {{ {', '.join(networks)} }}"
        for family, networks in tables.items()
        if networks
    ]
    for protocol in (FIREWALL_PROTOCOL_TCP, FIREWALL_PROTOCOL_UDP):
        numbers = [
            port.port for port in exposure.hub_ports if port.protocol == protocol
        ]
        if not numbers:
            continue
        ports = _port_list(numbers)
        proto = protocol.lower()
        lines.append(
            f"pass in quick on {FIREWALL_DARWIN_LOOPBACK} proto {proto} "
            f"from any to any port {ports}"
        )
        for family, networks in tables.items():
            if networks:
                table, word = names[family]
                lines.append(
                    f"pass in quick {word} proto {proto} "
                    f"from <{table}> to any port {ports}"
                )
        for device in exposure.link_local_devices:
            lines.append(
                f"pass in quick on {device} inet6 proto {proto} "
                f"from {ROUTER_IPV6_LINK_LOCAL_NETWORK} to any port {ports}"
            )
        if (
            protocol == FIREWALL_PROTOCOL_TCP
            and exposure.direct_port is not None
            and exposure.enabled_devices
        ):
            lines.append(
                f"pass in quick on {{ {' '.join(exposure.enabled_devices)} }} "
                f"proto tcp from any to any port {exposure.direct_port}"
            )
        lines.append(f"block drop in quick proto {proto} from any to any port {ports}")
    return "".join(f"{line}\n" for line in lines)


def render_firewalld_rules(
    exposure: FirewallExposure, *, zones: dict, default_zone: str
) -> dict:
    """firewalld's rich rules for the hub, by zone.

    Args:
        exposure: What the firewall answers.
        zones: Device name to the zone firewalld holds it in.
        default_zone: The zone of a device in none.

    Returns:
        Zone to its rules, each sorted and once: in the zone of each
        segment's device, one rule per network and hub port with that
        network as its source; in the zone of each enabled interface, each
        peer port and, while Direct is on, the agent port, with no source;
        in the zone of each device whose DHCP the hub serves, DHCP. Each rule
        carries the hub's priority.
    """
    found: dict = {}

    def add(device: str, rule: str) -> None:
        found.setdefault(zones.get(device) or default_zone, set()).add(rule)

    for segment in exposure.segments:
        for network in segment.networks:
            for port in exposure.hub_ports:
                add(
                    segment.device,
                    firewalld_rule(
                        family=segment.family,
                        source=network,
                        port=port.port,
                        protocol=port.protocol,
                    ),
                )
    for device in exposure.enabled_devices:
        for port in exposure.peer_ports:
            add(device, firewalld_rule(port=port.port, protocol=port.protocol))
        if exposure.direct_port is not None:
            add(
                device,
                firewalld_rule(
                    port=exposure.direct_port, protocol=FIREWALL_PROTOCOL_TCP
                ),
            )
    for device in exposure.dhcp_devices:
        add(
            device,
            firewalld_rule(
                family=ROUTER_FAMILY_IPV4,
                port=FIREWALL_DHCP_PORT,
                protocol=FIREWALL_PROTOCOL_UDP,
            ),
        )
    return {zone: sorted(rules) for zone, rules in sorted(found.items())}


def firewalld_rule(
    *, port: int, protocol: str, family: str = "", source: str = ""
) -> str:
    """One rich rule of the hub's, as firewall-cmd prints it.

    Args:
        port: The local port.
        protocol: ``TCP`` or ``UDP``.
        family: ``ipv4`` or ``ipv6``; empty for both.
        source: The sender's network; empty for every sender.

    Returns:
        ``rule priority=... [family=...] [source address=...] port ... accept``.
    """
    words = ["rule", f'priority="{FIREWALL_FIREWALLD_PRIORITY}"']
    if family:
        words.append(f'family="{family}"')
    if source:
        words.append(f'source address="{ipaddress.ip_network(source, strict=False)}"')
    words.append(f'port port="{port}" protocol="{protocol.lower()}"')
    words.append("accept")
    return " ".join(words)


def render_programs(
    *,
    hub_program: str,
    xray_program: str,
    overlay_programs: dict,
    overlays: list,
) -> list:
    """The programs macOS's application firewall allows.

    Args:
        hub_program: ``nhub``, which serves the panel and the agent channel.
        xray_program: xray, which serves the SOCKS ports; empty in a
            tree without the proxy.
        overlay_programs: Overlay key to the program its daemon runs.
        overlays: The enabled overlays' keys.

    Returns:
        The program paths, the hub first.
    """
    programs = [program for program in (hub_program, xray_program) if program]
    for provider in OVERLAY_ENGINES:
        if provider in overlays and provider in overlay_programs:
            programs.append(overlay_programs[provider])
    return programs


def _rule(
    purpose: str,
    port: FirewallPort,
    *,
    remote_addresses: tuple = (),
    interfaces: tuple = (),
) -> FirewallPortRule:
    """One Windows rule named by its purpose."""
    return FirewallPortRule(
        name=f"{FIREWALL_RULE_PREFIX}{purpose}",
        protocol=port.protocol,
        port=int(port.port),
        remote_addresses=remote_addresses,
        interfaces=interfaces,
    )


def _port_list(ports: list) -> str:
    """Ports as pf names them: one bare, several in braces, each once."""
    unique = list(dict.fromkeys(int(port) for port in ports))
    if len(unique) == 1:
        return str(unique[0])
    return "{ " + ", ".join(str(port) for port in unique) + " }"
