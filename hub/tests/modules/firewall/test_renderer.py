"""What the hub's firewall answers, and that answer in each system's form.

What these pin: the hub's ports are the panel's two, the agent port, DNS in
``router`` and ``side_gateway`` and each SOCKS port over TCP and UDP, and the
AI gateway's is none of them; each answers the senders inside the exposed
segments, an IPv6 segment's ``fe80::/64`` on its own interface; the running
engines' peer ports and DHCP open with no switch; Direct opens the agent
port to every sender on the enabled interfaces. Then the same answer as
Windows rules, one per purpose, with the segments as remote addresses; as a
pf anchor with an address table per family; as firewalld rich rules in the
zone of each interface; and on macOS the programs, the hub first. Before
setup the wizard's port is one Windows rule open to every sender, and one
firewalld rule with no source in every zone.
"""

import pytest
from neutrino_hub.modules.firewall.renderer import (
    FirewallPort,
    FirewallPortRule,
    firewalld_rule,
    render_exposure,
    render_firewalld_rules,
    render_firewalld_setup_rules,
    render_pf_anchor,
    render_port_rules,
    render_programs,
    render_setup_port_rule,
)
from neutrino_hub.modules.router.interfaces import RouterSegment

from tests.conftest import lan_entry, network_config, wan_entry

HELD = {
    "en0": ["192.168.1.20/24", "2001:db8:1::20/64", "fe80::20/64"],
    "en1": ["10.0.0.5/24", "fe80::5/64"],
    "utun4": ["100.92.4.5/16"],
}


def server(*entries, overlays=(), devices=None):
    """A server's configuration, NetBird on ``utun4`` when it runs."""
    network = network_config(*entries, mode="server", overlays=list(overlays))
    return network.with_overlay_devices(devices or {"netbird": ["utun4"]})


def exposure_of(network, *, held=HELD, socks_ports=(1080,), is_direct=False):
    return render_exposure(
        network,
        held=held,
        panel_http_port=80,
        panel_https_port=443,
        agent_port=8443,
        socks_ports=list(socks_ports),
        is_direct=is_direct,
    )


EN0_OPEN = {"name": "en0", "role": "disabled", "is_exposed": True}
EN1_CLOSED = {"name": "en1", "role": "disabled", "is_exposed": False}


# --- The exposure ---


def test_the_hubs_ports_are_its_panel_agent_and_socks_ports_and_not_the_gateway():
    exposure = exposure_of(server(EN0_OPEN), socks_ports=(1081, 1080, 1080))

    assert exposure.hub_ports == (
        FirewallPort("panel_http", "TCP", 80),
        FirewallPort("panel_https", "TCP", 443),
        FirewallPort("agent", "TCP", 8443),
        FirewallPort("socks_1080_tcp", "TCP", 1080),
        FirewallPort("socks_1080_udp", "UDP", 1080),
        FirewallPort("socks_1081_tcp", "TCP", 1081),
        FirewallPort("socks_1081_udp", "UDP", 1081),
    )
    assert 8317 not in {port.port for port in exposure.hub_ports}


@pytest.mark.parametrize("mode", ["router", "side_gateway"])
def test_dns_is_a_hub_port_where_the_hub_answers_names(mode):
    network = network_config(lan_entry("en0", address="192.168.1.20"), mode=mode)

    ports = exposure_of(network, socks_ports=()).hub_ports

    assert FirewallPort("dns_tcp", "TCP", 53) in ports
    assert FirewallPort("dns_udp", "UDP", 53) in ports


def test_the_segments_are_the_exposed_interfaces_networks_and_the_overlays():
    exposure = exposure_of(
        server(EN0_OPEN, EN1_CLOSED, overlays=[{"provider": "netbird"}])
    )

    assert exposure.segments == (
        RouterSegment("en0", "ipv4", ("192.168.1.0/24",)),
        RouterSegment("en0", "ipv6", ("2001:db8:1::/64", "fe80::/64")),
        RouterSegment("utun4", "ipv4", ("100.92.0.0/16",)),
    )
    assert exposure.networks("ipv4") == ["192.168.1.0/24", "100.92.0.0/16"]
    assert exposure.networks("ipv6") == ["2001:db8:1::/64"]
    assert exposure.link_local_devices == ["en0"]


def test_a_running_engines_peer_port_opens_whatever_its_chip():
    exposure = exposure_of(
        server(
            EN0_OPEN,
            overlays=[
                {"provider": "netbird", "is_exposed": False},
                {"provider": "easytier", "is_enabled": False},
            ],
        )
    )

    assert exposure.peer_ports == (FirewallPort("netbird_udp", "UDP", 51820),)
    assert "utun4" not in {segment.device for segment in exposure.segments}


def test_dhcp_opens_on_each_network_whose_dhcp_the_hub_serves():
    side = lan_entry("en1", address="10.0.0.5", is_dhcp_enabled=False)
    network = network_config(
        wan_entry("en2"), lan_entry("en0", address="192.168.1.20"), side, overlays=[]
    )

    assert exposure_of(network).dhcp_devices == ("en0",)


def test_direct_opens_the_agent_port_on_the_enabled_interfaces_holding_an_address():
    network = network_config(
        wan_entry("en2"),
        lan_entry("en0", address="192.168.1.20"),
        {"name": "en1", "role": "disabled"},
        overlays=[],
    )

    off = exposure_of(network, held={**HELD, "en2": ["198.51.100.2/24"]})
    on = exposure_of(network, held={**HELD, "en2": ["198.51.100.2/24"]}, is_direct=True)

    assert off.direct_port is None
    assert on.direct_port == 8443
    assert on.enabled_devices == ("en2", "en0")


# --- Windows ---


@pytest.mark.feature("proxy")
def test_windows_has_one_rule_per_purpose_naming_the_segments_as_remote_addresses():
    rules = render_port_rules(
        exposure_of(server(EN0_OPEN, EN1_CLOSED, overlays=[{"provider": "netbird"}]))
    )

    remote = ("192.168.1.0/24", "100.92.0.0/16", "2001:db8:1::/64")
    link = ("fe80::/64",)
    assert rules == [
        FirewallPortRule("neutrino_hub_panel_http", "TCP", 80, remote),
        FirewallPortRule("neutrino_hub_panel_http_link", "TCP", 80, link, ("en0",)),
        FirewallPortRule("neutrino_hub_panel_https", "TCP", 443, remote),
        FirewallPortRule("neutrino_hub_panel_https_link", "TCP", 443, link, ("en0",)),
        FirewallPortRule("neutrino_hub_agent", "TCP", 8443, remote),
        FirewallPortRule("neutrino_hub_agent_link", "TCP", 8443, link, ("en0",)),
        FirewallPortRule("neutrino_hub_socks_1080_tcp", "TCP", 1080, remote),
        FirewallPortRule(
            "neutrino_hub_socks_1080_tcp_link", "TCP", 1080, link, ("en0",)
        ),
        FirewallPortRule("neutrino_hub_socks_1080_udp", "UDP", 1080, remote),
        FirewallPortRule(
            "neutrino_hub_socks_1080_udp_link", "UDP", 1080, link, ("en0",)
        ),
        FirewallPortRule("neutrino_hub_netbird_udp", "UDP", 51820),
    ]


def test_windows_with_no_segment_exposed_keeps_no_hub_port_rule():
    """The profile's default inbound block closes a port no rule allows."""
    rules = render_port_rules(exposure_of(server(EN1_CLOSED), socks_ports=()))

    assert rules == []


def test_windows_direct_takes_any_remote_address_on_the_enabled_interfaces():
    rules = render_port_rules(
        exposure_of(server(EN0_OPEN, EN1_CLOSED), socks_ports=(), is_direct=True)
    )

    assert rules[-1] == FirewallPortRule(
        "neutrino_hub_agent_direct", "TCP", 8443, (), ("en0", "en1")
    )


# --- macOS ---


def test_the_pf_anchor_passes_loopback_and_the_segments_and_blocks_the_rest():
    anchor = render_pf_anchor(
        exposure_of(server(EN0_OPEN, EN1_CLOSED, overlays=[{"provider": "netbird"}]))
    )

    assert anchor.splitlines() == [
        "table <neutrino_hub_ipv4> const { 192.168.1.0/24, 100.92.0.0/16 }",
        "table <neutrino_hub_ipv6> const { 2001:db8:1::/64 }",
        "pass in quick on lo0 proto tcp from any to any port { 80, 443, 8443, 1080 }",
        "pass in quick inet proto tcp from <neutrino_hub_ipv4> to any port "
        "{ 80, 443, 8443, 1080 }",
        "pass in quick inet6 proto tcp from <neutrino_hub_ipv6> to any port "
        "{ 80, 443, 8443, 1080 }",
        "pass in quick on en0 inet6 proto tcp from fe80::/64 to any port "
        "{ 80, 443, 8443, 1080 }",
        "block drop in quick proto tcp from any to any port { 80, 443, 8443, 1080 }",
        "pass in quick on lo0 proto udp from any to any port 1080",
        "pass in quick inet proto udp from <neutrino_hub_ipv4> to any port 1080",
        "pass in quick inet6 proto udp from <neutrino_hub_ipv6> to any port 1080",
        "pass in quick on en0 inet6 proto udp from fe80::/64 to any port 1080",
        "block drop in quick proto udp from any to any port 1080",
    ]


def test_the_pf_anchor_with_nothing_exposed_passes_loopback_alone():
    anchor = render_pf_anchor(exposure_of(server(EN1_CLOSED), socks_ports=()))

    assert anchor.splitlines() == [
        "pass in quick on lo0 proto tcp from any to any port { 80, 443, 8443 }",
        "block drop in quick proto tcp from any to any port { 80, 443, 8443 }",
    ]


def test_the_pf_anchor_passes_the_agent_port_from_any_address_on_directs_interfaces():
    anchor = render_pf_anchor(
        exposure_of(server(EN1_CLOSED), socks_ports=(), is_direct=True)
    ).splitlines()

    direct = "pass in quick on { en1 } proto tcp from any to any port 8443"
    assert direct in anchor
    assert anchor.index(direct) < anchor.index(
        "block drop in quick proto tcp from any to any port { 80, 443, 8443 }"
    )


def test_macos_allows_the_hub_xray_and_the_enabled_overlays_daemons():
    programs = render_programs(
        hub_program="/usr/local/bin/nhub",
        xray_program="/app/bin/xray",
        overlay_programs={
            "netbird": "/app/bin/netbird",
            "easytier": "/app/bin/easytier-core",
        },
        overlays=["easytier"],
    )

    assert programs == [
        "/usr/local/bin/nhub",
        "/app/bin/xray",
        "/app/bin/easytier-core",
    ]


# --- firewalld ---


def test_firewalld_gets_a_rich_rule_per_network_and_hub_port_in_each_zone():
    network = network_config(
        wan_entry("en2"),
        lan_entry("en0", address="192.168.1.20"),
        overlays=[{"provider": "netbird"}],
    ).with_overlay_devices({"netbird": ["utun4"]})
    exposure = render_exposure(
        network,
        held={"en0": ["192.168.1.20/24"], "en2": ["198.51.100.2/24"], **HELD},
        panel_http_port=80,
        panel_https_port=443,
        agent_port=8443,
        socks_ports=[],
        is_direct=True,
    )

    rules = render_firewalld_rules(
        exposure, zones={"utun4": "trusted", "en2": "external"}, default_zone="public"
    )

    lan = [
        firewalld_rule(family="ipv4", source="192.168.1.0/24", port=port, protocol=p)
        for port, p in ((80, "TCP"), (443, "TCP"), (8443, "TCP"), (53, "TCP"))
    ]
    assert set(lan) <= set(rules["public"])
    assert firewalld_rule(family="ipv4", port=67, protocol="UDP") in rules["public"]
    assert firewalld_rule(port=51820, protocol="UDP") in rules["public"]
    assert firewalld_rule(port=51820, protocol="UDP") in rules["external"]
    assert firewalld_rule(port=8443, protocol="TCP") in rules["external"]
    assert not any("198.51.100" in rule for rule in rules["external"])
    assert (
        firewalld_rule(family="ipv4", source="100.92.0.0/16", port=80, protocol="TCP")
        in rules["trusted"]
    )
    assert all(zone_rules == sorted(set(zone_rules)) for zone_rules in rules.values())


def test_a_firewalld_rule_is_written_as_firewall_cmd_prints_it():
    assert firewalld_rule(
        family="ipv6", source="2001:db8:1::/64", port=8443, protocol="TCP"
    ) == (
        'rule priority="32123" family="ipv6" source address="2001:db8:1::/64" '
        'port port="8443" protocol="tcp" accept'
    )
    assert firewalld_rule(port=11010, protocol="UDP") == (
        'rule priority="32123" port port="11010" protocol="udp" accept'
    )


def test_the_wizards_port_is_one_windows_rule_open_to_every_sender():
    assert render_setup_port_rule(8080) == FirewallPortRule(
        name="neutrino_hub_setup", protocol="TCP", port=8080
    )


def test_the_wizards_port_is_one_firewalld_rule_in_every_zone_and_the_default():
    rules = render_firewalld_setup_rules(
        8080,
        zones={"eth0": "public", "wt0": "trusted", "eth1": "public"},
        default_zone="home",
    )

    rule = 'rule priority="32123" port port="8080" protocol="tcp" accept'
    assert rules == {"home": [rule], "public": [rule], "trusted": [rule]}
