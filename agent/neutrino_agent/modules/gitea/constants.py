"""Fixed values of the git server module."""

GITEA_BINARY_PATH = "/usr/local/bin/gitea"
GITEA_USER = "git"
GITEA_DIR = "/var/lib/gitea"
GITEA_ETC_DIR = "/etc/gitea"
GITEA_CONF_PATH = "/etc/gitea/app.ini"
GITEA_UNIT = "neutrino_gitea.service"
GITEA_UNIT_SOURCE_NAME = "neutrino_gitea.service"
GITEA_SYSTEMD_DIR = "/etc/systemd/system"

GITEA_DEFAULT_PORT = 3000
# The one address the server listens on, its web page and its own SSH server
# alike; a client reaches it through the agent's connect stream.
GITEA_LISTEN_HOST = "127.0.0.1"
# The port the agent takes Gitea's own SSH server's port from, the first free
# one up, kept in the module's root-only record; and the host SSH clone
# addresses name, a client's own forward.
GITEA_SSH_BASE_PORT = 2222
GITEA_SSH_DOMAIN = "127.0.0.1"
# The module's record: its file's name and the fields it holds.
GITEA_RECORD_NAME = "gitea"
GITEA_RECORD_FIELDS = ("account", "ssh_listen_port")

# Machine secrets app.ini needs: session signing, internal auth, JWTs. The
# hub generates them once per device and hands them down in the desired
# configuration.
GITEA_SECRET_NAMES = ("SECRET_KEY", "INTERNAL_TOKEN", "JWT_SECRET", "LFS_JWT_SECRET")

# The verbs a ``command {module: gitea}`` names, beside ``validate``.
GITEA_COMMAND_ADMIN = "admin"
GITEA_COMMAND_PASSWORD = "password"
# How long the version and the administrator list stand before they are
# read again. Each read starts two gitea processes, and the agent reports
# every few seconds.
GITEA_SURVEY_TTL_S = 60.0
# The words ``gitea --version`` opens with, compared in lower case.
GITEA_VERSION_PREFIX = "gitea version"

# How long a configure that runs the server waits for it to listen on its
# port, and how often it looks.
GITEA_START_WAIT_S = 60.0
GITEA_START_POLL_S = 0.5
# How many of the server's last log lines a failed start searches for an
# error, and the levels that mark one.
GITEA_FAILURE_LINES = 50
GITEA_FAILURE_LEVELS = (" [E] ", " [F] ")

# The refusal of an install or an apply on macOS or Windows while the
# machine has no git the server can run.
GITEA_CODE_GIT_MISSING = "gitea_git_missing"

# macOS and Windows: the binary in the module's own directory under the
# state root, and the server's data, app.ini included, in a directory of
# its own beside it.
GITEA_BINARY_DIR_NAME = "gitea"
GITEA_DATA_DIR_NAME = "gitea_data"
GITEA_CONF_PARTS = ("custom", "conf", "app.ini")
GITEA_LOG_PARTS = ("log", "gitea.log")
# The parts of the data directory the server writes into.
GITEA_DATA_PARTS = (("custom", "conf"), ("data",), ("log",))
# Gitea's own files: the first directory of each part above, with everything
# under it. The account step decides on a handover by their owners.
GITEA_OWN_PARTS = tuple(parts[0] for parts in GITEA_DATA_PARTS)

# macOS: the hidden account the server runs as, its LaunchDaemon, where
# launchd writes its output, and where a usable git is looked for, in that
# order. /usr/bin/git is never looked at: without the developer tools it is
# a stub that opens a dialog.
GITEA_DARWIN_ACCOUNT = "neutrino_gitea"
GITEA_DARWIN_ACCOUNT_FULL_NAME = "Neutrino Gitea"
GITEA_DARWIN_SHELL = "/usr/bin/false"
GITEA_DARWIN_LABEL = "com.neutrino.gitea"
GITEA_DARWIN_LAUNCHD_DIR = "/Library/LaunchDaemons"
GITEA_DARWIN_OUTPUT_PATH = "/Library/Logs/Neutrino/agent/gitea.log"
GITEA_DARWIN_GIT_PATHS = (
    "/Library/Developer/CommandLineTools/usr/bin/git",
    "/Applications/Xcode.app/Contents/Developer/usr/bin/git",
    "/opt/homebrew/bin/git",
    "/usr/local/bin/git",
)
GITEA_DARWIN_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
# What an account's record holds once it can run a process.
GITEA_DARWIN_ACCOUNT_KEYS = (
    "UniqueID",
    "PrimaryGroupID",
    "UserShell",
    "NFSHomeDirectory",
)
# How long a booted-out job is waited for to leave launchd.
GITEA_DARWIN_UNLOAD_TIMEOUT_S = 30
GITEA_DARWIN_UNLOAD_POLL_S = 0.5

# Windows: the service, and where Git for Windows is looked for when the
# machine's Path names none.
GITEA_WINDOWS_SERVICE = "neutrino_gitea"
GITEA_WINDOWS_DISPLAY_NAME = "Neutrino Gitea"
GITEA_WINDOWS_ENVIRONMENT_KEY = (
    "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment"
)
GITEA_WINDOWS_GIT_FALLBACK = "%ProgramFiles%\\Git\\cmd\\git.exe"
# How long a service is waited for to stop.
GITEA_WINDOWS_STOP_TIMEOUT_S = 30
GITEA_WINDOWS_STOP_POLL_S = 0.5
