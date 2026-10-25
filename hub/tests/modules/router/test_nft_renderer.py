"""Rendering the nftables ruleset that steers LAN traffic into xray.

The content assertions run anywhere. The ones that hand the result to the real
``nft -c`` are marked ``needs_root``, because checking a ruleset means opening a
netlink socket; run the suite with sudo to include them.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from neutrino_hub.modules.firewall.renderer import render_exposure
from neutrino_hub.modules.router import nft_renderer
from neutrino_hub.modules.router.constants import ROUTER_FWMARK_TPROXY
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


PANEL_HTTP_PORT = 8080
PANEL_HTTPS_PORT = 8444
AGENT_PORT = 8443
# What the box holds in most tests: an uplink on a public network, the
# served networks on their configured addresses, NetBird on its own.
HELD = {
    "enp2s0": ["203.0.113.7/24", "2001:db8:2::7/64", "fe80::2/64"],
    "enp1s0": ["192.168.100.1/24", "fd00:100::1/64", "fe80::1/64"],
    "wt0": ["100.92.4.5/16"],
    "easytier": ["10.144.0.1/24"],
}


def render(
    *entries,
    routing=None,
    held=None,
    is_direct=False,
    socks_ports=(),
    overlay_devices=None,
    engine_cgroups=None,
    **rest,
) -> str:
    """The whole ruleset for these interfaces, with the exposure they give."""
    network = network_config(*entries, **rest)
    found = (
        network
        if overlay_devices is None
        else network.with_overlay_devices(overlay_devices)
    )
    return RouterNftRenderer(
        network=network,
        routing={**ROUTING_DIRECT, **(routing or {})},
        xray_uid=999,
        exposure=render_exposure(
            found,
            held=HELD if held is None else held,
            panel_http_port=PANEL_HTTP_PORT,
            panel_https_port=PANEL_HTTPS_PORT,
            agent_port=AGENT_PORT,
            socks_ports=list(socks_ports),
            is_direct=is_direct,
        ),
        overlay_devices=overlay_devices,
        engine_cgroups=engine_cgroups,
    ).render()


def input_chain(ruleset: str) -> list:
    """The input chain's lines, comments left out."""
    chain = without_comments(ruleset).split("chain input {", 1)[1]
    chain = chain.split("\n    }", 1)[0]
    return [line.strip() for line in chain.splitlines() if line.strip()]


@pytest.mark.needs_root
@pytest.mark.parametrize("entries", TOPOLOGIES.values(), ids=list(TOPOLOGIES))
@pytest.mark.parametrize(
    "routing", [ROUTING_DIRECT, ROUTING_LOCAL_PROXY], ids=["direct", "local_proxy"]
)
def test_every_topology_renders_a_ruleset_nft_accepts(entries, routing):
    validate_nft(render(*entries, routing=routing))


@pytest.mark.feature("proxy")
def test_only_lan_traffic_is_diverted_into_the_proxy():
    ruleset = render(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))

    assert 'iifname != { "enp1s0" } return' in ruleset
    assert "tproxy ip to 127.0.0.1:12345" in ruleset


@pytest.mark.feature("proxy")
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


# DNS from a container, which its network's resolver on the bridge's
# gateway answers.
PODMAN_DNS = [
    'iifname "podman*" udp dport 53 accept',
    'iifname "podman*" tcp dport 53 accept',
    'iifname "cni-podman*" udp dport 53 accept',
    'iifname "cni-podman*" tcp dport 53 accept',
]
ROUTER_INPUT = [
    "type nat hook input priority 100; policy accept;",
    'iifname "lo" accept',
    *PODMAN_DNS,
    "ip saddr { 192.168.100.0/24, 100.92.0.0/16 } accept",
    "ip6 saddr { fd00:100::/64 } accept",
    'iifname "enp1s0" ip6 saddr fe80::/64 accept',
    "ct state new tcp dport { 8080, 8444, 8443, 53 } drop",
    "ct state new udp dport { 53 } drop",
]


def test_a_hub_port_answers_loopback_and_the_exposed_segments_and_no_one_else():
    """The served network's two segments and NetBird's network are exposed,
    the uplink's are not; every hub port is dropped from every other sender,
    and no other port is named."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing={"is_proxy_enabled": False},
    )

    assert input_chain(ruleset) == ROUTER_INPUT


def test_the_input_chain_is_the_only_input_chain_and_accepts_by_policy():
    """SSH, a file share and every other service the hub does not run pass
    the hub's chain: they are the system firewall's matter."""
    ruleset = without_comments(
        render(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))
    )

    assert ruleset.count("hook input") == 1
    assert "policy drop" not in ruleset.split("chain input {", 1)[1].split("}", 1)[0]


# NetBird 0.78.1's own test of a chain it inserts its accept into: a chain of
# another table, of type filter, on the input or forward hook
# (client/firewall/nftables/chains_linux.go, isExternalChain).
NETBIRD_EDITED_HOOKS = ("input", "forward")


def chains_an_engine_edits(ruleset: str) -> list:
    """The base chains of the hub's table NetBird inserts an accept into."""
    found = re.findall(r"chain (\w+) \{\s*type (\w+) hook (\w+)", ruleset)
    return [
        name
        for name, kind, hook in found
        if kind == "filter" and hook in NETBIRD_EDITED_HOOKS
    ]


def test_no_engine_edits_the_chain_that_drops_the_hub_ports():
    """An accept NetBird inserts at the top of a chain would pass NetBird's
    senders through that chain's drop, so the drop lives where it inserts
    nothing."""
    ruleset = without_comments(
        render(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))
    )
    dropping = [
        name
        for name, body in re.findall(r"chain (\w+) \{(.*?)\n    \}", ruleset, re.S)
        if "dport" in body and " drop" in body
    ]

    assert dropping == ["input"]
    assert "input" not in chains_an_engine_edits(ruleset)
    assert "forward" in chains_an_engine_edits(ruleset)


def test_a_closed_segment_drops_the_hub_ports_and_leaves_every_other_port():
    """A closed uplink's networks are in no accept; the drops name the hub's
    ports alone, so the uplink's lease, SSH and the rest pass."""
    chain = input_chain(
        render(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))
    )
    drops = [line for line in chain if line.endswith(" drop")]

    assert not any("203.0.113" in line or "2001:db8:2" in line for line in chain)
    assert drops == [
        "ct state new tcp dport { 8080, 8444, 8443, 53 } drop",
        "ct state new udp dport { 53 } drop",
    ]


def test_an_exposed_uplink_segment_answers_the_senders_in_its_network_alone():
    """A rule names the sender's network, never the wire: an uplink with a
    public address exposed opens the hub's ports to its own network, not to
    the internet behind it."""
    chain = input_chain(
        render(
            wan_entry("enp2s0", is_exposed=True),
            lan_entry("enp1s0", address="192.168.100.1", is_exposed=False),
            overlays=[],
        )
    )

    assert "ip saddr { 203.0.113.0/24 } accept" in chain
    assert "ip6 saddr { 2001:db8:2::/64 } accept" in chain
    assert 'iifname "enp2s0" ip6 saddr fe80::/64 accept' in chain
    assert not any("iifname {" in line for line in chain)


def test_each_family_has_its_own_switch():
    entry = {
        **lan_entry("enp1s0", address="192.168.100.1"),
        "is_ipv4_exposed": True,
        "is_ipv6_exposed": False,
    }
    chain = input_chain(render(entry, overlays=[]))

    assert "ip saddr { 192.168.100.0/24 } accept" in chain
    assert not any("ip6 saddr" in line for line in chain)


def test_a_row_with_the_earlier_switch_opens_both_families():
    entry = {"name": "enp1s0", "role": "disabled", "is_exposed": True}
    chain = input_chain(render(entry, overlays=[], mode="server"))

    assert "ip saddr { 192.168.100.0/24 } accept" in chain
    assert "ip6 saddr { fd00:100::/64 } accept" in chain


def test_a_changed_ipv6_prefix_keeps_its_switch():
    """The rule follows the networks the interface holds now."""
    entries = (lan_entry("enp1s0", address="192.168.100.1"),)
    before = input_chain(render(*entries, overlays=[]))
    after = input_chain(
        render(
            *entries,
            overlays=[],
            held={"enp1s0": ["192.168.100.1/24", "2001:db8:77::1/64"]},
        )
    )

    assert "ip6 saddr { fd00:100::/64 } accept" in before
    assert "ip6 saddr { 2001:db8:77::/64 } accept" in after
    assert not any("fd00:100" in line for line in after)


def test_a_link_local_sender_is_matched_on_its_own_interface():
    """``fe80::/64`` is every link's, so it opens on the interface whose
    IPv6 segment is exposed and on no other."""
    chain = input_chain(
        render(
            wan_entry("enp2s0"),
            lan_entry("enp1s0", address="192.168.100.1"),
            overlays=[],
        )
    )

    assert [line for line in chain if "fe80::/64" in line] == [
        'iifname "enp1s0" ip6 saddr fe80::/64 accept'
    ]


@pytest.mark.parametrize(
    ("mode", "is_dns"),
    [("router", True), ("side_gateway", True), ("server", False)],
)
def test_dns_is_a_hub_port_where_the_hub_answers_names(mode, is_dns):
    chain = input_chain(
        render(lan_entry("enp1s0", address="192.168.100.1"), mode=mode, overlays=[])
    )
    drops = " ".join(line for line in chain if line.endswith(" drop"))

    assert (" 53" in drops) is is_dns


def test_each_socks_port_is_a_hub_port_over_tcp_and_udp():
    chain = input_chain(
        render(
            lan_entry("enp1s0", address="192.168.100.1"),
            socks_ports=[1080, 1081],
            overlays=[],
        )
    )

    assert "ct state new tcp dport { 8080, 8444, 8443, 53, 1080, 1081 } drop" in chain
    assert "ct state new udp dport { 53, 1080, 1081 } drop" in chain


def test_nothing_drops_the_peer_ports_or_dhcp():
    """They open with no switch: the chain's accept policy passes them."""
    ruleset = without_comments(
        render(
            wan_entry("enp2s0"),
            lan_entry("enp1s0", address="192.168.100.1", is_exposed=False),
            overlays=[{"provider": "netbird"}, {"provider": "easytier"}],
        )
    )

    for port in ("51820", "11010", "67", "68"):
        assert not re.search(rf"\b{port}\b", ruleset)


def test_the_overlay_answers_on_a_box_that_exposes_nothing():
    """Otherwise closing the last interface is a lockout with no way back."""
    chain = input_chain(
        render(
            wan_entry("enp2s0"),
            lan_entry("enp1s0", address="192.168.100.1", is_exposed=False),
        )
    )

    assert "ip saddr { 100.92.0.0/16 } accept" in chain


def test_a_configuration_with_no_overlays_block_still_answers_on_one():
    """The firewall accepted the overlay unconditionally before it was
    configurable, so a box upgrading into this must find nothing changed. Who
    can reach the machine is not a thing to alter behind somebody's back."""
    ruleset = render(lan_entry("enp1s0", address="192.168.100.1", is_exposed=False))

    assert "ip saddr { 100.92.0.0/16 } accept" in input_chain(ruleset)
    assert 'iifname { "wt0" } accept' in ruleset


def test_a_closed_overlay_answers_none_of_the_hub_ports_and_forwards_nothing():
    """Its network is in no accept of the input chain, and the forward chain
    names it nowhere."""
    closed = render(
        lan_entry("enp1s0", address="192.168.100.1"),
        overlays=[{"provider": "netbird", "is_exposed": False}],
    )

    assert "wt0" not in closed
    assert "100.92" not in closed
    assert "51820" not in closed


def test_no_overlay_is_named_in_the_renderer_itself():
    """Every overlay rule comes from the configuration. A device name written
    into this module is the next overlay's rules being written by hand."""
    source = Path(nft_renderer.__file__).read_text()

    assert "wt0" not in source
    assert "51820" not in source
    assert '"easytier"' not in source
    assert "tun0" not in source


def render_console(*entries, devices, routing=None) -> str:
    """The ruleset for a box on EasyTier in console mode, its devices found."""
    return render(
        *entries,
        routing=routing,
        held={**HELD, "tun0": ["10.126.0.3/24"], "tun1": ["10.127.0.3/24"]},
        overlays=[{"provider": "easytier"}],
        overlay_devices={"easytier": devices},
    )


def test_a_console_overlay_answers_on_the_device_found_in_place_of_easytier():
    ruleset = render_console(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        devices=["tun0"],
    )

    assert "ip saddr { 192.168.100.0/24, 10.126.0.0/24 } accept" in ruleset
    assert '"easytier"' not in ruleset
    assert "10.144" not in ruleset


def test_a_console_overlay_is_forwarded_to_and_from_on_the_device_found():
    ruleset = render_console(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        devices=["tun0"],
    )

    assert '        iifname { "tun0" } accept' in ruleset
    assert 'iifname { "enp1s0" } oifname { "tun0" } accept' in ruleset


@pytest.mark.feature("proxy")
def test_the_overlay_scope_diverts_the_console_device_found():
    ruleset = render_console(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        devices=["tun0", "tun1"],
        routing={"is_proxy_enabled": True, "is_overlay_proxy_enabled": True},
    )

    assert 'iifname != { "enp1s0", "tun0", "tun1" } return' in ruleset


def test_a_console_overlay_with_no_device_found_is_named_nowhere():
    """Its peers still knock on the peer port; nothing else names it."""
    ruleset = render_console(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        devices=[],
        routing={"is_overlay_proxy_enabled": True},
    )

    assert "easytier" not in ruleset
    assert "tun0" not in ruleset
    assert "ip saddr { 192.168.100.0/24 } accept" in ruleset
    assert "11010" not in ruleset


def test_a_manual_overlay_keeps_the_device_its_engine_names():
    ruleset = render(
        lan_entry("enp1s0", address="192.168.100.1"),
        overlays=[{"provider": "easytier"}],
        overlay_devices={},
    )

    assert 'iifname { "easytier" } accept' in ruleset
    assert "ip saddr { 192.168.100.0/24, 10.144.0.0/24 } accept" in ruleset


def render_both(*entries, routing=None, devices=None) -> str:
    """The ruleset for a box running NetBird and EasyTier at once."""
    return render(
        *entries,
        routing=routing,
        held={**HELD, "tun0": ["10.126.0.3/24"]},
        overlays=[
            {"provider": "netbird", "is_enabled": True},
            {"provider": "easytier", "is_enabled": True},
        ],
        overlay_devices=devices,
    )


def test_two_overlays_answer_and_are_forwarded_on_both_devices():
    ruleset = render_both(
        wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1")
    )

    assert (
        "ip saddr { 192.168.100.0/24, 100.92.0.0/16, 10.144.0.0/24 } accept" in ruleset
    )
    assert 'iifname { "wt0", "easytier" } accept' in ruleset
    assert 'iifname { "enp1s0" } oifname { "wt0", "easytier" } accept' in ruleset


@pytest.mark.feature("proxy")
def test_the_overlay_scope_diverts_both_overlays():
    ruleset = render_both(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing={"is_proxy_enabled": True, "is_overlay_proxy_enabled": True},
    )

    assert 'iifname != { "enp1s0", "wt0", "easytier" } return' in ruleset


def test_nothing_is_forwarded_from_one_overlay_to_the_other():
    """A peer of one overlay is not a peer of the other, and the box between
    them is not a bridge. The drops sit in a chain ahead of forward, since
    an overlay daemon puts its own accept at the top of forward."""
    ruleset = render_both(
        wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1")
    )

    fence = ruleset[ruleset.index("chain forward_overlays") :]
    fence = fence[: fence.index("\n    }")]
    assert "priority filter - 1; policy accept;" in fence
    assert 'iifname { "wt0" } oifname { "easytier" } drop' in fence
    assert 'iifname { "easytier" } oifname { "wt0" } drop' in fence


@pytest.mark.feature("proxy")
def test_the_fence_follows_a_console_device_found():
    ruleset = render_both(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        devices={"easytier": ["tun0"]},
    )

    assert 'iifname { "wt0" } oifname { "tun0" } drop' in ruleset
    assert '"easytier"' not in ruleset


def test_a_box_that_routes_nothing_still_fences_two_overlays():
    ruleset = render_both()

    assert 'iifname { "easytier" } oifname { "wt0" } drop' in ruleset


def test_one_overlay_needs_no_fence():
    assert "forward_overlays" not in render(
        wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1")
    )


def test_an_overlay_turned_off_is_absent_from_the_whole_ruleset():
    ruleset = render(
        lan_entry("enp1s0", address="192.168.100.1"),
        overlays=[
            {"provider": "netbird", "is_enabled": False},
            {"provider": "easytier", "is_enabled": True},
        ],
    )

    assert "wt0" not in ruleset
    assert "100.92" not in ruleset
    assert "51820" not in ruleset
    assert "forward_overlays" not in ruleset


@pytest.mark.needs_root
def test_two_overlays_render_a_ruleset_nft_accepts():
    validate_nft(
        render_both(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))
    )


@pytest.mark.feature("proxy")
def test_the_local_proxy_chain_cannot_loop_back_into_itself():
    """xray's own egress must never be diverted into xray."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing=ROUTING_LOCAL_PROXY,
    )

    assert "meta skuid 999 return" in ruleset
    assert "meta mark 0xff return" in ruleset


ENGINE_CGROUPS = [
    "system.slice/neutrino_hub_netbird.service",
    "system.slice/neutrino_hub_easytier.service",
]


def render_with_engines(routing: dict, cgroups=ENGINE_CGROUPS) -> str:
    return render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing=routing,
        engine_cgroups=cgroups,
    )


@pytest.mark.feature("proxy")
def test_the_hubs_own_engines_are_accepted_before_the_mark():
    """Through xray an engine's handshakes leave from the exit's address."""
    ruleset = render_with_engines(ROUTING_LOCAL_PROXY)
    chain = ruleset.split("chain output {")[1].split("\n    }")[0]
    rules = [line.strip() for line in chain.splitlines()]

    netbird = rules.index(
        'socket cgroupv2 level 2 "system.slice/neutrino_hub_netbird.service" accept'
    )
    easytier = rules.index(
        'socket cgroupv2 level 2 "system.slice/neutrino_hub_easytier.service" accept'
    )
    mark = rules.index("meta l4proto { tcp, udp } meta mark set 0x1")
    assert rules.index("meta skuid 999 return") < netbird < easytier < mark


LOCAL_PROXY_OUTPUT = [
    "type route hook output priority mangle; policy accept;",
    "meta skuid 999 return",
    "meta mark 0xff return",
    "ip daddr @reserved_v4 return",
    'socket cgroupv2 level 2 "system.slice/neutrino_hub_netbird.service" accept',
    'socket cgroupv2 level 2 "system.slice/neutrino_hub_easytier.service" accept',
    "meta mark != 0x0 return",
    "udp sport 51820 return",
    "meta l4proto { tcp, udp } meta mark set 0x1",
]


@pytest.mark.feature("proxy")
def test_what_an_overlay_s_wireguard_sends_is_never_marked():
    """A kernel WireGuard device sends from no socket, so no cgroup row
    names it: it is known by its mark, and by NetBird's port for a device
    that sets none. Diverted, its packets leave from the exit's address and
    the peer's NAT drops them."""
    ruleset = render_with_engines(ROUTING_LOCAL_PROXY)
    chain = without_comments(ruleset).split("chain output {")[1].split("\n    }")[0]

    assert [line.strip() for line in chain.splitlines() if line.strip()] == (
        LOCAL_PROXY_OUTPUT
    )


@pytest.mark.feature("proxy")
def test_the_wireguard_returns_stand_with_no_engine_running():
    """The kernel device outlives its daemon's cgroup row."""
    ruleset = render_with_engines(ROUTING_LOCAL_PROXY, cgroups=[])
    rules = [line.strip() for line in without_comments(ruleset).splitlines()]

    assert "cgroupv2" not in ruleset
    assert (
        rules.index("meta mark != 0x0 return")
        < rules.index("udp sport 51820 return")
        < rules.index("meta l4proto { tcp, udp } meta mark set 0x1")
    )


@pytest.mark.needs_root
@pytest.mark.feature("proxy")
def test_nft_accepts_the_wireguard_returns():
    validate_nft(render_with_engines(ROUTING_LOCAL_PROXY, cgroups=[]))


@pytest.mark.feature("proxy")
def test_an_engine_not_running_is_not_named():
    ruleset = render_with_engines(ROUTING_LOCAL_PROXY, cgroups=ENGINE_CGROUPS[:1])

    assert "neutrino_hub_netbird.service" in ruleset
    assert "neutrino_hub_easytier.service" not in ruleset


def test_no_engine_is_named_while_the_local_proxy_is_off():
    assert "cgroupv2" not in render_with_engines(ROUTING_DIRECT)


@pytest.mark.needs_root
def test_nft_accepts_an_engine_accept_for_a_cgroup_that_exists():
    if not Path("/sys/fs/cgroup/init.scope").is_dir():
        pytest.skip("no systemd cgroup tree here")
    validate_nft(render_with_engines(ROUTING_LOCAL_PROXY, cgroups=["init.scope"]))


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

    assert "ip saddr { 192.168.100.0/24, 100.92.0.0/16 } accept" in ruleset
    assert 'iifname { "enp1s0" } oifname { "wt0" } accept' in ruleset
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


@pytest.mark.feature("proxy")
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


HUB_DIVERSION = (
    'iifname "lo" ip daddr != @reserved_v4 fib daddr type != local '
    "meta l4proto { tcp, udp } tproxy ip to 127.0.0.1:12345 meta mark set 0x1 "
    "accept"
)


@pytest.mark.feature("proxy")
def test_the_hub_s_own_diversion_needs_no_mark_another_table_can_replace():
    """A routing peer's daemon replaces the output chain's mark at mangle on
    every new connection from a network it routes, so the loopback rule takes
    the packet by where it is going and sets the mark after the tproxy."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing=ROUTING_LOCAL_PROXY,
    )
    lines = [line.strip() for line in without_comments(ruleset).splitlines()]

    assert HUB_DIVERSION in lines
    assert not any(line.startswith('iifname "lo" meta mark') for line in lines)
    assert lines.index(HUB_DIVERSION) > lines.index(
        "meta l4proto { tcp, udp } socket transparent 1 meta mark set 0x1 accept"
    )


@pytest.mark.needs_root
@pytest.mark.feature("proxy")
def test_the_hub_s_own_diversion_is_accepted_by_nft():
    validate_nft(
        render(
            wan_entry("enp2s0"),
            lan_entry("enp1s0", address="192.168.100.1"),
            routing=ROUTING_LOCAL_PROXY,
        )
    )


@pytest.mark.feature("proxy")
def test_fenced_lans_cannot_reach_each_other():
    """With the inter-LAN switch off, the drop policy holds between networks."""
    entries = (
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("enp1s0.10", address="192.168.110.1"),
    )
    fenced = render(*entries, is_inter_lan_allowed=False)

    lan_set = 'iifname { "enp1s0", "enp1s0.10" }'
    assert f'{lan_set} oifname {{ "enp1s0", "enp1s0.10" }} accept' not in fenced
    # Every network still reaches the internet and the overlay.
    assert f'{lan_set} oifname {{ "enp2s0" }} accept' in fenced
    assert f'{lan_set} oifname {{ "wt0" }} accept' in fenced


@pytest.mark.feature("proxy")
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


def test_a_closed_lan_keeps_dhcp_and_forwarding_and_loses_the_hubs_dns():
    """DHCP passes the chain's accept policy; DNS is a hub port, dropped
    from the senders of a closed segment like the panel and the agent port."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1", is_exposed=False),
        overlays=[],
    )
    chain = input_chain(ruleset)

    assert not any("192.168.100" in line for line in chain)
    assert "ct state new udp dport { 53 } drop" in chain
    assert " 67" not in without_comments(ruleset)
    assert 'iifname { "enp1s0" } oifname { "enp2s0" } accept' in ruleset


def test_a_served_network_is_in_its_segment_before_its_device_holds_the_address():
    """The router's first pass of a boot runs before the address is on the
    port; the configured network is the segment's already."""
    chain = input_chain(
        render(lan_entry("enp1s0", address="192.168.100.1"), held={}, overlays=[])
    )

    assert "ip saddr { 192.168.100.0/24 } accept" in chain


@pytest.mark.feature("proxy")
def test_what_tproxy_diverted_is_accepted_from_a_closed_lan():
    """The diverted packet is delivered to the input chain with the mark on
    it; a served network nobody exposed has no other rule that takes it."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("wlp3s0", address="192.168.111.1", is_exposed=False),
        routing={"is_proxy_enabled": True},
    )

    prerouting, input_chain = ruleset.split("chain input")
    assert "tproxy ip to" in prerouting
    assert f"meta mark {hex(ROUTER_FWMARK_TPROXY)} accept" in input_chain


def test_the_mark_is_not_accepted_while_nothing_diverts():
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("wlp3s0", address="192.168.111.1", is_exposed=False),
        routing={"is_proxy_enabled": False},
    )

    assert f"meta mark {hex(ROUTER_FWMARK_TPROXY)} accept" not in ruleset


@pytest.mark.feature("proxy")
def test_the_overlay_scope_diverts_the_exposed_overlay_beside_the_lan():
    """An overlay whose members use this box as their exit node is taken the
    way the served networks are, under a switch of its own."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing={"is_proxy_enabled": True, "is_overlay_proxy_enabled": True},
    )

    assert 'iifname != { "enp1s0", "wt0" } return' in ruleset


SERVER_OVERLAY_PREROUTING = """    chain prerouting {
        type filter hook prerouting priority mangle + 1; policy accept;
        meta l4proto { tcp, udp } socket transparent 1 meta mark set 0x1 accept
        iifname != { "wt0" } return
        ip daddr @reserved_v4 return
        meta l4proto { tcp, udp } tproxy ip to 127.0.0.1:12345 meta mark set 0x1 accept
    }"""


@pytest.mark.feature("proxy")
@pytest.mark.parametrize("is_proxy_enabled", [True, False], ids=["lan on", "lan off"])
def test_a_server_diverts_its_exposed_overlay_and_nothing_else(is_proxy_enabled):
    """Server mode serves no network, so the served networks' switch reads
    as nothing there; the overlay scope diverts the overlay's members whose
    exit this box is, as in every mode."""
    ruleset = render(
        mode="server",
        routing={
            "is_proxy_enabled": is_proxy_enabled,
            "is_overlay_proxy_enabled": True,
            "is_local_proxy_enabled": False,
        },
    )

    start = ruleset.index("    chain prerouting {")
    end = ruleset.index("    }", start) + len("    }")
    chain = without_comments(ruleset[start:end])
    assert "\n".join(line for line in chain.splitlines() if line.strip()) == (
        SERVER_OVERLAY_PREROUTING
    )
    assert "meta mark 0x1 accept" in ruleset


@pytest.mark.feature("proxy")
def test_the_overlay_scope_alone_diverts_only_the_overlay():
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        routing={"is_proxy_enabled": False, "is_overlay_proxy_enabled": True},
    )

    assert 'iifname != { "wt0" } return' in ruleset
    assert f"meta mark {hex(ROUTER_FWMARK_TPROXY)} accept" in ruleset


def forward_chain(ruleset: str) -> list:
    """The forward chain's lines, comments left out."""
    chain = without_comments(ruleset).split("chain forward {", 1)[1]
    chain = chain.split("\n    }", 1)[0]
    return [line.strip() for line in chain.splitlines() if line.strip()]


PODMAN_FORWARD = [
    'iifname "podman*" accept',
    'oifname "podman*" accept',
    'iifname "cni-podman*" accept',
    'oifname "cni-podman*" accept',
]


@pytest.mark.parametrize(
    "entries",
    [entries for entries in TOPOLOGIES.values() if entries],
    ids=[name for name, entries in TOPOLOGIES.items() if entries],
)
def test_a_box_that_routes_forwards_every_podman_bridge_both_ways(entries):
    """netavark names a module's network podman1 and on, CNI cni-podman1 and
    on; a drop policy would cut each container off beyond the box."""
    chain = forward_chain(render(*entries))

    assert "policy drop;" in chain[0]
    assert chain[-4:] == PODMAN_FORWARD


@pytest.mark.parametrize("mode", ["router", "side_gateway", "server"])
def test_dns_from_a_podman_bridge_is_accepted_ahead_of_the_hub_ports_drops(mode):
    """A container's resolver is its bridge's gateway, and port 53 is a hub
    port where the hub answers names."""
    chain = input_chain(
        render(lan_entry("enp1s0", address="192.168.100.1"), mode=mode, overlays=[])
    )
    first_drop = min(
        index for index, line in enumerate(chain) if line.endswith(" drop")
    )

    assert [line for line in chain if line in PODMAN_DNS] == PODMAN_DNS
    assert all(chain.index(line) < first_drop for line in PODMAN_DNS)


def test_a_podman_bridge_is_accepted_for_dns_alone():
    chain = input_chain(
        render(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))
    )

    assert [line for line in chain if "podman" in line] == PODMAN_DNS


@pytest.mark.parametrize("entries", TOPOLOGIES.values(), ids=list(TOPOLOGIES))
def test_loopback_reaches_every_port_in_every_topology(entries):
    """The hub's own agent dials the agent port on loopback, exposed or not."""
    chain = input_chain(render(*entries))

    assert chain[1] == 'iifname "lo" accept'


# --- Direct ---


def test_direct_off_opens_nothing_to_every_sender():
    chain = input_chain(
        render(wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"))
    )

    assert not any(
        "accept" in line and "tcp dport" in line
        for line in chain
        if line not in PODMAN_DNS
    )


def test_direct_opens_the_agent_port_alone_to_every_sender_on_the_enabled_interfaces():
    """The panel and the hub's other ports keep the exposure the Network page
    gives them; a port a router leaves disabled is not enabled."""
    chain = input_chain(
        render(
            wan_entry("enp2s0"),
            lan_entry("enp1s0", address="192.168.100.1"),
            {"name": "enp4s0", "role": "disabled"},
            held={**HELD, "enp4s0": ["198.51.100.4/24"]},
            is_direct=True,
        )
    )

    assert 'iifname { "enp2s0", "enp1s0" } tcp dport 8443 accept' in chain
    assert not any("enp4s0" in line or "198.51.100" in line for line in chain)
    assert chain.index('iifname { "enp2s0", "enp1s0" } tcp dport 8443 accept') < (
        chain.index("ct state new tcp dport { 8080, 8444, 8443, 53 } drop")
    )


def test_in_server_mode_every_listed_interface_is_enabled():
    chain = input_chain(
        render(
            {"name": "eno1", "role": "disabled", "is_exposed": True},
            {"name": "eno2", "role": "disabled", "is_exposed": False},
            held={"eno1": ["192.168.1.5/24"], "eno2": ["10.1.0.5/16"]},
            is_direct=True,
            mode="server",
            overlays=[],
        )
    )

    assert 'iifname { "eno1", "eno2" } tcp dport 8443 accept' in chain
    assert "ip saddr { 192.168.1.0/24 } accept" in chain
    assert not any("10.1.0.0" in line for line in chain)


def test_directs_rule_names_no_family_and_each_segment_rule_one():
    """The table is ``inet``: an IPv4 segment's rule matches IPv4 senders,
    an IPv6 segment's IPv6 senders, and Direct's rule both."""
    ruleset = render(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        is_direct=True,
    )
    chain = input_chain(ruleset)

    assert "table inet neutrino {" in ruleset
    (direct,) = [line for line in chain if line.endswith("tcp dport 8443 accept")]
    assert "ip " not in direct and "ip6 " not in direct
    assert any(line.startswith("ip saddr") for line in chain)
    assert any(line.startswith("ip6 saddr") for line in chain)


# --- What a packet meets, in a network namespace of the test's own ---

NAMESPACE_SCRIPT = r"""
set -e
ip link set lo up
unshare -n sleep 30 &
peer=$!
sleep 0.3
ip link add hub0 type veth peer name peer0 netns $peer
ip addr add 10.9.0.1/24 dev hub0
ip addr add fd00:9::1/64 dev hub0 nodad
ip link set hub0 up
nsenter -t $peer -n sh -c 'ip link set lo up; ip link set peer0 up
  ip addr add 10.9.0.2/24 dev peer0; ip addr add 10.8.0.2/24 dev peer0
  ip addr add fd00:9::2/64 dev peer0 nodad; ip route add default dev peer0'
ip route add 10.8.0.0/24 dev hub0
nft -f "$2"
"$3" "$4" serve &
sleep 0.5
for source in 10.9.0.2 10.8.0.2 fd00:9::2; do
  for port in 8080 2222; do
    nsenter -t $peer -n "$3" "$4" probe $source $port
  done
done
kill $peer
"""

NAMESPACE_PEER = r"""
import socket, sys, threading, time

if sys.argv[1] == "serve":
    def serve(family, host, port):
        server = socket.socket(family)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        server.bind((host, port))
        server.listen(8)
        while True:
            server.accept()[0].close()
    for port in (8080, 2222):
        threading.Thread(target=serve, args=(socket.AF_INET, "0.0.0.0", port), daemon=True).start()
        threading.Thread(target=serve, args=(socket.AF_INET6, "::", port), daemon=True).start()
    time.sleep(10)
else:
    source, port = sys.argv[2], int(sys.argv[3])
    family = socket.AF_INET6 if ":" in source else socket.AF_INET
    target = "fd00:9::1" if family == socket.AF_INET6 else "10.9.0.1"
    client = socket.socket(family)
    client.settimeout(0.6)
    client.bind((source, 0))
    try:
        client.connect((target, port))
        print(source, port, "open")
    except OSError:
        print(source, port, "dropped")
"""


def _has_namespaces() -> bool:
    if shutil.which("unshare") is None or shutil.which("nft") is None:
        return False
    probe = subprocess.run(
        ["unshare", "-rn", "nft", "list", "ruleset"], capture_output=True, text=True
    )
    return probe.returncode == 0


@pytest.mark.skipif(not _has_namespaces(), reason="no user network namespace here")
def test_a_closed_segment_drops_the_hub_ports_and_leaves_other_ports_alone(tmp_path):
    """The rendered table loaded in a namespace of the test's own: the hub's
    IPv4 segment is exposed and its IPv6 segment closed. A hub port answers
    the sender inside the exposed segment alone; port 2222, which is no hub
    port, answers every sender."""
    ruleset = render(
        {"name": "hub0", "role": "disabled", "is_ipv4_exposed": True},
        held={"hub0": ["10.9.0.1/24", "fd00:9::1/64"]},
        mode="server",
        overlays=[],
    )
    (tmp_path / "table.nft").write_text(ruleset)
    (tmp_path / "run.sh").write_text(NAMESPACE_SCRIPT)
    (tmp_path / "peer.py").write_text(NAMESPACE_PEER)

    result = subprocess.run(
        [
            "unshare",
            "-rn",
            "bash",
            str(tmp_path / "run.sh"),
            "--",
            str(tmp_path / "table.nft"),
            sys.executable,
            str(tmp_path / "peer.py"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.stdout.splitlines() == [
        "10.9.0.2 8080 open",
        "10.9.0.2 2222 open",
        "10.8.0.2 8080 dropped",
        "10.8.0.2 2222 open",
        "fd00:9::2 8080 dropped",
        "fd00:9::2 2222 open",
    ], result.stderr
