"""Fixed values of the VS Code module."""

# The runner a recipe names, the module's name on the wire, and the title its
# services carry.
VSCODE_RUNNER = "vscode"
VSCODE_NAME = "vscode"
VSCODE_TITLE = "VS Code server"

# The CLI's own name inside the archive Microsoft publishes, by system.
VSCODE_CLI_NAMES = {"windows": "code.exe", "linux": "code", "darwin": "code"}
# The token files' directory beside the CLI, which on Linux holds each
# account's environment file too.
VSCODE_TOKEN_DIR_NAME = "tokens"

# What the CLI prints its version with, the word its answer opens with, and
# how long it may take.
VSCODE_VERSION_ARGUMENT = "--version"
VSCODE_VERSION_PREFIX = "code"
VSCODE_VERSION_TIMEOUT_S = 30

# What every instance runs after the CLI's path.
VSCODE_SERVE_ARGUMENTS = ("serve-web", "--accept-server-license-terms")
# The address an instance listens on and a reported url names when the
# hub names none: loopback, where the agent's end of a ``connect`` stream
# reaches it.
VSCODE_LOOPBACK_ADDRESS = "127.0.0.1"
# The port the agent takes each instance's port from, the first free one up.
VSCODE_BASE_PORT = 8000

# The file watcher of a served workspace takes one inotify watch per directory
# and one instance per window; a distribution's defaults (8192 or 65536
# watches, 128 instances) run out on a home directory. These are the floors
# the module raises a Linux machine to, and the drop-in that holds them.
VSCODE_LINUX_SYSCTL_PATH = "/etc/sysctl.d/90-neutrino-vscode.conf"
VSCODE_LINUX_SYSCTL_FLOORS = {
    "fs.inotify.max_user_watches": 524288,
    "fs.inotify.max_user_instances": 512,
}
VSCODE_LINUX_SYSCTL_PROC_DIR = "/proc/sys"
