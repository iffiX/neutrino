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
    XRAY_SOCKS_DIRECT_PORT,
    XRAY_SOCKS_DIRECT_TAG,
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
    listens on the LAN and goes straight out the WAN, so applications that must
    look like they come from this network (remote desktop back home, for one)
    have a path that skips the proxy. ``dns_in`` is dnsmasq's only upstream.
    ``api_in`` exposes traffic statistics to the panel on loopback.
    """

    def __init__(
        self,
        *,
        node_list: XrayNodeList,
        routing: dict,
        lan_address: str,
    ):
        """
        Args:
            node_list: Parsed ``config/xray/nodes.json``.
            routing: Parsed ``config/xray/routing.json``.
            lan_address: Address the direct SOCKS inbound binds to.

        Raises:
            ValueError: If no node is enabled, since the balancer would have
                nothing to select and every proxied connection would fail.
        """
        self._is_proxy_enabled = routing.get("is_proxy_enabled", True)
        self._is_socks_direct_enabled = routing.get("is_socks_direct_enabled", True)
        if self._is_proxy_enabled and not node_list.enabled_nodes:
            raise ValueError(
                "no enabled nodes in config/xray/nodes.json; "
                "the balancer needs at least one, or turn the proxy off"
            )
        self._node_list = node_list
        self._routing = routing
        self._lan_address = lan_address

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
        if self._is_proxy_enabled and self._node_list.is_observatory_needed:
            config["observatory"] = self._render_observatory()
        return config

    def _render_dns(self) -> dict:
        remote = self._routing.get("remote_dns", {})
        servers: list = [remote.get("address", "1.1.1.1")]
        if self._is_geoip_split_enabled:
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
        if self._is_socks_direct_enabled:
            # A second way out of the box, and the one an application is
            # pointed at by hand, so it is published only when asked for.
            inbounds.append(
                {
                    "tag": XRAY_SOCKS_DIRECT_TAG,
                    "listen": self._lan_address,
                    "port": XRAY_SOCKS_DIRECT_PORT,
                    "protocol": "socks",
                    "settings": {"udp": True, "auth": "noauth"},
                    "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
                }
            )
        return inbounds

    def _render_outbounds(self) -> list[dict]:
        outbounds = (
            [self._render_node_outbound(node) for node in self._node_list.enabled_nodes]
            if self._is_proxy_enabled
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
        if self._is_socks_direct_enabled:
            rules.append(
                {
                    "type": "field",
                    "inboundTag": [XRAY_SOCKS_DIRECT_TAG],
                    "outboundTag": XRAY_DIRECT_TAG,
                }
            )
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
        if not self._is_proxy_enabled:
            # The proxy is out of the path. Nothing reaches xray by TPROXY at
            # all in this state — the firewall stops diverting — but the DNS
            # inbound is still wired up, and it has to answer from somewhere.
            rules.append(
                {
                    "type": "field",
                    "inboundTag": [XRAY_TPROXY_TAG, XRAY_DNS_TAG],
                    "outboundTag": XRAY_DIRECT_TAG,
                }
            )
            return {"domainStrategy": "IPIfNonMatch", "rules": rules}

        rules.append(
            {
                "type": "field",
                "inboundTag": [XRAY_TPROXY_TAG, XRAY_DNS_TAG],
                "balancerTag": XRAY_BALANCER_TAG,
            }
        )
        return {
            "domainStrategy": "IPIfNonMatch",
            "balancers": [
                {
                    "tag": XRAY_BALANCER_TAG,
                    "selector": [XRAY_NODE_TAG_PREFIX],
                    "strategy": {"type": self._node_list.strategy},
                }
            ],
            "rules": rules,
        }

    def _render_observatory(self) -> dict:
        return {
            "subjectSelector": [XRAY_NODE_TAG_PREFIX],
            "probeUrl": self._node_list.probe_url,
            "probeInterval": f"{self._node_list.probe_interval_s}s",
        }

    @property
    def _is_geoip_split_enabled(self) -> bool:
        return self._routing.get("is_geoip_split_enabled", True)
