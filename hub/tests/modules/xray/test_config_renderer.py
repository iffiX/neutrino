"""Rendering the xray configuration, and what the master switch does to it.

Turning the proxy off has to take it out of the path everywhere at once — the
firewall, the resolver, and this config. A state where one of the three still
thinks the proxy is in use is worse than either extreme, because traffic goes
somewhere nobody asked for.
"""

import pytest

from neutrino_hub.modules.xray.config_renderer import XrayConfigRenderer
from neutrino_hub.modules.xray.node_config import XrayNodeList

PROBE_TAG = "socks_probe_in"

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
        "reference_url": "http://www.msftconnecttest.com/connecttest.txt",
        "probe_interval_s": 60,
    },
}

SWITCHED_OFF_NODE = {
    "id": "hk2",
    "name": "Osaka",
    "address": "203.0.113.11",
    "is_enabled": False,
    "protocol": "shadowsocks",
    "secret_id": "1" * 32,
    "shadowsocks": {
        "port": 5800,
        "method": "aes-256-gcm",
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


def render_with_a_switched_off_node(**routing) -> dict:
    """A render of two nodes, the second one switched off."""
    nodes = {**NODES, "nodes": [NODES["nodes"][0], SWITCHED_OFF_NODE]}
    node_list = XrayNodeList.from_dict(nodes)
    for node in node_list.nodes:
        node.password = "secret"
    settings = {"is_proxy_enabled": True, "socks_ports": [], **routing}
    return XrayConfigRenderer(node_list=node_list, routing=settings).render()


def tags(config: dict, section: str) -> list[str]:
    return [entry["tag"] for entry in config[section]]


def published_socks_tags(config: dict) -> list[str]:
    """The tags of the per-port listeners, which the probe listener is not."""
    return [
        tag
        for tag in tags(config, "inbounds")
        if tag.startswith("socks_") and tag != PROBE_TAG
    ]


def rule_named(config: dict, rule_tag: str) -> dict:
    return next(
        rule for rule in config["routing"]["rules"] if rule["ruleTag"] == rule_tag
    )


# --- The LAN switch ---------------------------------------------------------


def test_the_proxy_on_balances_across_the_nodes():
    config = render()

    assert "balancers" in config["routing"]
    assert "node_hk1" in tags(config, "outbounds")


def test_the_proxy_off_sends_everything_straight_out():
    """Nothing anybody sends reaches an exit: every rule that carries real
    traffic leaves directly, and none of them reaches the balancer. The nodes
    stay rendered and stay measurable on loopback, so the panel can still say
    which one is worth switching back on."""
    config = render(is_proxy_enabled=False)

    rules = config["routing"]["rules"]
    traffic_rules = [
        rule for rule in rules if not rule["ruleTag"].startswith("rule_probe_")
    ]

    assert not any("balancerTag" in rule for rule in rules)
    assert [rule["outboundTag"] for rule in traffic_rules] == [
        "api",
        "direct",
        "direct",
        "direct",
    ]
    # The DNS inbound is still wired up and still has to answer from somewhere.
    catch_all = rules[-1]
    assert catch_all["inboundTag"] == ["tproxy_in", "dns_in"]
    assert catch_all["outboundTag"] == "direct"
    # The exit is out of the path, not out of the file.
    assert "node_hk1" in tags(config, "outbounds")
    assert PROBE_TAG in tags(config, "inbounds")
    # And the balancer stands, so the hub can override it the moment a scope
    # is switched back on.
    assert config["routing"]["balancers"][0]["selector"] == ["node_hk1"]


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

    assert tags(config, "outbounds") == ["direct", "block"]
    assert PROBE_TAG not in tags(config, "inbounds")


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

    assert published_socks_tags(config) == []
    named = [
        rule
        for rule in config["routing"]["rules"]
        if any(
            tag.startswith("socks_") and tag != PROBE_TAG
            for tag in rule.get("inboundTag", [])
        )
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


def test_the_split_list_is_not_read_by_the_resolver_while_the_proxy_is_off():
    """The direct resolver answers the names the split sends directly, and
    with the proxy off every name goes directly — so the split's own entry is
    one more place a bad value would be read from."""
    config = render(is_proxy_enabled=False, is_geoip_split_enabled=True)

    assert not any(
        "geosite:cn" in server.get("domains", []) for server in config["dns"]["servers"]
    )


def test_the_remote_resolver_keeps_the_port_it_was_given():
    """The DNS inbound dials that port, and the panel takes both halves."""
    config = render(remote_dns={"address": "9.9.9.9", "port": 5353})

    assert {"address": "9.9.9.9", "port": 5353} in config["dns"]["servers"]
    inbound = next(entry for entry in config["inbounds"] if entry["tag"] == "dns_in")
    assert inbound["settings"]["port"] == 5353


# --- the nodes xray holds, and the one it sends traffic to --------------------


def test_a_switched_off_node_is_still_measured_but_never_selected():
    """Switched off means not eligible to be selected, and nothing else: the
    hub measures every node it has, so a node can be switched back on with a
    reading already beside it."""
    config = render_with_a_switched_off_node()

    listener = next(entry for entry in config["inbounds"] if entry["tag"] == PROBE_TAG)
    accounts = [account["user"] for account in listener["settings"]["accounts"]]

    assert "node_hk2" in tags(config, "outbounds")
    assert "node_hk2" in accounts
    assert config["routing"]["balancers"][0]["selector"] == ["node_hk1"]


def test_every_node_switched_off_is_still_rendered_and_still_measured():
    """The state the measurements matter most in: switching the last node off
    switches every scope off, and a box that measured nothing there could
    never say which node to switch back on. xray refuses an empty selector,
    so the balancer is the one thing that goes."""
    nodes = {**NODES, "nodes": [{**NODES["nodes"][0], "is_enabled": False}]}
    node_list = XrayNodeList.from_dict(nodes)
    for node in node_list.nodes:
        node.password = "secret"

    config = XrayConfigRenderer(
        node_list=node_list,
        routing={"is_proxy_enabled": True, "socks_ports": []},
    ).render()

    assert "node_hk1" in tags(config, "outbounds")
    assert PROBE_TAG in tags(config, "inbounds")
    assert rule_named(config, "rule_probe_hk1")["outboundTag"] == "node_hk1"
    # The probe dials the node, so the resolver it dials by is still reached.
    assert rule_named(config, "rule_dns_direct")["outboundTag"] == "direct"
    assert "balancers" not in config["routing"]
    assert not any("balancerTag" in rule for rule in config["routing"]["rules"])


def test_the_probe_listener_carries_one_account_per_node():
    """One listener, one account per node, and the account name is the tag the
    routing rule matches on."""
    config = render_with_a_switched_off_node()

    listeners = [entry for entry in config["inbounds"] if entry["tag"] == PROBE_TAG]
    assert len(listeners) == 1
    assert listeners[0]["listen"] == "127.0.0.1"
    assert listeners[0]["port"] == 10086
    assert listeners[0]["settings"]["auth"] == "password"
    assert listeners[0]["settings"]["udp"] is False
    assert [account["user"] for account in listeners[0]["settings"]["accounts"]] == [
        "node_hk1",
        "node_hk2",
    ]
    # A sniffed name would put a lookup in front of every measurement.
    assert "sniffing" not in listeners[0]


def test_each_probe_account_leaves_by_its_own_node():
    config = render_with_a_switched_off_node()

    rule = rule_named(config, "rule_probe_hk2")

    assert rule["inboundTag"] == [PROBE_TAG]
    assert rule["user"] == ["node_hk2"]
    assert rule["outboundTag"] == "node_hk2"


def test_every_probe_rule_sits_ahead_of_the_destination_rules():
    """The probe target is somebody's own URL and may well be a name the
    direct lists claim, which would measure the uplink instead of the exit."""
    config = render_with_a_switched_off_node(
        is_geoip_split_enabled=True,
        direct_domains=["geosite:cn"],
        direct_ips=["geoip:cn"],
    )

    rules = config["routing"]["rules"]
    probes = [
        index
        for index, rule in enumerate(rules)
        if rule["ruleTag"].startswith("rule_probe_")
    ]
    destinations = [
        index for index, rule in enumerate(rules) if "domain" in rule or "ip" in rule
    ]
    assert probes and destinations
    assert max(probes) < min(destinations)


def test_every_rule_says_which_one_it_is():
    """`xray api lsrules` reads these back, and two rules under one name are
    two rules nobody can tell apart."""
    config = render_with_a_switched_off_node()

    rule_tags = [rule["ruleTag"] for rule in config["routing"]["rules"]]

    assert all(rule_tags)
    assert len(rule_tags) == len(set(rule_tags))


def test_the_direct_outbound_is_what_an_unmatched_connection_takes():
    """xray sends a connection no rule matched to the first outbound, and a
    node outbound may be one somebody switched off."""
    config = render_with_a_switched_off_node()

    assert tags(config, "outbounds")[0] == "direct"


# --- how the balancer is picked from ------------------------------------------


def test_the_balancer_needs_nothing_measured():
    """The hub measures the nodes itself and names the winner to xray, so the
    rendered strategy is the one that reads no measurement from xray."""
    node_list = resolved_nodes()
    config = XrayConfigRenderer(
        node_list=node_list,
        routing={"is_proxy_enabled": True},
    ).render()

    balancer = config["routing"]["balancers"][0]

    assert balancer["strategy"] == {"type": "roundRobin"}
    assert "fallbackTag" not in balancer


def test_the_fallback_is_not_something_the_balancer_carries():
    """A dead exit is answered by overriding the balancer with the direct
    outbound, which is the panel's switch, not a rendered field."""
    config = render(is_direct_fallback_enabled=True)

    assert "fallbackTag" not in config["routing"]["balancers"][0]


def test_a_dangling_reference_excludes_the_node():
    """A reference nothing resolves renders the node out, never a crash."""
    config = render(is_resolved=False)

    assert "node_hk1" not in tags(config, "outbounds")
    assert "balancers" not in config["routing"]
    assert PROBE_TAG not in tags(config, "inbounds")


# --- what dnsmasq's queries do inside xray ------------------------------------


def test_the_lan_scope_hands_the_dns_inbound_to_the_dns_outbound():
    config = render()

    dns_out = next(entry for entry in config["outbounds"] if entry["tag"] == "dns_out")
    rule = rule_named(config, "rule_dns_in")

    assert dns_out["protocol"] == "dns"
    assert dns_out["settings"]["nonIPQuery"] == "drop"
    assert rule["inboundTag"] == ["dns_in"]
    assert rule["outboundTag"] == "dns_out"


def test_without_the_lan_scope_nothing_reaches_the_dns_outbound():
    """dnsmasq asks the direct resolver itself with that scope off, so the
    DNS inbound is answered directly and the outbound has no caller."""
    config = render(is_proxy_enabled=False, is_local_proxy_enabled=True)

    assert "dns_out" not in tags(config, "outbounds")
    assert "dns_in" in rule_named(config, "rule_inbound_direct")["inboundTag"]


# --- what xray writes down ----------------------------------------------------


def test_the_access_log_is_off_and_the_error_log_is_the_journal():
    """A line per connection that nothing here reads. xray defaults the access
    log to the console, so it is turned off by name; the error log is given no
    path, which leaves it on the console for journald to bound."""
    config = render()

    assert config["log"]["access"] == "none"
    assert "error" not in config["log"]


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
        "domains": ["full:exit.example.net"],
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
        "ruleTag": "rule_dns_direct",
        "inboundTag": ["dns_internal"],
        "ip": ["223.5.5.5"],
        "outboundTag": "direct",
    } in rules
    balancer_rule = next(rule for rule in rules if "balancerTag" in rule)
    assert rules.index(balancer_rule) == len(rules) - 1


def test_the_probe_host_is_pinned_at_no_resolver():
    """The probe leaves through the node it measures, and that node
    resolves the probe's host; a pin here would send the name to the
    direct resolver from every device."""
    by_name = render_with_exit("exit.example.net")
    by_address = render_with_exit("203.0.113.10")

    for config in (by_name, by_address):
        pinned = [
            domain
            for server in config["dns"]["servers"]
            if isinstance(server, dict)
            for domain in server.get("domains", [])
        ]
        assert "full:www.gstatic.com" not in pinned
    assert "223.5.5.5" not in str(by_address["dns"]["servers"][0])


def test_the_resolvers_other_queries_follow_the_balancer():
    """A query nothing routes goes to the first outbound, and the direct
    outbound is first, so the resolver's own queries are routed by name."""
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


def test_with_every_scope_off_an_exits_name_still_resolves_where_it_answers():
    """The hub keeps measuring with every scope off, and a node addressed by
    name is dialled by an address xray looks up itself. Only the direct
    resolver answers that name correctly without the proxy: on a poisoned
    uplink the remote one hands back a forged address, and a healthy node
    then reads as unreachable."""
    config = render_with_exit("exit.example.net", is_proxy_enabled=False)

    assert config["dns"]["servers"][0] == {
        "address": "223.5.5.5",
        "port": 53,
        "domains": ["full:exit.example.net"],
        "skipFallback": True,
    }
    assert rule_named(config, "rule_dns_direct") == {
        "type": "field",
        "ruleTag": "rule_dns_direct",
        "inboundTag": ["dns_internal"],
        "ip": ["223.5.5.5"],
        "outboundTag": "direct",
    }
