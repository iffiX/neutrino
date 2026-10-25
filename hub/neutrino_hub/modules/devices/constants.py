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
    "binary",
    "msi",
    "pkg",
    "tar_zst",
    "raw_zst",
)
DEVICE_ARTIFACT_DIRECTORY_KINDS = ("msi", "pkg", "tar_zst", "raw_zst")
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
# stream, a zip, a release binary (ELF, a 64-bit Mach-O or PE) and a zstd
# frame.
AGENT_MODULE_PACKAGE_MAGIC = {
    "msi": (b"\xd0\xcf\x11\xe0",),
    "pkg": (b"xar!",),
    "tar_gz": (b"\x1f\x8b",),
    "zip": (b"PK\x03\x04",),
    "binary": (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"MZ"),
    "tar_zst": (b"\x28\xb5\x2f\xfd",),
    "raw_zst": (b"\x28\xb5\x2f\xfd",),
}

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
# agent applies them. One file per module under the device's directory.
DEVICE_MODULE_NAMES = (
    "zfs",
    "samba",
    "gitea",
    "podman",
    "hermes_webui",
    "vscode",
    "code_server",
    "cloudcli",
    "codeg",
)
# The directory under ``config/`` that holds one directory per device.
DEVICE_CONFIG_DIR_NAME = "devices"
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
# The systems whose containers run in an account's Podman machine; only these
# are sent the Run settings, ``machine`` in ``podman.json``.
DEVICE_PODMAN_MACHINE_OS = ("windows", "darwin")
DEVICE_PODMAN_MACHINE_KEY = "machine"
# The Containers module, which runs every container module's containers; the
# key its state holds them under, the start of every name the hub keeps for
# them, and the declared containers' key in ``podman.json``.
DEVICE_PODMAN_MODULE = "podman"
DEVICE_HUB_CONTAINERS_KEY = "hub_containers"
DEVICE_HUB_CONTAINER_PREFIX = "neutrino_"
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
# file under the device's directory holds the forwarder's port, two secrets
# the hub generates once and keeps sealed, the token secret and the webui's
# password, and the module's gateway key.
DEVICE_HERMES_WEBUI_MODULE = "hermes_webui"
DEVICE_HERMES_WEBUI_DEFAULT_PORT = 8787
DEVICE_HERMES_WEBUI_PORT_MIN = 1024
DEVICE_HERMES_WEBUI_PORT_MAX = 65535
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
# A token a CloudCLI, code-server or Codeg instance's forwarder takes once:
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
