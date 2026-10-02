"""Fixed values of the easytier module."""

from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER_UNIT
from neutrino_hub.utils.constants import carried_program

# What the hub's package carries. The packaging pins the same version in
# hub/packaging/venv_tree.py by reading this file. Upstream publishes no
# checksum file for these archives, so the hashes are ours, taken from the
# files this version was built against.
EASYTIER_VERSION = "2.6.4"
EASYTIER_DOWNLOAD_URL = (
    "https://github.com/EasyTier/EasyTier/releases/download/"
    "v{version}/easytier-linux-{asset_arch}-v{version}.zip"
)
EASYTIER_ASSET_ARCHITECTURES = {"amd64": "x86_64", "arm64": "aarch64"}
EASYTIER_SHA256 = {
    "amd64": "61b659eaedba658fa66fe47d17e1426cdd77e5d02fa15fed447bb4357c09dfd6",  # scan: allow
    "arm64": "f533ec25a7ea714e09f645615012200278058525795cc3bb690ff011aec1a70f",  # scan: allow
}
EASYTIER_SUPPORTED_ARCHITECTURES = ("amd64", "arm64")
# Only these two of the four the archive carries: the web console and its
# embedded twin serve other machines, and this box only runs a node.
EASYTIER_CORE_NAME = "easytier-core"
EASYTIER_CLI_NAME = "easytier-cli"
EASYTIER_CORE_PATH = carried_program(EASYTIER_CORE_NAME)
EASYTIER_CLI_PATH = carried_program(EASYTIER_CLI_NAME)

EASYTIER_UNIT = OVERLAY_EASYTIER_UNIT
EASYTIER_GENERATED_NAME = "easytier.toml"
# The engine's start line, a drop-in over the hub's unit. systemd shows a
# unit's start line to every local user, so its mode is the ordinary one;
# misc/config.md.
EASYTIER_DROPIN_DIR_NAME = f"{EASYTIER_UNIT}.d"
EASYTIER_DROPIN_NAME = "arguments.conf"
# The start arguments file of the 0.4.0 development builds; apply deletes it.
EASYTIER_STALE_ARGUMENTS_NAME = "easytier.env"
# The name the process controller knows the engine by; on macOS and
# Windows it holds the start line in place of the drop-in.
EASYTIER_SUPERVISED_NAME = "easytier"

# How the engine learns its network: from the files this hub renders, or from
# EasyTier's own console, which pushes the whole network configuration.
EASYTIER_MODE_MANUAL = "manual"
EASYTIER_MODE_CONSOLE = "console"
EASYTIER_MODES = (EASYTIER_MODE_MANUAL, EASYTIER_MODE_CONSOLE)
EASYTIER_CONFIG_SERVER_SCHEMES = ("tcp", "udp", "ws", "wss")

# The tunnel device the firewall rules name, and the port this box's own peers
# knock on. Both are stated rather than left to the engine: a device it named
# itself would be a device the ruleset matches by luck.
EASYTIER_DEVICE_NAME = "easytier"
# macOS names a tunnel utunN and nothing else, so there the engine picks
# its own and the device is found by its address.
EASYTIER_SYSTEM_NAMED_DEVICE_OS = ("darwin",)
EASYTIER_PEER_PORT = 11010
# Loopback only, and the engine's own default port. Reading the node's state
# goes through it; nothing else may.
EASYTIER_RPC_PORTAL = "127.0.0.1:15888"

# What a fresh network is given. The address is the engine's own first DHCP
# address, so a machine joining with `-d` lands in the same /24 without anybody
# working out an address; a box whose own networks collide with it is given a
# generated one instead.
EASYTIER_DEFAULT_ADDRESS = "10.0.0.1/24"
EASYTIER_DEFAULT_PREFIX_LEN = 24
EASYTIER_NAME_PREFIX = "neutrino-"
EASYTIER_NAME_BYTES = 4
EASYTIER_SECRET_BYTES = 24
EASYTIER_NAME_MAX_LEN = 64

# The network secret is the pre-shared key of the whole network: whoever holds
# it joins and decrypts. It is sealed under the vault's data key where it is
# stored, so config/easytier/easytier.json carries no key material.
EASYTIER_SECRET_AAD = b"easytier:network_secret"
# The console address carries an account token that admits machines to it.
EASYTIER_CONFIG_SERVER_AAD = b"easytier:config_server"

# What the engine may be told to connect to first. The three URL forms are the
# engine's discovery addresses, which answer with peer addresses rather than
# being one.
EASYTIER_PEER_SCHEMES = ("tcp", "udp", "ws", "wss", "quic", "ring")
EASYTIER_DISCOVERY_SCHEMES = ("http", "https", "txt", "srv")

EASYTIER_STATUS_TIMEOUT_S = 10

# The instance fields a console in secure mode may keep from this box, by the
# name the page shows them under.
EASYTIER_INSTANCE_FIELDS = ("network_name", "address", "hostname")
