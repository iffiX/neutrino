"""What the system firewall must allow on a macOS or Windows hub.

What these pin: one Windows rule per purpose, named ``neutrino_hub_<purpose>``,
for the panel's two ports, the agent port, the AI gateway's port, each SOCKS
port over TCP and UDP and each enabled overlay's peer port, each on the
exposed interfaces and a closed overlay's on none; the pf anchor blocking
each port on the interfaces it does not answer on; and on macOS the
programs, the hub first and the AI gateway's among them.
"""

from neutrino_hub.modules.firewall.renderer import (
    FirewallPortRule,
    render_pf_anchor,
    render_port_rules,
    render_programs,
)


def rules_on(exposed: list, *, exposed_overlays=("netbird",)) -> list:
    """The rules of a hub with one SOCKS port and NetBird running."""
    return render_port_rules(
        panel_http_port=80,
        panel_https_port=443,
        agent_port=8443,
        ai_gateway_port=8317,
        socks_ports=[1080],
        overlays=["netbird"],
        exposed_interfaces=exposed,
        exposed_overlays=list(exposed_overlays),
    )


def test_every_port_the_hub_serves_has_one_rule_per_purpose():
    rules = render_port_rules(
        panel_http_port=8080,
        panel_https_port=443,
        agent_port=8443,
        ai_gateway_port=8317,
        socks_ports=[1081, 1080, 1080],
        overlays=["easytier", "netbird"],
        exposed_interfaces=["en0", "en0"],
        exposed_overlays=["easytier", "netbird"],
    )

    on = ("en0",)
    assert rules == [
        FirewallPortRule("neutrino_hub_panel_http", "TCP", 8080, on),
        FirewallPortRule("neutrino_hub_panel_https", "TCP", 443, on),
        FirewallPortRule("neutrino_hub_agent", "TCP", 8443, on),
        FirewallPortRule("neutrino_hub_ai_gateway", "TCP", 8317, on),
        FirewallPortRule("neutrino_hub_socks_1080_tcp", "TCP", 1080, on),
        FirewallPortRule("neutrino_hub_socks_1080_udp", "UDP", 1080, on),
        FirewallPortRule("neutrino_hub_socks_1081_tcp", "TCP", 1081, on),
        FirewallPortRule("neutrino_hub_socks_1081_udp", "UDP", 1081, on),
        FirewallPortRule("neutrino_hub_netbird_udp", "UDP", 51820, on),
        FirewallPortRule("neutrino_hub_easytier_tcp", "TCP", 11010, on),
        FirewallPortRule("neutrino_hub_easytier_udp", "UDP", 11010, on),
    ]


def test_an_overlay_turned_off_opens_nothing():
    rules = render_port_rules(
        panel_http_port=9000,
        panel_https_port=9443,
        agent_port=8443,
        ai_gateway_port=9317,
        socks_ports=[],
        overlays=[],
        exposed_interfaces=["en0"],
        exposed_overlays=["netbird"],
    )

    assert [rule.name for rule in rules] == [
        "neutrino_hub_panel_http",
        "neutrino_hub_panel_https",
        "neutrino_hub_agent",
        "neutrino_hub_ai_gateway",
    ]
    assert rules[0].port == 9000
    assert rules[3].port == 9317


def test_one_of_two_interfaces_exposed_scopes_every_rule_to_it():
    rules = rules_on(["Ethernet Instance 0 2", "wt0"])

    on = ("Ethernet Instance 0 2", "wt0")
    assert [(rule.name, rule.interfaces) for rule in rules] == [
        ("neutrino_hub_panel_http", on),
        ("neutrino_hub_panel_https", on),
        ("neutrino_hub_agent", on),
        ("neutrino_hub_ai_gateway", on),
        ("neutrino_hub_socks_1080_tcp", on),
        ("neutrino_hub_socks_1080_udp", on),
        ("neutrino_hub_netbird_udp", on),
    ]


def test_a_closed_overlay_s_peer_port_answers_nowhere():
    rules = rules_on(["Wi-Fi"], exposed_overlays=())

    assert rules[-1].name == "neutrino_hub_netbird_udp"
    assert rules[-1].interfaces == ()
    assert rules[0].interfaces == ("Wi-Fi",)


def test_none_exposed_leaves_every_rule_on_no_interface():
    assert {rule.interfaces for rule in rules_on([], exposed_overlays=())} == {()}


def test_the_pf_anchor_blocks_each_port_on_the_interface_not_exposed():
    anchor = render_pf_anchor(
        rules_on(["en1", "utun4"]), interfaces=["en0", "en1", "utun4"]
    )

    assert anchor == (
        "block drop in quick on { en0 } proto tcp from any to any port 80\n"
        "block drop in quick on { en0 } proto tcp from any to any port 443\n"
        "block drop in quick on { en0 } proto tcp from any to any port 8443\n"
        "block drop in quick on { en0 } proto tcp from any to any port 8317\n"
        "block drop in quick on { en0 } proto tcp from any to any port 1080\n"
        "block drop in quick on { en0 } proto udp from any to any port 1080\n"
        "block drop in quick on { en0 } proto udp from any to any port 51820\n"
    )


def test_the_pf_anchor_with_none_exposed_blocks_everywhere_but_loopback():
    anchor = render_pf_anchor(
        rules_on([], exposed_overlays=()), interfaces=["en0", "en1"]
    )

    assert anchor.splitlines() == [
        "block drop in quick on ! lo0 proto tcp from any to any port 80",
        "block drop in quick on ! lo0 proto tcp from any to any port 443",
        "block drop in quick on ! lo0 proto tcp from any to any port 8443",
        "block drop in quick on ! lo0 proto tcp from any to any port 8317",
        "block drop in quick on ! lo0 proto tcp from any to any port 1080",
        "block drop in quick on ! lo0 proto udp from any to any port 1080",
        "block drop in quick on ! lo0 proto udp from any to any port 51820",
    ]


def test_the_pf_anchor_with_everything_exposed_is_empty():
    anchor = render_pf_anchor(rules_on(["en0", "en1"]), interfaces=["en0", "en1"])

    assert anchor == ""


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
