"""Fixed values of the xray layer.

Ports and tags here are referenced by the nftables ruleset and the dnsmasq
config, so they are wire-level identifiers rather than user settings.
"""

from neutrino_hub.utils.constants import UTILS_GENERATED_DIR

XRAY_CONFIG_PATH = UTILS_GENERATED_DIR / "xray_config.json"
XRAY_BINARY = "/usr/local/bin/xray"
XRAY_SERVICE_NAME = "xray"

# Transparent-proxy inbound. The nftables prerouting chain diverts here.
XRAY_TPROXY_LISTEN = "127.0.0.1"
XRAY_TPROXY_PORT = 12345
XRAY_TPROXY_TAG = "tproxy_in"

# SOCKS5 inbound on the LAN whose traffic bypasses the proxy and leaves through
# the WAN directly. Used by LAN applications that must appear local.
XRAY_SOCKS_DIRECT_PORT = 1080
XRAY_SOCKS_DIRECT_TAG = "socks_direct_in"

# DNS inbound; dnsmasq forwards every LAN query here. Not 5353: that is the
# registered mDNS port, and avahi-daemon holds it on every desktop Ubuntu.
XRAY_DNS_LISTEN = "127.0.0.1"
XRAY_DNS_PORT = 15353
XRAY_DNS_TAG = "dns_in"

# Statistics and handler API, loopback only.
XRAY_API_LISTEN = "127.0.0.1"
XRAY_API_PORT = 10085
XRAY_API_TAG = "api"
XRAY_API_INBOUND_TAG = "api_in"

XRAY_NODE_TAG_PREFIX = "node_"
XRAY_DIRECT_TAG = "direct"
XRAY_BLOCK_TAG = "block"
XRAY_BALANCER_TAG = "proxy_balance"

# Mark stamped on every outbound socket so the router's output chain can tell
# xray's own egress apart from traffic that still needs proxying.
XRAY_EGRESS_MARK = 255

XRAY_BALANCER_STRATEGIES = ("leastPing", "roundRobin", "random")
# The vendor install script selects the right release for the machine.
XRAY_SUPPORTED_ARCHITECTURES = ("*",)
