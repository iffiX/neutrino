"""Fixed values of the easytier module."""

from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER_UNIT
from neutrino_hub.utils.constants import UTILS_STATIC_ROOT

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
# embedded twin are a management plane for other people's nodes, which is the
# thing this overlay exists not to need.
EASYTIER_CORE_NAME = "easytier-core"
EASYTIER_CLI_NAME = "easytier-cli"
EASYTIER_CORE_PATH = UTILS_STATIC_ROOT / "bin" / EASYTIER_CORE_NAME
EASYTIER_CLI_PATH = UTILS_STATIC_ROOT / "bin" / EASYTIER_CLI_NAME

EASYTIER_UNIT = OVERLAY_EASYTIER_UNIT
EASYTIER_GENERATED_NAME = "easytier.toml"

# The tunnel device the firewall rules name, and the port this box's own peers
# knock on. Both are stated rather than left to the engine: a device it named
# itself would be a device the ruleset matches by luck.
EASYTIER_DEVICE_NAME = "easytier"
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

# What the engine may be told to connect to first. The three URL forms are the
# engine's discovery addresses, which answer with peer addresses rather than
# being one.
EASYTIER_PEER_SCHEMES = ("tcp", "udp", "ws", "wss", "quic", "ring")
EASYTIER_DISCOVERY_SCHEMES = ("http", "https", "txt", "srv")

# Reading the node's own state prints the running configuration, the network
# secret in it, so only the peer table is ever asked for.
EASYTIER_STATUS_TIMEOUT_S = 10
