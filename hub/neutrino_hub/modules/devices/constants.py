from neutrino_hub.utils.constants import UTILS_STATE_ROOT

# What a device is addressed by, everywhere. Six hexadecimal pairs, colon or
# hyphen separated, in any case; the registry lowercases and normalises on the
# way in. Anything else is not an address this box can wake, pin a host key
# against, or match a scan to, so it is refused rather than stored.
DEVICE_MAC_PATTERN = r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$"

DEVICE_LAN_SCAN_TIMEOUT_S = 30
# How long an agent's last heartbeat still counts as "reporting". It beats
# every five seconds, so this is several missed beats rather than one.
DEVICE_AGENT_ONLINE_WINDOW_S = 30

# The shape of what crosses the agent channel. Must match the agent's own
# AGENT_WIRE_GENERATION; a beat carrying another number is answered with
# agent_wire_stale so the agent reinstalls itself.
AGENT_WIRE_GENERATION = 4
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
AGENT_MODULE_CACHE_DIR = UTILS_STATE_ROOT / "agent_modules"
AGENT_MODULE_FETCH_TIMEOUT_S = 300
AGENT_MODULE_FETCH_LIMIT_BYTES = 512 * 1024 * 1024
AGENT_MODULE_KEY_DIGEST_CHARS = 16
AGENT_MODULE_GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"

# What the copyleft licenses oblige beside a binary the hub conveys: the
# corresponding source, kept next to the artifact under this suffix. A
# manifest naming ``source_archive`` is fetched with its binary and neither
# is served without the other.
AGENT_MODULE_SOURCE_SUFFIX = ".source"

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
