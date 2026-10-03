"""What the system firewall must allow on a macOS or Windows hub.

What these pin: one Windows rule per purpose, named ``neutrino_hub_<purpose>``,
for the panel's two ports, the agent port, the AI gateway's port, each SOCKS
port over TCP and UDP and each enabled overlay's peer port; and on macOS the
programs, the hub first and the AI gateway's among them.
"""

from neutrino_hub.modules.firewall.renderer import (
    FirewallPortRule,
    render_port_rules,
    render_programs,
)


def test_every_port_the_hub_serves_has_one_rule_per_purpose():
    rules = render_port_rules(
        panel_http_port=8080,
        panel_https_port=443,
        agent_port=8443,
        ai_gateway_port=8317,
        socks_ports=[1081, 1080, 1080],
        overlays=["easytier", "netbird"],
    )

    assert rules == [
        FirewallPortRule("neutrino_hub_panel_http", "TCP", 8080),
        FirewallPortRule("neutrino_hub_panel_https", "TCP", 443),
        FirewallPortRule("neutrino_hub_agent", "TCP", 8443),
        FirewallPortRule("neutrino_hub_ai_gateway", "TCP", 8317),
        FirewallPortRule("neutrino_hub_socks_1080_tcp", "TCP", 1080),
        FirewallPortRule("neutrino_hub_socks_1080_udp", "UDP", 1080),
        FirewallPortRule("neutrino_hub_socks_1081_tcp", "TCP", 1081),
        FirewallPortRule("neutrino_hub_socks_1081_udp", "UDP", 1081),
        FirewallPortRule("neutrino_hub_netbird_udp", "UDP", 51820),
        FirewallPortRule("neutrino_hub_easytier_tcp", "TCP", 11010),
        FirewallPortRule("neutrino_hub_easytier_udp", "UDP", 11010),
    ]


def test_an_overlay_turned_off_opens_nothing():
    rules = render_port_rules(
        panel_http_port=9000,
        panel_https_port=9443,
        agent_port=8443,
        ai_gateway_port=9317,
        socks_ports=[],
        overlays=[],
    )

    assert [rule.name for rule in rules] == [
        "neutrino_hub_panel_http",
        "neutrino_hub_panel_https",
        "neutrino_hub_agent",
        "neutrino_hub_ai_gateway",
    ]
    assert rules[0].port == 9000
    assert rules[3].port == 9317


def test_macos_allows_the_hub_xray_and_the_enabled_overlays_daemons():
    programs = render_programs(
        hub_program="/usr/local/bin/nhub",
        xray_program="/app/bin/xray",
        ai_gateway_program="/app/bin/cli-proxy-api",
        overlay_programs={
            "netbird": "/app/bin/netbird",
            "easytier": "/app/bin/easytier-core",
        },
        overlays=["easytier"],
    )

    assert programs == [
        "/usr/local/bin/nhub",
        "/app/bin/xray",
        "/app/bin/cli-proxy-api",
        "/app/bin/easytier-core",
    ]
