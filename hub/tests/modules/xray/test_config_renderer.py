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
            "secret_id": "0" * 32,
            "shadowsocks": {
                "port": 5800,
                "method": "aes-256-gcm",
            },
        }
    ],
    "balancer": {
        "strategy": "leastPing",
        "probe_url": "https://www.gstatic.com/generate_204",
        "probe_interval_s": 60,
    },
}


def resolved_nodes() -> XrayNodeList:
    """The node list with its reference opened, as a live render sees it."""
    node_list = XrayNodeList.from_dict(NODES)
    for node in node_list.nodes:
        node.password = "secret"
    return node_list


def render(*, is_resolved: bool = True, **routing) -> dict:
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
    node_list = XrayNodeList.from_dict(NODES)
    if is_resolved:
        # What resolve_node_secrets does on a live box: the reference opened
        # into memory.
        for node in node_list.nodes:
            node.password = "secret"
    return XrayConfigRenderer(
        node_list=node_list,
        routing=settings,
    ).render()


def tags(config: dict, section: str) -> list[str]:
    return [entry["tag"] for entry in config[section]]


# --- The LAN switch ---------------------------------------------------------


def test_the_proxy_on_balances_across_the_nodes():
    config = render()

    assert "balancers" in config["routing"]
    assert "node_hk1" in tags(config, "outbounds")
    assert "burstObservatory" in config


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

    assert "burstObservatory" not in config
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

    config = XrayConfigRenderer(node_list=resolved_nodes(), routing=routing).render()

    socks = [i for i in config["inbounds"] if i["tag"] == "socks_1081_in"]
    balanced = [r for r in config["routing"]["rules"] if r.get("balancerTag")]
    assert socks and socks[0]["port"] == 1081
    assert "socks_1081_in" in balanced[0]["inboundTag"]


def test_a_proxied_port_outlives_the_lan_switch():
    """The scopes stand alone: a server keeps its proxied port with the LAN
    switch off, because it has no LAN for that switch to mean anything on."""
    routing = {
        "is_proxy_enabled": False,
        "socks_ports": [{"port": 1081, "is_proxied": True}],
    }

    config = XrayConfigRenderer(node_list=resolved_nodes(), routing=routing).render()

    balanced = next(r for r in config["routing"]["rules"] if r.get("balancerTag"))
    assert [i for i in config["inbounds"] if i["tag"] == "socks_1081_in"]
    assert balanced["inboundTag"] == ["socks_1081_in", "dns_internal"]


def test_a_proxied_port_is_not_published_without_an_exit():
    """It would answer, and send everything out directly under a name that
    says the opposite."""
    routing = {
        "is_proxy_enabled": False,
        "socks_ports": [{"port": 1081, "is_proxied": True}],
    }

    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict({"nodes": [], "balancer": NODES["balancer"]}),
        routing=routing,
    ).render()

    assert not [i for i in config["inbounds"] if i["tag"] == "socks_1081_in"]


def test_the_hub_scope_stands_alone():
    """The box's own traffic reaches the balancer with the LAN switch off,
    while the DNS inbound — LAN queries — still answers directly."""
    routing = {
        "is_proxy_enabled": False,
        "is_local_proxy_enabled": True,
        "socks_ports": [],
    }

    config = XrayConfigRenderer(node_list=resolved_nodes(), routing=routing).render()

    balanced = next(r for r in config["routing"]["rules"] if r.get("balancerTag"))
    dns = next(
        r
        for r in config["routing"]["rules"]
        if r.get("inboundTag") == ["dns_in"] and r.get("outboundTag") == "direct"
    )
    assert balanced["inboundTag"] == ["tproxy_in", "dns_internal"]
    assert dns is not None
    assert "node_hk1" in tags(config, "outbounds")


def test_a_direct_port_is_published_with_the_proxy_off():
    """It never went through the proxy, so the master switch is nothing to it."""
    routing = {
        "is_proxy_enabled": False,
        "socks_ports": [{"port": 1080, "is_proxied": False}],
    }

    config = XrayConfigRenderer(node_list=resolved_nodes(), routing=routing).render()

    assert [i for i in config["inbounds"] if i["tag"] == "socks_1080_in"]


def test_every_scope_off_is_the_way_out_of_a_bad_direct_entry():
    """The direct lists reach the xray config, and a bad entry there makes it
    unrenderable — which used to take the whole apply with it, firewall and
    resolver included. Switching every scope off is documented as the blunt
    instrument for exactly that, so with nothing sent to the balancer the
    lists are not read at all.
    """
    config = render(
        is_proxy_enabled=False,
        is_geoip_split_enabled=True,
        direct_domains=["geosite:doesnotexist"],
        direct_ips=["geoip:nope"],
    )

    body = str(config)
    assert "doesnotexist" not in body
    assert "geoip:nope" not in body


def test_the_direct_resolver_is_not_named_while_the_proxy_is_off():
    """It is the resolver for the names the split sends directly, and with the
    proxy off every name goes directly — so the split's own entry is one more
    place a bad value would be read from."""
    config = render(is_proxy_enabled=False, is_geoip_split_enabled=True)

    assert config["dns"]["servers"] == ["1.1.1.1"]


# --- what happens when no exit answers ----------------------------------------


def test_without_the_fallback_a_dead_exit_takes_the_traffic_with_it():
    """The default: what was sent to the proxy fails rather than leaving in
    the clear under the real address."""
    config = render()

    assert "fallbackTag" not in config["routing"]["balancers"][0]


def test_the_fallback_names_the_direct_outbound():
    config = render(is_direct_fallback_enabled=True)

    assert config["routing"]["balancers"][0]["fallbackTag"] == "direct"


@pytest.mark.parametrize("strategy", ["leastPing", "roundRobin", "random"])
def test_the_fallback_brings_the_observatory_with_it(strategy):
    """xray refuses the whole configuration with "not all dependencies are
    resolved" when a balancer names a fallbackTag and no observatory is
    configured: falling back means knowing every node is dead, and the
    observatory is what knows it. Only leastPing needs one for its own sake,
    so turning the fallback on under either other strategy used to render a
    config xray would not load — measured on Debian 12, xray 26.3.27."""
    node_list = resolved_nodes()
    node_list.strategy = strategy
    config = XrayConfigRenderer(
        node_list=node_list,
        routing={"is_proxy_enabled": True, "is_direct_fallback_enabled": True},
    ).render()

    assert config["routing"]["balancers"][0]["fallbackTag"] == "direct"
    assert "burstObservatory" in config


@pytest.mark.parametrize("strategy", ["roundRobin", "random"])
def test_without_the_fallback_those_strategies_need_no_observatory(strategy):
    """They pick without measuring, and probing every node for nothing is a
    request a minute to somebody's exit."""
    nodes = dict(NODES, balancer=dict(NODES["balancer"], strategy=strategy))
    config = XrayConfigRenderer(
        node_list=XrayNodeList.from_dict(nodes),
        routing={"is_proxy_enabled": True},
    ).render()

    assert "burstObservatory" not in config


def test_a_dangling_reference_excludes_the_node():
    """A reference nothing resolves renders the node out, never a crash."""
    config = render(is_resolved=False)

    assert "node_hk1" not in tags(config, "outbounds")
    assert "balancers" not in config["routing"]
    assert "burstObservatory" not in config


# --- how an exit's own name is resolved ---------------------------------------


def render_with_exit(address: str, **routing) -> dict:
    """A render whose one node is at the given address."""
    nodes = {**NODES, "nodes": [{**NODES["nodes"][0], "address": address}]}
    node_list = XrayNodeList.from_dict(nodes)
    for node in node_list.nodes:
        node.password = "secret"
    settings = {
        "is_proxy_enabled": True,
        "socks_ports": [],
        "is_geoip_split_enabled": False,
        "remote_dns": {"address": "1.1.1.1", "port": 53},
        "direct_dns": {"address": "223.5.5.5", "port": 53},
        **routing,
    }
    return XrayConfigRenderer(node_list=node_list, routing=settings).render()


def test_an_exit_named_by_hostname_is_resolved_at_the_direct_resolver():
    """The system resolver is the LAN's dnsmasq, whose upstream is this same
    xray, so a node resolved there is a node reached through itself."""
    config = render_with_exit("exit.example.net")

    node = next(entry for entry in config["outbounds"] if entry["tag"] == "node_hk1")
    assert node["streamSettings"]["sockopt"]["domainStrategy"] == "UseIP"
    assert config["dns"]["queryStrategy"] == "UseIPv4"
    assert config["dns"]["servers"][0] == {
        "address": "223.5.5.5",
        "port": 53,
        "domains": ["full:exit.example.net", "full:www.gstatic.com"],
        "skipFallback": True,
    }


def test_the_resolvers_own_queries_reach_the_direct_resolver_directly():
    """Whatever the split says about that address: the lookup of an exit's
    name cannot wait on the exit."""
    config = render_with_exit("exit.example.net", is_geoip_split_enabled=False)

    rules = config["routing"]["rules"]
    assert config["dns"]["tag"] == "dns_internal"
    assert {
        "type": "field",
        "inboundTag": ["dns_internal"],
        "ip": ["223.5.5.5"],
        "outboundTag": "direct",
    } in rules
    balancer_rule = next(rule for rule in rules if "balancerTag" in rule)
    assert rules.index(balancer_rule) == len(rules) - 1


def test_an_exit_at_a_literal_address_leaves_only_the_probe_host():
    config = render_with_exit("203.0.113.10")

    assert config["dns"]["servers"][0]["domains"] == ["full:www.gstatic.com"]


def test_the_resolvers_other_queries_follow_the_balancer():
    """A query nothing routes goes to the first outbound, alive or not,
    and the observatory ranks exits by what it resolved through it."""
    config = render_with_exit("exit.example.net")

    balanced = next(r for r in config["routing"]["rules"] if r.get("balancerTag"))
    assert balanced["inboundTag"][-1] == "dns_internal"


def test_the_overlay_scope_sends_the_transparent_inbound_to_the_balancer():
    """An overlay whose members use this box as their exit node arrives on
    the same transparent inbound the LAN does; dnsmasq is not its resolver,
    so the DNS inbound answers directly while the LAN scope is off."""
    config = render_with_exit(
        "exit.example.net", is_proxy_enabled=False, is_overlay_proxy_enabled=True
    )

    balanced = next(r for r in config["routing"]["rules"] if r.get("balancerTag"))
    assert balanced["inboundTag"][0] == "tproxy_in"
    assert "dns_in" not in balanced["inboundTag"]
    assert "node_hk1" in tags(config, "outbounds")


def test_with_every_scope_off_the_exits_names_are_nobodys_to_resolve():
    config = render_with_exit("exit.example.net", is_proxy_enabled=False)

    assert config["dns"]["servers"] == ["1.1.1.1"]
    assert not any(
        rule.get("inboundTag") == ["dns_internal"]
        for rule in config["routing"]["rules"]
    )
