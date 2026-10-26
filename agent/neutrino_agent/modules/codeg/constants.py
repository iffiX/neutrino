"""Fixed values of the Codeg module."""

# The runner a recipe names, the module's name on the wire, and the title its
# services carry.
CODEG_RUNNER = "codeg"
CODEG_NAME = "codeg"
CODEG_TITLE = "Codeg"

# The two artifacts, each unpacked under its own directory in the
# module's: the server bundle and the Node.js the agents Codeg installs run
# on.
CODEG_SERVER_DIR_NAME = "server"
CODEG_NODE_DIR_NAME = "node"
# Inside the server artifact: the server, by system, and the web UI.
CODEG_SERVER_NAMES = {
    "linux": "codeg-server",
    "darwin": "codeg-server",
    "windows": "codeg-server.exe",
}
CODEG_WEB_DIR_NAME = "web"
# Inside the node artifact: the directory the interpreter is in, by system.
CODEG_NODE_BIN_PARTS = {"linux": ("bin",), "darwin": ("bin",), "windows": ()}
# What the server prints its version with, and how long it may take.
CODEG_VERSION_ARGUMENT = "--version"
CODEG_VERSION_TIMEOUT_S = 30

# Each account's data directory, under its home, by system: the database,
# the uploads, the daily logs, and the prefix and the cache of the npm
# packages Codeg installs.
CODEG_DATA_PARTS = {
    "linux": (".local", "share", "neutrino", "agent", "codeg"),
    "darwin": ("Library", "Application Support", "Neutrino", "agent", "codeg"),
    "windows": ("AppData", "Local", "Neutrino", "agent", "codeg"),
}
CODEG_NPM_PREFIX_NAME = "npm"
CODEG_NPM_CACHE_NAME = "npm_cache"
# Codeg's daily log under the data directory: ``logs/codeg-server.<date>.log``.
CODEG_LOG_DIR_NAME = "logs"
CODEG_LOG_PREFIX = "codeg-server."
CODEG_LOG_SUFFIX = ".log"

# The environment the service runs with, written from scratch.
CODEG_ENV_HOST = "CODEG_HOST"
CODEG_ENV_PORT = "CODEG_PORT"
CODEG_ENV_TOKEN = "CODEG_TOKEN"
CODEG_ENV_DATA_DIR = "CODEG_DATA_DIR"
CODEG_ENV_STATIC_DIR = "CODEG_STATIC_DIR"
CODEG_ENV_BRIDGE_PORTS = "CODEG_BRIDGE_PORTS"
CODEG_ENV_NPM_PREFIX = "NPM_CONFIG_PREFIX"
CODEG_ENV_NPM_CACHE = "npm_config_cache"
CODEG_BRIDGE_PORTS_OFF = "off"
# The umask the service runs under: every file Codeg and its agents write is
# the account's alone.
CODEG_UMASK = "077"
# What a service's PATH holds after Node's directory on Linux and macOS:
# the account's usual command directories under its home, then the system's
# own; on Windows the task's script expands the account's npm directory and
# its own PATH.
CODEG_ACCOUNT_PATH_PARTS = ((".local", "bin"), ("bin",))
CODEG_SYSTEM_PATH = {
    "linux": ("/usr/local/bin", "/usr/bin", "/bin"),
    "darwin": ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"),
}
CODEG_WINDOWS_SERVICE_PATH = ("%APPDATA%\\npm", "%PATH%")

# Codeg listens on loopback alone, on a port the agent picks.
CODEG_UPSTREAM_HOST = "127.0.0.1"
# The port the agent takes each instance's port from, the first free one up.
CODEG_BASE_PORT = 3101

# The text the instance token is derived from the instance's secret by.
CODEG_TOKEN_LABEL = b"neutrino codeg token"
# Where Codeg's web UI keeps the token, the page the forwarder sends the
# browser to once it is kept, and the subprotocol the UI's WebSocket
# carries it in.
CODEG_STORAGE_KEY = "codeg_token"
CODEG_WORKSPACE_PATH = "/workspace"
CODEG_SUBPROTOCOL_PREFIX = "codeg-token."
# The page a token that verifies is answered with; the key, the token and
# the path are inserted as JSON strings.
CODEG_LOGIN_PAGE = (
    '<!doctype html><meta charset="utf-8"><title>Codeg</title>'
    "<script>localStorage.setItem(%s, %s);location.replace(%s);</script>"
)
# The forwarder's login cookie, named per entry by the hub; this name and
# the port stand in when the state names none. Its value is the shared
# forwarder's, the key derived from the instance's secret.
CODEG_COOKIE_PREFIX = "neutrino_codeg_"
CODEG_COOKIE_LABEL = b"neutrino codeg cookie"
CODEG_LOGIN_LIFETIME_S = 7 * 24 * 3600

# The fields one instance's record holds.
CODEG_RECORD_FIELDS = (
    "account",
    "port",
    "upstream_port",
    "secret",
    "local_name",
    "cookie_name",
)
