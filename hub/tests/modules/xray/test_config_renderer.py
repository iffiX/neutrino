"""Rendering the xray configuration, and what the master switch does to it.

Turning the proxy off has to take it out of the path everywhere at once — the
firewall, the resolver, and this config. A state where one of the three still
thinks the proxy is in use is worse than either extreme, because traffic goes
somewhere nobody asked for.
"""

import pytest

from neutrino_hub.modules.xray.config_renderer import XrayConfigRenderer
from neutrino_hub.modules.xray.node_config import XrayNodeList

NODES = {
    "nodes": [
        {
            "id": "hk1",
            "name": "Tokyo",
            "address": "203.0.113.10",
            "is_enabled": True,
            "protocol": "shadowsocks",
            "shadowsocks": {
                "port": 5800,
                "method": "aes-256-gcm",
                "password": "secret",
            },
        }
    ],
    "balancer": {
        "strategy": "leastPing",
        "probe_url": "https://www.gstatic.com/generate_204",
        "probe_interval_s": 60,
    },
}


def render(**routing) -> dict:
    settings = {
        "is_proxy_enabled": True,
        "socks_ports": [{"port": 1080, "is_proxied": False}],
        "is_geoip_split_enabled": True,
        "direct_domains": ["geosite:cn"],
        "direct_ips": ["geoip:cn"],
        "remote_dns": {"address": "1.1.1.1", "port": 53},
        "direct_dns": {"address": "223.5.5.5", "port": 53},
        **routing,
    }
    return XrayConfigRenderer(
        node_list=XrayNodeList.from_dict(NODES),
        routing=settings,
    ).render()


def tags(config: dict, section: str) -> list[str]:
    return [entry["tag"] for entry in config[section]]


# --- The master switch ------------------------------------------------------


def test_the_proxy_on_balances_across_the_nodes():
    config = render()

    assert "balancers" in config["routing"]
    assert "node_hk1" in tags(config, "outbounds")
    assert "observatory" in config


def test_the_proxy_off_sends_everything_straight_out():
    config = render(is_proxy_enabled=False)

    assert "balancers" not in config["routing"]
    assert "node_hk1" not in tags(config, "outbounds")
    # The DNS inbound is still wired up and still has to answer from somewhere.
    catch_all = config["routing"]["rules"][-1]
    assert catch_all["inboundTag"] == ["tproxy_in", "dns_in"]
    assert catch_all["outboundTag"] == "direct"


def test_the_proxy_off_needs_no_nodes_at_all():
    """The switch has to work on a box that has never been given an exit.

    Refusing to render without a node would make the off state unreachable on a
    fresh install, which is exactly when someone wants the gateway to behave as
    a plain router.
    """
    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict({"nodes": [], "balancer": NODES["balancer"]}),
        routing={"is_proxy_enabled": False},
    ).render()

    assert "observatory" not in config
    assert tags(config, "outbounds") == ["direct", "block"]


def test_the_proxy_on_with_no_enabled_node_renders_as_off():
    """It used to raise, and every Apply on a box in that state failed with
    it — including the one that would have turned the switch off. The panel
    writes the switch off when the list empties; this is what keeps a
    hand-edited file renderable."""
    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict({"nodes": [], "balancer": NODES["balancer"]}),
        routing={"is_proxy_enabled": True},
    ).render()

    assert "balancers" not in config["routing"]
    assert tags(config, "outbounds") == ["direct", "block"]


# --- The direct SOCKS listener ----------------------------------------------


def test_a_listener_is_published_on_the_port_it_names():
    config = render(socks_ports=[{"port": 1088, "is_proxied": False}])

    assert "socks_1088_in" in tags(config, "inbounds")
    socks = next(
        entry for entry in config["inbounds"] if entry["tag"] == "socks_1088_in"
    )
    assert socks["port"] == 1088


def test_a_listener_binds_every_address():
    """As every service on this box does. Which interfaces it answers on is a
    firewall answer per interface, and a listener pinned to a LAN address is
    one that vanishes when that address changes under it."""
    config = render()

    socks = next(
        entry for entry in config["inbounds"] if entry["tag"] == "socks_1080_in"
    )
    assert socks["listen"] == "0.0.0.0"


def test_a_listener_nobody_asked_for_leaves_no_trace():
    """A second way out of the box should be as revocable as the proxy itself."""
    config = render(socks_ports=[])

    assert not [tag for tag in tags(config, "inbounds") if tag.startswith("socks_")]
    named = [
        rule
        for rule in config["routing"]["rules"]
        if any(tag.startswith("socks_") for tag in rule.get("inboundTag", []))
    ]
    assert named == []


def test_a_direct_listener_never_reaches_an_exit_node():
    """The whole point of it: never through an exit node, whatever else is set."""
    config = render()

    rule = next(
        rule
        for rule in config["routing"]["rules"]
        if "socks_1080_in" in rule.get("inboundTag", [])
    )
    assert rule["outboundTag"] == "direct"


def test_both_kinds_of_listener_stand_side_by_side():
    """One port an application uses to look local, one it uses to look
    elsewhere, on the same box at once."""
    config = render(
        socks_ports=[
            {"port": 1080, "is_proxied": False},
            {"port": 1081, "is_proxied": True},
        ]
    )

    direct = next(
        rule
        for rule in config["routing"]["rules"]
        if "socks_1080_in" in rule.get("inboundTag", [])
    )
    balanced = next(
        rule for rule in config["routing"]["rules"] if rule.get("balancerTag")
    )
    assert direct["outboundTag"] == "direct"
    assert "socks_1081_in" in balanced["inboundTag"]


# --- The split, which is separate from the master switch --------------------


def test_the_geoip_split_adds_direct_rules_ahead_of_the_balancer():
    config = render(is_geoip_split_enabled=True)

    rules = config["routing"]["rules"]
    direct_domains = next(rule for rule in rules if "domain" in rule)
    assert direct_domains["outboundTag"] == "direct"
    assert rules.index(direct_domains) < len(rules) - 1


def test_without_the_split_everything_reaches_the_balancer():
    config = render(is_geoip_split_enabled=False)

    assert not any("domain" in rule for rule in config["routing"]["rules"])
    assert "balancers" in config["routing"]


def test_a_socks_port_can_be_the_whole_proxy():
    """A box that diverts nothing has no transparent path to be on, so the
    port applications are pointed at is the only way through."""
    routing = {
        "is_proxy_enabled": True,
        "socks_ports": [{"port": 1081, "is_proxied": True}],
    }

    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict(NODES), routing=routing
    ).render()

    socks = [i for i in config["inbounds"] if i["tag"] == "socks_1081_in"]
    balanced = [r for r in config["routing"]["rules"] if r.get("balancerTag")]
    assert socks and socks[0]["port"] == 1081
    assert "socks_1081_in" in balanced[0]["inboundTag"]


def test_a_proxied_port_is_not_published_with_the_proxy_off():
    """It would answer, and send everything out directly under a name that
    says the opposite."""
    routing = {
        "is_proxy_enabled": False,
        "socks_ports": [{"port": 1081, "is_proxied": True}],
    }

    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict(NODES), routing=routing
    ).render()

    assert not [i for i in config["inbounds"] if i["tag"] == "socks_1081_in"]


def test_a_direct_port_is_published_with_the_proxy_off():
    """It never went through the proxy, so the master switch is nothing to it."""
    routing = {
        "is_proxy_enabled": False,
        "socks_ports": [{"port": 1080, "is_proxied": False}],
    }

    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict(NODES), routing=routing
    ).render()

    assert [i for i in config["inbounds"] if i["tag"] == "socks_1080_in"]
