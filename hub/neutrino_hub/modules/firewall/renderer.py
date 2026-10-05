"""What the system firewall must allow on a macOS or Windows hub.

Pure: ports, interfaces and paths in, rules, programs and pf text out.
Windows allows ports, one rule per purpose named ``neutrino_hub_<purpose>``,
each on the exposed interfaces; macOS's application firewall allows
programs, and a pf anchor blocks the same ports on every interface that is
not exposed. Linux has its own nftables ruleset instead.
"""

from dataclasses import dataclass

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_DARWIN_LOOPBACK,
    FIREWALL_OVERLAY_PROTOCOLS,
    FIREWALL_PROTOCOL_TCP,
    FIREWALL_PROTOCOL_UDP,
    FIREWALL_PURPOSE_AGENT,
    FIREWALL_PURPOSE_AI_GATEWAY,
    FIREWALL_PURPOSE_OVERLAY,
    FIREWALL_PURPOSE_PANEL_HTTP,
    FIREWALL_PURPOSE_PANEL_HTTPS,
    FIREWALL_PURPOSE_SOCKS,
    FIREWALL_RULE_PREFIX,
)
from neutrino_hub.modules.overlay.constants import OVERLAY_ENGINES


@dataclass(frozen=True)
class FirewallPortRule:
    """One inbound port the system firewall allows.

    Attributes:
        name: ``neutrino_hub_<purpose>``.
        protocol: ``TCP`` or ``UDP``.
        port: The local port.
        interfaces: The interfaces the port answers on; none keeps the rule
            disabled on Windows and blocks the port on every interface on
            macOS.
    """

    name: str
    protocol: str
    port: int
    interfaces: tuple = ()


def render_port_rules(
    *,
    panel_http_port: int,
    panel_https_port: int,
    agent_port: int,
    ai_gateway_port: int,
    socks_ports: list,
    overlays: list,
    exposed_interfaces: list,
    exposed_overlays: list,
    direct_interfaces: list = (),
) -> list:
    """The rules for the ports the hub serves.

    Args:
        panel_http_port: The panel's HTTP port.
        panel_https_port: The panel's HTTPS port.
        agent_port: The agent channel's port.
        ai_gateway_port: The port CLIProxyAPI, the AI gateway, listens on.
        socks_ports: Every configured SOCKS port, each opened for TCP and UDP.
        overlays: The enabled overlays' keys; each opens its peers' port.
        exposed_interfaces: The interfaces the hub answers on, the exposed
            overlays' devices among them, as the system names them.
        exposed_overlays: The enabled overlays' keys that are exposed; a
            closed one's peer port answers on no interface.
        direct_interfaces: The enabled interfaces Direct opens the agent
            port alone on; empty while Direct is off.

    Returns:
        One :class:`FirewallPortRule` per purpose, in a stable order.
    """
    answering = tuple(dict.fromkeys(exposed_interfaces))
    rules = [
        _rule(
            FIREWALL_PURPOSE_PANEL_HTTP,
            FIREWALL_PROTOCOL_TCP,
            panel_http_port,
            answering,
        ),
        _rule(
            FIREWALL_PURPOSE_PANEL_HTTPS,
            FIREWALL_PROTOCOL_TCP,
            panel_https_port,
            answering,
        ),
        _rule(
            FIREWALL_PURPOSE_AGENT,
            FIREWALL_PROTOCOL_TCP,
            agent_port,
            tuple(dict.fromkeys([*answering, *direct_interfaces])),
        ),
        _rule(
            FIREWALL_PURPOSE_AI_GATEWAY,
            FIREWALL_PROTOCOL_TCP,
            ai_gateway_port,
            answering,
        ),
    ]
    for port in sorted({int(port) for port in socks_ports}):
        for protocol in (FIREWALL_PROTOCOL_TCP, FIREWALL_PROTOCOL_UDP):
            purpose = FIREWALL_PURPOSE_SOCKS.format(
                port=port, protocol=protocol.lower()
            )
            rules.append(_rule(purpose, protocol, port, answering))
    for provider in OVERLAY_ENGINES:
        if provider not in overlays:
            continue
        knocked = answering if provider in exposed_overlays else ()
        for protocol in FIREWALL_OVERLAY_PROTOCOLS.get(provider, ()):
            purpose = FIREWALL_PURPOSE_OVERLAY.format(
                provider=provider, protocol=protocol.lower()
            )
            rules.append(
                _rule(purpose, protocol, OVERLAY_ENGINES[provider].peer_port, knocked)
            )
    return rules


def render_pf_anchor(rules: list, *, interfaces: list) -> str:
    """The pf anchor that closes the hub's ports where they do not answer.

    Args:
        rules: The :class:`FirewallPortRule` list :func:`render_port_rules`
            gave.
        interfaces: Every interface the box has, as the system names them.

    Returns:
        One ``block`` line per rule closed somewhere: on the interfaces it
        does not answer on, or on every interface but loopback when it
        answers on none. Empty when every rule answers everywhere.
    """
    lines = []
    for rule in rules:
        protocol = rule.protocol.lower()
        if not rule.interfaces:
            lines.append(
                f"block drop in quick on ! {FIREWALL_DARWIN_LOOPBACK} proto {protocol} "
                f"from any to any port {rule.port}"
            )
            continue
        closed = [name for name in interfaces if name not in rule.interfaces]
        if not closed:
            continue
        lines.append(
            f"block drop in quick on {{ {' '.join(closed)} }} proto {protocol} "
            f"from any to any port {rule.port}"
        )
    return "".join(f"{line}\n" for line in lines)


def render_programs(
    *,
    hub_program: str,
    xray_program: str,
    ai_gateway_program: str,
    overlay_programs: dict,
    overlays: list,
) -> list:
    """The programs macOS's application firewall allows.

    Args:
        hub_program: ``nhub``, which serves the panel and the agent channel.
        xray_program: xray, which serves the SOCKS ports; empty in a
            tree without the proxy.
        ai_gateway_program: ``cli-proxy-api``, which serves the AI gateway.
        overlay_programs: Overlay key to the program its daemon runs.
        overlays: The enabled overlays' keys.

    Returns:
        The program paths, the hub first.
    """
    programs = [
        program
        for program in (hub_program, xray_program, ai_gateway_program)
        if program
    ]
    for provider in OVERLAY_ENGINES:
        if provider in overlays and provider in overlay_programs:
            programs.append(overlay_programs[provider])
    return programs


def _rule(
    purpose: str, protocol: str, port: int, interfaces: tuple
) -> FirewallPortRule:
    """One rule named by its purpose."""
    return FirewallPortRule(
        name=f"{FIREWALL_RULE_PREFIX}{purpose}",
        protocol=protocol,
        port=int(port),
        interfaces=interfaces,
    )
