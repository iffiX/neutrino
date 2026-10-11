"""Fixed values of the CloudCLI module."""

# The recipe kind, the module's name on the wire, and the title its
# services carry.
CLOUDCLI_KIND = "cloudcli"
CLOUDCLI_NAME = "cloudcli"
CLOUDCLI_TITLE = "CloudCLI"
# What a failed download of Node.js reports.
CLOUDCLI_NODE_DOWNLOAD_FAILED = "cloudcli_node_download_failed"

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
# What a command run as an account starts from on each system while npm
# installs, Node's directory first.
CLOUDCLI_INSTALL_PATH = {
    "linux": ("/usr/bin", "/bin"),
    "darwin": ("/usr/bin", "/bin", "/usr/sbin", "/sbin"),
}

# CloudCLI listens on loopback alone, on a port the agent picks.
CLOUDCLI_UPSTREAM_HOST = "127.0.0.1"
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
# What a forwarder reports while CloudCLI refuses to register or sign in
# its administrator.
CLOUDCLI_REGISTER_FAILED = "cloudcli_register_failed"

# Linux: an account's npm install runs as a transient service of its own, so
# a kill for want of memory ends that service and not the agent's own unit.
CLOUDCLI_INSTALL_UNIT_PREFIX = "neutrino_cloudcli_install_"
# What systemd records for a service the kernel killed for want of memory.
CLOUDCLI_OOM_RESULT = "oom-kill"
# How many lines of an installer's own words a refusal carries, and how long.
CLOUDCLI_FAILURE_LINES = 4
CLOUDCLI_FAILURE_DETAIL_CHARS = 400
# The variable the Linux unit reads the server script from.
CLOUDCLI_SERVER_VARIABLE = "CLOUDCLI_SERVER"

# Windows: a second task under the account's login runs its install once;
# the task's script and its log sit under ``run`` beside Node.js.
CLOUDCLI_INSTALL_TASK_PREFIX = "neutrino_cloudcli_install_"
CLOUDCLI_INSTALL_SCRIPT_PATTERN = "install_{account}.cmd"
CLOUDCLI_INSTALL_LOG_PATTERN = "install_{account}.log"
# What follows Node's directory on a task's PATH, expanded by the task's
# script in the account's context: for the service the account's npm
# directory and its own PATH, for npm the system's own directories first.
CLOUDCLI_WINDOWS_SERVICE_PATH = ("%APPDATA%\\npm", "%PATH%")
CLOUDCLI_WINDOWS_NPM_PATH = ("%SystemRoot%\\System32", "%SystemRoot%", "%PATH%")

# The fields one instance's record holds, and the ones its forwarder
# serves: the database file it runs on changes under a running forwarder.
CLOUDCLI_RECORD_FIELDS = (
    "account",
    "port",
    "upstream_port",
    "web_password",
    "token_secret",
    "database",
)
CLOUDCLI_FORWARDER_FIELDS = (
    "account",
    "port",
    "upstream_port",
    "web_password",
    "token_secret",
)
