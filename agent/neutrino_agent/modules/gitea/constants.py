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
