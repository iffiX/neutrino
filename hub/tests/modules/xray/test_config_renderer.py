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
        "is_socks_direct_enabled": True,
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
        lan_address="192.168.100.1",
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
        lan_address="192.168.100.1",
    ).render()

    assert "observatory" not in config
    assert tags(config, "outbounds") == ["direct", "block"]


def test_the_proxy_on_with_no_enabled_node_is_refused():
    """The balancer would have nothing to select and every request would fail."""
    with pytest.raises(ValueError, match="at least one"):
        XrayConfigRenderer(
            node_list=XrayNodeList.from_dict(
                {"nodes": [], "balancer": NODES["balancer"]}
            ),
            routing={"is_proxy_enabled": True},
            lan_address="192.168.100.1",
        )


# --- The direct SOCKS listener ----------------------------------------------


def test_the_socks_listener_is_published_when_switched_on():
    config = render(is_socks_direct_enabled=True)

    assert "socks_direct_in" in tags(config, "inbounds")
    socks = next(
        entry for entry in config["inbounds"] if entry["tag"] == "socks_direct_in"
    )
    assert socks["listen"] == "192.168.100.1"
    assert socks["port"] == 1080


def test_the_socks_listener_leaves_no_trace_when_switched_off():
    """A second way out of the box should be as revocable as the proxy itself."""
    config = render(is_socks_direct_enabled=False)

    assert "socks_direct_in" not in tags(config, "inbounds")
    named = [
        rule
        for rule in config["routing"]["rules"]
        if "socks_direct_in" in rule.get("inboundTag", [])
    ]
    assert named == []


def test_socks_traffic_always_leaves_directly():
    """The whole point of it: never through an exit node, whatever else is set."""
    config = render()

    rule = next(
        rule
        for rule in config["routing"]["rules"]
        if "socks_direct_in" in rule.get("inboundTag", [])
    )
    assert rule["outboundTag"] == "direct"


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
        "is_socks_proxy_enabled": True,
        "socks_proxy_port": 1081,
    }

    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict(NODES), routing=routing, lan_address="10.0.0.1"
    ).render()

    socks = [i for i in config["inbounds"] if i["tag"] == "socks_proxy_in"]
    balanced = [r for r in config["routing"]["rules"] if r.get("balancerTag")]
    assert socks and socks[0]["port"] == 1081
    assert "socks_proxy_in" in balanced[0]["inboundTag"]


def test_that_port_is_not_published_with_the_proxy_off():
    """It would answer, and send everything out directly under a name that
    says the opposite."""
    routing = {"is_proxy_enabled": False, "is_socks_proxy_enabled": True}

    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict(NODES), routing=routing, lan_address="10.0.0.1"
    ).render()

    assert not [i for i in config["inbounds"] if i["tag"] == "socks_proxy_in"]


def test_the_direct_port_stays_out_of_the_proxied_rule():
    """It exists precisely to bypass the proxy."""
    routing = {"is_proxy_enabled": True, "is_socks_direct_enabled": True}

    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict(NODES), routing=routing, lan_address="10.0.0.1"
    ).render()

    balanced = [r for r in config["routing"]["rules"] if r.get("balancerTag")]
    assert "socks_direct_in" not in balanced[0]["inboundTag"]


def test_the_direct_port_is_the_one_configured():
    routing = {
        "is_proxy_enabled": True,
        "is_socks_direct_enabled": True,
        "socks_direct_port": 1088,
    }

    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict(NODES), routing=routing, lan_address="10.0.0.1"
    ).render()

    socks = [i for i in config["inbounds"] if i["tag"] == "socks_direct_in"]
    assert socks[0]["port"] == 1088
