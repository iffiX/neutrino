"""What the system firewall must allow on a macOS or Windows hub.

Pure: ports and paths in, rules and programs out. Windows allows ports, one
rule per purpose named ``neutrino_hub_<purpose>``; macOS's application
firewall allows programs. Linux has its own nftables ruleset instead.
"""

from dataclasses import dataclass

from neutrino_hub.modules.firewall.constants import (
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
    """

    name: str
    protocol: str
    port: int


def render_port_rules(
    *,
    panel_http_port: int,
    panel_https_port: int,
    agent_port: int,
    ai_gateway_port: int,
    socks_ports: list,
    overlays: list,
) -> list:
    """The Windows rules for the ports the hub serves.

    Args:
        panel_http_port: The panel's HTTP port.
        panel_https_port: The panel's HTTPS port.
        agent_port: The agent channel's port.
        ai_gateway_port: The port CLIProxyAPI, the AI gateway, listens on.
        socks_ports: Every configured SOCKS port, each opened for TCP and UDP.
        overlays: The enabled overlays' keys; each opens its peers' port.

    Returns:
        One :class:`FirewallPortRule` per purpose, in a stable order.
    """
    rules = [
        _rule(FIREWALL_PURPOSE_PANEL_HTTP, FIREWALL_PROTOCOL_TCP, panel_http_port),
        _rule(FIREWALL_PURPOSE_PANEL_HTTPS, FIREWALL_PROTOCOL_TCP, panel_https_port),
        _rule(FIREWALL_PURPOSE_AGENT, FIREWALL_PROTOCOL_TCP, agent_port),
        _rule(FIREWALL_PURPOSE_AI_GATEWAY, FIREWALL_PROTOCOL_TCP, ai_gateway_port),
    ]
    for port in sorted({int(port) for port in socks_ports}):
        for protocol in (FIREWALL_PROTOCOL_TCP, FIREWALL_PROTOCOL_UDP):
            purpose = FIREWALL_PURPOSE_SOCKS.format(
                port=port, protocol=protocol.lower()
            )
            rules.append(_rule(purpose, protocol, port))
    for provider in OVERLAY_ENGINES:
        if provider not in overlays:
            continue
        for protocol in FIREWALL_OVERLAY_PROTOCOLS.get(provider, ()):
            purpose = FIREWALL_PURPOSE_OVERLAY.format(
                provider=provider, protocol=protocol.lower()
            )
            rules.append(_rule(purpose, protocol, OVERLAY_ENGINES[provider].peer_port))
    return rules


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
        xray_program: xray, which serves the SOCKS ports.
        ai_gateway_program: ``cli-proxy-api``, which serves the AI gateway.
        overlay_programs: Overlay key to the program its daemon runs.
        overlays: The enabled overlays' keys.

    Returns:
        The program paths, the hub first.
    """
    programs = [hub_program, xray_program, ai_gateway_program]
    for provider in OVERLAY_ENGINES:
        if provider in overlays and provider in overlay_programs:
            programs.append(overlay_programs[provider])
    return programs


def _rule(purpose: str, protocol: str, port: int) -> FirewallPortRule:
    """One rule named by its purpose."""
    return FirewallPortRule(
        name=f"{FIREWALL_RULE_PREFIX}{purpose}", protocol=protocol, port=int(port)
    )
