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
# What each database is called in the directory xray reads, which is the key
# every table here and every reader spells it under.
XRAY_GEODATA_GEOIP_FILE = "geoip.dat"
XRAY_GEODATA_GEOSITE_FILE = "geosite.dat"
XRAY_GEODATA = {
    XRAY_GEODATA_GEOIP_FILE: {
        "url": (
            "https://github.com/v2fly/geoip/releases/download/"
            "202608050239/geoip-only-cn-private.dat"
        ),
        "sha256": "81f4dda453e16cc2f4609318554eac8f61628f7611c6ee773a996519200a3ca1",  # scan: allow
    },
    XRAY_GEODATA_GEOSITE_FILE: {
        "url": (
            "https://github.com/v2fly/domain-list-community/releases/download/"
            "20260830143421/dlc.dat"
        ),
        "sha256": "edfdd950f51603879657a87ddaab670736d8d5f146d4c77778014ea617c314ba",  # scan: allow
    },
}

# Where a newer release of each database comes from, and how a machine records
# which one it holds. The pins above name one release of exactly these assets;
# every other release of them answers at the same address under another tag.
XRAY_GEODATA_LATEST_URL = "https://api.github.com/repos/{repository}/releases/latest"
XRAY_GEODATA_DOWNLOAD_URL = (
    "https://github.com/{repository}/releases/download/{release}/{asset}"
)
# Every release publishes a digest beside each asset, which is what a fetched
# file is held against: the pins above are one release and say nothing about
# the next one.
XRAY_GEODATA_SUM_SUFFIX = ".sha256sum"
XRAY_GEODATA_TIMEOUT_S = 120
# Which release each database on this machine came from. State rather than
# configuration: it describes the files on the disk, and a restored backup
# carries neither the databases nor this.
XRAY_GEODATA_VERSION_PATH = UTILS_GEODATA_DIR / "version.json"
# Where the databases came from: carried by the package, or fetched from the
# repository that publishes them.
XRAY_GEODATA_SOURCE_PACKAGE = "package"
XRAY_GEODATA_SOURCE_RELEASE = "release"

# How often the hub measures every node, switched on or off. The floor is not
# xray's: one round is a request through every node, so ten seconds across six
# nodes is a request leaving somebody's exit every 1.7 seconds.
XRAY_PROBE_INTERVAL_MIN_S = 10
XRAY_PROBE_INTERVAL_MAX_S = 3600
XRAY_PROBE_INTERVAL_DEFAULT_S = 60
# One measurement's patience, start to finish: the loopback connect, the SOCKS
# handshake, the TLS handshake and the status line.
XRAY_PROBE_TIMEOUT_S = 5.0
# How many nodes are measured at once; a round opens one connection per node.
XRAY_PROBE_WORKER_LIMIT = 8
# What each node is measured against, and what says the uplink itself is up.
# The reference is fetched directly, so it has to answer without the proxy: a
# reference that needs an exit reads every uplink outage as every node failing.
XRAY_PROBE_URL_DEFAULT = "https://www.gstatic.com/generate_204"
XRAY_REFERENCE_URL_DEFAULT = "http://www.msftconnecttest.com/connecttest.txt"

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
# The tag xray's own resolver sends its queries under, so a routing rule can
# name them. It resolves the exit nodes' hostnames, and that query cannot
# travel through the exit it is asking about.
XRAY_DNS_INTERNAL_TAG = "dns_internal"
# How a node outbound resolves the address it dials: through xray's own
# resolver, never the system's. The system resolver is the LAN's dnsmasq,
# whose upstream is the DNS inbound here, and a node reached through itself
# is a loop.
XRAY_NODE_DOMAIN_STRATEGY = "UseIP"
# What xray's own resolver asks for: A records only. The router forwards
# IPv4 only, and one record kind is one packet per name; asking for both at
# once puts two packets on a new UDP flow within microseconds, and a NAT
# router in front of the uplink was measured dropping the second.
XRAY_DNS_QUERY_STRATEGY = "UseIPv4"

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

# The balancer's strategy. It is never consulted while the hub holds an
# override, and roundRobin is the one strategy that needs no observatory, so a
# box whose panel is not running still reaches every enabled exit.
XRAY_BALANCER_STRATEGY = "roundRobin"

# The probe inbound. One SOCKS listener on loopback carries one account per
# node, and one routing rule per account sends it out that node, so measuring
# a chosen exit needs no listener of its own. The account name is the node's
# outbound tag, which is what the rule matches.
XRAY_PROBE_LISTEN = "127.0.0.1"
XRAY_PROBE_PORT = 10086
XRAY_PROBE_TAG = "socks_probe_in"
# The password the rendered accounts carry. It guards nothing: the listener
# answers loopback only, and the account name is what selects the exit. SOCKS5
# has no account without a password, so there is one.
XRAY_PROBE_PASSWORD = "probe"  # scan: allow

# Where dnsmasq's queries go once they are inside xray. The DNS outbound hands
# them to the resolver the dns object configures, so a client's lookup takes
# the same per-domain split and the same UseIPv4 that xray's own lookups take.
XRAY_DNS_OUTBOUND_TAG = "dns_out"
# What that outbound does with a query that is neither A nor AAAA. Dropping it
# keeps the property that no plaintext query leaves this box.
XRAY_DNS_NON_IP_QUERY = "drop"

# Every rendered routing rule carries one of these, so `xray api lsrules`
# names what it is looking at.
XRAY_RULE_TAG_API = "rule_api"
XRAY_RULE_TAG_PROBE = "rule_probe_{node_id}"
XRAY_RULE_TAG_DNS_IN = "rule_dns_in"
XRAY_RULE_TAG_DNS_DIRECT = "rule_dns_direct"
XRAY_RULE_TAG_SOCKS_DIRECT = "rule_socks_direct"
XRAY_RULE_TAG_INBOUND_DIRECT = "rule_inbound_direct"
XRAY_RULE_TAG_SPLIT_DOMAIN = "rule_split_domain"
XRAY_RULE_TAG_SPLIT_IP = "rule_split_ip"
XRAY_RULE_TAG_BALANCER = "rule_balancer"

# The measurement window each node keeps. The count bounds the state file and
# the arithmetic; the age bounds how stale a reading may be after the box was
# off, whatever the interval is set to.
XRAY_HEALTH_WINDOW_SAMPLES = 20
XRAY_HEALTH_SAMPLE_MAX_AGE_S = 3600
# What one failure costs a node's score, in milliseconds, spread over a full
# window. A node that drops one connection in ten loses to a node two hundred
# milliseconds slower that drops none.
XRAY_HEALTH_FAILURE_PENALTY_MS = 2000

# What it takes to move the exit off a node that still answers: the challenger
# is better by all three at once. Without them two nodes a millisecond apart
# trade the exit every round.
XRAY_EXIT_SWITCH_RATIO = 0.2
XRAY_EXIT_SWITCH_MARGIN_MS = 30
XRAY_EXIT_DWELL_S = 300
# How many times the override is set after a restart before the hub leaves it
# for the next round. The unit is Type=simple, so systemd reports the restart
# before the API inbound is listening.
XRAY_EXIT_REASSERT_TRIES = 6
XRAY_EXIT_REASSERT_DELAY_S = 0.5

# Where the measurements live between runs, under the state root.
XRAY_NODE_HEALTH_RELATIVE = "xray_node_health.json"

# xray's own logs. The access log is a line per connection that nothing reads,
# so it is never written. The error log is given no path, which leaves it on
# the console, where systemd collects it into the journal and journald bounds
# it without anything here rotating a file.
XRAY_ACCESS_LOG = "none"
XRAY_LOG_LEVEL = "warning"
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

# The routing switches that send a scope to the exit nodes. Each stands
# alone; every one needs an enabled exit, and with none they all read off.
XRAY_SCOPE_LAN = "is_proxy_enabled"
XRAY_SCOPE_OVERLAY = "is_overlay_proxy_enabled"
XRAY_SCOPE_HUB = "is_local_proxy_enabled"
XRAY_SCOPE_SWITCHES = (XRAY_SCOPE_LAN, XRAY_SCOPE_OVERLAY, XRAY_SCOPE_HUB)
