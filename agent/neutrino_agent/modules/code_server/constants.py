"""Fixed values of the code-server module."""

# The recipe kind, the module's name on the wire, and the title its
# services carry.
CODE_SERVER_KIND = "code_server"
CODE_SERVER_NAME = "code_server"
CODE_SERVER_TITLE = "code-server"
# What a failed install of the release reports.
CODE_SERVER_DOWNLOAD_FAILED = "code_server_download_failed"

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

CODE_SERVER_PORT_MIN = 1024
CODE_SERVER_PORT_MAX = 65535

# The forwarder's login cookie, per port, since a cookie belongs to a host
# and not to a port; its value is the shared forwarder's, the key derived
# from the instance's secret.
CODE_SERVER_COOKIE_PREFIX = "neutrino_code_server_"
CODE_SERVER_COOKIE_LABEL = b"neutrino code_server cookie"
CODE_SERVER_LOGIN_LIFETIME_S = 7 * 24 * 3600

# macOS: the environment a LaunchDaemon's instance starts with, and the
# shell its terminal opens when the account names none.
CODE_SERVER_DARWIN_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CODE_SERVER_DARWIN_SHELL = "/bin/zsh"

# The fields one instance's record holds.
CODE_SERVER_RECORD_FIELDS = ("account", "port", "secret")
