from neutrino_hub.utils.constants import UTILS_DATA_DIR, UTILS_STATE_ROOT

# What a device is addressed by, everywhere. Six hexadecimal pairs, colon or
# hyphen separated, in any case; the registry lowercases and normalises on the
# way in. Anything else is not an address this box can wake, pin a host key
# against, or match a scan to, so it is refused rather than stored.
DEVICE_MAC_PATTERN = r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$"

DEVICE_LAN_SCAN_TIMEOUT_S = 30
# How long a machine's last report still stands for what it declared: a
# desktop share outlives the report that made it by this much.
DEVICE_AGENT_ONLINE_WINDOW_S = 30

# The shape of what crosses the agent channel. Must match the agent's own
# AGENT_WIRE_GENERATION; a hello carrying another number is answered with
# agent_wire_stale so the agent reinstalls itself.
AGENT_WIRE_GENERATION = 7
# The agent channel's one socket, on the agent TLS port. An agent opens it
# after enrolling and keeps it open; every stream the hub needs rides it.
AGENT_WS_PATH = "/api/agent/ws"
# What a session on the agent port is: a managed machine's agent, or a
# person's client program. Each kind has a registry of its own.
AGENT_SESSION_KIND_AGENT = "agent"
AGENT_SESSION_KIND_CLIENT = "client"
# How long a fresh socket may stay silent before its hello is due.
AGENT_WS_HELLO_TIMEOUT_S = 10.0
# How long the hub waits for an agent to answer an open before giving up
# on that stream.
AGENT_WS_OPEN_TIMEOUT_S = 15.0
# Protocol-level keepalive: uvicorn pings on this interval and drops a
# socket whose pong is late by this much.
AGENT_WS_PING_INTERVAL_S = 20.0
AGENT_WS_PING_TIMEOUT_S = 20.0
# What a stream may have in flight before the receiving side grants more:
# one window of bytes, so a transfer through the hub stays bounded.
AGENT_WS_STREAM_CREDIT_BYTES = 1024 * 1024
# The largest binary frame either side sends on one stream.
AGENT_WS_CHUNK_BYTES = 64 * 1024
# A binary frame starts with the stream id, this many ASCII characters.
AGENT_WS_STREAM_ID_LENGTH = 8
# Close codes in the application range, one per way the hub turns a socket
# away. The reason carries the code word.
AGENT_WS_CLOSE_BAD_HELLO = 4400
AGENT_WS_CLOSE_UNKNOWN_TOKEN = 4401
AGENT_WS_CLOSE_REFUSED = 4409
AGENT_WS_CLOSE_REPLACED = 4410
DEVICE_WOL_PORT = 9
# Pure Python over the network; nothing architecture-bound is installed here.
DEVICE_SUPPORTED_ARCHITECTURES = ("*",)

# What a command reports when the device could not be asked at all: it was
# off, the credentials were refused, the host key had changed. The shell's own
# "command not found" is 127 and a refused connection has no status of its
# own, so one is chosen here — and it is not a failure of the command, which
# is what makes it worth telling apart.
SSH_UNREACHABLE_STATUS = 255

# What an install task ends with when the device answered `uname -s` with
# something other than Linux. Distinct from the installer's own failures (1)
# and from SSH_UNREACHABLE_STATUS.
SSH_UNSUPPORTED_OS_STATUS = 95

# Who puts a module on a machine. platform: the OS carries it and the hub
# switches it. hub: the hub fetches an artifact and the agent installs it.
# user: the person installs it themselves and the hub only detects and
# manages it — no order ever installs or uninstalls a user-tier module.
AGENT_MODULE_INSTALLER_TIERS = ("platform", "hub", "user")
AGENT_MODULE_INSTALLER_USER = "user"

# The agent module cache: what the hub presents when it fetches a module for
# a managed machine, and what it accepts back. The ceiling is generous —
# remote desktop packages run past 100 MB — and exists so a mirror serving
# something endless cannot fill the panel's memory.
AGENT_MODULE_CACHE_DIR = UTILS_STATE_ROOT / "agent_module_cache"
AGENT_MODULE_FETCH_TIMEOUT_S = 300
AGENT_MODULE_FETCH_LIMIT_BYTES = 512 * 1024 * 1024
AGENT_MODULE_KEY_DIGEST_CHARS = 16
AGENT_MODULE_GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"

# The hub's own agent packages, which are not third-party modules: the hub's
# package lands the builds it was made with here, and a platform it carries
# none for is fetched from the release the manifest names. A file is named the
# way the release publishes it, so one name addresses a package here, in the
# manifest and in the release.
AGENT_PACKAGE_CACHE_DIR = UTILS_STATE_ROOT / "agent_cache"

# Per platform key, ``{name, url, sha256, size}``. Stamped by the build that
# seeded the cache: a release stamps the URL its assets are published at, and
# a local build stamps none, which is what makes a platform it did not seed
# refuse rather than reach for a file nobody published.
AGENT_PACKAGE_MANIFEST_NAME = "agent_packages.json"
AGENT_PACKAGE_MANIFEST_PATH = UTILS_DATA_DIR / AGENT_PACKAGE_MANIFEST_NAME

# Our own release asset over plain HTTP, pinned by the manifest's hash. The
# ceiling is what one agent package can weigh many times over; it exists so a
# mirror serving something endless cannot fill the panel's memory.
AGENT_PACKAGE_FETCH_TIMEOUT_S = 300
AGENT_PACKAGE_FETCH_LIMIT_BYTES = 256 * 1024 * 1024

# Browser headers cost nothing; GitHub's API refuses a request that carries
# no User-Agent at all.
AGENT_MODULE_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# What each package kind starts with, so a page served in a package's place is
# caught before anything hands it to an installer.
AGENT_MODULE_PACKAGE_MAGIC = {
    "deb": (b"!<arch>",),
    "rpm": (b"\xed\xab\xee\xdb",),
    "msi": (b"\xd0\xcf\x11\xe0",),
    "exe": (b"MZ",),
    "pkg": (b"xar!",),
    # A UDIF image opens with its compressor: zlib at any level, bzip2, or
    # the koly trailer when the image is uncompressed.
    "dmg": (
        b"koly",
        b"\x78\x01",
        b"\x78\x9c",
        b"\x78\xda",
        b"\x42\x5a\x68",
    ),
    "tar_binary": (b"\x1f\x8b", b"BZh", b"\xfd7zXZ"),
    "zip_binary": (b"PK\x03\x04",),
    "binary": (b"\x7fELF",),
}

# How long one order may stand handed-down before the controller stops
# waiting for the machine's word. An install can genuinely take minutes; an
# agent that went away mid-order must not hold its device's lock for ever.
AGENT_MODULE_ORDER_TIMEOUT_S = 30 * 60
# How many finished orders a device keeps, so the drawer can still show the
# install a person is asking about without holding every install ever run.
AGENT_MODULE_ORDER_HISTORY = 12
# What an agent reports back of a failed install. Enough to read the package
# manager's own complaint, bounded so a verbose failure cannot fill a beat.
AGENT_MODULE_OUTPUT_LIMIT_BYTES = 16 * 1024
# How many lines of an operation's output the heartbeat reply carries, the
# same tail the panel's journals show.
AGENT_OPERATION_OUTPUT_LINES = 200

# The modules a device hosts from the hub's desired state, in the order the
# agent applies them. One file per module under the device's directory.
DEVICE_MODULE_NAMES = ("zfs", "samba", "gitea", "podman")
# What ``config/devices/<dir>/modules.json`` is called, and the per-module
# files beside it. A device directory is its key with ``:`` written ``-``.
DEVICE_MODULES_FILE = "modules.json"
DEVICE_RDP_FILE = "rdp.json"
DEVICE_GITEA_SECRETS_FILE = "gitea_secrets.json"  # scan: allow
# The files a device directory may hold that are not a module's own.
DEVICE_DIR_FILES = (DEVICE_MODULES_FILE, DEVICE_RDP_FILE, DEVICE_GITEA_SECRETS_FILE)

# The remote desktop host every agent package carries, as the module report
# names it, and the two states its row can take.
DEVICE_RDP_MODULE = "rustdesk"
DEVICE_MODULE_STATE_INSTALLED = "installed"
DEVICE_MODULE_STATE_ABSENT = "absent"
# The seat password the hub generates for a device, sealed under the vault's
# data key and bound to the one thing it opens. As long as
# ``secrets.token_urlsafe(16)`` is, and letters and digits alone, so it
# survives being copied by hand into a client.
DEVICE_RDP_SEAT_PASSWORD_AAD = b"device_rdp:seat_password"
DEVICE_RDP_SEAT_PASSWORD_CHARS = 22

# Machine secrets Gitea's app.ini needs, generated once per device by the
# hub and handed down in the desired configuration.
DEVICE_GITEA_SECRET_NAMES = (
    "SECRET_KEY",
    "INTERNAL_TOKEN",
    "JWT_SECRET",
    "LFS_JWT_SECRET",
)

# How long a panel route waits on an agent to check a configuration or run
# a command before answering that the machine never reported.
DEVICE_MODULE_VALIDATE_TIMEOUT_S = 30.0
DEVICE_MODULE_COMMAND_TIMEOUT_S = 120.0
# How long a file listing or one small file operation may take on the
# agent before the route answers that the machine never reported.
DEVICE_FILE_OP_TIMEOUT_S = 30.0

# The user-tier remote desktops the agent reads and sets up.
DEVICE_REMOTE_DESKTOP_PRODUCTS = ("anydesk", "teamviewer")
