"""Fixed values of the SSH server module."""

# The module's name on the wire, the runner a recipe names, and the title
# its services carry.
SSH_SERVER_NAME = "ssh_server"
SSH_SERVER_RUNNER = "ssh_server"
SSH_SERVER_TITLE = "SSH server"

# The program the agent's package carries under the platform's
# ``agent_bin_dir()``.
SSH_SERVER_BINARY_NAME = "neutrino_ssh_server"
SSH_SERVER_WINDOWS_BINARY_NAME = "neutrino_ssh_server.exe"

# The port the shared runner takes the first instance's from on 127.0.0.1,
# and the address it listens on.
SSH_SERVER_BASE_PORT = 22000
SSH_SERVER_LISTEN_HOST = "127.0.0.1"

# Under the module's directory in the state root, one run directory per
# account, root's, which the account alone reads beside root: the
# instance's host key, its one authorized key, and the launcher folders a
# session's PATH starts with. ``host_key``, under the module's directory and
# in each run directory, is the one host key of an earlier version and its
# copies, each deleted at the first apply.
SSH_SERVER_INSTANCE_KEY_NAME = "instance_host_key"
SSH_SERVER_HOST_KEY_NAME = "host_key"
SSH_SERVER_RUN_DIR_NAME = "run"
SSH_SERVER_AUTHORIZED_KEY_NAME = "authorized_key"
SSH_SERVER_PATH_FOLDERS_NAME = "path_folders"
# What the program writes a new host key as, beside the instance's host key.
SSH_SERVER_MADE_HOST_KEY_SUFFIX = ".made"

# Linux: the variables of each instance's environment file the template
# unit's command line reads.
SSH_SERVER_PORT_VARIABLE = "NEUTRINO_SSH_SERVER_PORT"
SSH_SERVER_SHELL_VARIABLE = "NEUTRINO_SSH_SERVER_SHELL"

# The shell an instance starts when the account names none and its account
# database entry names none either, on Linux and macOS.
SSH_SERVER_FALLBACK_SHELL = "/bin/sh"
# Windows: PowerShell under the system root, the shell when the row names none.
SSH_SERVER_WINDOWS_SYSTEM_ROOT_DEFAULT = "C:\\Windows"
SSH_SERVER_WINDOWS_POWERSHELL_PARTS = (
    "System32",
    "WindowsPowerShell",
    "v1.0",
    "powershell.exe",
)

# macOS: the environment a LaunchDaemon's instance starts with.
SSH_SERVER_DARWIN_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# The fields one instance's record holds.
SSH_SERVER_RECORD_FIELDS = ("account", "port")

# How long the host key's making may take.
SSH_SERVER_MAKE_HOST_KEY_TIMEOUT_S = 30
