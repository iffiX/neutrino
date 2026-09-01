"""Fixed values of the xray layer.

Ports and tags here are referenced by the nftables ruleset and the dnsmasq
config, so they are wire-level identifiers rather than user settings.
"""

from neutrino_hub.utils.constants import (
    UTILS_GEODATA_DIR,
    UTILS_GENERATED_DIR,
    UTILS_STATIC_ROOT,
)

XRAY_CONFIG_PATH = UTILS_GENERATED_DIR / "xray_config.json"
# Carried by the hub's package rather than installed by the vendor's script,
# so it lives under the hub's own prefix instead of /usr/local, which belongs
# to whoever administers the machine.
XRAY_BINARY = str(UTILS_STATIC_ROOT / "bin" / "xray")

# xray reads its databases from beside its own binary unless told otherwise,
# and they are replaced while the machine runs, so it is told otherwise. Every
# path that starts xray sets this: the unit, and the validation that runs
# `xray -test` before a render is accepted.
XRAY_ASSET_ENV = "XRAY_LOCATION_ASSET"
XRAY_ASSET_DIR = str(UTILS_GEODATA_DIR)
XRAY_SERVICE_NAME = "neutrino_hub_xray"

# The release the hub runs, pinned to a version and to the hash of the file
# that version serves. A package carries it; a checkout fetches the same one,
# so the two describe one machine rather than two. Packaging reads these
# rather than restating them.
XRAY_VERSION = "26.3.27"
XRAY_DOWNLOAD_URL = (
    "https://github.com/XTLS/Xray-core/releases/download/"
    "v{version}/Xray-linux-{asset_arch}.zip"
)
# The vendor's release assets name the machine its own way.
XRAY_ASSET_ARCHITECTURES = {"amd64": "64", "arm64": "arm64-v8a"}
XRAY_SHA256 = {
    "amd64": "23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae",  # scan: allow
    "arm64": "4d30283ae614e3057f730f67cd088a42be6fdf91f8639d82cb69e48cde80413c",  # scan: allow
}
XRAY_BINARY_NAME = "xray"

# The permissive v2fly databases, which a package may carry. A running machine
# may replace them with the fuller Loyalsoldier set, which is GPL-3.0 and is
# therefore fetched rather than shipped.
XRAY_GEODATA = {
    "geoip.dat": {
        "url": (
            "https://github.com/v2fly/geoip/releases/download/"
            "202608050239/geoip-only-cn-private.dat"
        ),
        "sha256": "81f4dda453e16cc2f4609318554eac8f61628f7611c6ee773a996519200a3ca1",  # scan: allow
    },
    "geosite.dat": {
        "url": (
            "https://github.com/v2fly/domain-list-community/releases/download/"
            "20260830143421/dlc.dat"
        ),
        "sha256": "edfdd950f51603879657a87ddaab670736d8d5f146d4c77778014ea617c314ba",  # scan: allow
    },
}

# What the observatory's probe interval may be. Zero is not a fast probe, it
# is xray probing in a loop; the ceiling is a day, past which a "latency" is a
# number from another era.
XRAY_PROBE_INTERVAL_MIN_S = 5
XRAY_PROBE_INTERVAL_MAX_S = 86400

# How much of the address digest a node's id carries. Eight hexadecimal
# characters is short enough to read in a URL and long enough that two servers
# a person actually holds will not collide.
XRAY_NODE_ID_DIGEST = 8

# Transparent-proxy inbound. The nftables prerouting chain diverts here.
XRAY_TPROXY_LISTEN = "127.0.0.1"
XRAY_TPROXY_PORT = 12345
XRAY_TPROXY_TAG = "tproxy_in"

# Where every SOCKS inbound binds. Every address, as every service on this box
# binds every address: which interfaces they answer on is one firewall answer
# per interface rather than a listen address each of them gets half right —
# and a listener pinned to a LAN address is one that vanishes when the LAN
# address changes under it.
XRAY_SOCKS_LISTEN = "0.0.0.0"

# A SOCKS5 inbound is a port and one question about it: does what arrives
# there leave through an exit node, or straight out the WAN. Applications are
# pointed at one by hand — a box that diverts nothing transparently has this
# as the whole of its proxy, and a box that does still needs a direct port for
# the applications that must appear to come from this network.
XRAY_SOCKS_PORT = 1080
XRAY_SOCKS_TAG = "socks_{port}_in"

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
XRAY_SUPPORTED_ARCHITECTURES = ("amd64", "arm64")

# The direct lists reach xray as one routing rule each. An entry naming a
# database rather than an address is taken as written: what is inside it is
# known only to the file xray loads it from.
XRAY_RULE_DATABASE_PREFIXES = ("geoip:", "ext:")
XRAY_RULE_REGEXP_PREFIX = "regexp:"

# How long xray is given to reach its listeners before the restart is believed.
# The unit is Type=simple, so systemd reports success at fork; a port it cannot
# take kills it a moment later, with the apply already reported as done.
XRAY_RESTART_SETTLE_S = 1.0
XRAY_RESTART_LOG_LINES = 5
