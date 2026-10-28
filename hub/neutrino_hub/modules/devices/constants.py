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
# The widest network a LAN scan covers whole, 256 addresses; of a wider one
# it covers the network of this prefix that holds the hub's own address.
DEVICE_LAN_SCAN_PREFIX_MIN = 24
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

# How a module is installed on a machine, by the method its platform entry
# names (design/agent/module_install.md, "Install methods"): the agent's own
# package, software the system holds, the system's package manager, the hub's
# cache, or container images.
DEVICE_METHOD_AGENT = "agent"
DEVICE_METHOD_BUILTIN = "builtin"
DEVICE_METHOD_SYSTEM = "system"
DEVICE_METHOD_HUB = "hub"
DEVICE_METHOD_CONTAINER = "container"
# The order both surfaces draw the modules in, by the first method a
# manifest names: what the agent carries, what the system holds or installs,
# what the hub's cache fetches, then container images.
DEVICE_METHOD_RANKS = {
    DEVICE_METHOD_AGENT: 0,
    DEVICE_METHOD_BUILTIN: 1,
    DEVICE_METHOD_SYSTEM: 1,
    DEVICE_METHOD_HUB: 2,
    DEVICE_METHOD_CONTAINER: 3,
}
# The methods whose entry the catalog shows a licence and a source address for.
DEVICE_METHODS_WITH_LICENSE = (DEVICE_METHOD_HUB, DEVICE_METHOD_CONTAINER)
# The version a system entry names: the system's own.
DEVICE_SYSTEM_VERSION = "system"
# The systems a platform key starts with.
DEVICE_PLATFORM_OS = ("linux", "windows", "darwin")
# The artifact kinds the hub's cache fetches, those of them kept under a
# directory of their own, and the two kinds the machine fetches itself.
DEVICE_ARTIFACT_FILE_KINDS = (
    "tar_gz",
    "zip",
    "dmg",
    "nsis",
    "binary",
    "msi",
    "pkg",
    "tar_zst",
    "raw_zst",
)
DEVICE_ARTIFACT_DIRECTORY_KINDS = ("msi", "pkg", "tar_zst", "raw_zst")
# The kind that names ``member``, the folder a macOS disk image holds the
# program in.
DEVICE_ARTIFACT_KIND_DMG = "dmg"
DEVICE_ARTIFACT_KIND_NPM = "npm"
DEVICE_ARTIFACT_KIND_IMAGE = "image"
# A source set's name, and a variable its ecosystem's tools read the
# address from (design/agent/module_install.md, "Source sets").
DEVICE_SOURCE_SET_NAME_PATTERN = r"[a-z][a-z0-9_]*"
DEVICE_SOURCE_SET_VARIABLE_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"
# The state's section of the source sets its recipes name.
DEVICE_SOURCE_SETS_KEY = "source_sets"
# The keys each kind of release feed names beside ``kind`` and ``sources``.
DEVICE_FEED_KEYS = {
    "github": ("repository", "tag"),
    "vscode_update": ("platform",),
    "oci": ("repository", "tag"),
    "npm": ("package",),
}

# The agent module cache: the files a module's installer fetches for managed
# machines, each named by its digest. The ceiling exists so a source serving
# something endless cannot fill the hub's disk; Podman's machine image for
# applehv runs past 1 GB.
AGENT_MODULE_CACHE_DIR = UTILS_STATE_ROOT / "agent_module_cache"
AGENT_MODULE_FETCH_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
# A ``package`` stream's progress line is written every this many percent, or
# after this many seconds when the percent moves slower.
AGENT_MODULE_PROGRESS_PERCENT_STEP = 5
AGENT_MODULE_PROGRESS_INTERVAL_S = 2.0

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

# The largest agent package the hub takes from a release site; it exists so a
# source serving something endless cannot fill the hub's disk.
AGENT_PACKAGE_FETCH_LIMIT_BYTES = 256 * 1024 * 1024

# What each artifact kind starts with, so a page served in a file's place is
# never kept: a Windows Installer package, a macOS installer package, a gzip
# stream, a zip, a release binary (ELF, a 64-bit Mach-O or PE), a zstd frame
# and an NSIS installer, a PE program.
AGENT_MODULE_PACKAGE_MAGIC = {
    "msi": (b"\xd0\xcf\x11\xe0",),
    "pkg": (b"xar!",),
    "tar_gz": (b"\x1f\x8b",),
    "zip": (b"PK\x03\x04",),
    "binary": (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"MZ"),
    "tar_zst": (b"\x28\xb5\x2f\xfd",),
    "raw_zst": (b"\x28\xb5\x2f\xfd",),
    "nsis": (b"MZ",),
}
# What a kind's last bytes start with where its head names nothing: a macOS
# disk image ends with its 512-byte trailer, which opens with ``koly``.
AGENT_MODULE_PACKAGE_TAIL_MAGIC = {"dmg": b"koly"}
AGENT_MODULE_PACKAGE_TAIL_BYTES = 512

# The five kinds of device module the description table sorts every module
# into: carried by the agent's own package, installed from the system's own
# sources, a service with a system account of its own, a program run as a
# person's account, and container images run on the Containers module.
DEVICE_MODULE_KIND_AGENT = "agent"
DEVICE_MODULE_KIND_SYSTEM_PACKAGE = "system_package"
DEVICE_MODULE_KIND_SERVICE_ACCOUNT = "service_account"
DEVICE_MODULE_KIND_ACCOUNT_PROGRAM = "account_program"
DEVICE_MODULE_KIND_CONTAINER = "container"
DEVICE_MODULE_KINDS = (
    DEVICE_MODULE_KIND_AGENT,
    DEVICE_MODULE_KIND_SYSTEM_PACKAGE,
    DEVICE_MODULE_KIND_SERVICE_ACCOUNT,
    DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
    DEVICE_MODULE_KIND_CONTAINER,
)
# The panel the Modules page draws every program run as an account with;
# every other module is drawn by a panel named after it.
DEVICE_MODULE_PANEL_INSTANCES = "instances"
# The key an instance of a program run as an account holds its vault login
# under, the login a Windows machine runs the instance as.
DEVICE_INSTANCE_LOGIN_KEY = "login_id"

# The modules a device hosts from the hub's desired state, in the order the
# agent applies them, the SSH server the agent carries among them. One file
# per module under the device's directory.
DEVICE_MODULE_NAMES = (
    "samba",
    "ssh_server",
    "gitea",
    "podman",
    "hermes_webui",
    "ayakaleaf",
    "vscode",
    "code_server",
    "cloudcli",
    "codeg",
    "siyuan",
)
# The directory under ``config/`` that holds one directory per device.
DEVICE_CONFIG_DIR_NAME = "devices"
# What ``config/devices/<id>/modules.json`` is called, and the per-module
# files beside it. A device directory is named by the device's id.
DEVICE_MODULES_FILE = "modules.json"
DEVICE_RDP_FILE = "rdp.json"
DEVICE_GITEA_SECRETS_FILE = "gitea_secrets.json"  # scan: allow
# The machine's available accounts, the account layer's one form per account
# (agent.md, "The two layers and the accounts"): the name the file takes
# beside the modules' own, and each row's fields.
DEVICE_ACCOUNTS_NAME = "accounts"
DEVICE_ACCOUNTS_FILE = f"{DEVICE_ACCOUNTS_NAME}.json"
DEVICE_ACCOUNT_FIELDS = (
    "account",
    "login_id",
    "share_path",
    "shell_path",
    "is_ai_tools_enabled",
    "tool_configs",
)
# The key the machine's AI tools setting takes in the state and in the
# retry marks; the setting itself is each account's switch.
DEVICE_AI_TOOLS_NAME = "ai_tools"
# The 0.5 file of the machine-wide AI tools setting, read once at the first
# start to move its switch onto each account.
DEVICE_AI_TOOLS_FILE = f"{DEVICE_AI_TOOLS_NAME}.json"
# The files a device directory may hold that are not a module's own.
DEVICE_DIR_FILES = (
    DEVICE_MODULES_FILE,
    DEVICE_RDP_FILE,
    DEVICE_GITEA_SECRETS_FILE,
    DEVICE_ACCOUNTS_FILE,
)
# The key an account-layer module's file holds its enabled accounts under,
# and the one its records of accounts disabled since keep their secrets
# under, so a toggle keeps a login a browser or a client holds.
DEVICE_ENABLED_ACCOUNTS_KEY = "accounts"
DEVICE_DISABLED_ACCOUNTS_KEY = "disabled"

# The module whose configuration is the hub's own secrets and nothing the
# machine can be read for.
DEVICE_GITEA_MODULE = "gitea"
# VS Code in the browser. Each instance in its file under the device's
# directory holds, beside its account and port, two keys the hub keeps there:
# its connection token sealed under the vault's data key, and the vault login
# a Windows machine runs it as. A token's seal is bound to what it opens, and
# a fresh token is this many random bytes.
DEVICE_VSCODE_MODULE = "vscode"
DEVICE_VSCODE_TOKEN_KEY = "token_sealed"  # scan: allow
DEVICE_VSCODE_TOKEN_AAD = b"device_vscode:token"
DEVICE_VSCODE_TOKEN_BYTES = 24
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
# The program the agent runs as each account to switch its AI tools, which
# the hub pins in data/manifests/cc_switch.json and serves on the package
# stream.
DEVICE_AI_SWITCHER_NAME = "cc_switch"
# code-server, once per account. Each instance in its file holds, beside its
# account and port, the secret its tokens are signed with, which the hub
# generates once and keeps sealed.
DEVICE_CODE_SERVER_MODULE = "code_server"
# The three modules the agent's package carries, each composed from its own
# file under the device's directory and sent to every managed device. The
# Terminal module's file holds its enabled accounts, and so does the SSH
# server's, whose ``want`` is running while it enables one; the Remote
# desktop module's switch is its ``want``: running while on, stopped while
# off.
DEVICE_TERMINAL_MODULE = "terminal"
DEVICE_REMOTE_DESKTOP_MODULE = "remote_desktop"
DEVICE_SSH_SERVER_MODULE = "ssh_server"
DEVICE_AGENT_MODULES = (
    DEVICE_TERMINAL_MODULE,
    DEVICE_REMOTE_DESKTOP_MODULE,
    DEVICE_SSH_SERVER_MODULE,
)
# The system whose accounts start a process only with their password, so
# every feature of an account there is sent the account's login.
DEVICE_PASSWORD_OS = "windows"
# A module's per-account data directory on each system (module_template.md,
# "Disk layout"). An uninstall line's ``{data_dir}`` names it. A machine that
# has not reported its system takes the Linux one.
DEVICE_ACCOUNT_DATA_DIRS = {
    "linux": "~/.local/share/neutrino/agent/{module}/",
    "darwin": "~/Library/Application Support/Neutrino/agent/{module}/",
    "windows": "%LOCALAPPDATA%\\Neutrino\\agent\\{module}\\",
}
DEVICE_ACCOUNT_DATA_DIR_DEFAULT_OS = "linux"
# The file share's SMB user of an enabled account (agent.md, "The file
# share's accounts"): ``neutrino-<account>`` on every system, cut to 20
# characters on Windows; its generated password, 24 random bytes in
# base64url, sealed in samba.json under this key.
DEVICE_SAMBA_MODULE = "samba"
DEVICE_SAMBA_USER_PREFIX = "neutrino-"
DEVICE_SAMBA_USER_CHARS_MAX = 20
DEVICE_SAMBA_USER_CUT_OS = ("windows",)
# The folder shares in samba.json, each ``{name, path, accounts}``, the
# accounts among the enabled ones (file_share.md). A name is 1 to 64
# letters, digits, ``-``, ``_`` and ``.``, none of smb.conf's own sections,
# compared without case.
DEVICE_SAMBA_SHARES_KEY = "shares"
DEVICE_FOLDER_SHARE_NAME_PATTERN = r"[A-Za-z0-9._-]{1,64}"
DEVICE_FOLDER_SHARE_RESERVED_NAMES = ("global", "homes", "printers")
DEVICE_SAMBA_PASSWORD_KEY = "password_sealed"  # scan: allow
DEVICE_SAMBA_PASSWORD_AAD = b"device_samba:password"
DEVICE_SAMBA_PASSWORD_BYTES = 24
# The SSH server's key for an enabled account, one Ed25519 pair per account
# and machine: the private half sealed in ssh_server.json under this key,
# the public half the instance's one authorized key.
DEVICE_SSH_SERVER_KEY_KEY = "private_key_sealed"  # scan: allow
DEVICE_SSH_SERVER_KEY_AAD = b"device_ssh_server:private_key"
DEVICE_SSH_SERVER_KEY_COMMENT = "neutrino"
# Where the module versions feature keeps the publishers' feeds as last read
# (module_install.md, "Module versions"), how often it reads them, and what
# a feed answer may weigh.
DEVICE_MODULE_RELEASES_PATH = UTILS_STATE_ROOT / "module_releases.json"
DEVICE_MODULE_RELEASES_INTERVAL_S = 24 * 60 * 60
DEVICE_MODULE_RELEASES_VERSIONS_MAX = 50
# The systems whose containers run in an account's Podman machine; only these
# are sent the Run settings, ``machine`` in ``podman.json``.
DEVICE_PODMAN_MACHINE_OS = ("windows", "darwin")
DEVICE_PODMAN_MACHINE_KEY = "machine"
# The key a guest_account module's state holds its guests under, and the
# fields of each guest.
DEVICE_GUESTS_KEY = "guests"
DEVICE_GUEST_FIELDS = ("account", "email", "password", "secret")
# The Containers module, which runs every container module's containers; the
# key its state holds them under, the start of every name the hub keeps for
# them, and the declared containers' key in ``podman.json``.
DEVICE_PODMAN_MODULE = "podman"
DEVICE_HUB_CONTAINERS_KEY = "hub_containers"
DEVICE_HUB_CONTAINER_PREFIX = "neutrino_"
# The longest stop timeout a hub container may name, as the agent takes it,
# and the highest exit code there is.
DEVICE_HUB_CONTAINER_STOP_MAX_S = 3600
DEVICE_HUB_CONTAINER_EXIT_CODE_MAX = 255
DEVICE_PODMAN_CONTAINERS_KEY = "containers"
# The key a container module that uses the AI gateway keeps its own gateway
# key under, in its file under the device's directory: the key's record,
# sealed as the gateway's own keys are, and labelled
# ``device/<device>/<module>``.
DEVICE_MODULE_GATEWAY_KEY = "gateway_key"
DEVICE_MODULE_GATEWAY_LABEL = "device/{device}/{module}"
# Where a container reaches the AI gateway: the agent's forward on a managed
# machine, the gateway's own port on the hub's machine, relayed to the
# container.
DEVICE_CONTAINER_GATEWAY_URL = "http://host.containers.internal:{port}"
DEVICE_CONTAINER_GATEWAY_FORWARD_PORT = 8317
# Hermes WebUI: two hub containers, the agent's gateway and the webui. Its
# file under the device's directory holds two secrets the hub generates once
# and keeps sealed, the token secret and the webui's password, and the
# module's gateway key; the forwarder's port is the agent's.
DEVICE_HERMES_WEBUI_MODULE = "hermes_webui"
DEVICE_HERMES_WEBUI_SECRET_KEY = "secret_sealed"  # scan: allow
DEVICE_HERMES_WEBUI_PASSWORD_KEY = "password_sealed"  # scan: allow
DEVICE_HERMES_WEBUI_SECRET_AAD = b"device_hermes_webui:secret"
DEVICE_HERMES_WEBUI_PASSWORD_AAD = b"device_hermes_webui:password"
DEVICE_HERMES_WEBUI_SECRET_BYTES = 32
# Its two containers, the images they run by artifact name, and what each
# mounts and is given. Both images rename their user to uid and gid 1024,
# and the webui's 8787 is the port its forwarder serves.
DEVICE_HERMES_WEBUI_AGENT_CONTAINER = "neutrino_hermes_webui_agent"
DEVICE_HERMES_WEBUI_WEBUI_CONTAINER = "neutrino_hermes_webui"
DEVICE_HERMES_WEBUI_AGENT_IMAGE = "agent"
DEVICE_HERMES_WEBUI_WEBUI_IMAGE = "webui"
DEVICE_HERMES_WEBUI_AGENT_COMMAND = "gateway run"
DEVICE_HERMES_WEBUI_PAGE_PORT = 8787
DEVICE_HERMES_WEBUI_UID = 1024
DEVICE_HERMES_WEBUI_AGENT_VOLUMES = (
    "neutrino_hermes_webui_home:/opt/data",
    "neutrino_hermes_webui_agent:/opt/hermes",
)
DEVICE_HERMES_WEBUI_WEBUI_VOLUMES = (
    "neutrino_hermes_webui_home:/home/hermeswebui/.hermes",
    "neutrino_hermes_webui_workspace:/workspace",
    "neutrino_hermes_webui_agent:/home/hermeswebui/.hermes/hermes-agent:ro",
    "neutrino_hermes_webui_app:/app",
)
DEVICE_HERMES_WEBUI_STATE_DIR = "/home/hermeswebui/.hermes/webui"
# The webui's login cookie: its name on each device is this prefix and the
# first characters of the device id, so the pages of two devices open in one
# browser keep their own logins.
DEVICE_HERMES_WEBUI_COOKIE_PREFIX = "hermes_session_"
DEVICE_HERMES_WEBUI_COOKIE_ID_CHARS = 12
# Ayakaleaf: three hub containers, the app, MongoDB and Redis. Its file under
# the device's directory holds four secrets the hub generates once and keeps
# sealed, the token secret, the administrator's password and the app's
# session and invitation secrets, the module's gateway key and the tab's AI
# model; the forwarder's port is the agent's.
DEVICE_AYAKALEAF_MODULE = "ayakaleaf"
DEVICE_AYAKALEAF_SECRET_KEY = "secret_sealed"  # scan: allow
DEVICE_AYAKALEAF_PASSWORD_KEY = "password_sealed"  # scan: allow
DEVICE_AYAKALEAF_SESSION_SECRET_KEY = "session_secret_sealed"  # scan: allow
DEVICE_AYAKALEAF_INVITE_SECRET_KEY = "invite_secret_sealed"  # scan: allow
DEVICE_AYAKALEAF_SECRET_AAD = b"device_ayakaleaf:secret"
DEVICE_AYAKALEAF_PASSWORD_AAD = b"device_ayakaleaf:password"
DEVICE_AYAKALEAF_SESSION_SECRET_AAD = b"device_ayakaleaf:session_secret"
DEVICE_AYAKALEAF_INVITE_SECRET_AAD = b"device_ayakaleaf:invite_secret"
DEVICE_AYAKALEAF_SECRET_BYTES = 32
DEVICE_AYAKALEAF_MODEL_KEY = "model"
# Its three containers, the images they run by artifact name, and what each
# mounts, runs and is given. The app's 80 is the port its forwarder serves,
# and its stop flushes the open edits for about 19 seconds.
DEVICE_AYAKALEAF_APP_CONTAINER = "neutrino_ayakaleaf"
DEVICE_AYAKALEAF_MONGO_CONTAINER = "neutrino_ayakaleaf_mongo"
DEVICE_AYAKALEAF_REDIS_CONTAINER = "neutrino_ayakaleaf_redis"
DEVICE_AYAKALEAF_APP_IMAGE = "app"
DEVICE_AYAKALEAF_MONGO_IMAGE = "mongo"
DEVICE_AYAKALEAF_REDIS_IMAGE = "redis"
DEVICE_AYAKALEAF_MONGO_COMMAND = "--replSet overleaf"
DEVICE_AYAKALEAF_REDIS_COMMAND = "redis-server --appendonly yes"
DEVICE_AYAKALEAF_PAGE_PORT = 80
DEVICE_AYAKALEAF_APP_STOP_TIMEOUT_S = 60
# The app exits 2 on the stop's SIGTERM once its flush has ended.
DEVICE_AYAKALEAF_APP_SUCCESS_EXIT_CODES = (2,)
DEVICE_AYAKALEAF_APP_VOLUMES = (
    "neutrino_ayakaleaf_data:/var/lib/overleaf",
    "neutrino_ayakaleaf_texlive:/usr/local/texlive",
)
DEVICE_AYAKALEAF_MONGO_VOLUMES = ("neutrino_ayakaleaf_mongo:/data/db",)
DEVICE_AYAKALEAF_REDIS_VOLUMES = ("neutrino_ayakaleaf_redis:/data",)
# The app's fixed environment; the secrets, the cookie's name and the
# gateway's variables are composed per device.
DEVICE_AYAKALEAF_APP_ENVIRONMENT = (
    "OVERLEAF_MONGO_URL=mongodb://neutrino_ayakaleaf_mongo/sharelatex",
    "OVERLEAF_REDIS_HOST=neutrino_ayakaleaf_redis",  # scan: allow
    "REDIS_HOST=neutrino_ayakaleaf_redis",
    "REDIS_PORT=6379",
    "V1_HISTORY_URL=http://127.0.0.1:3100/api",
    "GIT_BRIDGE_ENABLED=false",
    "EMAIL_CONFIRMATION_DISABLED=true",
    "DOCS_MCP_URL=",
)
# The app's session cookie: its name on each device is this prefix and the
# first characters of the device id, so the pages of two devices open in one
# browser keep their own logins.
DEVICE_AYAKALEAF_COOKIE_PREFIX = "ayakaleaf_sid_"
DEVICE_AYAKALEAF_COOKIE_ID_CHARS = 12
# The suffix the gateway's address takes in the app's ``AI_BASE_URL``.
DEVICE_AYAKALEAF_AI_PATH = "/v1"
# Where a container comes from, by the owner rule: the label, the declared
# names, else a person's own.
DEVICE_CONTAINER_SOURCE_HUB = "hub"
DEVICE_CONTAINER_SOURCE_DECLARED = "declared"
DEVICE_CONTAINER_SOURCE_MANUAL = "manual"
DEVICE_CODE_SERVER_SECRET_KEY = "secret_sealed"  # scan: allow
DEVICE_CODE_SERVER_SECRET_AAD = b"device_code_server:secret"
DEVICE_CODE_SERVER_SECRET_BYTES = 32
# Codeg, once per account. Each instance in its file holds, beside its
# account and port, the vault login a Windows machine runs it as and the
# secret its tokens are signed with, which the hub generates once and keeps
# sealed.
DEVICE_CODEG_MODULE = "codeg"
DEVICE_CODEG_SECRET_KEY = "secret_sealed"  # scan: allow
DEVICE_CODEG_SECRET_AAD = b"device_codeg:secret"
DEVICE_CODEG_SECRET_BYTES = 32
# SiYuan, once per account. Each enabled account's record holds, beside the
# account, the secret its tokens are signed with and the kernel's access
# code, which the hub generates once and keeps sealed, and while the account
# is enabled its own key to the AI gateway, the key's record sealed as the
# gateway's own keys are and labelled ``device/<device>/siyuan/<account>``.
DEVICE_SIYUAN_MODULE = "siyuan"
DEVICE_SIYUAN_SECRET_KEY = "secret_sealed"  # scan: allow
DEVICE_SIYUAN_SECRET_AAD = b"device_siyuan:secret"
DEVICE_SIYUAN_ACCESS_CODE_KEY = "access_code_sealed"  # scan: allow
DEVICE_SIYUAN_ACCESS_CODE_AAD = b"device_siyuan:access_code"
DEVICE_SIYUAN_SECRET_BYTES = 32
DEVICE_INSTANCE_GATEWAY_KEY = "gateway_key_sealed"  # scan: allow
DEVICE_INSTANCE_GATEWAY_LABEL = "device/{device}/{module}/{account}"
# Where a program run as an account reaches the AI gateway on a managed
# machine: the agent's forward on its loopback.
DEVICE_INSTANCE_GATEWAY_FORWARD_URL = "http://127.0.0.1:8317"
# A token a CloudCLI, code-server, Codeg or SiYuan instance's forwarder takes once:
# ``base64url(expiry || nonce || HMAC-SHA256(secret, expiry || nonce))``,
# the expiry eight bytes big-endian in seconds since the epoch, minted for
# one ``service`` answer; the agent's forwarder checks the same layout.
DEVICE_FORWARDER_TOKEN_LIFETIME_S = 60
DEVICE_FORWARDER_TOKEN_EXPIRY_BYTES = 8
DEVICE_FORWARDER_TOKEN_NONCE_BYTES = 16
# How a Web share's visitor is signed in to a module's page, as its
# manifest's ``web_share`` names it: the app's own login page, one account of
# the app per share, or the account the app runs as.
DEVICE_GUEST_LOGIN_APP = "app"
DEVICE_GUEST_LOGIN_GUEST_ACCOUNT = "guest_account"
DEVICE_GUEST_LOGIN_RUN_ACCOUNT = "run_account"
DEVICE_GUEST_LOGINS = (
    DEVICE_GUEST_LOGIN_APP,
    DEVICE_GUEST_LOGIN_GUEST_ACCOUNT,
    DEVICE_GUEST_LOGIN_RUN_ACCOUNT,
)
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

# The remote desktops a person installs themselves, which the Remote desktop
# module detects and the ``status`` command reads.
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

# The module catalog the machine page's Add module dialog draws, shipped in
# the package: every module by the activity it serves, in the dialog's order.
DEVICE_MODULE_CATALOG_PATH = UTILS_DATA_DIR / "module_catalog.json"
