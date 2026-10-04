"""NetBird's constants in the client."""

from neutrino_client.constants import CLIENT_STATE_DIR_DARWIN, CLIENT_STATE_DIR_LINUX

# The provider name a hub's NetBird overlay object carries.
NETBIRD_PROVIDER = "netbird"
# The management server a NetBird setup key names when the hub names none.
NETBIRD_DEFAULT_MANAGEMENT_URL = "https://api.netbird.io:443"
# What ``netbird status`` answers when no daemon is listening.
NETBIRD_DAEMON_DOWN_MARKS = (
    "failed to connect to daemon",
    "connection refused",
    "no such file or directory",
)
# The prefix every NetBird address sits in.
NETBIRD_NETWORK = "100.64.0.0/10"

# The fields a NetBird overlay object carries, which a binding keeps: it has
# no mode, a management URL left empty is NetBird's own cloud, and a hub
# whose daemon reports no name has no fqdn.
NETBIRD_OVERLAY_OBJECT = {
    "fields": {
        (NETBIRD_PROVIDER, ""): ("setup_key", "management_url", "fqdn", "hub_address")
    },
    "default_modes": {NETBIRD_PROVIDER: ""},
    "optional_fields": ("management_url", "fqdn"),
}

# Where the packages install NetBird's binary, as the client's own bundled
# paths name each system's.
NETBIRD_BUNDLED_PATHS = {
    "linux": {"netbird": "netbird/netbird"},
    "windows": {"netbird": "bin\\netbird.exe"},
    "darwin": {"netbird": "Resources/netbird/netbird"},
}

# NetBird's daemon as the packages register it, and its state, on each
# system: under /var/lib on Linux, and the client's state directory of the
# one Neutrino tree elsewhere.
CLIENT_NETBIRD_CONFIG_PATH_LINUX = CLIENT_STATE_DIR_LINUX + "/netbird/config.json"
CLIENT_NETBIRD_SERVICE_LINUX = "neutrino_client_netbird.service"
CLIENT_NETBIRD_CONFIG_NAME_WINDOWS = "netbird\\config.json"
CLIENT_NETBIRD_SERVICE_WINDOWS = "NeutrinoClientNetbird"
CLIENT_NETBIRD_CONFIG_PATH_DARWIN = CLIENT_STATE_DIR_DARWIN + "/netbird/config.json"
CLIENT_NETBIRD_LAUNCHD_LABEL = "com.neutrino.client.netbird"
