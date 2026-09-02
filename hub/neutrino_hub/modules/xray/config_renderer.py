"""Rendering the complete xray configuration from ``config/``.

Pure: this module turns the node list and routing options into the config
object xray consumes. Validating and restarting is :mod:`neutrino_hub.modules.xray.apply`.
"""

from neutrino_hub.modules.xray.constants import (
    XRAY_API_INBOUND_TAG,
    XRAY_API_LISTEN,
    XRAY_API_PORT,
    XRAY_API_TAG,
    XRAY_BALANCER_TAG,
    XRAY_BLOCK_TAG,
    XRAY_DIRECT_TAG,
    XRAY_DNS_LISTEN,
    XRAY_DNS_PORT,
    XRAY_DNS_TAG,
    XRAY_EGRESS_MARK,
    XRAY_NODE_TAG_PREFIX,
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

from neutrino_hub.utils.constants import UTILS_LOG_DIR


class XrayConfigRenderer:
    """Builds the xray config: inbounds, outbounds, balancer, and routing.

    Four inbounds are always present. ``tproxy_in`` receives everything the
    router diverts from the LAN and goes to the balancer. ``socks_direct_in``
    goes straight out the WAN, so applications that must look like they come
    from this network (remote desktop back home, for one) have a path that
    skips the proxy. ``dns_in`` is dnsmasq's only upstream.
    ``api_in`` exposes traffic statistics to the panel on loopback.
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
        # A scope switched on with nothing to go out through renders as off.
        # Raising instead made every apply fail on a box in that state — and
        # the one thing that fixes it, switching the scope off, is what the
        # failure prevented anybody from applying. The panel writes the
        # switches off when the list empties, so the two agree; this is what
        # keeps a hand-edited file from being unrenderable.
        has_exit = bool(node_list.enabled_nodes)
        self._is_lan_proxied = routing.get("is_proxy_enabled", True) and has_exit
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
            or self._is_local_proxied
            or self._socks_tags(is_proxied=True)
        )

    def render(self) -> dict:
        """Render the whole configuration.

        Returns:
            A JSON-ready object for ``/var/lib/neutrino/generated/xray_config.json``.
        """
        config = {
            "log": {
                "loglevel": "warning",
                "access": str(UTILS_LOG_DIR / "xray_access.log"),
                "error": str(UTILS_LOG_DIR / "xray_error.log"),
            },
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
        if self._is_anything_proxied and self._node_list.is_observatory_needed:
            config["observatory"] = self._render_observatory()
        return config

    def _render_dns(self) -> dict:
        remote = self._routing.get("remote_dns", {})
        servers: list = [remote.get("address", "1.1.1.1")]
        if self._is_geoip_split_enabled and self._is_anything_proxied:
            direct = self._routing.get("direct_dns", {})
            servers.insert(
                0,
                {
                    "address": direct.get("address", "223.5.5.5"),
                    "domains": self._routing.get("direct_domains", []),
                    "skipFallback": True,
                },
            )
        return {"servers": servers, "queryStrategy": "UseIP"}

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
        outbounds = (
            [self._render_node_outbound(node) for node in self._node_list.enabled_nodes]
            if self._is_anything_proxied
            else []
        )
        outbounds.append(
            {
                "tag": XRAY_DIRECT_TAG,
                "protocol": "freedom",
                "settings": {"domainStrategy": "UseIP"},
                "streamSettings": {"sockopt": {"mark": XRAY_EGRESS_MARK}},
            }
        )
        outbounds.append({"tag": XRAY_BLOCK_TAG, "protocol": "blackhole"})
        return outbounds

    def _render_node_outbound(self, node: XrayNodeConfig) -> dict:
        stream: dict = {"sockopt": {"mark": XRAY_EGRESS_MARK}}
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
        rules: list[dict] = [
            {
                "type": "field",
                "inboundTag": [XRAY_API_INBOUND_TAG],
                "outboundTag": XRAY_API_TAG,
            },
        ]
        direct_ports = self._socks_tags(is_proxied=False)
        if direct_ports:
            rules.append(
                {
                    "type": "field",
                    "inboundTag": direct_ports,
                    "outboundTag": XRAY_DIRECT_TAG,
                }
            )
        balanced = self._socks_tags(is_proxied=True)
        if self._is_lan_proxied:
            balanced = [XRAY_TPROXY_TAG, XRAY_DNS_TAG] + balanced
        else:
            # With the LAN scope off, whatever still reaches these inbounds
            # leaves directly — the DNS inbound has to answer from somewhere,
            # and the transparent inbound carries the hub's own traffic when
            # that scope stands alone.
            if self._is_local_proxied:
                balanced = [XRAY_TPROXY_TAG] + balanced
                direct_inbounds = [XRAY_DNS_TAG]
            else:
                direct_inbounds = [XRAY_TPROXY_TAG, XRAY_DNS_TAG]
            rules.append(
                {
                    "type": "field",
                    "inboundTag": direct_inbounds,
                    "outboundTag": XRAY_DIRECT_TAG,
                }
            )
        if not balanced:
            # Nothing is sent to the balancer, so the split has nothing to
            # split and the lists are not read at all — which is what makes
            # switching every scope off the way out of a bad entry in one of
            # them: a rejected config takes the whole apply with it.
            return {"domainStrategy": "IPIfNonMatch", "rules": rules}

        if self._is_geoip_split_enabled:
            direct_domains = self._routing.get("direct_domains", [])
            direct_ips = self._routing.get("direct_ips", [])
            if direct_domains:
                rules.append(
                    {
                        "type": "field",
                        "domain": direct_domains,
                        "outboundTag": XRAY_DIRECT_TAG,
                    }
                )
            if direct_ips:
                rules.append(
                    {
                        "type": "field",
                        "ip": direct_ips,
                        "outboundTag": XRAY_DIRECT_TAG,
                    }
                )
        rules.append(
            {
                "type": "field",
                "inboundTag": balanced,
                "balancerTag": XRAY_BALANCER_TAG,
            }
        )
        return {
            "domainStrategy": "IPIfNonMatch",
            "balancers": [self._render_balancer()],
            "rules": rules,
        }

    def _render_balancer(self) -> dict:
        """The balancer, and what it does when no exit answers.

        Without a fallback a dead exit is a dead network: what was sent to the
        proxy fails, and so does every name, because the LAN's resolver is
        this same balancer. With one, that traffic leaves directly instead —
        which is connectivity bought with the thing the proxy was for, and so
        is the person's switch to throw rather than a default.

        Returns:
            The balancer object.
        """
        balancer = {
            "tag": XRAY_BALANCER_TAG,
            "selector": [XRAY_NODE_TAG_PREFIX],
            "strategy": {"type": self._node_list.strategy},
        }
        if self._routing.get("is_direct_fallback_enabled", False):
            balancer["fallbackTag"] = XRAY_DIRECT_TAG
        return balancer

    def _render_observatory(self) -> dict:
        return {
            "subjectSelector": [XRAY_NODE_TAG_PREFIX],
            "probeUrl": self._node_list.probe_url,
            "probeInterval": f"{self._node_list.probe_interval_s}s",
        }

    @property
    def _is_geoip_split_enabled(self) -> bool:
        return self._routing.get("is_geoip_split_enabled", True)
