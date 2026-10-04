"""Fixed values of the code-server module."""

# The recipe kind and the module's name on the wire.
CODE_SERVER_KIND = "code_server"
CODE_SERVER_NAME = "code_server"

# The release the hub sends is coder's standalone tarball, holding one
# ``code-server-<version>-<system>-<arch>`` directory with its own Node.js.
# The agent keeps it under the module's directory as ``release``.
CODE_SERVER_PACKAGE_TAR = "tar"
CODE_SERVER_RELEASE_PREFIX = "code-server-"
CODE_SERVER_RELEASE_DIR_NAME = "release"
# Inside the release: the launcher, the Node.js it runs, and the file that
# names the version.
CODE_SERVER_LAUNCHER_PARTS = ("bin", "code-server")
CODE_SERVER_NODE_PARTS = ("lib", "node")
CODE_SERVER_PACKAGE_JSON = "package.json"

# The module's directory under the agent's state root, where the release
# and the run directories are, and under its configuration root, where the
# instances' records are.
CODE_SERVER_DIR_NAME = "code_server"
# Each account's run directory under the module's, which holds the socket.
CODE_SERVER_RUN_DIR_NAME = "run"
CODE_SERVER_SOCKET_NAME = "code_server.sock"
# The longest socket path the system takes, in bytes, without the ending
# zero: ``sun_path`` holds 108 bytes on Linux and 104 on macOS.
CODE_SERVER_SOCKET_PATH_MAX = {"linux": 107, "darwin": 103}

# What every instance runs with, after its socket.
CODE_SERVER_FLAGS = (
    "--auth",
    "none",
    "--socket-mode",
    "600",
    "--disable-telemetry",
    "--disable-update-check",
)

# The forwarder listens on loopback alone, at the configured port.
CODE_SERVER_LISTEN_HOST = "127.0.0.1"
CODE_SERVER_PORT_MIN = 1024
CODE_SERVER_PORT_MAX = 65535

# The forwarder's login cookie, per port, since a cookie belongs to a host
# and not to a port: ``base64url(expiry || HMAC-SHA256(key, expiry))``, the
# expiry eight bytes big-endian, the key derived from the instance's secret.
CODE_SERVER_COOKIE_PREFIX = "neutrino_code_server_"
CODE_SERVER_COOKIE_LABEL = b"neutrino code_server cookie"
CODE_SERVER_COOKIE_EXPIRY_BYTES = 8
CODE_SERVER_COOKIE_MAC_BYTES = 32
CODE_SERVER_LOGIN_LIFETIME_S = 7 * 24 * 3600
# How long the forwarder waits for code-server, and how long a bind that
# failed waits before it is tried again.
CODE_SERVER_UPSTREAM_TIMEOUT_S = 10.0
CODE_SERVER_BIND_RETRY_S = 30.0

# Linux: one systemd unit per account, from a template.
CODE_SERVER_UNIT_TEMPLATE = "neutrino_code_server@.service"
CODE_SERVER_UNIT_PREFIX = "neutrino_code_server@"
CODE_SERVER_SYSTEMD_DIR = "/etc/systemd/system"

# macOS: one LaunchDaemon per account, its output in its own log file.
CODE_SERVER_LAUNCHD_PREFIX = "com.neutrino.code_server."
CODE_SERVER_LAUNCHD_DIR = "/Library/LaunchDaemons"
CODE_SERVER_DARWIN_LOG_DIR = "/Library/Logs/Neutrino/agent"
CODE_SERVER_DARWIN_LOG_PREFIX = "code_server_"
# The PATH a LaunchDaemon's instance starts with.
CODE_SERVER_DARWIN_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# The end of every instance's log file, and of its record.
CODE_SERVER_LOG_SUFFIX = ".log"
CODE_SERVER_RECORD_SUFFIX = ".json"
# The fields one instance's record holds.
CODE_SERVER_RECORD_FIELDS = ("account", "port", "secret")

# How long one reading of the instances is believed.
CODE_SERVER_STATUS_TTL_S = 30.0
