"""Fixed values of the routing layer.

These are wire-level identifiers, not user settings: changing one means changing
the nftables ruleset and the policy routes together. Anything a user tunes lives
in ``config/router/network.json`` instead.
"""

from pathlib import Path

from neutrino_hub.utils.constants import UTILS_GENERATED_DIR

ROUTER_NFT_TABLE = "neutrino"
ROUTER_NFT_FAMILY = "inet"

# What an interface is for. Every interface carries exactly one of these, and
# the role decides which block of its settings applies. ``split`` turns a wired
# port into a pure 802.1Q trunk: it carries no untagged network of its own, and
# each VLAN on it is a further interface with a role of its own.
ROUTER_ROLE_WAN = "wan"
ROUTER_ROLE_LAN = "lan"
ROUTER_ROLE_SPLIT = "split"
ROUTER_ROLE_DISABLED = "disabled"
ROUTER_ROLES = (
    ROUTER_ROLE_WAN,
    ROUTER_ROLE_LAN,
    ROUTER_ROLE_SPLIT,
    ROUTER_ROLE_DISABLED,
)

# 802.1Q tag bounds; 0 and 4095 are reserved by the standard.
ROUTER_VLAN_ID_MIN = 1
ROUTER_VLAN_ID_MAX = 4094

# What the user wants of an uplink, as opposed to what the gateway can work out
# for itself. Ordering is inferred; these three are the parts that cannot be.
#
# ``auto`` lets the gateway place it. ``primary`` pins it first — for when two
# uplinks look alike to the ranking but one is known to be better. And
# ``backup_only`` keeps it dark until nothing else is left, which is the one
# that genuinely cannot be guessed: a metered mobile link may benchmark faster
# than the broadband beside it and must still never carry traffic by choice.
ROUTER_INTENT_AUTO = "auto"
ROUTER_INTENT_PRIMARY = "primary"
ROUTER_INTENT_BACKUP_ONLY = "backup_only"
ROUTER_INTENTS = (
    ROUTER_INTENT_AUTO,
    ROUTER_INTENT_PRIMARY,
    ROUTER_INTENT_BACKUP_ONLY,
)

# What to do when the box has more than one way out. Failover keeps one uplink
# carrying everything; balance spreads across the distinct upstream lines.
# Balance is opt-in rather than inferred, because inferring it would put
# traffic on a metered link whose owner simply forgot to mark it.
ROUTER_POLICY_FAILOVER = "failover"
ROUTER_POLICY_BALANCE = "balance"
ROUTER_POLICIES = (ROUTER_POLICY_FAILOVER, ROUTER_POLICY_BALANCE)

# How a WAN gets its address.
ROUTER_WAN_METHOD_DHCP = "dhcp"
ROUTER_WAN_METHOD_STATIC = "static"
ROUTER_WAN_METHODS = (ROUTER_WAN_METHOD_DHCP, ROUTER_WAN_METHOD_STATIC)

# Route metrics that rank the uplinks. NetworkManager installs each WAN's
# default route at the metric of its connection, and the kernel prefers the
# lowest, so backups only win once no balanced uplink has a route at all.
ROUTER_METRIC_BALANCE = 100
ROUTER_METRIC_BACKUP = 700
# A LAN with an upstream router (side-gateway mode) sits between the two: any
# real uplink beats it, and it beats a backup that is meant to stay dark.
ROUTER_METRIC_SIDE_GATEWAY = 300
# The multipath route that actually splits traffic across balanced uplinks sits
# below both, so it wins whenever it exists.
ROUTER_METRIC_MULTIPATH = 90

# NetworkManager connections the gateway creates and owns. Anything with this
# prefix was made here and may be rewritten; everything else is the user's and
# is only ever modified in place.
ROUTER_NM_CONNECTION_PREFIX = "neutrino-"

# Where NetworkManager is told which interfaces are not its business. Marking a
# device unmanaged with nmcli lasts only until the next reboot, and a radio that
# NetworkManager reclaims at boot is one it will fight hostapd for.
ROUTER_NM_UNMANAGED_CONF = Path("/etc/NetworkManager/conf.d/99_neutrino_unmanaged.conf")
ROUTER_NM_AP_CONNECTION_PREFIX = "neutrino-ap-"

# Packets carrying this mark are delivered locally to the TPROXY socket.
ROUTER_FWMARK_TPROXY = 0x1
# xray stamps its own egress sockets with this mark so they escape the proxy.
ROUTER_FWMARK_XRAY_EGRESS = 0xFF
# Routing table holding the "local default" route that TPROXY delivery needs.
ROUTER_ROUTE_TABLE = 100
ROUTER_ROUTE_RULE_PRIORITY = 100

ROUTER_NFT_PATH = UTILS_GENERATED_DIR / "router.nft"
# One access point per wireless interface, so both the rendered files and the
# systemd unit are named after the interface they serve.
ROUTER_HOSTAPD_UNIT = "neutrino_hostapd@{interface}.service"


def router_hostapd_config_path(interface: str):
    """Where an interface's rendered hostapd configuration lives.

    Args:
        interface: Wireless interface name.

    Returns:
        The path the systemd unit reads.
    """
    return UTILS_GENERATED_DIR / f"hostapd_{interface}.conf"


def router_hostapd_address_path(interface: str):
    """Where an interface's access-point address is recorded for its unit.

    Args:
        interface: Wireless interface name.

    Returns:
        The environment file path the systemd unit reads.
    """
    return UTILS_GENERATED_DIR / f"hostapd_{interface}.env"


ROUTER_DNSMASQ_PATH = UTILS_GENERATED_DIR / "dnsmasq_neutrino.conf"

# Destinations that never go through the proxy: loopback, link-local, LAN, and
# multicast ranges.
ROUTER_RESERVED_NETWORKS = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "224.0.0.0/4",
    "240.0.0.0/4",
)
# Everything here arrives through apt, which picks the machine's build.
ROUTER_SUPPORTED_ARCHITECTURES = ("*",)
