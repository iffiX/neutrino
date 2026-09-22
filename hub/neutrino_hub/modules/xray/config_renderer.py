"""Rendering the complete xray configuration from ``config/``.

Pure: this module turns the node list and routing options into the config
object xray consumes. Validating and restarting is :mod:`neutrino_hub.modules.xray.apply`.
"""

import ipaddress

from neutrino_hub.modules.xray.constants import (
    XRAY_ACCESS_LOG,
    XRAY_API_INBOUND_TAG,
    XRAY_API_LISTEN,
    XRAY_API_PORT,
    XRAY_API_TAG,
    XRAY_BALANCER_STRATEGY,
    XRAY_BALANCER_TAG,
    XRAY_BLOCK_TAG,
    XRAY_DIRECT_TAG,
    XRAY_DNS_INTERNAL_TAG,
    XRAY_DNS_LISTEN,
    XRAY_DNS_NON_IP_QUERY,
    XRAY_DNS_OUTBOUND_TAG,
    XRAY_DNS_PORT,
    XRAY_DNS_QUERY_STRATEGY,
    XRAY_DNS_TAG,
    XRAY_EGRESS_MARK,
    XRAY_LOG_LEVEL,
    XRAY_NODE_DOMAIN_STRATEGY,
    XRAY_PROBE_LISTEN,
    XRAY_PROBE_PASSWORD,
    XRAY_PROBE_PORT,
    XRAY_PROBE_TAG,
    XRAY_RULE_TAG_API,
    XRAY_RULE_TAG_BALANCER,
    XRAY_RULE_TAG_DNS_DIRECT,
    XRAY_RULE_TAG_DNS_IN,
    XRAY_RULE_TAG_INBOUND_DIRECT,
    XRAY_RULE_TAG_PROBE,
    XRAY_RULE_TAG_SOCKS_DIRECT,
    XRAY_RULE_TAG_SPLIT_DOMAIN,
    XRAY_RULE_TAG_SPLIT_IP,
    XRAY_SOCKS_LISTEN,
    XRAY_SOCKS_TAG,
    XRAY_TPROXY_LISTEN,
    XRAY_TPROXY_PORT,
    XRAY_TPROXY_TAG,
)
from neutrino_hub.modules.xray.node_config import (
    SHADOWSOCKS_PROTOCOL,
    XrayNodeConfig,
    XrayNodeList,
)


class XrayConfigRenderer:
    """Builds the xray config: inbounds, outbounds, balancer, and routing.

    ``tproxy_in`` takes what the router diverts, ``dns_in`` is dnsmasq's only
    upstream, ``api_in`` answers the panel on loopback, and one SOCKS listener
    per published port leaves the way its entry says. ``socks_probe_in``
    carries one account per resident node, and one rule per account sends that
    account out its own node.
    """

    def __init__(
        self,
        *,
        node_list: XrayNodeList,
        routing: dict,
    ):
        """
        Args:
            node_list: Parsed ``config/xray/nodes.json``.
            routing: Parsed ``config/xray/routing.json``.
        """
        # Every node whose secret resolved is resident: an outbound and a
        # probe account, whatever the scopes say, so the hub can measure it on
        # a box that proxies nothing and name the one worth switching back on.
        # Only an enabled node is selectable, which is the whole of what the
        # switch means. A node whose reference dangles is in neither list: the
        # caller resolves before rendering, and a dangling reference must not
        # take the whole apply with it.
        self._resident_nodes = [
            node for node in node_list.nodes if node.has_secret_material
        ]
        self._selectable_nodes = [
            node for node in self._resident_nodes if node.is_enabled
        ]
        # A scope switched on with nothing to go out through renders as off.
        # Raising instead made every apply fail on a box in that state, and
        # the one thing that fixes it, switching the scope off, is what the
        # failure prevented anybody from applying. The panel writes the
        # switches off when the list empties, so the two agree; this is what
        # keeps a hand-edited file from being unrenderable.
        has_exit = bool(self._selectable_nodes)
        # The forwarded scopes read alike here: what the firewall diverts,
        # LAN or overlay, arrives on the one transparent inbound.
        self._is_lan_proxied = routing.get("is_proxy_enabled", True) and has_exit
        self._is_overlay_proxied = (
            routing.get("is_overlay_proxy_enabled", False) and has_exit
        )
        self._is_local_proxied = (
            routing.get("is_local_proxy_enabled", False) and has_exit
        )
        # A proxied listener with no exit would answer and send everything out
        # directly under a name that says the opposite, so it is not published
        # at all in that state.
        self._socks_ports = [
            entry
            for entry in routing.get("socks_ports", [])
            if has_exit or not entry.get("is_proxied", False)
        ]
        self._node_list = node_list
        self._routing = routing

    @property
    def _is_anything_proxied(self) -> bool:
        """Whether any scope sends traffic to the balancer at all."""
        return bool(
            self._is_lan_proxied
            or self._is_overlay_proxied
            or self._is_local_proxied
            or self._socks_tags(is_proxied=True)
        )

    @property
    def _is_transparent_proxied(self) -> bool:
        """Whether what the firewall diverts goes to the balancer."""
        return bool(
            self._is_lan_proxied or self._is_overlay_proxied or self._is_local_proxied
        )

    def render(self) -> dict:
        """Render the whole configuration.

        Returns:
            A JSON-ready object for ``/var/lib/neutrino/generated/xray_config.json``.
        """
        return {
            "log": {"loglevel": XRAY_LOG_LEVEL, "access": XRAY_ACCESS_LOG},
            "stats": {},
            "api": {
                "tag": XRAY_API_TAG,
                "services": ["StatsService", "HandlerService", "RoutingService"],
            },
            "policy": {
                "system": {
                    "statsInboundUplink": True,
                    "statsInboundDownlink": True,
                    "statsOutboundUplink": True,
                    "statsOutboundDownlink": True,
                }
            },
            "dns": self._render_dns(),
            "inbounds": self._render_inbounds(),
            "outbounds": self._render_outbounds(),
            "routing": self._render_routing(),
        }

    def _render_dns(self) -> dict:
        remote = self._routing.get("remote_dns", {})
        direct = self._routing.get("direct_dns", {})
        servers: list = [
            {
                "address": remote.get("address", "1.1.1.1"),
                "port": remote.get("port", 53),
            }
        ]
        if self._is_geoip_split_enabled and self._is_anything_proxied:
            servers.insert(
                0,
                {
                    "address": direct.get("address", "223.5.5.5"),
                    "port": direct.get("port", 53),
                    "domains": self._routing.get("direct_domains", []),
                    "skipFallback": True,
                },
            )
        own_names = self._exit_hostnames
        if own_names and self._resident_nodes:
            # An exit's name resolves at the direct resolver: it is the
            # resolver that answers that name correctly without the proxy,
            # and a lookup sent through an exit waits on the exit it is
            # asking about. This holds while a node is rendered, whatever the
            # scopes say, because the probe dials that node by the address
            # this pin resolves.
            servers.insert(
                0,
                {
                    "address": direct.get("address", "223.5.5.5"),
                    "port": direct.get("port", 53),
                    "domains": [f"full:{host}" for host in own_names],
                    "skipFallback": True,
                },
            )
        return {
            "tag": XRAY_DNS_INTERNAL_TAG,
            "servers": servers,
            "queryStrategy": XRAY_DNS_QUERY_STRATEGY,
        }

    @property
    def _exit_hostnames(self) -> list[str]:
        """The exit nodes addressed by name, in configuration order."""
        names = []
        for node in self._resident_nodes:
            if not _is_ip_address(node.address) and node.address not in names:
                names.append(node.address)
        return names

    def _render_inbounds(self) -> list[dict]:
        inbounds = [
            {
                "tag": XRAY_API_INBOUND_TAG,
                "listen": XRAY_API_LISTEN,
                "port": XRAY_API_PORT,
                "protocol": "dokodemo-door",
                "settings": {"address": XRAY_API_LISTEN},
            },
            {
                "tag": XRAY_TPROXY_TAG,
                "listen": XRAY_TPROXY_LISTEN,
                "port": XRAY_TPROXY_PORT,
                "protocol": "dokodemo-door",
                "settings": {"network": "tcp,udp", "followRedirect": True},
                "streamSettings": {"sockopt": {"tproxy": "tproxy"}},
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": True,
                },
            },
            {
                "tag": XRAY_DNS_TAG,
                "listen": XRAY_DNS_LISTEN,
                "port": XRAY_DNS_PORT,
                "protocol": "dokodemo-door",
                "settings": {
                    "address": self._routing.get("remote_dns", {}).get(
                        "address", "1.1.1.1"
                    ),
                    "port": self._routing.get("remote_dns", {}).get("port", 53),
                    "network": "tcp,udp",
                },
            },
        ]
        if self._resident_nodes:
            inbounds.append(self._render_probe_inbound())
        # One inbound per published port, tagged by the port so a rule can name
        # exactly the listeners that leave one way.
        for entry in self._socks_ports:
            inbounds.append(
                {
                    "tag": XRAY_SOCKS_TAG.format(port=entry["port"]),
                    "listen": XRAY_SOCKS_LISTEN,
                    "port": entry["port"],
                    "protocol": "socks",
                    "settings": {"udp": True, "auth": "noauth"},
                    "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
                }
            )
        return inbounds

    def _render_probe_inbound(self) -> dict:
        """The loopback listener the hub measures every node through."""
        # No sniffing: the destination arrives as a domain in the SOCKS
        # request and the rule matches on the account, so a sniffed name would
        # only put a lookup in front of every measurement.
        return {
            "tag": XRAY_PROBE_TAG,
            "listen": XRAY_PROBE_LISTEN,
            "port": XRAY_PROBE_PORT,
            "protocol": "socks",
            "settings": {
                "udp": False,
                "auth": "password",
                "accounts": [
                    {"user": node.tag, "pass": XRAY_PROBE_PASSWORD}
                    for node in self._resident_nodes
                ],
            },
        }

    def _socks_tags(self, *, is_proxied: bool) -> list[str]:
        """The inbound tags of the listeners that leave one way.

        Args:
            is_proxied: True for the ones going out through an exit node,
                False for the ones leaving directly.

        Returns:
            One tag per matching listener, in configuration order.
        """
        return [
            XRAY_SOCKS_TAG.format(port=entry["port"])
            for entry in self._socks_ports
            if bool(entry.get("is_proxied", False)) is is_proxied
        ]

    def _render_outbounds(self) -> list[dict]:
        # xray sends a connection no rule matched to the first outbound, and a
        # node outbound may be one the person switched off.
        outbounds: list[dict] = [
            {
                "tag": XRAY_DIRECT_TAG,
                "protocol": "freedom",
                "settings": {"domainStrategy": "UseIP"},
                "streamSettings": {"sockopt": {"mark": XRAY_EGRESS_MARK}},
            }
        ]
        outbounds += [self._render_node_outbound(node) for node in self._resident_nodes]
        if self._is_lan_proxied:
            # With the LAN scope off dnsmasq asks the direct resolver itself,
            # so nothing reaches the DNS inbound and this has no caller.
            outbounds.append(
                {
                    "tag": XRAY_DNS_OUTBOUND_TAG,
                    "protocol": "dns",
                    "settings": {"nonIPQuery": XRAY_DNS_NON_IP_QUERY},
                }
            )
        outbounds.append({"tag": XRAY_BLOCK_TAG, "protocol": "blackhole"})
        return outbounds

    def _render_node_outbound(self, node: XrayNodeConfig) -> dict:
        stream: dict = {
            "sockopt": {
                "mark": XRAY_EGRESS_MARK,
                "domainStrategy": XRAY_NODE_DOMAIN_STRATEGY,
            }
        }
        if node.protocol == SHADOWSOCKS_PROTOCOL:
            settings = {
                "servers": [
                    {
                        "address": node.address,
                        "port": node.port,
                        "method": node.method,
                        "password": node.password,
                    }
                ]
            }
            protocol = "shadowsocks"
        else:
            user: dict = {"id": node.uuid, "encryption": "none"}
            if node.flow:
                user["flow"] = node.flow
            settings = {
                "vnext": [{"address": node.address, "port": node.port, "users": [user]}]
            }
            protocol = "vless"
            stream["network"] = "tcp"
            if node.has_reality:
                stream["security"] = "reality"
                stream["realitySettings"] = {
                    "serverName": node.reality.server_name,
                    "fingerprint": node.reality.fingerprint,
                    "publicKey": node.reality.public_key,
                    "shortId": node.reality.short_id,
                    "spiderX": "/",
                }
        return {
            "tag": node.tag,
            "protocol": protocol,
            "settings": settings,
            "streamSettings": stream,
        }

    def _render_routing(self) -> dict:
        # Every rule matching by inbound comes before every rule matching by
        # destination. The probe target is somebody's own URL and may well be
        # a name the direct lists claim, which would measure the uplink
        # instead of the exit.
        rules: list[dict] = [
            {
                "type": "field",
                "ruleTag": XRAY_RULE_TAG_API,
                "inboundTag": [XRAY_API_INBOUND_TAG],
                "outboundTag": XRAY_API_TAG,
            },
        ]
        rules += self._render_probe_rules()
        if self._is_lan_proxied:
            # dnsmasq's queries reach the resolver the dns object configures,
            # so a LAN client's lookup takes the same split and the same
            # UseIPv4 that xray's own lookups take.
            rules.append(
                {
                    "type": "field",
                    "ruleTag": XRAY_RULE_TAG_DNS_IN,
                    "inboundTag": [XRAY_DNS_TAG],
                    "outboundTag": XRAY_DNS_OUTBOUND_TAG,
                }
            )
        if self._resident_nodes:
            # The direct resolver is reached directly, whatever the split
            # says about its address: the exits' names are looked up there,
            # and a lookup sent through an exit waits on its own answer. It
            # is rendered with the pin above rather than left to the first
            # outbound, which carries an unmatched query only by accident of
            # the order.
            direct = self._routing.get("direct_dns", {})
            rules.append(
                {
                    "type": "field",
                    "ruleTag": XRAY_RULE_TAG_DNS_DIRECT,
                    "inboundTag": [XRAY_DNS_INTERNAL_TAG],
                    "ip": [direct.get("address", "223.5.5.5")],
                    "outboundTag": XRAY_DIRECT_TAG,
                }
            )
        direct_ports = self._socks_tags(is_proxied=False)
        if direct_ports:
            rules.append(
                {
                    "type": "field",
                    "ruleTag": XRAY_RULE_TAG_SOCKS_DIRECT,
                    "inboundTag": direct_ports,
                    "outboundTag": XRAY_DIRECT_TAG,
                }
            )
        balanced = self._socks_tags(is_proxied=True)
        direct_inbounds = []
        # The transparent inbound carries whatever the firewall diverts: the
        # LAN's traffic, an overlay's, or the hub's own. The DNS inbound is
        # dnsmasq's upstream, and dnsmasq only asks it while the LAN scope is
        # on; with that scope off it answers directly.
        if self._is_transparent_proxied:
            balanced = [XRAY_TPROXY_TAG] + balanced
        else:
            direct_inbounds.append(XRAY_TPROXY_TAG)
        if not self._is_lan_proxied:
            direct_inbounds.append(XRAY_DNS_TAG)
        if direct_inbounds:
            rules.append(
                {
                    "type": "field",
                    "ruleTag": XRAY_RULE_TAG_INBOUND_DIRECT,
                    "inboundTag": direct_inbounds,
                    "outboundTag": XRAY_DIRECT_TAG,
                }
            )
        # With nothing sent to the balancer the split has nothing to split and
        # the direct lists are not read at all, which is what makes switching
        # every scope off the way out of a bad entry in one of them: a config
        # xray rejects takes the whole apply with it.
        if balanced:
            # The resolver's other queries, for the names the split and the
            # direct outbound resolve, go the way proxied traffic goes: an
            # unrouted query would go to the first outbound, alive or not.
            balanced = balanced + [XRAY_DNS_INTERNAL_TAG]
            if self._is_geoip_split_enabled:
                direct_domains = self._routing.get("direct_domains", [])
                direct_ips = self._routing.get("direct_ips", [])
                if direct_domains:
                    rules.append(
                        {
                            "type": "field",
                            "ruleTag": XRAY_RULE_TAG_SPLIT_DOMAIN,
                            "domain": direct_domains,
                            "outboundTag": XRAY_DIRECT_TAG,
                        }
                    )
                if direct_ips:
                    rules.append(
                        {
                            "type": "field",
                            "ruleTag": XRAY_RULE_TAG_SPLIT_IP,
                            "ip": direct_ips,
                            "outboundTag": XRAY_DIRECT_TAG,
                        }
                    )
            rules.append(
                {
                    "type": "field",
                    "ruleTag": XRAY_RULE_TAG_BALANCER,
                    "inboundTag": balanced,
                    "balancerTag": XRAY_BALANCER_TAG,
                }
            )
        routing: dict = {"domainStrategy": "IPIfNonMatch"}
        # The balancer stands whether a rule names it or not, so the hub has
        # something to override the moment a scope is switched on. xray
        # refuses an empty selector, so with no enabled node there is none.
        if self._selectable_nodes:
            routing["balancers"] = [self._render_balancer()]
        routing["rules"] = rules
        return routing

    def _render_probe_rules(self) -> list[dict]:
        """One rule per probe account, sending that account out its own node."""
        return [
            {
                "type": "field",
                "ruleTag": XRAY_RULE_TAG_PROBE.format(node_id=node.id),
                "inboundTag": [XRAY_PROBE_TAG],
                "user": [node.tag],
                "outboundTag": node.tag,
            }
            for node in self._resident_nodes
        ]

    def _render_balancer(self) -> dict:
        """The balancer, selecting the exact tags of the enabled nodes."""
        # Exact tags rather than the node prefix: every node is rendered now,
        # and a prefix would let the strategy cycle through switched-off ones
        # between an xray restart and the hub's next override.
        return {
            "tag": XRAY_BALANCER_TAG,
            "selector": [node.tag for node in self._selectable_nodes],
            "strategy": {"type": XRAY_BALANCER_STRATEGY},
        }

    @property
    def _is_geoip_split_enabled(self) -> bool:
        return self._routing.get("is_geoip_split_enabled", True)


def _is_ip_address(address: str) -> bool:
    """Whether an address is a literal rather than a name to resolve.

    Args:
        address: A node's server address.

    Returns:
        True for an IPv4 or IPv6 literal.
    """
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return False
    return True
