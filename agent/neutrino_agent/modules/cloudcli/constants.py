"""Fixed values of the CloudCLI module."""

# The recipe kind and the module's name on the wire.
CLOUDCLI_KIND = "cloudcli"
CLOUDCLI_NAME = "cloudcli"

# The npm package every instance runs, at the one version the hub pins.
CLOUDCLI_PACKAGE = "@cloudcli-ai/cloudcli"
CLOUDCLI_VERSION = "1.37.3"
# Where the package lands under an app directory, and the server it starts.
CLOUDCLI_PACKAGE_PARTS = ("node_modules", "@cloudcli-ai", "cloudcli")
CLOUDCLI_SERVER_PARTS = ("dist-server", "server", "index.js")
# The native modules npm fetches a prebuilt binary for during the install.
CLOUDCLI_NATIVE_MODULES = ("better-sqlite3", "node-pty", "bcrypt")

# The prefix of the one directory each Node.js archive the hub sends holds.
CLOUDCLI_NODE_PREFIX = "node-v"
# Inside that directory: the interpreter and npm, by system.
CLOUDCLI_NODE_PARTS = {
    "linux": ("bin", "node"),
    "darwin": ("bin", "node"),
    "windows": ("node.exe",),
}
CLOUDCLI_NPM_PARTS = {
    "linux": ("lib", "node_modules", "npm", "bin", "npm-cli.js"),
    "darwin": ("lib", "node_modules", "npm", "bin", "npm-cli.js"),
    "windows": ("node_modules", "npm", "bin", "npm-cli.js"),
}
# The module's directory under the agent's state root, where Node.js is, and
# under its configuration root, where the instances' records are.
CLOUDCLI_DIR_NAME = "cloudcli"

# Each account's own directory, under its home, by system: the app
# directory npm installs into is ``app`` inside it, and CloudCLI keeps its
# database beside it.
CLOUDCLI_ACCOUNT_PARTS = {
    "linux": (".local", "share", "neutrino", "agent", "cloudcli"),
    "darwin": ("Library", "Application Support", "Neutrino", "agent", "cloudcli"),
    "windows": ("AppData", "Local", "Neutrino", "agent", "cloudcli"),
}
CLOUDCLI_APP_DIR_NAME = "app"
CLOUDCLI_DATABASE_NAME = "auth.db"
# The database file an instance starts afresh on when its CloudCLI was set
# up for another hub, the old one left beside it; the time is UTC.
CLOUDCLI_FRESH_DATABASE_PATTERN = "auth-{stamp}.db"
CLOUDCLI_FRESH_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# Inside the app directory: npm's cache, and the empty file npm reads as the
# account's configuration instead of ``~/.npmrc``.
CLOUDCLI_NPM_CACHE_NAME = ".npm"
CLOUDCLI_NPM_USERCONFIG_NAME = ".npmrc"
# How long one account's install may take where the apply waits on it,
# and how long the task that runs it on Windows, where nothing waits, may run.
CLOUDCLI_INSTALL_TIMEOUT_S = 1800
CLOUDCLI_WINDOWS_INSTALL_LIMIT_S = 4 * 3600
# How long a check run as an account may take.
CLOUDCLI_LOOKUP_TIMEOUT_S = 30
# What a service's PATH holds after Node's directory: the account's usual
# command directories under its home, then the system's own.
CLOUDCLI_ACCOUNT_PATH_PARTS = (".local/bin", "bin")
CLOUDCLI_SYSTEM_PATH = {
    "linux": ("/usr/local/bin", "/usr/bin", "/bin"),
    "darwin": ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"),
}

# CloudCLI listens on loopback alone, on a port the agent picks.
CLOUDCLI_UPSTREAM_HOST = "127.0.0.1"
# The forwarder listens on loopback alone at the configured port, where the
# agent's end of a ``connect`` stream reaches it.
CLOUDCLI_LISTEN_HOST = "127.0.0.1"
CLOUDCLI_PORT_MIN = 1024
CLOUDCLI_PORT_MAX = 65535

# What CloudCLI 1.37.3 answers on: the first-run check, the two routes the
# forwarder never passes on, and where its page keeps the login.
CLOUDCLI_STATUS_PATH = "/api/auth/status"
CLOUDCLI_REGISTER_PATH = "/api/auth/register"
CLOUDCLI_LOGIN_PATH = "/api/auth/login"
CLOUDCLI_BLOCKED_PATHS = (CLOUDCLI_REGISTER_PATH, CLOUDCLI_LOGIN_PATH)
CLOUDCLI_STORAGE_KEY = "auth-token"
# The query parameter CloudCLI's page sends its login in on a WebSocket.
CLOUDCLI_QUERY_TOKEN = "token"
# CloudCLI refuses a username shorter than this.
CLOUDCLI_USERNAME_MIN = 3
# How long a login CloudCLI issues lasts, which the forwarder's cookie
# matches.
CLOUDCLI_LOGIN_LIFETIME_S = 7 * 24 * 3600

# The cookie the forwarder keeps CloudCLI's login in, per port, since a
# cookie belongs to a host and not to a port.
CLOUDCLI_COOKIE_PREFIX = "neutrino_cloudcli_"
# The text CloudCLI's login secret is derived from the instance's secret by.
CLOUDCLI_JWT_LABEL = b"neutrino cloudcli jwt"

# How long the forwarder waits for CloudCLI.
CLOUDCLI_UPSTREAM_TIMEOUT_S = 10.0
CLOUDCLI_READY_POLL_S = 3.0
CLOUDCLI_REGISTER_RETRY_S = 30.0

# Linux: an account's npm install runs as a transient service of its own, so
# a kill for want of memory ends that service and not the agent's own unit.
CLOUDCLI_INSTALL_UNIT_PREFIX = "neutrino_cloudcli_install_"
# What systemd records for a service the kernel killed for want of memory.
CLOUDCLI_OOM_RESULT = "oom-kill"
# How many lines of an installer's own words a refusal carries, and how long.
CLOUDCLI_FAILURE_LINES = 4
CLOUDCLI_FAILURE_DETAIL_CHARS = 400

# Linux: one systemd unit per account, from a template, its environment in
# a root-only file beside the instance's record.
CLOUDCLI_UNIT_TEMPLATE = "neutrino_cloudcli@.service"
CLOUDCLI_UNIT_PREFIX = "neutrino_cloudcli@"
CLOUDCLI_SYSTEMD_DIR = "/etc/systemd/system"

# macOS: one LaunchDaemon per account, its output in its own log file.
CLOUDCLI_LAUNCHD_PREFIX = "com.neutrino.cloudcli."
CLOUDCLI_LAUNCHD_DIR = "/Library/LaunchDaemons"
CLOUDCLI_DARWIN_LOG_DIR = "/Library/Logs/Neutrino/agent"
CLOUDCLI_DARWIN_LOG_PREFIX = "cloudcli_"

# Windows: one scheduled task per account, started at boot with its login,
# running a script that sets the environment; a second task runs an
# account's install once.
CLOUDCLI_TASK_PREFIX = "neutrino_cloudcli_"
CLOUDCLI_INSTALL_TASK_PREFIX = "neutrino_cloudcli_install_"
CLOUDCLI_TASK_MARKER = "neutrino:"
CLOUDCLI_WINDOWS_SHELL = "cmd.exe"
CLOUDCLI_WINDOWS_SCRIPT_DIR_NAME = "run"
# The name an older build gave the inbound firewall rule of an instance's
# port; an apply removes every rule under it.
CLOUDCLI_WINDOWS_RULE_PREFIX = "neutrino_cloudcli_port_"
# What follows Node's directory on a task's PATH, expanded by the task's
# script in the account's context: for the service the account's npm
# directory and its own PATH, for npm the system's own directories first.
CLOUDCLI_WINDOWS_SERVICE_PATH = ("%APPDATA%\\npm", "%PATH%")
CLOUDCLI_WINDOWS_NPM_PATH = ("%SystemRoot%\\System32", "%SystemRoot%", "%PATH%")
CLOUDCLI_LOGON_FAILURES = (0x8007052E,)

# The end of every instance's log file, and of its record.
CLOUDCLI_LOG_SUFFIX = ".log"
CLOUDCLI_RECORD_SUFFIX = ".json"

# How long one reading of the instances is believed.
CLOUDCLI_STATUS_TTL_S = 30.0
