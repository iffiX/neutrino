"""Rendering the nftables ruleset that steers LAN traffic into xray.

The content assertions run anywhere. The ones that hand the result to the real
``nft -c`` are marked ``needs_root``, because checking a ruleset means opening a
netlink socket; run the suite with sudo to include them.
"""

import pytest

from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer

from tests.conftest import (
    lan_entry,
    network_config,
    validate_nft,
    wan_entry,
    without_comments,
)

ROUTING_DIRECT = {"is_local_proxy_enabled": False}
ROUTING_LOCAL_PROXY = {"is_local_proxy_enabled": True}

TOPOLOGIES = {
    "one uplink, one lan": (
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
    ),
    "two uplinks, two lans": (
        wan_entry("enp2s0"),
        wan_entry("wlp3s0", intent="backup_only"),
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("enp3s0", address="192.168.101.1"),
    ),
    "wifi access point, wired uplink": (
        wan_entry("enp2s0"),
        lan_entry("wlp3s0", address="192.168.101.1"),
    ),
    "uplink only, nothing served": (wan_entry("enp2s0"),),
    "lan only, no way out": (lan_entry("enp1s0", address="192.168.100.1"),),
    "nothing configured": (),
}


AGENT_PORT = 8443


def render(*entries, routing=None) -> str:
    return RouterNftRenderer(
        network=network_config(*entries),
        routing={**ROUTING_DIRECT, **(routing or {})},
        xray_uid=999,
        agent_port=AGENT_PORT,
    ).render()


@pytest.mark.needs_root
@pytest.mark.parametrize("entries", TOPOLOGIES.values(), ids=list(TOPOLOGIES))
@pytest.mark.parametrize(
    "routing", [ROUTING_DIRECT, ROUTING_LOCAL_PROXY], ids=["direct", "local_proxy"]
)
def test_every_topology_renders_a_ruleset_nft_accepts(entries, routing):
    validate_nft(render(*entries, routing=routing))


def test_only_lan_traffic_is_diverted_into_the_proxy():
    ruleset = render(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))

    assert 'iifname != { "enp1s0" } return' in ruleset
    assert "tproxy ip to 127.0.0.1:12345" in ruleset


def test_both_lans_are_named_wherever_one_would_be():
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("wlp3s0", address="192.168.101.1"),
    )

    assert 'iifname != { "enp1s0", "wlp3s0" } return' in ruleset
    assert 'iifname { "enp1s0", "wlp3s0" } oifname { "enp2s0" } accept' in ruleset
    # The gateway's own networks are one trust domain: a device on the Wi-Fi and
    # one on the wire must be able to reach each other.
    assert 'iifname { "enp1s0", "wlp3s0" } oifname { "enp1s0", "wlp3s0" } accept' in (
        ruleset
    )


def test_every_uplink_is_masqueraded():
    ruleset = render(
        wan_entry("enp2s0"),
        wan_entry("wlp3s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
    )

    assert 'oifname { "enp2s0", "wlp3s0" } masquerade' in ruleset


def test_an_uplink_answers_nothing_until_it_is_exposed():
    """Remote access arrives over the overlay. An uplink that answers is one
    somebody asked to answer, and then it answers with everything this box
    listens on — there is no port list to get half right."""
    served = lan_entry("enp1s0", address="192.168.100.1")
    closed = render(wan_entry("enp2s0"), served)
    opened = render(wan_entry("enp2s0", is_exposed=True), served)

    assert 'iifname { "enp2s0" } accept' not in closed
    assert 'iifname { "enp2s0", "enp1s0" } accept' in opened


def test_a_closed_uplink_can_still_take_a_lease():
    """That is the box being a DHCP client, not a service answering."""
    ruleset = render(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))

    assert 'iifname { "enp2s0" } udp dport 68 accept' in ruleset


def test_an_exposed_uplink_is_not_told_twice_about_its_lease():
    """The accept for the whole interface already covers it, and a second
    rule saying so is a rule somebody has to read and dismiss."""
    ruleset = render(
        wan_entry("enp2s0", is_exposed=True), lan_entry("enp1s0", address="10.0.0.1")
    )

    assert "udp dport 68" not in ruleset


def test_the_overlay_answers_on_a_box_that_exposes_nothing():
    """Otherwise closing the last interface is a lockout with no way back."""
    ruleset = render(
        wan_entry("enp2s0"), lan_entry("enp1s0", address="10.0.0.1", is_exposed=False)
    )

    assert 'iifname "wt0" accept' in ruleset


def test_the_local_proxy_chain_cannot_loop_back_into_itself():
    """xray's own egress must never be diverted into xray."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing=ROUTING_LOCAL_PROXY,
    )

    assert "meta skuid 999 return" in ruleset
    assert "meta mark 0xff return" in ruleset


def test_the_output_chain_is_empty_while_the_local_proxy_is_off():
    ruleset = render(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))

    assert "meta skuid 999 return" not in ruleset


def test_an_unconfigured_box_renders_no_empty_sets():
    """nft rejects `{ }`, so every rule naming a set has to be skipped instead.

    A box whose interfaces have not been given roles yet still has to produce a
    loadable ruleset — otherwise the installer cannot bring the firewall up on
    a fresh machine.
    """
    body = without_comments(render())

    assert "{  }" not in body
    assert "{ }" not in body
    assert "masquerade" not in body


def test_a_box_with_no_uplink_still_serves_and_firewalls_its_lan():
    ruleset = render(lan_entry("enp1s0", address="192.168.100.1"))

    assert 'iifname { "enp1s0" } accept' in ruleset
    assert "masquerade" not in without_comments(ruleset)


def test_the_lan_switch_off_stops_the_firewall_diverting():
    """The proxy has to leave the path everywhere at once.

    A ruleset that still diverts into a proxy the rest of the box has been told
    to stop using would send LAN traffic to a socket nothing is answering on.
    """
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing={"is_proxy_enabled": False},
    )
    body = without_comments(ruleset)

    assert "tproxy ip to" not in body
    # It still routes and masquerades, so the box works as a plain router.
    assert 'iifname { "enp1s0" } oifname { "enp2s0" } accept' in body
    assert 'oifname { "enp2s0" } masquerade' in body


def test_the_hub_scope_outlives_the_lan_switch():
    """The scopes stand alone: the box's own traffic is still diverted with
    the LAN switch off, and the LAN's is still not."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing={"is_proxy_enabled": False, "is_local_proxy_enabled": True},
    )
    body = without_comments(ruleset)

    assert "meta skuid 999 return" in body
    assert 'iifname "lo"' in body
    assert "iifname !=" not in body


def test_fenced_lans_cannot_reach_each_other():
    """With the inter-LAN switch off, the drop policy holds between networks."""
    entries = (
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("enp1s0.10", address="192.168.110.1"),
    )
    fenced = RouterNftRenderer(
        network=network_config(*entries, is_inter_lan_allowed=False),
        routing=ROUTING_DIRECT,
        xray_uid=999,
        agent_port=AGENT_PORT,
    ).render()

    lan_set = 'iifname { "enp1s0", "enp1s0.10" }'
    assert f'{lan_set} oifname {{ "enp1s0", "enp1s0.10" }} accept' not in fenced
    # Every network still reaches the internet and the overlay.
    assert f'{lan_set} oifname {{ "enp2s0" }} accept' in fenced
    assert f'{lan_set} oifname "wt0" accept' in fenced


def test_the_untagged_main_names_the_port_itself():
    """The firewall matches the trunk port, not the panel-side main name."""
    ruleset = render(
        wan_entry("wlp3s0"),
        {"name": "enp2s0", "role": "split"},
        {
            **wan_entry("enp2s0.main"),
            "vlan": {"parent": "enp2s0", "id": None},
        },
        {
            **lan_entry("enp2s0.20", address="192.168.104.1"),
            "vlan": {"parent": "enp2s0", "id": 20},
        },
    )

    assert '"enp2s0.main"' not in ruleset
    assert 'oifname { "wlp3s0", "enp2s0" } masquerade' in ruleset
    assert 'iifname != { "enp2s0.20" } return' in ruleset


def test_a_side_gateway_hairpins_and_masquerades_precisely():
    """One port in and out: forwarded traffic to the router is masqueraded,
    delivery to the network's own hosts is not."""
    entry = lan_entry("enp1s0", address="192.168.1.2", is_dhcp_enabled=False)
    entry["lan"]["upstream_gateway"] = "192.168.1.1"
    ruleset = render(entry)

    assert 'iifname { "enp1s0" } oifname { "enp1s0" } accept' in ruleset
    assert 'oifname "enp1s0" ip daddr != 192.168.1.0/24 masquerade' in ruleset


def test_a_closed_lan_is_still_served_its_lease_and_names():
    """Exposure gates what the box hosts, never the serving itself: a LAN
    nobody exposed still gets DHCP and DNS through the input chain."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.93.1", is_exposed=False),
    )

    assert 'iifname { "enp1s0" } udp dport 67 accept' in ruleset
    assert 'iifname { "enp1s0" } udp dport 53 accept' in ruleset
    assert 'iifname { "enp1s0" } tcp dport 53 accept' in ruleset
    assert 'iifname { "enp1s0" } accept' not in ruleset


def test_an_exposed_lan_needs_no_extra_serving_rules():
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.93.1"),
    )

    assert 'iifname { "enp1s0" } accept' in ruleset
    assert 'iifname { "enp1s0" } udp dport 67 accept' not in ruleset
    assert f"tcp dport {AGENT_PORT}" not in ruleset


def test_the_agent_port_answers_on_a_served_network_nobody_exposed():
    """The agent channel opens wherever the panel does and on every served
    wire besides: a device the hub manages heartbeats to it whether or not
    its network hosts anything else."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.93.1", is_exposed=False),
    )

    assert f'iifname {{ "enp1s0" }} tcp dport {AGENT_PORT} accept' in ruleset


def test_a_closed_uplink_does_not_answer_the_agent_port():
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.93.1"),
    )

    assert f'iifname {{ "enp2s0" }} tcp dport {AGENT_PORT} accept' not in ruleset
