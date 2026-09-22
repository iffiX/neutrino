from neutrino_hub.utils.constants import UTILS_DATA_DIR, UTILS_STATE_ROOT

# What a reported or scanned MAC has to look like to be stored on a device:
# six hexadecimal pairs, colon or hyphen separated, in any case. The registry
# lowercases and writes colons on the way in.
DEVICE_MAC_PATTERN = r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$"
# The id a scan row no device claims is shown under, followed by its MAC. A
# person acting on the row gives it an id of its own.
DEVICE_SCAN_ID_PREFIX = "scan:"
# The directory under ``config/devices/`` holding hand-pinned agent builds;
# the only entry there that is not a device's own directory.
DEVICE_PACKAGES_DIR_NAME = "packages"

DEVICE_LAN_SCAN_TIMEOUT_S = 30
# How long a machine's last report still stands for what it declared: a
# desktop share outlives the report that made it by this much.
DEVICE_AGENT_ONLINE_WINDOW_S = 30

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
# manages it, so no ``want`` is ever written for a user-tier module.
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

# The modules a device hosts from the hub's desired state, in the order the
# agent applies them. One file per module under the device's directory.
DEVICE_MODULE_NAMES = ("zfs", "samba", "gitea", "podman")
# What ``config/devices/<id>/modules.json`` is called, and the per-module
# files beside it. A device directory is named by the device's id.
DEVICE_MODULES_FILE = "modules.json"
DEVICE_RDP_FILE = "rdp.json"
DEVICE_GITEA_SECRETS_FILE = "gitea_secrets.json"  # scan: allow
# The files a device directory may hold that are not a module's own.
DEVICE_DIR_FILES = (DEVICE_MODULES_FILE, DEVICE_RDP_FILE, DEVICE_GITEA_SECRETS_FILE)

# The module whose configuration is the hub's own secrets and nothing the
# machine can be read for.
DEVICE_GITEA_MODULE = "gitea"
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
# How long a route waits, after a command took, for the report the agent
# sends at once behind it. The agent's heartbeat is five seconds, so a
# report arrives inside this even when the command changed nothing.
DEVICE_MODULE_REPORT_WAIT_S = 6.0
# How long a file listing or one small file operation may take on the
# agent before the route answers that the machine never reported.
DEVICE_FILE_OP_TIMEOUT_S = 30.0

# The user-tier remote desktops the agent reads and sets up.
DEVICE_REMOTE_DESKTOP_PRODUCTS = ("anydesk", "teamviewer")

# What the panel answers with when pasted key material cannot be used; the
# wording is the panel's.
DEVICE_KEY_ERROR_NOTHING_PASTED = "key_nothing_pasted"
DEVICE_KEY_ERROR_IS_PUBLIC = "key_is_public"
DEVICE_KEY_ERROR_NOT_A_PRIVATE_KEY = "key_not_a_private_key"
DEVICE_KEY_ERROR_NO_BCRYPT = "key_encryption_unsupported"
DEVICE_KEY_ERROR_PASSPHRASE_WRONG = "key_passphrase_wrong"
DEVICE_KEY_ERROR_PASSPHRASE_NEEDED = "key_passphrase_needed"
DEVICE_KEY_ERROR_UNREADABLE = "key_unreadable"
