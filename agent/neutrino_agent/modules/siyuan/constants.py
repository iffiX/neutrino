"""Fixed values of the SiYuan module."""

# The runner a recipe names, the module's name on the wire, and the title its
# services carry.
SIYUAN_RUNNER = "siyuan"
SIYUAN_NAME = "siyuan"
SIYUAN_TITLE = "SiYuan"

# The one artifact, the publisher's desktop build, unpacked under this
# directory in the module's.
SIYUAN_APP_DIR_NAME = "app"
# The kernel's working directory under the unpack, by system: the desktop
# build's ``resources``, which the dmg's copy already is on macOS.
SIYUAN_RESOURCES_PARTS = {
    "linux": ("resources",),
    "darwin": (),
    "windows": ("resources",),
}
# The kernel under the working directory, by system.
SIYUAN_KERNEL_PARTS = {
    "linux": ("kernel", "SiYuan-Kernel"),
    "darwin": ("kernel", "SiYuan-Kernel"),
    "windows": ("kernel", "SiYuan-Kernel.exe"),
}
# The desktop app's own description under the working directory, whose
# ``version`` names the build.
SIYUAN_PACKAGE_PARTS = ("app", "package.json")

# Each account's data directory, under its home, by system: the workspace,
# and the kernel's own files under ``.config/siyuan``.
SIYUAN_DATA_PARTS = {
    "linux": (".local", "share", "neutrino", "agent", "siyuan"),
    "darwin": ("Library", "Application Support", "Neutrino", "agent", "siyuan"),
    "windows": ("AppData", "Local", "Neutrino", "agent", "siyuan"),
}
SIYUAN_WORKSPACE_NAME = "workspace"
# The settings file under the workspace.
SIYUAN_CONF_PARTS = ("conf", "conf.json")

# The kernel's command: its subcommand and the flags it takes.
SIYUAN_SERVE = "serve"
SIYUAN_FLAG_WD = "--wd="
SIYUAN_FLAG_WORKSPACE = "--workspace="
SIYUAN_FLAG_HOME_DIR = "--home-dir="
SIYUAN_FLAG_PORT = "--port="
# The variable the kernel reads its access code from.
SIYUAN_ENV_ACCESS_CODE = "SIYUAN_ACCESS_AUTH_CODE"
# On Linux one template unit runs every account, so the account's own paths
# and port reach its command line through these variables.
SIYUAN_ENV_WORKSPACE = "NEUTRINO_SIYUAN_WORKSPACE"
SIYUAN_ENV_DATA = "NEUTRINO_SIYUAN_DATA"
SIYUAN_ENV_PORT = "NEUTRINO_SIYUAN_PORT"
# The umask the kernel runs under: its key and its records are the account's
# alone, and every directory it makes is mode 700.
SIYUAN_UMASK = "077"

# The kernel listens on loopback alone, on a port the agent picks.
SIYUAN_UPSTREAM_HOST = "127.0.0.1"
# The port the agent takes each instance's port from, the first free one up.
SIYUAN_BASE_PORT = 6810

# The kernel's login: the path, and the cookie it sets, whose fixed name the
# forwarder renames both ways.
SIYUAN_LOGIN_PATH = "/api/system/loginAuth"
SIYUAN_COOKIE = "siyuan"
# Where a token that verifies is sent once the login is set.
SIYUAN_HOME_PATH = "/"

# The module's provider and models in the kernel's settings: SiYuan's own id
# form, a fixed stamp and seven hex characters of the SHA-256 of a seed.
SIYUAN_ID_STAMP = "20000101000000-"
SIYUAN_ID_HEX_CHARS = 7
SIYUAN_PROVIDER_SEED = "neutrino"
SIYUAN_MODEL_SEED_PREFIX = "neutrino/"
SIYUAN_PROVIDER_PROTOCOL = "openai"
SIYUAN_PROVIDER_TIMEOUT_S = 120
# What the gateway's address takes after it for an OpenAI client.
SIYUAN_GATEWAY_PATH = "/v1"
# Writes standard input to the file the first argument names, the account's
# alone, through a file beside it.
SIYUAN_POSIX_WRITE_SHELL = (
    'umask 077; cat > "$1.neutrino" && mv -f -- "$1.neutrino" "$1"'
)
# Makes the directory the first argument names, with the ones above it, the
# account's alone.
SIYUAN_POSIX_MKDIR_SHELL = 'umask 077; mkdir -p -- "$1"'
# How long one step run as the account may take.
SIYUAN_ACCOUNT_STEP_TIMEOUT_S = 30

# The fields one instance's record holds, and those its forwarder serves: a
# change in one of these replaces the forwarder, which writes the settings
# again before it listens.
SIYUAN_RECORD_FIELDS = (
    "account",
    "port",
    "kernel_port",
    "secret",
    "access_code",
    "local_name",
    "cookie_name",
    "gateway_key",
    "gateway_url",
    "models",
    "settings_written",
)
SIYUAN_FORWARDER_FIELDS = SIYUAN_RECORD_FIELDS[:-1]
