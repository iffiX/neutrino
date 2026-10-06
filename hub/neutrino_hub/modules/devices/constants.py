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
# switches it. hub: the module's installer fetches an artifact and the
# agent installs it.
# user: the person installs it themselves and the hub only detects and
# manages it, so no ``want`` is ever written for a user-tier module.
# agent: the agent's own package carries it on every system; no branch
# names a platform, the hub composes its entry from its own file, and none
# of the four presses applies to it.
AGENT_MODULE_INSTALLER_TIERS = ("agent", "platform", "hub", "user")
AGENT_MODULE_INSTALLER_AGENT = "agent"
# A manifest that says ``is_module: false`` names a program the agent runs
# itself rather than a module: it stays out of the catalog, and each of its
# platform branches names these fields.
AGENT_TOOL_FIELDS = ("url", "cn_url", "sha256", "package_kind")
# What a ``cn_url`` names for the release this hub was built for: the
# address its build stamped for the agent packages, which the project's own
# release publishes beside them.
AGENT_MODULE_RELEASE_PLACEHOLDER = "{release}"
AGENT_MODULE_INSTALLER_USER = "user"
# A platform branch whose ``installer`` is this names software the system
# itself carries, such as Windows' and macOS's own SMB servers: nothing is
# downloaded or installed, and the agent's runner checks for it itself.
AGENT_MODULE_INSTALLER_BUILTIN = "builtin"
# The branch fields that say the module's installer fetches or installs
# something, none of which a builtin branch may name.
AGENT_MODULE_DOWNLOAD_FIELDS = (
    "url",
    "github_repo",
    "asset_pattern",
    "download",
    "package_kind",
    "packages",
    "pre_install",
)

# The agent module cache: what the hub presents when a module's installer
# fetches an artifact for a managed machine, and what it accepts back. The ceiling is generous —
# remote desktop packages run past 100 MB — and exists so a mirror serving
# something endless cannot fill the panel's memory.
AGENT_MODULE_CACHE_DIR = UTILS_STATE_ROOT / "agent_module_cache"
AGENT_MODULE_FETCH_TIMEOUT_S = 300
AGENT_MODULE_FETCH_LIMIT_BYTES = 512 * 1024 * 1024
AGENT_MODULE_KEY_DIGEST_CHARS = 16
AGENT_MODULE_FETCH_CHUNK_BYTES = 64 * 1024
# How much of a download's start is kept for the check of what kind of file
# it is.
AGENT_MODULE_HEAD_BYTES = 512
# A download's progress line is written every this many percent, or after
# this many seconds when the percent moves slower or the size is unknown.
AGENT_MODULE_PROGRESS_PERCENT_STEP = 5
AGENT_MODULE_PROGRESS_INTERVAL_S = 2.0
AGENT_MODULE_GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"
# The edition whose installer fetches from a manifest entry's ``cn_url``
# where the entry names one, and how much of a mirror's listing of its
# latest release is read.
AGENT_MODULE_EDITION_INTL = "intl"
AGENT_MODULE_EDITION_CN = "cn"
AGENT_MODULE_LISTING_LIMIT_BYTES = 1024 * 1024

# The hub's own agent packages, which are not third-party modules: the hub's
# package lands the one of its own platform here, and every other platform is
# fetched from the release the manifest names. A file is named the way the
# release publishes it, so one name addresses a package here, in the manifest
# and in the release.
AGENT_PACKAGE_CACHE_DIR = UTILS_STATE_ROOT / "agent_cache"

# The retry marks a press on a failed module puts into a device's state: one
# per module and device, under the state root, and the key each takes in the
# state. A mark is this many random bytes, written in hex.
DEVICE_RETRY_MARKS_PATH = UTILS_STATE_ROOT / "device_retry_marks.json"
DEVICE_RETRY_MARK_KEY = "retry_mark"
DEVICE_RETRY_MARK_BYTES = 8

# Per platform key, ``{name, url, sha256, size}``. Stamped by the build that
# seeded the cache: a release names every platform it publishes, with the URL
# and the hash of each, and a local build names the one it seeded alone, which
# is what makes another platform refuse rather than reach for a file nobody
# published.
AGENT_PACKAGE_MANIFEST_NAME = "agent_packages.json"
AGENT_PACKAGE_MANIFEST_PATH = UTILS_DATA_DIR / AGENT_PACKAGE_MANIFEST_NAME

# Our own release asset over plain HTTP, pinned by the manifest's hash. The
# ceiling is what one agent package can weigh many times over; it exists so a
# mirror serving something endless cannot fill the panel's memory.
AGENT_PACKAGE_FETCH_TIMEOUT_S = 300
AGENT_PACKAGE_FETCH_LIMIT_BYTES = 256 * 1024 * 1024

# The headers a module fetch carries: a program's own User-Agent, which
# GitHub's API requires one of, and no browser's. A mirror that answers a
# browser with a page of its own (the USTC mirror asks a browser to run a
# script before it serves a file) hands a program the file itself.
AGENT_MODULE_FETCH_HEADERS = {"User-Agent": "neutrino-hub"}

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
    # An archive the agent unpacks one member of: VS Code's CLI.
    "tar": (b"\x1f\x8b", b"BZh", b"\xfd7zXZ"),
    "zip": (b"PK\x03\x04",),
    # A release binary: ELF on Linux, a 64-bit Mach-O on macOS, PE on
    # Windows.
    "binary": (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"MZ"),
}

# The modules a device hosts from the hub's desired state, in the order the
# agent applies them. One file per module under the device's directory.
DEVICE_MODULE_NAMES = (
    "zfs",
    "samba",
    "gitea",
    "podman",
    "vscode",
    "code_server",
    "cloudcli",
)
# What ``config/devices/<id>/modules.json`` is called, and the per-module
# files beside it. A device directory is named by the device's id.
DEVICE_MODULES_FILE = "modules.json"
DEVICE_RDP_FILE = "rdp.json"
DEVICE_GITEA_SECRETS_FILE = "gitea_secrets.json"  # scan: allow
# The machine's AI tools setting, read and written by the name its file
# takes beside the modules' own: whether its tools use the hub's gateway, and
# the tool configuration the client's Configure dialog saves.
DEVICE_AI_TOOLS_NAME = "ai_tools"
DEVICE_AI_TOOLS_FILE = f"{DEVICE_AI_TOOLS_NAME}.json"
# The files a device directory may hold that are not a module's own.
DEVICE_DIR_FILES = (
    DEVICE_MODULES_FILE,
    DEVICE_RDP_FILE,
    DEVICE_GITEA_SECRETS_FILE,
    DEVICE_AI_TOOLS_FILE,
)

# The module whose configuration is the hub's own secrets and nothing the
# machine can be read for.
DEVICE_GITEA_MODULE = "gitea"
# VS Code in the browser. Each instance in its file under the device's
# directory holds, beside its account and port, two keys the hub keeps there:
# its connection token sealed under the vault's data key, and the vault login
# a Windows machine runs it as. A token's seal is bound to what it opens.
DEVICE_VSCODE_MODULE = "vscode"
DEVICE_VSCODE_TOKEN_KEY = "token_sealed"  # scan: allow
DEVICE_VSCODE_LOGIN_KEY = "login_id"
DEVICE_VSCODE_TOKEN_AAD = b"device_vscode:token"
# When the person accepted Microsoft's VS Code Server license terms for the
# machine, an ISO 8601 time in the same file; absent until they do. The
# address of those terms, as the VS Code CLI names it.
DEVICE_VSCODE_TERMS_KEY = "terms_accepted_at"
DEVICE_VSCODE_TERMS_URL = "https://aka.ms/vscode-server-license"
# CloudCLI, once per account. Each instance in its file holds, beside its
# account and port, the vault login a Windows machine runs it as and two
# secrets the hub generates once and keeps sealed: the password CloudCLI's
# administrator signs in with, and the secret the instance's tokens are
# signed with.
DEVICE_CLOUDCLI_MODULE = "cloudcli"
# The npm registry each edition's agents install CloudCLI from.
DEVICE_CLOUDCLI_NPM_REGISTRIES = {
    "intl": "https://registry.npmjs.org",
    "cn": "https://registry.npmmirror.com",
}
DEVICE_CLOUDCLI_LOGIN_KEY = "login_id"
DEVICE_CLOUDCLI_PASSWORD_KEY = "web_password_sealed"  # scan: allow
DEVICE_CLOUDCLI_SECRET_KEY = "token_secret_sealed"  # scan: allow
DEVICE_CLOUDCLI_PASSWORD_AAD = b"device_cloudcli:web_password"
DEVICE_CLOUDCLI_SECRET_AAD = b"device_cloudcli:token_secret"
DEVICE_CLOUDCLI_SECRET_BYTES = 32
# The tools and the knobs of each the AI tools setting holds, the client's
# own: Claude Code's four role slots, Codex's model and reasoning effort,
# Gemini's model.
DEVICE_AI_CLAUDE_SLOTS = ("default", "opus", "sonnet", "haiku")
DEVICE_AI_TOOL_CONFIG_KEYS = {
    "claude": DEVICE_AI_CLAUDE_SLOTS,
    "codex": ("model", "model_reasoning_effort"),
    "gemini": ("model",),
}
DEVICE_AI_REASONING_EFFORT_KEY = "model_reasoning_effort"
DEVICE_AI_REASONING_EFFORTS = ("minimal", "low", "medium", "high")
# The modules whose instances name the accounts the setting acts on, in the
# order an account's Windows login is taken from.
DEVICE_AI_TOOL_MODULES = ("vscode", "cloudcli", "code_server")
# The program the agent runs as each account to switch its AI tools, which
# the hub pins in data/manifests/cc_switch.json and serves on the package
# stream.
DEVICE_AI_SWITCHER_NAME = "cc_switch"
# code-server, once per account. Each instance in its file holds, beside its
# account and port, the secret its tokens are signed with, which the hub
# generates once and keeps sealed.
DEVICE_CODE_SERVER_MODULE = "code_server"
# The two modules the agent's package carries, each composed from its own
# file under the device's directory and sent to every managed device. The
# Terminal module's settings name the account a shell runs as and its shell
# program, both empty for the default; a Windows machine is sent no account.
# The Remote desktop module's switch is its ``want``: running while on,
# stopped while off.
DEVICE_TERMINAL_MODULE = "terminal"
DEVICE_REMOTE_DESKTOP_MODULE = "remote_desktop"
DEVICE_AGENT_MODULES = (DEVICE_TERMINAL_MODULE, DEVICE_REMOTE_DESKTOP_MODULE)
DEVICE_TERMINAL_ACCOUNT_OS = ("linux", "darwin")
DEVICE_CODE_SERVER_SECRET_KEY = "secret_sealed"  # scan: allow
DEVICE_CODE_SERVER_SECRET_AAD = b"device_code_server:secret"
DEVICE_CODE_SERVER_SECRET_BYTES = 32
# A token a CloudCLI or code-server instance's forwarder takes once:
# ``base64url(expiry || nonce || HMAC-SHA256(secret, expiry || nonce))``,
# the expiry eight bytes big-endian in seconds since the epoch, minted for
# one ``service`` answer; the agent's forwarder checks the same layout.
DEVICE_FORWARDER_TOKEN_LIFETIME_S = 60
DEVICE_FORWARDER_TOKEN_EXPIRY_BYTES = 8
DEVICE_FORWARDER_TOKEN_NONCE_BYTES = 16
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
