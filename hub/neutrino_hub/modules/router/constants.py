"""Fixed values of the routing layer.

These are wire-level identifiers, not user settings: changing one means changing
the nftables ruleset and the policy routes together. Anything a user tunes lives
in ``config/router/network.json`` instead.
"""

from pathlib import Path

from neutrino_hub.utils.constants import (
    UTILS_GENERATED_DIR,
    UTILS_RUNTIME_ROOT,
    UTILS_STATE_ROOT,
)

ROUTER_NFT_TABLE = "neutrino"
ROUTER_NFT_FAMILY = "inet"

# What the whole machine is, stored in ``config/router/network.json``.
# Everything downstream of it — which panels the page draws, whether the hub
# addresses anything — is a reading of it rather than a separate answer
# somebody has to keep in step.
#
# Three, and a one-armed router is not a fourth: it is a router whose single
# port is a trunk, which is a wiring the interface panel already describes.
ROUTER_MODE_ROUTER = "router"
ROUTER_MODE_SIDE_GATEWAY = "side_gateway"
ROUTER_MODE_SERVER = "server"
ROUTER_MODES_KEYS = (
    ROUTER_MODE_SERVER,
    ROUTER_MODE_SIDE_GATEWAY,
    ROUTER_MODE_ROUTER,
)
# The mode in which this box addresses its own interfaces. The other two are
# a guest on somebody else's machine: they answer on the address a port
# already has and change nothing about how it got there.
ROUTER_MODES_ADDRESSING_OWNED = (ROUTER_MODE_ROUTER,)

# The layout the wizard offers for a router on one wire. Not a mode: what it
# plans is a router, and what reaches `config/` says so.
ROUTER_LAYOUT_ONE_ARM = "one_arm_router"

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

# --- the networks this box knows how to join ---
# What `wpa_supplicant` calls each way of authenticating. Only these three are
# stored: an enterprise network needs a certificate and an identity, which is
# not something the wizard asks for and not something to half-hold.
ROUTER_KEY_MGMT_PSK = "WPA-PSK"
ROUTER_KEY_MGMT_SAE = "SAE"
ROUTER_KEY_MGMT_NONE = "NONE"
ROUTER_KEY_MGMTS = (ROUTER_KEY_MGMT_PSK, ROUTER_KEY_MGMT_SAE, ROUTER_KEY_MGMT_NONE)

# Where an entry came from. A network somebody typed into the panel and one
# read out of what this machine already held are both decisions; which is
# which is what lets the panel say where a passphrase it never asked for came
# from.
ROUTER_SOURCE_PANEL = "panel"
ROUTER_SOURCE_INHERITED = "inherited:{manager}"

# A derived key is 64 hexadecimal characters. wpa_supplicant takes either that
# or the passphrase in quotes, and the two are told apart by looking.
ROUTER_PSK_HEX_LENGTH = 64
# WPA2 permits 8 to 63 characters, which is also what a derived key is made
# from. Shorter is not a passphrase any network would have accepted.
ROUTER_PASSPHRASE_MIN_LENGTH = 8
ROUTER_PASSPHRASE_MAX_LENGTH = 63

# One supplicant per radio, so the rendered file and the unit are named after
# the interface they drive, exactly as the access point already is.
ROUTER_SUPPLICANT_UNIT = "neutrino_hub_supplicant@{interface}.service"
# Our own control socket directory, not `/run/wpa_supplicant`: the machine's
# own supplicant may be running, and two of them in one directory is a
# collision that shows up as whichever started second failing to bind.
ROUTER_SUPPLICANT_CONTROL_DIR = UTILS_RUNTIME_ROOT / "wpa_supplicant"


def router_supplicant_config_path(interface: str):
    """Where a radio's rendered supplicant configuration lives.

    Args:
        interface: Wireless interface name.

    Returns:
        The path the systemd unit reads.
    """
    return UTILS_GENERATED_DIR / f"wpa_supplicant_{interface}.conf"


# --- the lease client ---
# Driven the way dnsmasq already is: our binary invocation, our configuration,
# our state directory, and every hook the distribution ships turned off. Left
# on, dhcpcd is not an engine that fetches a lease, it is a second manager
# with opinions about the resolver, the hostname and the clock.
ROUTER_DHCP_UNIT = "neutrino_hub_dhcpcd@{interface}.service"

# --- what the hub stood down ---
# Which units the hub stopped so it could drive the interfaces itself. State
# rather than configuration: it is a note of what was done, not a copy of
# anybody's files, and losing it costs one `systemctl unmask` by hand.
ROUTER_STACK_RECORD_PATH = UTILS_STATE_ROOT / "stood_down.json"

# What the two files under `config/router/` are called, for the code that
# reads them by name rather than through the panel's runtime.
ROUTER_NETWORK_FILE = "router/network.json"
ROUTER_CONNECTIONS_FILE = "router/connections.json"
ROUTER_DHCP_STATE_DIR = UTILS_STATE_ROOT / "dhcpcd"


def router_dhcp_config_path(interface: str):
    """Where an uplink's rendered dhcpcd configuration lives.

    Args:
        interface: Interface name.

    Returns:
        The path the systemd unit reads.
    """
    return UTILS_GENERATED_DIR / f"dhcpcd_{interface}.conf"


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
